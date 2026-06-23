from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import case, desc
from sqlalchemy.orm import aliased
from models.precall_plan_models import KnowledgeBase
from datetime import datetime, timedelta
from logger import *
import uuid
from uuid import UUID
from schemas.knowledgebase_schema import KnowledgeBaseResponse
from utils.s3_bucket_helper import delete_file_from_s3
from api.roleplay_assistant import get_general_bot
from models.users import Organization, User
import os
from urllib.parse import urlparse
import asyncio, json
from utils.workers import upload_file_to_s3_task


async def format_file_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} Bytes"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024 ** 2):.2f} MB"
    else:
        return f"{size_bytes / (1024 ** 3):.2f} GB"

async def create_upload_session(db, current_user):
    try:
        session_id = str(uuid.uuid4())
        logger.info(f"Created upload session {session_id} for {current_user.email}")

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Upload session created",
                "data": {
                    "session_id": session_id
                }
            }
        )
    except Exception as e:
        logger.error(f"Error creating session: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failure", "message": "Failed to create upload session", "data": None}
        )

async def upload_file(files, session_id, db, current_user):
    logger.info(f"Uploading files by admin {current_user.email}")
    try:
        if current_user.user_type in ["org_admin", "content_creator"]:
            organization = db.query(Organization).filter(Organization.id == current_user.organization_id).first()

        logger.info(f"Uploading file by admin {current_user.email}")  

        responses = []
        failed_files = []
        parsed_session_id = UUID(session_id) if session_id else uuid.uuid4()

        allowed_types = ["txt", "pdf", "docx", "doc", "ppt", "pptx", "xlsx", "csv", "xls"]
        for file in files:
            contents = await file.read()
            file_size = len(contents)
            formatted_file_size = await format_file_size(file_size)
        
            file_id = None
            
            try:
                logger.info(f"Uploading file {file.filename} by admin {current_user.email}")

                allowed_types = ["txt", "pdf", "docx", "doc", "ppt", "pptx", "xlsx", "csv", "xls"]
                if "." not in file.filename:
                    raise ValueError("Invalid file name format")

                name, file_type = file.filename.rsplit(".", 1)
                if file_type.lower() not in allowed_types:
                    logger.warning(f"Unsupported file type attempted: {file_type}")
                    failed_files.append({
                        "filename": file.filename,
                        "reason": "Unsupported file type"
                    })
                    continue

                # Create initial entry with "queued" status
                new_entry = KnowledgeBase(
                    admin_id=current_user.id,
                    name=name,
                    file_type=file_type,
                    file_path="",  # Will be updated after upload
                    priority=0,
                    uploaded_by=current_user.email,
                    uploaded_at=datetime.now(),
                    status="queued",
                    session_id=parsed_session_id,
                    reason=None,
                    file_size=formatted_file_size
                )
                db.add(new_entry)
                db.commit()
                db.refresh(new_entry)
                file_id = new_entry.id
                logger.info(f"Created file entry {file_id} with status 'queued' for file {file.filename}")

                # Prepare S3 key
                s3_key = f"Organizations/{current_user.organization_id}/knowledgebase/{file.filename}"
                
                # Read file content for Celery task
                
                # Trigger S3 upload task asynchronously (no await)
                upload_file_to_s3_task.delay(
                    kb_id=new_entry.id,
                    user_id=current_user.id,
                    org_id=organization.id,
                    s3_key=s3_key,
                    file_content=contents,
                    file_name=file.filename,
                    content_type=file.content_type or "application/octet-stream"
                )
                logger.info(f"Triggered S3 upload task for file {file.filename} (KB ID: {file_id})")

                responses.append({
                    "file_id": new_entry.id,
                    "filename": name,
                    "status": "processing"
                })

            except Exception as e:
                logger.error(f"Error uploading {file.filename}: {str(e)}")
                # Update status to "failed" if file entry was created
                if file_id:
                    try:
                        file_entry = db.query(KnowledgeBase).filter(KnowledgeBase.id == file_id).first()
                        if file_entry:
                            file_entry.status = "failed uploading"
                            file_entry.reason = str(e)
                            db.commit()
                            logger.error(f"Updated file {file_id} status to 'failed': {str(e)}")
                    except Exception as db_error:
                        logger.error(f"Failed to update file status: {str(db_error)}")
                
                failed_files.append({
                    "filename": file.filename,
                    "reason": str(e)
                })
                continue

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "partial_success" if failed_files else "success",
                "message": "Some files failed to upload" if failed_files else "All files uploaded successfully",
                "data": {
                    "uploaded": responses,
                    "failed": failed_files
                }
            }
        )

    except Exception as e:
        logger.error(str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occured while uploading files",
                "data": None
            }
        )


async def get_uploaded_file(file_id, db, current_user):
    logger.info(f"Admin {current_user.email} requested file path for file ID: {file_id}")
 
    file_entry = db.query(KnowledgeBase).filter(KnowledgeBase.id == file_id).first()
 
    if not file_entry:
        logger.warning(f"File not found in DB for ID: {file_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "status": "failure",
                "message": "File not found.",
                "data": None
            }
        )
 
    data = KnowledgeBaseResponse.from_orm_model(file_entry).model_dump(mode="json")
 
    logger.info(f"Returning file path: {data['file_path']}")
 
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "success",
            "message": "File fetched successfully",
            "data": data
        }
    )
 
 
async def remove_uploaded_file(file_id, db, current_user):
    try:
        logger.info(f"Removing uploaded file by user {current_user.email}")
        file_record = db.query(KnowledgeBase).filter(KnowledgeBase.id == file_id).first()
 
        if not file_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                "status": "failure",
                "message": "File not found.",
                "data": None
            }
        )
 
        # S3 deletion
        if file_record.file_path:
            deletion_successful = await delete_file_from_s3(file_record.file_path)
         
            if not deletion_successful:
                logger.error("S3 deletion failed. Aborting DB delete.")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "status": "failure",
                        "message": "S3 file deletion failed. DB record not deleted.",
                        "data": None
                    }
                )

        else:
            logger.error(f"S3 file path not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "S3 file path not found.",
                    "data": None
                }
            )


        def extract_filename_from_url(url: str) -> str:
            return os.path.basename(urlparse(url).path)

        file_path = extract_filename_from_url(file_record.file_path)

        chatbot = get_general_bot(str(current_user.id))
        chatbot.delete_document(file_path)
 
        db.delete(file_record)
        db.commit()
 
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "File deleted successfully.",
                "data": file_id
            }
        )
 
    except HTTPException as http_exc:
        raise http_exc
 
    except Exception as e:
        logger.error(str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Internal server error",
                "data": None
            }
        )
 
 
async def get_all_uploads(search_query, file_name, file_type, priority, date_from, date_to, limit, offset, db, current_user):
    logger.info(f"Fetching files by admin: {current_user.email}")
    try:
        Creator = aliased(User)
        query = db.query(KnowledgeBase).join(Creator, Creator.email == KnowledgeBase.uploaded_by)

        query = query.filter(Creator.organization_id == current_user.organization_id, KnowledgeBase.file_path != None)

        if search_query:
            ilike_pattern = f"%{search_query}%"
            query = query.filter(KnowledgeBase.name.ilike(ilike_pattern))

        if file_name:
            query = query.filter(KnowledgeBase.name.ilike(f"%{file_name}%"))

        if file_type:
            query = query.filter(KnowledgeBase.file_type == file_type)

        if priority:
            query = query.filter(KnowledgeBase.priority == priority)

        if date_from:
            query = query.filter(KnowledgeBase.uploaded_at >= date_from)

        if date_to:
            query = query.filter(KnowledgeBase.uploaded_at <= date_to + timedelta(days=1))
        
        total = query.count()
        priority_case = case((KnowledgeBase.priority == 0, 1), else_=0)

        files = (
            query
            .order_by(priority_case, KnowledgeBase.priority.asc(), desc(KnowledgeBase.uploaded_at))
            .limit(limit)
            .offset(offset)
            .all()
        )
        if not files:
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "success",
                    "message": "No files found.",
                    "data": []
                }
            )

        
        data = [KnowledgeBaseResponse.from_orm_model(file).model_dump(mode="json") for file in files]

        logger.info(f"Files fetched successfully by admin: {current_user.email}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Files fetched successfully",
                "data": {"content": data, "total": total}
            }
        )

    except Exception as e:
        logger.error(str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occured while fetching files",
                "data": None
            }
        )


async def update_priority(file_id, form, db, current_user):
    logger.info(f"Updating priority of file by admin: {current_user.email}")
    try:

        if current_user.user_type in ["org_admin", "content_creator"]:
            organization = db.query(Organization).filter(Organization.id == current_user.organization_id).first()       

        file = db.query(KnowledgeBase).filter_by(id = file_id).first()
        if not file:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "No file found",
                    "data": None
                }
            )
        
        file.priority = form.priority
        db.commit()

        chatbot = get_general_bot(str(current_user.id))
        chatbot.update_vectorstore_document(file.file_path, form.priority, org_id = organization.id)

        logger.info(f"Priority updated successfully of file id {file_id} by {current_user.email}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Priority updated successfully.",
                "data": None
            }
        )
    
    except HTTPException as http_exe:
        raise http_exe

    except Exception as e:
        logger.error(str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occured while updating priority",
                "data": None
            }
        )


async def update_bulk_priority(form, db, current_user):
    logger.info(f"Updating priority of files {form.file_ids} to {form.priority} by admin {current_user.email}")
    try:

        if current_user.user_type in ["org_admin", "content_creator"]:
            organization = db.query(Organization).filter(Organization.id == current_user.organization_id).first()

        files = db.query(KnowledgeBase).filter(KnowledgeBase.id.in_(form.file_ids)).all()
        if not files:
            logger.warning("No file founds with provided ids")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "No file founds with provided ids",
                    "data": None
                }
            )
        
        for file in files:
            file.priority = form.priority
            chatbot = get_general_bot(str(current_user.id))
            chatbot.update_vectorstore_document(file.file_path, form.priority, org_id=organization.id)
        
        db.commit()
        
        logger.info(f"Priority updated successfully for file ids: {', '.join(map(str, form.file_ids))} by {current_user.email}")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Priorities updated successfully.",
                "data": None
            }
        )
    
    except HTTPException as http_exe:
        raise http_exe

    except Exception as e:
        logger.error(str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occurred while updating priorities",
                "data": None
            }
        )


async def bulk_deletion_files(form, db, current_user):
    logger.info(f"Bulk removing uploaded files by user {current_user.email}")
    try:
        files = db.query(KnowledgeBase).filter(KnowledgeBase.id.in_(form.file_ids)).all()
        if not files:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "No files found with provided IDs.",
                    "data": None
                }
            )
        
        deleted_ids = []
        failed_ids = []

        for file in files:
            try:
                if file.file_path:
                    deletion_successfull = await delete_file_from_s3(file.file_path)
                    if not deletion_successfull:
                        logger.error(f"S3 deletion failed for file {file.id}")
                        failed_ids.append(file.id)
                        continue

                db.delete(file)
                deleted_ids.append(file.id)

                def extract_filename_from_url(url: str) -> str:
                    return os.path.basename(urlparse(url).path)

                file_path = extract_filename_from_url(file.file_path)
                chatbot = get_general_bot(str(current_user.id))
                chatbot.delete_document(file_path)
            
            except Exception as inner_e:
                logger.error(f"Failed to delete file {file.id}: {str(inner_e)}")
                failed_ids.append(file.id)
        
        db.commit()

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "partial_success" if failed_ids else "success",
                "message": "Some files could not be deleted." if failed_ids else "All files deleted successfully.",
                "data": {
                    "deleted_ids": deleted_ids,
                    "failed_ids": failed_ids
                }
            }
        )
    
    except HTTPException as http_exc:
        raise http_exc

    except Exception as e:
        logger.error(f"Bulk deletion failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Internal server error during bulk file deletion.",
                "data": None
            }
        )


ACTIVE_STATUSES = {"queued", "uploaded", "processing"}


def _get_stage_description(status: str) -> str:
    stage_map = {
        "queued": "Queued for upload",
        "uploaded": "File uploaded",
        "processing": "Processing file",
        "completed": "Upload completed",
        "failed uploading": "Failed to upload",
        "failed processing": "Failed to process",
    }

    return stage_map.get(status, "Unknown status")


ACTIVE_STATUSES = ["queued", "uploading", "uploaded", "processing"]

FAILED_STATUSES = [
    "failed uploading",
    "failed processing",
    "failed indexing",
    "timeout"
]

FINAL_STATUSES = [
    "completed",
    *FAILED_STATUSES
]

MAX_STREAM_SECONDS = 300
STALE_STATUS_MINUTES = 10
POLL_INTERVAL = 3


def _is_stale(file):
    check_time = file.uploaded_at

    if not check_time:
        return False

    return (
        file.status in ACTIVE_STATUSES
        and check_time < datetime.now() - timedelta(minutes=STALE_STATUS_MINUTES)
    )


async def generate_upload_status_events(session_id, request, db, current_user):
    started_at = datetime.now()

    while True:
        if await request.is_disconnected():
            logger.info(f"[UPLOAD_STATUS] Client disconnected: {session_id}")
            break

        db.expire_all()

        files = (
            db.query(KnowledgeBase)
            .filter(
                KnowledgeBase.session_id == session_id,
                KnowledgeBase.admin_id == current_user.id
            )
            .all()
        )

        # Fallback 1: mark stale active files as timeout
        for file in files:
            if _is_stale(file):
                file.status = "timeout"
                file.reason = (
                    "Upload/indexing took too long or worker did not complete. "
                    "Please retry upload."
                )
                db.commit()
                logger.warning(
                    f"[UPLOAD_STATUS] KB {file.id} marked as timeout"
                )

        db.expire_all()

        files = (
            db.query(KnowledgeBase)
            .filter(
                KnowledgeBase.session_id == session_id,
                KnowledgeBase.admin_id == current_user.id
            )
            .all()
        )

        active = []
        completed = []
        failed = []

        for file in files:
            entry = {
                "file_id": file.id,
                "filename": file.name,
                "file_type": file.file_type,
                "status": file.status,
                "stage": _get_stage_description(file.status),
            }

            if file.status in ACTIVE_STATUSES:
                active.append(entry)

            elif file.status == "completed":
                completed.append({
                    **entry,
                    "file_path": file.file_path
                })

            elif file.status in FAILED_STATUSES:
                failed.append({
                    **entry,
                    "reason": file.reason
                })

        total = len(files)

        session_complete = (
            total > 0 and
            (len(completed) + len(failed)) == total
        )

        # Fallback 2: hard stop SSE after max time
        stream_timed_out = (
            datetime.now() - started_at
        ).total_seconds() > MAX_STREAM_SECONDS

        payload = {
            "session_complete": session_complete or stream_timed_out,
            "stream_timeout": stream_timed_out,
            "summary": {
                "total": total,
                "active": len(active),
                "completed": len(completed),
                "failed": len(failed),
            },
            "data": {
                "active": active,
                "completed": completed,
                "failed": failed,
            }
        }

        yield f"data: {json.dumps(payload)}\n\n"

        if session_complete:
            break

        if stream_timed_out:
            logger.warning(
                f"[UPLOAD_STATUS] SSE stream timeout for session {session_id}"
            )
            break

        await asyncio.sleep(POLL_INTERVAL)