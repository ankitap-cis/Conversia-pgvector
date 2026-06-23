import calendar
from io import BytesIO
from celery import Celery
from sqlalchemy import desc
from starlette.datastructures import UploadFile
from api.ai_consumption.ai_email_helper import send_avatar_80_email, send_avatar_suspend_email, send_compute_80_email, send_compute_suspend_email
from api.roleplay_assistant import get_general_bot
from connection import SessionLocal
from logger import *
from models.users import GlobalCreditSetting, User, UserMonthlyCredit
from celery.schedules import crontab
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from models.users import User, UserMonthlyCredit
from connection import SessionLocal
from api.ai_consumption.ai_token_credit import deduct_ai_credits


celery_app = Celery(
    "worker",
    broker="redis://localhost:6379/0",  # Redis as broker
    backend="redis://localhost:6379/0"  # Optional: result backend
)

celery_app.conf.beat_schedule = {
    "monthly-credit-reset": {
        "task": "utils.workers.monthly_credit_reset_task",
        "schedule": crontab(hour=0, minute=1, day_of_month=1),
    },
}

from models.precall_plan_models import KnowledgeBase
from utils.s3_bucket_helper import upload_file_to_s3, get_s3_client, generate_presigned_url
import asyncio
from io import BytesIO
from fastapi import UploadFile
from botocore.exceptions import NoCredentialsError
from starlette.datastructures import Headers


import boto3
import configparser
from botocore.config import Config


@celery_app.task(name="utils.workers.upload_file_to_s3_task")
def upload_file_to_s3_task(
    kb_id: int,
    user_id: int,
    org_id: int,
    s3_key: str,
    file_content: bytes,
    file_name: str,
    content_type: str = "application/octet-stream"
):
    """
    Upload file to S3 and trigger document indexing in background.
    """

    db = SessionLocal()
    logger.info(f"[Celery] S3 upload task started for KB ID: {kb_id}")

    try:
        # Get KB entry
        kb = db.query(KnowledgeBase).filter(
            KnowledgeBase.id == kb_id
        ).first()

        if not kb:
            logger.error(f"[Celery] KB {kb_id} not found")
            return

        # Update status
        kb.status = "uploading"
        db.commit()

        logger.info(f"[Celery] Uploading {file_name} to S3...")

        try:
            # Create UploadFile object from bytes
            upload_file = UploadFile(
                filename=file_name,
                file=BytesIO(file_content),
                headers=Headers({
                    "content-type": content_type
                })
            )

            config = configparser.ConfigParser()
            config.read("config.ini")

            aws_access_key = config["aws"]["access_key"]
            aws_secret_key = config["aws"]["secret_key"]
            aws_region_name = config["aws"]["s3_bucket_region"]

            s3_client = boto3.client(
                "s3",
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                region_name=aws_region_name,
            )

            file_path = asyncio.run(
                upload_file_to_s3(
                    s3_key=s3_key,
                    file=upload_file,
                    s3_client=s3_client
                )
            )

            logger.info(
                f"[Celery] File uploaded successfully to S3: {file_path}"
            )

        except NoCredentialsError:
            logger.error("[Celery] AWS credentials not found")
            raise Exception("AWS credentials not found")

        # Update DB after upload
        kb.file_path = file_path
        kb.status = "uploaded"
        kb.reason = None
        db.commit()

        logger.info(
            f"[Celery] Updated KB {kb_id} "
            f"with file path and 'uploaded' status"
        )

        # Create sync boto3 client for presigned URL
        config = configparser.ConfigParser()
        config.read("config.ini")

        aws_access_key = config["aws"]["access_key"]
        aws_secret_key = config["aws"]["secret_key"]
        aws_region_name = config["aws"]["s3_bucket_region"]

        s3_client = boto3.client(
            "s3",
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            region_name=aws_region_name,
        )

        # Reuse your existing generate_presigned_url
        presigned_url = asyncio.run(
            generate_presigned_url(
                s3_client=s3_client,
                s3_key=file_path
            )
        )

        # Trigger indexing
        add_document_to_bot.delay(
            kb_id=kb_id,
            user_id=user_id,
            org_id=org_id,
            file_path=presigned_url
        )

        logger.info(
            f"[Celery] add_document_to_bot "
            f"triggered for KB {kb_id}"
        )

    except Exception as e:
        logger.error(
            f"[Celery] S3 upload failed for KB {kb_id}: {str(e)}",
            exc_info=True
        )

        try:
            kb = db.query(KnowledgeBase).filter(
                KnowledgeBase.id == kb_id
            ).first()

            if kb:
                kb.status = "failed uploading"
                kb.reason = str(e)
                db.commit()

                logger.error(
                    f"[Celery] Updated KB {kb_id} "
                    f"status to 'failed uploading'"
                )

        except Exception as db_error:
            db.rollback()

            logger.error(
                f"[Celery] Failed to update KB status: "
                f"{str(db_error)}",
                exc_info=True
            )

    finally:
        db.close()

@celery_app.task(name="utils.workers.add_document_to_bot")
def add_document_to_bot(kb_id: int, user_id: int, org_id: int, file_path: str):
    db = SessionLocal()  # Create a new session for this task
    logger.info("[Celery] Task started")

    try:
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
        if kb:
            kb.status = "processing"
            db.commit()

        chatbot = get_general_bot(str(user_id))

        usage_metadata = chatbot.add_document(
            file_path=file_path,
            priority=0,
            org_id=org_id
        )

        logger.info(f"[Celery] usage_metadata: {usage_metadata}")

        if kb:
            kb.status = "completed"
            kb.reason = None
            db.commit()

        logger.info(f"[Celery] Document indexing completed for KB {kb_id}")

        total_tokens = 0

        if usage_metadata:
            if isinstance(usage_metadata, dict):
                total_tokens = (
                    usage_metadata.get("total_tokens")
                    or usage_metadata.get("prompt_tokens")
                    or usage_metadata.get("input_tokens")
                    or 0
                )
            else:
                total_tokens = getattr(usage_metadata, "total_tokens", 0) or 0

        logger.info(f"[Celery] Deducting tokens: {total_tokens}")

        import asyncio
        asyncio.run(
            deduct_ai_credits(
                db=db,
                user_id=user_id,
                input_tokens=total_tokens,
                output_tokens=0,
                stt_minutes=0.0,
                tts_minutes=0.0
            )
        )

        db.commit()
        logger.info("[Celery] Credits deducted successfully")

    except Exception as e:
        db.rollback()
        logger.error(f"[Celery] Failed: {str(e)}", exc_info=True)

    finally:
        db.close()

@celery_app.task
def check_avatar_limits_task(credit_id: int, user_id: int):
    db = SessionLocal()

    try:
        credit = db.query(UserMonthlyCredit).get(credit_id)
        if not credit:
            return

        user = (
            db.query(User)
            .filter(User.id == user_id)
            .first()
        )

        if not user:
            return

        total_allocated = (
            credit.avatar_credit_allocated
            + credit.rollover_avatar_credit
            + credit.bonus_avatar_credit
        )

        if total_allocated == 0:
            return

        percent_used = (credit.avatar_credit_used / total_allocated) * 100
        logger.info(f"percentage used - {percent_used}")

        # 80% WARNING
        if 80 <= percent_used < 100 and not credit.avatar_warning_sent:

            send_avatar_80_email(user, credit)

            credit.avatar_warning_sent = True
            db.commit()

        # 100% HARD CAP
        if percent_used >= 100 and not credit.avatar_suspended_sent:

            credit.avatar_access = False  # suspend avatar
            credit.avatar_suspended_sent = True

            send_avatar_suspend_email(user, credit)

            db.commit()

    finally:
        db.close()


@celery_app.task
def check_compute_limits_task(credit_id: int, user_id: int):
    db = SessionLocal()

    try:
        credit = db.query(UserMonthlyCredit).get(credit_id)
        if not credit:
            return

        user = (
            db.query(User)
            .filter(User.id == user_id)
            .first()
        )

        if not user:
            return

        total_allocated = (
            credit.compute_credit_allocated
            + credit.rollover_compute_credit
            + credit.bonus_compute_credit
        )

        if total_allocated == 0:
            return

        percent_used = (credit.compute_credit_used / total_allocated) * 100
        logger.info(f"percentage used - {percent_used}")

        # 80% WARNING
        if 80 <= percent_used < 100 and not credit.compute_warning_sent:

            send_compute_80_email(user, credit)

            credit.compute_warning_sent = True
            db.commit()

        # 100% HARD CAP
        if percent_used >= 100 and not credit.compute_suspended_sent:

            credit.compute_access = False  # suspend avatar
            # credit.compute_suspended_sent = True

            send_compute_suspend_email(user, credit)

            db.commit()

    finally:
        db.close()


@celery_app.task(name="utils.workers.monthly_credit_reset_task")
def monthly_credit_reset_task():
    db: Session = SessionLocal()
    try:
        logger.info("Starting monthly credit reset")
        # current_user = db.query(User).filter(User.user_type == "superadmin").first()
        global_credit = db.query(GlobalCreditSetting).filter(GlobalCreditSetting.is_active.is_(True)).order_by(desc(GlobalCreditSetting.created_at)).first()
        logger.info(f"Global credit settings: {global_credit}")
        if not global_credit:
            logger.error("Global credit config missing")
            return

        active_users = db.query(User).filter(User.archive == False, User.user_type !='superadmin').all()
        logger.info(f"Active users: {active_users}")

        now = datetime.now(timezone.utc)
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # Last day of current month
        last_day = calendar.monthrange(start_date.year, start_date.month)[1]
        # End date → last day of month
        end_date = start_date.replace(day=last_day, hour=23, minute=59, second=59)

        for user in active_users:

            existing_credit = (
                db.query(UserMonthlyCredit)
                .filter(
                    UserMonthlyCredit.user_id == user.id,
                    UserMonthlyCredit.start_date == start_date
                )
                .first()
            )

            if existing_credit:
                skipped_count += 1
                logger.info(f"Skipping user {user.id}, already has credit")
                continue

            # deactivate previous active credit
            old_credit = (
                db.query(UserMonthlyCredit)
                .filter(
                    UserMonthlyCredit.user_id == user.id,
                    UserMonthlyCredit.is_active == True
                )
                .first()
            )

            # rollover_compute = 0
            # rollover_avatar = 0

            if old_credit:
                # rollover_compute = max(old_credit.remaining_compute_credit, 0)
                # rollover_avatar = max(old_credit.remaining_avatar_credit, 0)

                old_credit.is_active = False

            new_credit = UserMonthlyCredit(
                user_id=user.id,
                start_date=start_date,
                end_date=end_date,  # safer than 30/31
                compute_credit_allocated=global_credit.monthly_compute_credit,
                avatar_credit_allocated=global_credit.monthly_avatar_credit,
                # rollover_compute_credit=rollover_compute,
                # rollover_avatar_credit=rollover_avatar,
                compute_access=True,
                avatar_access=True,
                compute_warning_sent=False,
                compute_suspended_sent=False,
                avatar_warning_sent=False,
                avatar_suspended_sent=False,
                is_active=True,
            )

            db.add(new_credit)

        db.commit()

        logger.info("Monthly credit reset completed")

    except Exception as e:
        logger.exception("Monthly reset failed")
        db.rollback()

    finally:
        db.close()
