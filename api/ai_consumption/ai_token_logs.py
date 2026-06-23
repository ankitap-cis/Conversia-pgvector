from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi import status
from sqlalchemy.orm import Session
from models.users import AdminAuditLogs
from logger import *


class AuditAction:
    PRORATED_CAP_ASSIGNED = "PRORATED_CAP_ASSIGNED"
    MONTHLY_CAP_ASSIGNED = "MONTHLY_CAP_ASSIGNED"
    # BONUS_CAP_ASSIGNED = "BONUS_CAP_ASSIGNED"
    SUSPEND_COMPUTE = "SUSPEND_COMPUTE"
    SUSPEND_AVATAR = "SUSPEND_AVATAR"
    REINSTATE_COMPUTE = "REINSTATE_COMPUTE"
    REINSTATE_AVATAR = "REINSTATE_AVATAR"



async def create_audit_log(
    db: Session,
    actor_id: int,
    actor_role: str,
    action_type: str,
    target_type: str,
    target_id: int | None = None,
    message: str | None = None,
    metadata: dict | None = None,
):
    log = AdminAuditLogs(
        actor_id=actor_id,
        actor_role=actor_role,
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
        message=message,
        audit_metadata=metadata or {},
    )

    db.add(log)
    db.commit()
    db.refresh(log)

    return log


async def log_prorated_cap(actor_id, actor_name, user_id, target_name, compute_cap, avatar_cap, days_remaining, db, current_user):
    await create_audit_log(
        db=db,
        actor_id=actor_id,  # 0 or NULL → represents SYSTEM
        actor_role="SYSTEM" if actor_id == 0 else "ADMIN",
        action_type=AuditAction.PRORATED_CAP_ASSIGNED,
        target_type="USER",
        target_id=user_id,
        message=f"Admin {actor_name} performed action on {target_name}",
        metadata={
            "compute": compute_cap,
            "avatar": avatar_cap,
            "days_remaining": days_remaining,
            "details": (
                f"Assigned {compute_cap} compute credits and "
                f"{avatar_cap} avatar minutes for {days_remaining} days"
            ),
        },
    )


async def log_monthly_cap(actor_id, actor_name, user_id, target_name, compute_cap, avatar_cap, db, current_user):
    await create_audit_log(
        db,
        actor_id=actor_id,
        actor_role="SYSTEM",
        action_type=AuditAction.MONTHLY_CAP_ASSIGNED,
        target_type="USER",
        target_id=user_id,
        message=f"{actor_name} performed action on {target_name}",
        metadata={
            "compute": compute_cap,
            "avatar": avatar_cap,
            "details": (
                f"Assigned monthly {compute_cap} compute credits and "
                f"{avatar_cap} avatar minutes"
            ),
        },
    )


async def log_bonus_cap(admin_id, admin_name, user_id, target_name, db, current_user, compute_bonus=None, avatar_bonus=None):
    if compute_bonus:
        details = f"Bonus assigned: {compute_bonus} compute credits"
        metadata = {
            "compute": compute_bonus,
            "details": details,
        }

    else:
        details = f"Bonus assigned: {avatar_bonus} avatar minutes"
        metadata = {
            "avatar": avatar_bonus,
            "details": details,
        }

    await create_audit_log(
        db,
        actor_id=admin_id,
        actor_role="ADMIN",
        action_type=AuditAction.BONUS_CAP_ASSIGNED,
        target_type="USER",
        target_id=user_id,
        message=f"Admin {admin_name} performed action on {target_name}",
        metadata=metadata
    )


async def log_suspend_compute(db, admin_id, admin_name, user_id, target_name):
    await create_audit_log(
        db,
        actor_id=admin_id,
        actor_role="ADMIN",
        action_type=AuditAction.SUSPEND_COMPUTE,
        target_type="USER",
        target_id=user_id,
        message=f"Admin {admin_name} performed action on {target_name}",
        metadata={},
    )


async def log_suspend_avatar(db, admin_id, admin_name, user_id, target_name):
    await create_audit_log(
        db,
        actor_id=admin_id,
        actor_role="ADMIN",
        action_type=AuditAction.SUSPEND_AVATAR,
        target_type="USER",
        target_id=user_id,
        message=f"Admin {admin_name} performed action on {target_name}",
        metadata={},
    )


async def log_reinstate_avatar(db, admin_id, admin_name, user_id, target_name, avatar_minutes):
    details = "Avatar access reinstated"
    if avatar_minutes:
        details = f"Avatar reinstated with bonus {avatar_minutes} minutes"
    await create_audit_log(
        db,
        actor_id=admin_id,
        actor_role="ADMIN",
        action_type=AuditAction.REINSTATE_AVATAR,
        target_type="USER",
        target_id=user_id,
        message=f"Admin {admin_name} performed action on {target_name}",
        metadata={"details": details},
    )


async def log_reinstate_compute(db, admin_id, admin_name, user_id, target_name, compute_amount):
    details = "Compute access reinstated"
    if compute_amount:
        details = f"Compute reinstated with bonus {compute_amount} credits"
    await create_audit_log(
        db,
        actor_id=admin_id,
        actor_role="ADMIN",
        action_type=AuditAction.REINSTATE_COMPUTE,
        target_type="USER",
        target_id=user_id,
        message=f"Admin {admin_name} performed action on {target_name}",
        metadata={"details": details},
    )


from sqlalchemy import func, select, desc, or_
from models.users import AdminAuditLogs


async def get_audit_logs(search, action_type, limit, offset, db, current_user):
    logger.info(f"Fetching audit logs by superadmin {current_user.email}")

    query = select(AdminAuditLogs)

    # 🔹 Filter by action
    if action_type:
        query = query.where(AdminAuditLogs.action_type == action_type)

    # 🔹 Search in message or metadata
    if search:
        query = query.where(
            or_(
                AdminAuditLogs.message.ilike(f"%{search}%"),
            )
        )

    # 🔹 Order latest first
    query = query.order_by(desc(AdminAuditLogs.created_at))

    count_query = select(func.count()).select_from(query.subquery())
    total = db.execute(count_query).scalar()

    # 🔹 Pagination
    query = query.offset(offset).limit(limit)

    logs = db.execute(query).scalars().all()

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "success",
            "message": "Audit logs fetched successfully.",
            "data": jsonable_encoder({
                "logs": logs,
                "total": total,
                "limit": limit,
                "offset": offset
            })
        }
    )
