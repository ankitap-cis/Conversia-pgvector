from fastapi import APIRouter, UploadFile, File, HTTPException, status, Depends
from typing import List
from sqlalchemy.orm import Session
from api.default_scenario_images.default_images import get_scenario_images, upload_scenario_images
from utils.utils import check_admin_role, get_current_user
from connection import get_db
default_image_router = APIRouter()

@default_image_router.post("/upload-scenario-images")
async def upload_scenario_images_api(
    scenario_images: List[UploadFile] = File(...)):
    return await upload_scenario_images(scenario_images)

@default_image_router.get("/get-scenario-images")
async def get_scenario_images_api(
    db: Session = Depends(get_db),
    current_user: Session = Depends(get_current_user),
):
    return await get_scenario_images(db, current_user)