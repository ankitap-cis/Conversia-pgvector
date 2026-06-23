from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from api.auth.permission import require_permission
from connection import get_db
from schemas.user_management_schema import CompanyContextForm, EditOrganizationForm, ImpersonateForm, SalesRepsForm, SessionLogCreateUpdate, UpdateUser
from utils.utils import check_admin_role, check_superadmin_role, get_current_user
from api.user_management.user_management import (
    get_company_context,
    get_user_profile,
    set_company_context,
    update_company_context, 
    update_user_profile,
    create_org_members,
    edit_org_member_role,
    get_org_members,
    get_sales_rep,
    remove_sales_rep,
    get_organizations,
    update_organization_data,
    get_organization,
    get_field_managers,
    impersonate_user,
    stop_impersonation,
    create_update_session_log,
    get_organization_session_logs
)


user_management_router = APIRouter()


@user_management_router.get("/get-user-profile/{user_id}")
async def get_user_profile_api(user_id: int, db : Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    return await get_user_profile(user_id, db, current_user)


@user_management_router.post("/update-user-profile/{user_id}")
async def update_user_profile_api(user_id: int, update_user: UpdateUser, db : Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    return await update_user_profile(user_id, update_user, db, current_user)


@user_management_router.post("/create-sales-reps")
async def create_org_members_api(sales_reps: SalesRepsForm, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("user_management.create")):
    return await create_org_members(sales_reps, db, current_user)


@user_management_router.post("/edit-sales-reps/{reps_id}")
async def edit_org_members_api(reps_id: int, sales_reps: SalesRepsForm, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user),  _ = require_permission("user_management.update")):
    return await edit_org_member_role(reps_id, sales_reps, db, current_user)


@user_management_router.get("/get-sales-reps")
async def get_org_members_api(search_query: Optional[str] = None, limit: int = 10, offset:int = 0, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("user_management.list")):
    return await get_org_members(search_query, limit, offset, db, current_user)


@user_management_router.get("/get-sales-rep/{rep_id}")
async def get_sales_rep_api(rep_id: int, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("user_management.get")):
    return await get_sales_rep(rep_id, db, current_user)


@user_management_router.post("/remove-sales-rep/{rep_id}")
async def remove_sales_rep_api(rep_id: int, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("user_management.delete")):
    return await remove_sales_rep(rep_id, db, current_user)


@user_management_router.get("/get-organizations")
async def get_organizations_api(search_query: Optional[str] = None, limit:int = 10, offset:int = 0, db: Session = Depends(get_db), current_user: Session = Depends(check_superadmin_role)):
    return await get_organizations(search_query, limit, offset, db, current_user)


@user_management_router.post("/update-organization-data/{organization_id}")
async def update_organization_data_api(organization_id: int, form: EditOrganizationForm, db: Session = Depends(get_db), current_user: Session = Depends(check_superadmin_role)):
    return await update_organization_data(organization_id, form, db, current_user)


@user_management_router.get("/get-organizations/{organization_id}")
async def get_organization_api(organization_id: int, db: Session = Depends(get_db), current_user: Session = Depends(check_superadmin_role)):
    return await get_organization(organization_id, db, current_user)


@user_management_router.get("/get-field-managers")
async def get_field_managers_api(db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("field_manager.list")):
    return await get_field_managers(db, current_user)


@user_management_router.post("/impersonate")
async def impersonate_user_api(data: ImpersonateForm, db: Session = Depends(get_db), current_user: Session = Depends(check_superadmin_role)):
    return await impersonate_user(data, db, current_user)


@user_management_router.post("/impersonate-stop")
async def stop_impersonation_api(db: Session = Depends(get_db), current_user = Depends(check_superadmin_role)):
    return await stop_impersonation(db, current_user)

# roles permission left
@user_management_router.post("/session-logs")
async def create_update_session_log_api(payload: SessionLogCreateUpdate, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    return await create_update_session_log(payload, db, current_user)


@user_management_router.get("/get-session-log")
async def get_session_log_api(db: Session = Depends(get_db), current_user: dict = Depends(check_admin_role)):
    return await get_organization_session_logs(db, current_user)


@user_management_router.post("/trigger-monthly-reset")
async def trigger_monthly_reset():
    from utils.workers import monthly_credit_reset_task
    monthly_credit_reset_task.delay()
    return {"message": "Monthly credit reset triggered"}



@user_management_router.post("/add-company-context")
async def set_company_context_api(company_data: CompanyContextForm, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    print(company_data)
    return await set_company_context(company_data, db, current_user)


@user_management_router.put("/update-company-context")
async def update_company_context_api(company_data: CompanyContextForm, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    return await update_company_context(company_data, db, current_user)


@user_management_router.get("/get-company-context")
async def get_company_context_api(db: Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    return await get_company_context(db, current_user)