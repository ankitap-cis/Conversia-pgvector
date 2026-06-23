from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from api.auth.permission import require_permission
from api.evaluation_criteria.evaluation_criteria import (
    create_eval_criteria, 
    edit_eval_criteria, 
    get_all_eval_criteria, 
    get_eval_criteria,
    delete_eval_criteria,
    get_unique_eval_title
)
from connection import get_db
from schemas.evaluation_schema import EvaluationSchema
from utils.utils import check_admin_role, get_current_user


eval_criteria_router = APIRouter()


@eval_criteria_router.post('/create-eval-criteria')
async def create_eval_criteria_api(eval_criteria: EvaluationSchema, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("evaluation.create")):
    return await create_eval_criteria(eval_criteria, db, current_user)


@eval_criteria_router.put("/edit-eval-criteria/{criteria_id}")
async def edit_eval_criteria_api(criteria_id: int, eval_criteria: EvaluationSchema, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("evaluation.update")):
    return await edit_eval_criteria(criteria_id, eval_criteria, db, current_user)


@eval_criteria_router.get("/get-all-eval-criteria")
async def get_all_eval_criteria_api(search_query: Optional[str] = None, limit: int = 10, offset: int = 0, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("evaluation.list")):
    return await get_all_eval_criteria(search_query, limit, offset, db, current_user)


@eval_criteria_router.get("/get-eval-criteria/{criteria_id}")
async def get_eval_criteria_api(criteria_id: int, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("evaluation.get")):
    return await get_eval_criteria(criteria_id, db, current_user)


@eval_criteria_router.delete("/delete-eval-criteria/{criteria_id}")
async def delete_eval_criteria_api(criteria_id: int , db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("evaluation.delete")):
    return await delete_eval_criteria(criteria_id, db, current_user)


@eval_criteria_router.get("/get-evaluation-list")
async def get_evaluation_list_api(db: Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    return await get_unique_eval_title(db, current_user)
