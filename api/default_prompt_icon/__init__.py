from fastapi import APIRouter, UploadFile, File, Depends
from typing import List
from api.default_prompt_icon.default_icons import upload_prompt_icons, get_prompt_icons
from connection import get_db
from sqlalchemy.orm import Session
from utils.utils import get_current_user

default_prompt_icon_router = APIRouter()

@default_prompt_icon_router.post("/upload-prompt-icons")
async def upload_prompt_icon_api(
    prompt_icons: List[UploadFile] = File(...)):
    return await upload_prompt_icons(prompt_icons)


@default_prompt_icon_router.get("/get-prompt-icons")
async def get_prompt_icons_api(
    db: Session = Depends(get_db),
    current_user: Session = Depends(get_current_user)
):
    return await get_prompt_icons(db, current_user)