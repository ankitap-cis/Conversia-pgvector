from datetime import date
from fastapi import APIRouter, Depends, File, Query, UploadFile, Request
from fastapi.params import Form
from sqlalchemy.orm import Session
from api.auth.permission import require_permission
from connection import get_db
from schemas.knowledgebase_schema import BulkDeletionForm, BulkPriorityForm, SetPriorityForm
from utils.s3_bucket_helper import generate_presigned_url, get_s3_client
from utils.utils import get_current_user
from typing import List, Optional
from fastapi.responses import StreamingResponse
from .knowledge_base import(
    upload_file,
    get_uploaded_file,
    remove_uploaded_file,
    get_all_uploads,
    update_priority,
    update_bulk_priority,
    bulk_deletion_files,
    create_upload_session,
    generate_upload_status_events
)


file_upload_router = APIRouter()


# Bulk file upload feature

@file_upload_router.post("/createupload-session/")
async def create_upload_session_api(db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("knowledgebase.create")):
    return await create_upload_session(db, current_user)

@file_upload_router.post('/upload-file')
async def upload_file_api(
    files: List[UploadFile] = File(...),
    session_id: str = Form(...),
    db: Session = Depends(get_db),
    current_user: Session = Depends(get_current_user),
    _ = require_permission("knowledgebase.create")
):
    return await upload_file(files,session_id, db, current_user)
 

@file_upload_router.get("/get-file/{file_id}")
async def get_uploaded_file_api(file_id: int, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("knowledgebase.get")):
    return await get_uploaded_file(file_id, db, current_user)
 
 
@file_upload_router.delete("/remove-file/{file_id}")
async def remove_uploaded_file_api(file_id: int, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("knowledgebase.delete")):
    return await remove_uploaded_file(file_id,db, current_user)
 
 
@file_upload_router.get("/get-files")
async def get_all_uploads_api(
    search_query: Optional[str] = None,
    file_name: Optional[str] = Query(None),
    file_type: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    limit: int = 10,
    offset:int = 0,
    db: Session = Depends(get_db),
    current_user: Session = Depends(get_current_user),
    _ = require_permission("knowledgebase.list")):
    return await get_all_uploads(search_query, file_name, file_type, priority, date_from, date_to, limit, offset, db, current_user)


@file_upload_router.post("/update-priority/{file_id}")
async def update_priority_api(file_id: int, form: SetPriorityForm, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("knowledgebase.update")):
    return await update_priority(file_id, form, db, current_user)


@file_upload_router.post("/update-bulk-priority")
async def update_bulk_priority_api(form: BulkPriorityForm, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("knowledgebase.update")):
    return await update_bulk_priority(form, db, current_user)


@file_upload_router.delete("/remove-files")
async def bulk_deletion_files_api(form: BulkDeletionForm, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("knowledgebase.delete")):
    return await bulk_deletion_files(form, db, current_user)


@file_upload_router.get("/generate-presigned-url/")
async def generate_presigned_url_api(key: str = Query(..., description="S3 object key (path inside bucket)"),
                           expires_in: int = 900):
    '''
    Generate a presigned URL for a private S3 object
    - key: path inside bucket (e.g., Organizations/36/courses/images/myfile.png)
    - expires_in: URL expiration time in seconds (default: 900 = 15 minutes)
    '''
    s3_client = await get_s3_client()

    url = await generate_presigned_url(s3_client, key, expires_in)
    return url


@file_upload_router.get("/upload/stream/{session_id}")
async def stream_session_status(
    session_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Session = Depends(get_current_user),
):
    return StreamingResponse(
        generate_upload_status_events(
            session_id=session_id,
            request=request,
            db=db,
            current_user=current_user
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )