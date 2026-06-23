import csv
from decimal import Decimal
import io
from fastapi import Depends, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.encoders import jsonable_encoder
from requests import Session
from connection import get_db
from models.users import Organization, Profile, User, UserMonthlyCredit
from sqlalchemy import case, func
from logger import *
from utils.utils import get_current_user
from datetime import date
from dateutil.relativedelta import relativedelta
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session


async def admin_token_consumption_dashboard(timeframe, db, current_user):
    try:
        logger.info(f"Fetching AI consumption dashboard by superadmin: {current_user.email}")
        base_query = (
            db.query(User)
            .outerjoin(UserMonthlyCredit, User.id == UserMonthlyCredit.user_id)
            .filter(
                User.archive == False
            )
        )

        all_users_with_plan = base_query.count()

        active_users_count = (
            base_query
            .filter(UserMonthlyCredit.is_active == True)
            .count()
        )

        suspended_compute_count = (
            base_query
            .filter(UserMonthlyCredit.compute_access == False)
            .count()
        )

        suspended_avatar_count = (
            base_query
            .filter(UserMonthlyCredit.avatar_access == False)
            .count()
        )

        usage_query = db.query(UserMonthlyCredit).join(User).filter(
            User.archive == False
        )

        start_date, end_date = get_date_range(timeframe)
        if start_date and end_date:
            usage_query = usage_query.filter(
                UserMonthlyCredit.start_date >= start_date,
                UserMonthlyCredit.start_date < end_date
            )


        compute_ratio = (
            UserMonthlyCredit.compute_credit_used /
            func.nullif(
                UserMonthlyCredit.compute_credit_allocated +
                UserMonthlyCredit.rollover_compute_credit +
                UserMonthlyCredit.bonus_compute_credit,
                0
            )
        )

        avatar_ratio = (
            UserMonthlyCredit.avatar_credit_used /
            func.nullif(UserMonthlyCredit.avatar_credit_allocated, 0)
        )

        risk_query = usage_query.filter(
            (compute_ratio >= Decimal("0.8")) |
            (avatar_ratio >= Decimal("0.8"))
        )

        users_at_risk = risk_query.count()

        compute_agg = usage_query.with_entities(
            func.coalesce(func.sum(UserMonthlyCredit.compute_credit_used), 0),
            func.coalesce(
                func.sum(
                    UserMonthlyCredit.compute_credit_allocated +
                    UserMonthlyCredit.rollover_compute_credit +
                    UserMonthlyCredit.bonus_compute_credit
                ),
                0
            )
        ).first()

        compute_used, compute_allocated = compute_agg

        compute_used = Decimal(compute_used)
        compute_allocated = Decimal(compute_allocated)

        compute_remaining = compute_allocated - compute_used
        compute_percentage = (
            (compute_used / compute_allocated) * 100
            if compute_allocated > 0 else Decimal("0")
        )

        avatar_agg = usage_query.with_entities(
            func.coalesce(func.sum(UserMonthlyCredit.avatar_credit_used), 0),
            func.coalesce(func.sum(UserMonthlyCredit.avatar_credit_allocated), 0),
        ).first()

        avatar_used, avatar_allocated = avatar_agg

        avatar_used = Decimal(avatar_used)
        avatar_allocated = Decimal(avatar_allocated)

        avatar_remaining = avatar_allocated - avatar_used
        avatar_percentage = (
            (avatar_used / avatar_allocated) * 100
            if avatar_allocated > 0 else Decimal("0")
        )

        data = {
            "active_users": active_users_count,
            "total_users": all_users_with_plan,
            "users_at_risk": users_at_risk,
            "suspended_compute": suspended_compute_count,
            "suspended_avatar": suspended_avatar_count,
            "organization_compute": {
                "used": compute_used.quantize(Decimal("0.01")),
                "allocated": compute_allocated.quantize(Decimal("0.01")),
                "percentage_used": compute_percentage.quantize(Decimal("0.01")),
                "remaining": compute_remaining.quantize(Decimal("0.01")),
            },
            "organization_avatar": {
                "used": avatar_used.quantize(Decimal("0.01")),
                "allocated": avatar_allocated.quantize(Decimal("0.01")),
                "percentage_used": avatar_percentage.quantize(Decimal("0.01")),
                "remaining": avatar_remaining.quantize(Decimal("0.01")),
            },
        }

        logger.info("AI consumption dashboard fetched successfully.")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=jsonable_encoder({
                "status": "success",
                "message": "AI consumption dashboard fetched successfully.",
                "data": data
            })
        )

    except ValueError as ve:
        logger.error(f"Value error in admin_token_consumption_dashboard: {str(ve)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "status": "failure",
                "message": "Invalid data format.",
                "data": None
            }
        )

    except Exception as e:
        logger.error(f"Error in admin_token_consumption_dashboard: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occurred while fetching the dashboard.",
                "data": None
            }
        )




def get_date_range(timeframe: str):
    today = date.today().replace(day=1)

    if not timeframe or timeframe == "all_time":
        # No filter
        return None, None

    if timeframe == "this_month":
        start = today
        end = today + relativedelta(months=1)

    elif timeframe == "last_month":
        start = today - relativedelta(months=1)
        end = today

    elif timeframe == "quarter_to_date":
        start = today - relativedelta(months=3)
        end = today + relativedelta(months=1)

    elif timeframe == "previous_quarter":
        start = today - relativedelta(months=6)
        end = today - relativedelta(months=3)

    else:
        raise ValueError("Invalid timeframe")

    return start, end


async def user_leaderboard(search_query, timeframe, limit, offset, db, current_user):
    try:
        logger.info(f"Fetching user leaderboard by superadmin: {current_user.email}")
 
        start_date, end_date = get_date_range(timeframe)
 
        base_query = (
            db.query(
                User.id.label("user_id"),
                Profile.full_name,
                User.email,
                Organization.org_name,
                User.user_type,
 
                # COMPUTE 
                func.coalesce(
                    func.sum(UserMonthlyCredit.compute_credit_used),
                    0
                ).label("compute_used"),
 
                func.coalesce(
                    func.sum(
                        UserMonthlyCredit.compute_credit_allocated +
                        UserMonthlyCredit.rollover_compute_credit +
                        UserMonthlyCredit.bonus_compute_credit
                    ),
                    0
                ).label("compute_allocated"),
 
                # AVATAR
                func.coalesce(
                    func.sum(UserMonthlyCredit.avatar_credit_used),
                    0
                ).label("avatar_used"),
 
                func.coalesce(
                    func.sum(UserMonthlyCredit.avatar_credit_allocated),
                    0
                ).label("avatar_allocated"),
                func.coalesce(
                    func.sum(UserMonthlyCredit.input_tokens_used),
                    0
                ).label("input_tokens_used"),
 
                func.coalesce(
                    func.sum(UserMonthlyCredit.output_tokens_used),
                    0
                ).label("output_tokens_used"),
 
                func.coalesce(
                    func.sum(UserMonthlyCredit.stt_minutes_used),
                    0
                ).label("stt_minutes_used"),
 
                func.coalesce(
                    func.sum(UserMonthlyCredit.tts_minutes_used),
                    0
                ).label("tts_minutes_used"),
                func.bool_or(
                    case(
                        (UserMonthlyCredit.is_active.is_(True), UserMonthlyCredit.compute_access),
                        else_=False
                    )
                ).label("compute_access"),
                func.bool_or(
                    case(
                        (UserMonthlyCredit.is_active.is_(True), UserMonthlyCredit.avatar_access),
                        else_=False
                    )
                ).label("avatar_access"),
            )
            .join(UserMonthlyCredit, UserMonthlyCredit.user_id == User.id)
            .join(Organization, Organization.id == User.organization_id)
            .join(Profile, Profile.user_id == User.id)
        )
        # Apply date filter
        if start_date and end_date:
            base_query = base_query.filter(
                UserMonthlyCredit.start_date >= start_date,
                UserMonthlyCredit.start_date < end_date
            )
        #  Search
        if search_query:
            base_query = base_query.filter(
                func.lower(Profile.full_name).like(f"%{search_query.lower()}%") |
                func.lower(User.email).like(f"%{search_query.lower()}%")
            )
                # func.lower(Organization.name).like(f"%{search_query.lower()}%")
        base_query = base_query.group_by(
            User.id,
            Profile.full_name,
            User.email,
            User.user_type,
            Organization.org_name,
            UserMonthlyCredit.created_at
        )
        total = base_query.count()
 
        rows = (
            base_query
            # .order_by(func.sum(UserMonthlyCredit.compute_credit_used).desc())
            .order_by(UserMonthlyCredit.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
 
        data = []
 
        for r in rows:
            compute_used = Decimal(r.compute_used)
            compute_allocated = Decimal(r.compute_allocated)
            avatar_used = Decimal(r.avatar_used)
            avatar_allocated = Decimal(r.avatar_allocated)
 
            compute_pct = (
                (compute_used / compute_allocated * 100)
                if compute_allocated > 0 else Decimal("0")
            )
 
            avatar_pct = (
                (avatar_used / avatar_allocated * 100)
                if avatar_allocated > 0 else Decimal("0")
            )
 
            input_tokens = r.input_tokens_used
            output_tokens = r.output_tokens_used
            stt_minutes = r.stt_minutes_used
            tts_minutes = r.tts_minutes_used
 
            # Alerts
            alert = None
            if compute_pct >= 100 or avatar_pct >= 100:
                alert = "Critical"
            elif compute_pct >= 80 or avatar_pct >= 80:
                alert = "Warning"
 
            # Status
            if not r.compute_access and not r.avatar_access:
                user_status = "Suspended"
            elif not r.compute_access:
                user_status = "Suspended (Compute)"
            elif not r.avatar_access:
                user_status = "Suspended (Avatar)"
            else:
                user_status = "Active"
 
            data.append({
                "user_id": r.user_id,
                "name": r.full_name,
                "email": r.email,
                "org_name": r.org_name,
                "role": r.user_type,
 
                "compute": {
                    "used": round(float(compute_used), 2),
                    "allocated": round(float(compute_allocated), 2),
                    "percentage": round(float(compute_pct), 2)
                },
                "avatar": {
                    "used": round(float(avatar_used), 2),
                    "allocated": round(float(avatar_allocated), 2),
                    "percentage": round(float(avatar_pct), 2)
                },
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "stt_minutes": stt_minutes,
                "tts_minutes": tts_minutes,
                "alert": alert,
                "status": user_status
            })
        logger.info("User leaderboard fetched successfully.")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content = jsonable_encoder({
                "status": "success",
                "message": "User leaderboard fetched successfully.",
                "data": {
                    "user_leaderboard":data,
                    "pagination": {
                        "limit": limit,
                        "offset": offset,
                        "total": total
                    },
                    "timeframe": timeframe
                }
            })
        )

    except ValueError as ve:
        logger.error(f"Value error in user_leaderboard: {str(ve)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "status": "failure",
                "message": "Invalid data format or timeframe.",
                "data": None
            }
        )

    except Exception as e:
        logger.error(f"Error in user_leaderboard: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occurred while fetching the leaderboard.",
                "data": None
            }
        )


async def user_consumption_data(user_id, db, current_user):
    logger.info(f"Fetching current cycle AI consumption data for user_id={user_id} requested by {current_user.email}")
    try:
        user_consumption = (
            db.query(
                User.id.label("user_id"),
                Profile.full_name,
                User.email,
                UserMonthlyCredit.start_date,
                UserMonthlyCredit.end_date,

                # COMPUTE
                UserMonthlyCredit.compute_credit_used.label("compute_used"),
                (
                    UserMonthlyCredit.compute_credit_allocated +
                    UserMonthlyCredit.rollover_compute_credit +
                    UserMonthlyCredit.bonus_compute_credit
                ).label("compute_allocated"),

                # AVATAR
                UserMonthlyCredit.avatar_credit_used.label("avatar_used"),
                (
                    UserMonthlyCredit.avatar_credit_allocated +
                    UserMonthlyCredit.rollover_avatar_credit +
                    UserMonthlyCredit.bonus_avatar_credit
                ).label("avatar_allocated"),
                UserMonthlyCredit.avatar_credit_allocated.label("base_avatar"),
                UserMonthlyCredit.compute_credit_allocated.label("base_credit"),
                UserMonthlyCredit.compute_access,
                UserMonthlyCredit.avatar_access
            )
            .join(User, User.id == UserMonthlyCredit.user_id)
            .join(Profile, Profile.user_id == User.id)
            .filter(
                UserMonthlyCredit.user_id == user_id,
                UserMonthlyCredit.is_active == True,
                User.archive == False
            )
            .first()
        )

        if not user_consumption:
            logger.warning(f"No active billing cycle found for user_id={user_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status":"failure",
                    "message":"Active billing cycle not found for this user",
                    "data":None
                }
            )

        # Compute Percentage
        compute_allocated = Decimal(user_consumption.compute_allocated or 0)
        compute_used = Decimal(user_consumption.compute_used or 0)

        compute_pct = (
            (compute_used / compute_allocated * 100)
            if compute_allocated > 0 else Decimal("0")
        )

        # Avatar Percentage
        avatar_allocated = Decimal(user_consumption.avatar_allocated or 0)
        avatar_used = Decimal(user_consumption.avatar_used or 0)

        avatar_pct = (
            (avatar_used / avatar_allocated * 100)
            if avatar_allocated > 0 else Decimal("0")
        )

        if not user_consumption.compute_access and not user_consumption.avatar_access:
            user_status = "Suspended"
        elif not user_consumption.compute_access:
            user_status = "Suspended (Compute)"
        elif not user_consumption.avatar_access:
            user_status = "Suspended (Avatar)"
        else:
            user_status = "Active"

        data = {
            "user_id": user_consumption.user_id,
            "name": user_consumption.full_name,
            "email": user_consumption.email,
            "cycle_start": user_consumption.start_date,
            "cycle_end": user_consumption.end_date,
            "compute": {
                "used": round(float(compute_used), 2),
                "allocated": round(float(compute_allocated), 2),
                "base": float(user_consumption.base_credit),
                "percentage": round(float(compute_pct), 2),
                "remaining": round(float(compute_allocated - compute_used), 2)
            },
            "avatar": {
                "used": round(float(avatar_used), 2),
                "allocated": round(float(avatar_allocated), 2),
                "base": float(user_consumption.base_avatar),
                "percentage": round(float(avatar_pct), 2),
                "remaining": round(float(avatar_allocated - avatar_used), 2)
            },
            "compute_access": user_consumption.compute_access, 
            "avatar_access": user_consumption.avatar_access,
            "status": user_status
        }

        logger.info(f"Successfully fetched AI consumption data for user_id={user_id}")

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content = jsonable_encoder({
                "status": "success",
                "message": "AI consumption data fetched successfully.",
                "data": data
            })
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Unexpected error in user_consumption_data for user_id={user_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Unexpected error occurred while fetching user consumption data.",
                "data": None
            }
        )

async def require_compute_access(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    credit = (
        db.query(UserMonthlyCredit.compute_access)
        .filter(
            UserMonthlyCredit.user_id == current_user.id,
            UserMonthlyCredit.is_active.is_(True)
        )
        .first()
    )

    if not credit or credit.compute_access is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "status": "failure",
                "message": "Compute access suspended for current billing cycle.",
                "data": None
            }
        )


async def require_avatar_access(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    credit = (
        db.query(UserMonthlyCredit.avatar_access)
        .filter(
            UserMonthlyCredit.user_id == current_user.id,
            UserMonthlyCredit.is_active.is_(True)
        )
        .first()
    )

    if not credit or credit.avatar_access is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "status": "failure",
                "message": "Avatar access suspended for current billing cycle.",
                "data": None
            }
        )


async def export_user_leaderboard_csv(timeframe, search, db, current_user):
    logger.info(f"Exporting user leaderboard data by superadmin {current_user.email}")
    start_date, end_date = get_date_range(timeframe)

    # Get filtered query
    query  = (
        db.query(
            User.id.label("user_id"),
            Profile.full_name,
            User.email,
            # Organization.name.label("organization"),
            User.user_type,

            # COMPUTE
            func.coalesce(
                func.sum(UserMonthlyCredit.compute_credit_used),
                0
            ).label("compute_used"),

            func.coalesce(
                func.sum(
                    UserMonthlyCredit.compute_credit_allocated +
                    UserMonthlyCredit.rollover_compute_credit +
                    UserMonthlyCredit.bonus_compute_credit
                ),
                0
            ).label("compute_allocated"),

            # AVATAR
            func.coalesce(
                func.sum(UserMonthlyCredit.avatar_credit_used),
                0
            ).label("avatar_used"),

            func.coalesce(
                func.sum(UserMonthlyCredit.avatar_credit_allocated),
                0
            ).label("avatar_allocated"),
            func.coalesce(
                func.sum(UserMonthlyCredit.input_tokens_used),
                0
            ).label("input_tokens_used"),

            func.coalesce(
                func.sum(UserMonthlyCredit.output_tokens_used),
                0
            ).label("output_tokens_used"),

            func.coalesce(
                func.sum(UserMonthlyCredit.stt_minutes_used),
                0
            ).label("stt_minutes_used"),

            func.coalesce(
                func.sum(UserMonthlyCredit.tts_minutes_used),
                0
            ).label("tts_minutes_used"),
            func.bool_or(
                case(
                    (UserMonthlyCredit.is_active.is_(True), UserMonthlyCredit.compute_access),
                    else_=False
                )
            ).label("compute_access"),

            func.bool_or(
                case(
                    (UserMonthlyCredit.is_active.is_(True), UserMonthlyCredit.avatar_access),
                    else_=False
                )
            ).label("avatar_access"),
        )
        .join(UserMonthlyCredit, UserMonthlyCredit.user_id == User.id)
        .join(Organization, Organization.id == User.organization_id)
        .join(Profile, Profile.user_id == User.id)
    )

    # Apply date filter
    if start_date and end_date:
        query = query.filter(
            UserMonthlyCredit.start_date >= start_date,
            UserMonthlyCredit.start_date < end_date
        )

    # Search
    if search:
        query = query.filter(
            func.lower(Profile.full_name).like(f"%{search.lower()}%") |
            func.lower(User.email).like(f"%{search.lower()}%")
        )
                # func.lower(Organization.name).like(f"%{search_query.lower()}%")

    query = query.group_by(
        User.id,
        Profile.full_name,
        User.email,
        User.user_type,
        UserMonthlyCredit.created_at
    )

    results = query.order_by(UserMonthlyCredit.created_at.desc()).all()

    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "User ID",
        "Full Name",
        "Email",
        "Role",
        "Compute Used",
        "Compute Allocated",
        "Avatar Used",
        "Avatar Allocated",
        "Input Tokens",
        "Output Tokens",
        "STT Minutes",
        "TTS Minutes",
    ])

    # Rows
    for r in results:
        writer.writerow([
            r.user_id,
            r.full_name,
            r.email,
            r.user_type,
            r.compute_used,
            r.compute_allocated,
            r.avatar_used,
            r.avatar_allocated,
            r.input_tokens_used,
            r.output_tokens_used,
            r.stt_minutes_used,
            r.tts_minutes_used,
        ])

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=user_leaderboard.csv"
        },
    )
    

async def require_avatar_and_compute_access(
    user_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    logger.info(f"Checking avatar and compute access for user_id={user_id}")
    try:
        credit = (
            db.query(UserMonthlyCredit)
            .filter(
                UserMonthlyCredit.user_id == current_user.id,
                UserMonthlyCredit.is_active.is_(True),
        )
        .first()
        )

        avatar_access = credit.avatar_access if credit else False
        compute_access = credit.compute_access if credit else False

        logger.info(f"Successfully fetched avatar and compute access for user_id={user_id}")

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content = jsonable_encoder({
                "status": "success",
                "message": "Avatar and Compute access fetched successfully.",
                "data":  {
                        "avatar_access": avatar_access,
                        "compute_access": compute_access,
                    }
                })
            )

    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"Unexpected error in require_avatar_and_compute_access for user_id={user_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Unexpected error occurred while checking access.",
                "data": None
            }
        )