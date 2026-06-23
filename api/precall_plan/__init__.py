import json
from typing import List, Optional, Union
from fastapi import APIRouter, Depends, File, Form, UploadFile
from requests import Session
from api.auth.permission import require_permission
from api.precall_plan.export_precall_plan import export_precall_plan_report, send_feedback_report, send_debrief_feedback_report
from connection import get_db
from schemas.precall_plan_schema import CreatePreCallForm, EvaluationPayload, Section
from utils.utils import check_admin_role, get_current_user
from .precall_plan import precall_plan_form, get_precall_plan_form


precall_plan_router = APIRouter()


@precall_plan_router.post("/create-precall-plan-form")
async def precall_plan_form_api(
    fields: str = Form(...),
    file: Optional[Union[UploadFile, str]] = File(None),
    db: Session = Depends(get_db),
    current_user: Session= Depends(check_admin_role),
    _ = require_permission("precallplan.create")
):
    form = CreatePreCallForm(**json.loads(fields))
    return await precall_plan_form(form, file, db, current_user)


@precall_plan_router.get("/get-precall-plan-form")
async def get_precall_plan_form_api(db: Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    return await get_precall_plan_form(db, current_user)


@precall_plan_router.post("/export-precall-plan-report")
async def export_precall_plan_report_api(sections: List[Section], current_user: Session = Depends(get_current_user)):
    return await export_precall_plan_report(sections, current_user)


@precall_plan_router.post("/send-feedback")
async def send_feedback_report_api(sections: List[Section], feedback: str = None, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await send_feedback_report(sections, feedback, db, current_user)



@precall_plan_router.post("/send-feedback/debrief")
async def send_debrief_feedback_report_api(payload: EvaluationPayload, feedback: str = None, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await send_debrief_feedback_report(payload, feedback, db, current_user)
