from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, Query
from requests import Session

from api.ai_consumption.ai_token_credit import deduct_ai_credits, deduct_avatar_minutes, fetch_global_credit, global_credit_setup, reinstate_user_credits, suspend_user_credits
from api.ai_consumption.ai_token_logs import get_audit_logs, log_bonus_cap, log_monthly_cap, log_prorated_cap
from api.ai_consumption.superadmin_token_dashboard import admin_token_consumption_dashboard, require_avatar_and_compute_access, user_leaderboard, user_consumption_data, export_user_leaderboard_csv
from connection import get_db
from schemas.authentication_schema import CreditForm
from utils.utils import check_superadmin_role, get_current_user


ai_consumption_router = APIRouter()


@ai_consumption_router.get("/ai-consumption-dashboard")
async def admin_token_dashboard_api(
    timeframe: str = 'this_month',
    db: Session = Depends(get_db),
    current_user: Session = Depends(check_superadmin_role)
):
    return await admin_token_consumption_dashboard(timeframe, db, current_user)


@ai_consumption_router.get("/user-leaderboard")
async def user_leaderboard_api(
    search_query: str | None = None,
    timeframe: str = 'this_month',
    limit: int = 10,
    offset :int = 0, 
    db: Session = Depends(get_db), 
    current_user: Session = Depends(check_superadmin_role)
):
    return await user_leaderboard(search_query, timeframe, limit, offset, db, current_user)


@ai_consumption_router.get("/user-leaderboard/{user_id}")
async def user_consumption_data_api(user_id: int, db: Session =Depends(get_db), current_user: Session = Depends(check_superadmin_role)):
    return await user_consumption_data(user_id, db, current_user)


@ai_consumption_router.post("/reinstate")
async def reinstate_user_credits_api(
    user_id: int,
    credit_type: str,  # "compute" or "avatar"
    bonus_amount: Decimal | None = None,  # optional manual override
    reinstate_only: bool = False,
    db: Session = Depends(get_db),
    current_user: Session = Depends(check_superadmin_role)
):
    return await reinstate_user_credits(user_id, credit_type, bonus_amount, reinstate_only, db, current_user)


@ai_consumption_router.post("/suspend")
async def reinstate_user_credits_api(
    user_id: int,
    credit_type: str,  # "compute" or "avatar"
    db: Session = Depends(get_db),
    current_user: Session = Depends(check_superadmin_role)
):
    return await suspend_user_credits(user_id, credit_type, db, current_user)




@ai_consumption_router.post("/global-credit-setup")
async def global_credit_setup_api(credit_form: CreditForm, db: Session = Depends(get_db), current_user: Session = Depends(check_superadmin_role)):
    return await global_credit_setup(credit_form, db, current_user)


@ai_consumption_router.get("/fetch-global-credit")
async def fetch_global_credit_api(db: Session = Depends(get_db), current_user: Session = Depends(check_superadmin_role)):
    return await fetch_global_credit(db, current_user)


@ai_consumption_router.get("/user-leaderboard-data/export")
async def export_user_leaderboard_csv_api(timeframe: str = 'this_month', search: str | None = None, db: Session = Depends(get_db), current_user: Session = Depends(check_superadmin_role)):
    return await export_user_leaderboard_csv(timeframe, search, db, current_user)


@ai_consumption_router.get("/audit-logs")
async def get_audit_logs_api(
    search: str | None = None,
    action_type: str | None = None,
    limit: int = 10,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: Session = Depends(check_superadmin_role)
):
    return await get_audit_logs(search, action_type, limit, offset, db, current_user)


@ai_consumption_router.post("/test-deduct")
async def test_deduct_ai_credits(
    user_id: int = Query(...),

    input_tokens: int = Query(0),
    output_tokens: int = Query(0),

    stt_minutes: Decimal = Query(Decimal("0")),
    tts_minutes: Decimal = Query(Decimal("0")),

    db: Session = Depends(get_db),
):
    return await deduct_ai_credits(
        db=db,
        user_id=user_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        stt_minutes=stt_minutes,
        tts_minutes=tts_minutes,
    )
    

@ai_consumption_router.get("/check-media-credits")
async def require_avatar_and_compute_access_api(
    user_id: int = Query(...),
    db: Session = Depends(get_db),
    current_user: Session = Depends(get_current_user)
):
    return await require_avatar_and_compute_access(user_id, db, current_user)


@ai_consumption_router.post("/test-deduct-avatar")
async def test_deduct_ai_avatar(
    user_id: int = Query(...),
    avatar_minutes:Decimal = Query(Decimal("0")),
    db: Session = Depends(get_db),
):
    return await deduct_avatar_minutes(
        db=db,
        user_id=user_id,
        avatar_minutes=avatar_minutes
    )


@ai_consumption_router.post("/audit/test")
async def test_audit_logs(
    actor_name: str,
    user_id: int,
    target_name,
    compute_cap: Optional[int] = None,
    avatar_cap: Optional[int] = None,
    actor_id: Optional[int] = None,
    days_remaining: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: Session = Depends(check_superadmin_role)
):
    # Test prorated cap log
    # await log_prorated_cap(actor_id, actor_name, user_id, target_name, compute_cap, avatar_cap, days_remaining, db, current_user)

    # Test monthly cap log
    # await log_monthly_cap(actor_id, actor_name, user_id, target_name, compute_cap, avatar_cap, db, current_user)

    await log_bonus_cap(actor_id, actor_name, user_id, target_name, db, current_user, compute_cap, avatar_cap)

    return {"message": "Audit logs created successfully"}
