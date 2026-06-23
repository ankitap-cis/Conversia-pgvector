import calendar
from datetime import date, datetime, timezone
import json
from dateutil.relativedelta import relativedelta
from fastapi.responses import JSONResponse
from fastapi import HTTPException, status
from sqlalchemy import desc, func, select, update
from api.ai_consumption.ai_token_logs import log_prorated_cap, log_reinstate_avatar, log_reinstate_compute, log_suspend_avatar, log_suspend_compute
from logger import *
from models.users import GlobalCreditSetting, User, UserMonthlyCredit
from decimal import Decimal, getcontext

getcontext().prec = 28

INPUT_TOKENS_PER_CREDIT = Decimal("1000000")
OUTPUT_TOKENS_PER_CREDIT = Decimal("125000")
STT_TOKENS_PER_CREDIT = Decimal("60")
TTS_TOKENS_PER_CREDIT = Decimal("120")


async def global_credit_setup(credit_form, db, current_user):
    logger.info(f"Creating global credits by superadmin: {current_user.email}")

    try:
        previous_credit = (
            db.query(GlobalCreditSetting)
            .filter(GlobalCreditSetting.is_active.is_(True))
            .order_by(desc(GlobalCreditSetting.created_at))
            .first()
        )

        if previous_credit:
            previous_credit.is_active = False

        global_credit = GlobalCreditSetting(
            monthly_compute_credit = credit_form.monthly_compute_credit,
            monthly_avatar_credit = credit_form.monthly_avatar_credit,
            input_tokens_per_credit = credit_form.input_tokens_per_credit,
            output_tokens_per_credit = credit_form.output_tokens_per_credit,
            stt_minutes_per_credit = credit_form.stt_minutes_per_credit,
            tts_minutes_per_credit = credit_form.tts_minutes_per_credit,
            created_by = current_user.email
        )

        db.add(global_credit)
        db.commit()

        logger.info(f"Global credits created successfully")
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "status": "success",
                "message": "Global credits created successfully",
                "data": None
            }
        )
    
    except Exception as e:
        logger.error(str(e))
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to create credits",
                "data": None
            }
        )


async def fetch_global_credit(db, current_user):
    logger.info(f"Fetching global credits by superadmin: {current_user.email}")
    try:
        global_credit = db.query(GlobalCreditSetting).filter(GlobalCreditSetting.is_active.is_(True)).order_by(desc(GlobalCreditSetting.created_at)).first()

        if not global_credit:
            logger.error("No active global credit configuration found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "error",
                    "message": "Active global credit configuration not found",
                    "data": None
                }
            )
        
        logger.info(" Global credits fetched successfully")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Global credit configuration fetched successfully",
                "data": {
                    "id": global_credit.id,
                    "monthly_compute_credit": global_credit.monthly_compute_credit,
                    "monthly_avatar_credit": global_credit.monthly_avatar_credit,
                    "input_tokens_per_credit":global_credit.input_tokens_per_credit,
                    "output_tokens_per_credit":global_credit.output_tokens_per_credit,
                    "stt_minutes_per_credit":global_credit.stt_minutes_per_credit,
                    "tts_minutes_per_credit":global_credit.tts_minutes_per_credit
                }
            }
        )
    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Unexpected error in fetch_global_credit: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Unexpected error occurred while fetching global credit configuration",
                "data": None
            }
        )
    

async def assign_prorated_credit(db, new_user, admin):
    logger.info(f"Assigning credits to user: {new_user.email}")
    try:
        today = datetime.now(timezone.utc).date()
        total_days = calendar.monthrange(today.year, today.month)[1]
        remaining_days = total_days - today.day + 1

        global_credits = db.query(GlobalCreditSetting).filter(GlobalCreditSetting.is_active.is_(True)).order_by(desc(GlobalCreditSetting.created_at)).first()

        if not global_credits:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status":"failure",
                    "message": "Global credit setting not configured.",
                    "data":None
                }
            )

        assign_compute_credit = round(
            global_credits.monthly_compute_credit * remaining_days / total_days
        )

        assign_avatar_credit = round(
            global_credits.monthly_avatar_credit * remaining_days / total_days
        )

        end_date = today + relativedelta(day=31, hour=23, minute=59, second=59)

        credit = UserMonthlyCredit(
            user_id = new_user.id,
            start_date = datetime.now(),
            end_date = end_date,
            compute_credit_allocated = assign_compute_credit,
            avatar_credit_allocated = assign_avatar_credit
        )

        db.add(credit)

        await log_prorated_cap(actor_id=admin.id, actor_name=admin.email, user_id=new_user.id, target_name=new_user.email, compute_cap=assign_compute_credit, avatar_cap=assign_avatar_credit, db=db, days_remaining=None, current_user=None)

        logger.info(f"Credit assigned successfully to user: {new_user.email}")
    
    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Failed to assign prorated credit: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status":"failure",
                "message": "Failed to assign prorated credit.",
                "data":None
            }
        )


async def calculate_credits(
    db,
    input_tokens: int = 0,
    output_tokens: int = 0,
    stt_minutes: Decimal = Decimal("0"),
    tts_minutes: Decimal = Decimal("0")
) -> Decimal:
    credits = Decimal("0")

    tokens = db.query(GlobalCreditSetting).filter(GlobalCreditSetting.is_active.is_(True)).order_by(desc(GlobalCreditSetting.created_at)).first()

    INPUT_TOKENS_PER_CREDIT = Decimal(tokens.input_tokens_per_credit) if tokens and tokens.input_tokens_per_credit else Decimal("1000000")
    OUTPUT_TOKENS_PER_CREDIT = Decimal(tokens.output_tokens_per_credit) if tokens and tokens.output_tokens_per_credit else Decimal("125000")
    STT_TOKENS_PER_CREDIT = Decimal(tokens.stt_minutes_per_credit) if tokens and tokens.stt_minutes_per_credit else Decimal("60")
    TTS_TOKENS_PER_CREDIT = Decimal(tokens.tts_minutes_per_credit) if tokens and tokens.tts_minutes_per_credit else Decimal("120")

    # Token-based credits
    if input_tokens:
        credits += Decimal(input_tokens) / INPUT_TOKENS_PER_CREDIT

    if output_tokens:
        credits += Decimal(output_tokens) / OUTPUT_TOKENS_PER_CREDIT

    # Audio-based credits
    if stt_minutes:
        credits += stt_minutes / STT_TOKENS_PER_CREDIT

    if tts_minutes:
        credits += tts_minutes / TTS_TOKENS_PER_CREDIT
    
    return credits



async def deduct_ai_credits(
    db,
    user_id: int,
    input_tokens: int,
    output_tokens: int,
    stt_minutes: Decimal = Decimal("0"),
    tts_minutes: Decimal = Decimal("0")
):
    logger.info(f"input token - {input_tokens}, output token - {output_tokens}, stt - {stt_minutes}, tts - {tts_minutes}")
    try:
        credits_needed = await calculate_credits(db,input_tokens, output_tokens, stt_minutes, tts_minutes)
        
        stmt = (
            update(UserMonthlyCredit)
            .where(UserMonthlyCredit.user_id == user_id, UserMonthlyCredit.is_active.is_(True))
            .values(
                compute_credit_used=func.coalesce(UserMonthlyCredit.compute_credit_used, 0) + credits_needed,
                input_tokens_used=func.coalesce(UserMonthlyCredit.input_tokens_used, 0) + input_tokens,
                output_tokens_used=func.coalesce(UserMonthlyCredit.output_tokens_used, 0) + output_tokens,
                stt_minutes_used=func.coalesce(UserMonthlyCredit.stt_minutes_used, 0) + stt_minutes,
                tts_minutes_used=func.coalesce(UserMonthlyCredit.tts_minutes_used, 0) + tts_minutes
            )
            .returning(
                UserMonthlyCredit.id,
                UserMonthlyCredit.compute_credit_used,
                UserMonthlyCredit.compute_credit_allocated,
                UserMonthlyCredit.rollover_compute_credit,
                UserMonthlyCredit.bonus_compute_credit
            )
        )

        row = db.execute(stmt).fetchone()
        db.commit()

        # Calculate remaining balance
        if row is None:
            logger.error(f"No active credit cycle found for user_id: {user_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "error",
                    "message": "Active credit cycle not found",
                    "data": None
                }
            )

        credit_id, compute_credit_used, allocated, rollover, bonus = row
        remaining_balance = allocated + rollover + bonus - compute_credit_used

        logger.info(f"credits_used: {credits_needed}, remaining_balance: {remaining_balance}")

        # LAZY import for scheduler
        from utils.workers import check_compute_limits_task
        check_compute_limits_task.delay(credit_id, user_id)

        return {
            "credits_used": credits_needed,
            "remaining_balance": remaining_balance
        }

    except Exception as e:
        logger.error(f"Failed to deduct AI credits: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to deduct AI credits",
                "data": None
            }
        )


async def deduct_avatar_minutes(
    db,
    user_id: int,
    avatar_minutes: Decimal
):
    logger.info(f"Avatar minutes used: {avatar_minutes}")
    try:
        stmt = (
            update(UserMonthlyCredit)
            .where(
                UserMonthlyCredit.user_id == user_id,
                UserMonthlyCredit.is_active.is_(True)
            )
            .values(
                avatar_credit_used=func.coalesce(
                    UserMonthlyCredit.avatar_credit_used, 0
                ) + avatar_minutes
            )
            .returning(
                UserMonthlyCredit.id,
                UserMonthlyCredit.avatar_credit_used,
                UserMonthlyCredit.avatar_credit_allocated,
                UserMonthlyCredit.rollover_avatar_credit,
                UserMonthlyCredit.bonus_avatar_credit
            )
        )

        row = db.execute(stmt).fetchone()
        db.commit()

        # Remaining avatar balance
        credit_id, avatar_used, allocated, rollover, bonus = row
        remaining_balance = allocated + rollover + bonus - avatar_used

        logger.info(f"avatar_minutes_used: {avatar_minutes}, remaining_avatar_balance: {remaining_balance}")

        # LAZY import for scheduler
        from utils.workers import check_avatar_limits_task
        check_avatar_limits_task.delay(credit_id, user_id)

        return {
            "avatar_minutes_used": avatar_minutes,
            "remaining_avatar_balance": remaining_balance
        }
    
    except Exception as e:
        logger.error(f"Failed to deduct avatar minutes: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to deduct avatar minutes",
                "data": None
            }
        )


def calculate_prorated_bonus(
    full_month_credit: Decimal,
    cycle_end: date
) -> Decimal:
    today = date.today()
    remaining_days = max((cycle_end.date() - today).days + 1, 0)
    days_in_month = cycle_end.day
    return (full_month_credit * Decimal(remaining_days) / Decimal(days_in_month)).quantize(
        Decimal("0.01")
    )


async def reinstate_user_credits(user_id, credit_type, bonus_amount, reinstate_only, db, current_user):
    logger.info(f"Reinitiating user credit for user_id: {user_id} by superadmin: {current_user.email}")
    target_email = db.query(User.email).filter(User.id == user_id).scalar()
    try:
        credit_row = db.execute(
            select(UserMonthlyCredit)
            .where(
                UserMonthlyCredit.user_id == user_id,
                UserMonthlyCredit.is_active.is_(True),
            )
        ).scalar_one_or_none()

        if not credit_row:
            logger.error(f"Active credit cycle not found for user_id: {user_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "error",
                    "message": "Active credit cycle not found",
                    "data": None,
                },
            )

        # VALIDATE CREDIT TYPE
        if credit_type not in ["compute", "avatar"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "error",
                    "message": "Invalid credit_type",
                    "data": None,
                },
            )

        # REINSTATE ONLY (NO BONUS)
        if reinstate_only:
            if credit_type == "compute":
                stmt = (
                    update(UserMonthlyCredit)
                    .where(UserMonthlyCredit.id == credit_row.id)
                    .values(compute_access=True)
                )
                await log_reinstate_compute(db=db, admin_id=current_user.id, admin_name=current_user.email, user_id=user_id, target_name=target_email, compute_amount=None)

            else:
                stmt = (
                    update(UserMonthlyCredit)
                    .where(UserMonthlyCredit.id == credit_row.id)
                    .values(avatar_access=True)
                )

                await log_reinstate_avatar(db=db, admin_id=current_user.id, admin_name=current_user.email, user_id=user_id, target_name=target_email, avatar_minutes=None)

            db.execute(stmt)
            db.commit()


            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "success",
                    "message": "User access reinstated successfully",
                    "data": {
                        "user_id": user_id,
                        "credit_type": credit_type,
                        "bonus_added": 0,
                    },
                },
            )

        # BONUS FLOW (CUSTOM OR PRORATED)
        if not bonus_amount:
            base_credit = (
                db.query(GlobalCreditSetting)
                .filter(GlobalCreditSetting.is_active.is_(True))
                .first()
            )

            if credit_type == "compute":
                bonus_amount = calculate_prorated_bonus(
                    base_credit.monthly_compute_credit,
                    credit_row.end_date,
                )

                await log_reinstate_avatar(db=db, admin_id=current_user.id, admin_name=current_user.email, user_id=user_id, target_name=target_email, avatar_minutes=bonus_amount)
                
            else:
                bonus_amount = calculate_prorated_bonus(
                    base_credit.monthly_avatar_credit,
                    credit_row.end_date,
                )

                await log_reinstate_compute(db=db, admin_id=current_user.id, admin_name=current_user.email, user_id=user_id, target_name=target_email, compute_amount=bonus_amount)
        
        if bonus_amount:
            await log_reinstate_avatar(db=db, admin_id=current_user.id, admin_name=current_user.email, user_id=user_id, target_name=target_email, avatar_minutes=bonus_amount) if credit_type == "avatar" else await log_reinstate_compute(db=db, admin_id=current_user.id, admin_name=current_user.email, user_id=user_id, target_name=target_email, compute_amount=bonus_amount)

        if credit_type == "compute":
            stmt = (
                update(UserMonthlyCredit)
                .where(UserMonthlyCredit.id == credit_row.id)
                .values(
                    bonus_compute_credit=UserMonthlyCredit.bonus_compute_credit + bonus_amount,
                    compute_access=True,
                )
            )
        else:
            stmt = (
                update(UserMonthlyCredit)
                .where(UserMonthlyCredit.id == credit_row.id)
                .values(
                    bonus_avatar_credit=UserMonthlyCredit.bonus_avatar_credit + bonus_amount,
                    avatar_access=True,
                )
            )

        db.execute(stmt)
        db.commit()

        logger.info(f"User credits reinstated successfully for user_id: {user_id}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "User credits reinstated successfully",
                "data": {
                    "user_id": user_id,
                    "credit_type": credit_type,
                    "bonus_added": float(bonus_amount),
                },
            },
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Failed to reinstate user credits: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to reinstate user credits",
                "data": None,
            },
        )


async def suspend_user_credits(user_id, credit_type, db, current_user):
    logger.info(
        f"Suspending user credit for user_id: {user_id} "
        f"by superadmin: {current_user.email}"
    )
    target_email = db.query(User.email).filter(User.id == user_id).scalar()
    try:
        credit_row = db.execute(
            select(UserMonthlyCredit)
            .where(
                UserMonthlyCredit.user_id == user_id,
                UserMonthlyCredit.is_active.is_(True),
            )
        ).scalar_one_or_none()

        if not credit_row:
            logger.error(f"Active credit cycle not found for user_id: {user_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "error",
                    "message": "Active credit cycle not found",
                    "data": None
                }
            )

        # Validate credit type
        if credit_type not in ["compute", "avatar"]:
            logger.error(f"Invalid credit_type: {credit_type}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "error",
                    "message": "Invalid credit_type",
                    "data": None
                }
            )

        # Update access flag
        if credit_type == "compute":
            stmt = (
                update(UserMonthlyCredit)
                .where(UserMonthlyCredit.id == credit_row.id)
                .values(compute_access=False)
            )
            await log_suspend_compute(db, admin_id=current_user.id, admin_name=current_user.email, user_id=user_id, target_name=target_email)
        else:  # avatar
            stmt = (
                update(UserMonthlyCredit)
                .where(UserMonthlyCredit.id == credit_row.id)
                .values(avatar_access=False)
            )
            await log_suspend_avatar(db, admin_id=current_user.id, admin_name=current_user.email, user_id=user_id, target_name=target_email)

        db.execute(stmt)
        db.commit()

        logger.info(
            f"User {credit_type} access suspended successfully for user_id: {user_id}"
        )

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": f"{credit_type.capitalize()} access suspended successfully",
                "data": {
                    "user_id": user_id,
                    "credit_type": credit_type
                }
            }
        )

    except HTTPException:
        raise

    except Exception as e:
        db.rollback()
        logger.error(
            f"Unexpected error in suspend_user_credits for user_id={user_id}: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status":"failure",
                "message":"Unexpected error occurred while suspending user credit",
                "data":None
            }
        )
