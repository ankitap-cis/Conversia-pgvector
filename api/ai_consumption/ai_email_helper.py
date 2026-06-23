from utils.utils import send_email
from logger import *


def send_avatar_80_email(user, credit):
    subject = "[Action] You have reached 80% of monthly avatar minutes"

    total_limit = (
        credit.avatar_credit_allocated
        + credit.rollover_avatar_credit
        + credit.bonus_avatar_credit
    )

    return send_email(
        user.email,
        subject=subject,
        data={
            "name": user.email,
            "avatar_used": credit.avatar_credit_used,
            "avatar_limit": total_limit,
            # "reset_date": credit.end_date,
        },
        template="warning_avatar.html",
    )


from datetime import datetime


def send_avatar_suspend_email(user, credit):
    subject = f"[Suspension] Avatar usage paused for {user.email}"

    total_limit = (
        credit.avatar_credit_allocated
        + credit.rollover_avatar_credit
        + credit.bonus_avatar_credit
    )

    return send_email(
        user.email,
        subject=subject,
        data={
            "name": user.email,
            "avatar_used": credit.avatar_credit_used,
            "avatar_limit": total_limit,
            # "timestamp": datetime.utcnow(),
            # "reset_date": credit.end_date,
        },
        template="avatar_suspention.html",
    )


def send_compute_80_email(user, credit):
    subject = "[Action] You have reached 80% of monthly compute credit"

    total_limit = (
        credit.compute_credit_allocated
        + credit.rollover_compute_credit
        + credit.bonus_compute_credit
    )

    return send_email(
        user.email,
        subject=subject,
        data={
            "name": user.email,
            "credits_used": credit.compute_credit_used,
            "credits_limit": total_limit,
            # "reset_date": credit.end_date,
        },
        template="warning_compute.html",
    )


def send_compute_suspend_email(user, credit):
    try:
        subject = f"[Suspension] Compute paused for {user.email}"
        total_limit = (
            credit.compute_credit_allocated
            + credit.rollover_compute_credit
            + credit.bonus_compute_credit
        )

        return send_email(
            user.email,
            subject=subject,
            data={
                "name": user.email,
                "credits_used": credit.compute_credit_used,
                "credits_limit": total_limit,
                # "timestamp": datetime.utcnow(),
                # "reset_date": credit.end_date,
            },
            template="compute_suspention.html",
        )
    except Exception as e:
        logger.error(e)


