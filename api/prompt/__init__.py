from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session

from connection import get_db
from utils.utils import check_superadmin_role, get_current_user
from models.users import User
from schemas.prompt_schema import (
    CreatePromptMasterForm,
    UpdatePromptMasterForm,
    UpdateUserPromptForm,
)
from api.prompt.prompt_master import (
    create_prompt_master,
    update_prompt_master,
    get_prompt_masters,
    get_prompt_master,
    delete_prompt_master,
)
from api.prompt.user_prompt import (
    update_user_prompt,
    get_user_prompts,
    get_user_prompt,
    delete_user_prompt,
)


prompt_router = APIRouter()


@prompt_router.post("/master-prompts", status_code=status.HTTP_201_CREATED)
async def create_master_prompt(
    prompt_data: CreatePromptMasterForm,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_superadmin_role),
):
    return await create_prompt_master(prompt_data, db, current_user)


@prompt_router.get("/master-prompts")
async def list_master_prompts(
    search_query: str = Query(None, description="Search in title and description"),
    category: str = Query(None, description="Filter by category"),
    limit: int = Query(10, ge=1, le=100, description="Number of results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
    current_user: User = Depends(check_superadmin_role),
):
    return await get_prompt_masters(
        search_query=search_query,
        category=category,
        limit=limit,
        offset=offset,
        db=db,
        current_user=current_user,
    )


@prompt_router.get("/master-prompts/{prompt_id}")
async def get_master_prompt_detail(
    prompt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_superadmin_role),
):
    return await get_prompt_master(prompt_id, db, current_user)


@prompt_router.put("/master-prompts/{prompt_id}")
async def update_master_prompt(
    prompt_id: int,
    prompt_data: UpdatePromptMasterForm,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_superadmin_role),
):
    return await update_prompt_master(prompt_id, prompt_data, db, current_user)


@prompt_router.delete("/master-prompts/{prompt_id}")
async def delete_master_prompt(
    prompt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_superadmin_role),
):
    return await delete_prompt_master(prompt_id, db, current_user)


@prompt_router.get("/user-prompts")
async def list_user_prompts(
    search_query: str = Query(None, description="Search in title and description"),
    category: str = Query(None, description="Filter by category"),
    limit: int = Query(10, ge=1, le=100, description="Number of results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await get_user_prompts(
        search_query=search_query,
        category=category,
        limit=limit,
        offset=offset,
        db=db,
        current_user=current_user,
    )


@prompt_router.get("/user-prompts/{prompt_id}")
async def get_user_prompt_detail(
    prompt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await get_user_prompt(prompt_id, db, current_user)


@prompt_router.put("/user-prompts/{prompt_id}")
async def update_existing_user_prompt(
    prompt_id: int,
    prompt_data: UpdateUserPromptForm,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await update_user_prompt(prompt_id, prompt_data, db, current_user)


@prompt_router.delete("/user-prompts/{prompt_id}")
async def delete_existing_user_prompt(
    prompt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await delete_user_prompt(prompt_id, db, current_user)
