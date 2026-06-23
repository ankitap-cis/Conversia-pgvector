from typing import Literal, Optional
from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile

from uuid import UUID
from fastapi.params import Body
from sqlalchemy.orm import Session
from api.auth.permission import require_permission
from api.chatbot_conversation.chatbot_conversation import get_conversation, get_conversations, new_conversation, save_message
from api.courses.courses import (
    create_course, 
    update_course, 
    get_courses, 
    get_course, 
    delete_course, 
    assign_course, 
    assign_bulk_courses,
    get_assigned_courses,
    remove_assigned_course,
    # realtime_course_context,
    audio_course_rag,
    format_response
)
from api.roleplay_assistant.features.course_services import course_chat
from connection import get_db
from schemas.chatbot_schema import MessageForm
from schemas.course_schema import AssignBulkCoursesForm, AssignCourseForm, CourseChatRequest, CourseForm
from utils.utils import ALGORITHM, SECRET_KEY, get_current_user, get_current_user
from typing import Union
from api.ai_consumption.superadmin_token_dashboard import require_compute_access



courses_router = APIRouter()


@courses_router.post("/create-course")
async def create_course_api(
    title: str = Form(..., title="Course Title"),
    audience: str = Form(..., title="Course Audience"),
    description: str = Form(..., title="Course Description"),
    additional_info: str = Form(..., title="Additional Information"),
    course_image: UploadFile = File(...),
    course_file: UploadFile = File(...), 
    db: Session = Depends(get_db),
    current_user: Session = Depends(get_current_user),
    _ = require_permission("courses.create"),
    compute_access = Depends(require_compute_access)
):

    course_data = CourseForm(
        title=title,
        audience=audience,
        description=description,
        additional_info=additional_info
    )
    return await create_course(course_data, course_image, course_file, db, current_user)


@courses_router.put("/update-course/{course_id}")
async def update_course_api(
    course_id: int,
    title: Optional[str] = Form(None),
    audience: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    additional_info: Optional[str] = Form(None),
    course_image: Optional[UploadFile] = File(None), 
    course_file: Optional[Union[UploadFile, str]] = File(None), 
    db: Session = Depends(get_db),
    current_user: Session = Depends(get_current_user),
    _ = require_permission("courses.update")
):
    
    course_data = CourseForm(
        title=title,
        audience=audience,
        description=description,
        additional_info=additional_info
    )
    return await update_course(course_id, course_data, course_image, course_file, db, current_user)


@courses_router.get("/get-courses")
async def get_courses_api(search_query: Optional[str] = None, limit: int = 10, offset: int = 0, source: Literal["home", "settings"] = Query("home"), db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("courses.list")):
    return await get_courses(search_query, limit, offset, source, db, current_user)


@courses_router.get("/get-course/{course_id}")
async def get_course_api(course_id: int, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user),_ = require_permission("courses.get")):
    return await get_course(course_id, db, current_user)


@courses_router.delete("/delete-course/{course_id}")
async def delete_course_api(course_id: int, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("courses.delete")):
    return await delete_course(course_id, db, current_user)


@courses_router.post("/assign-course")
async def assign_course_api(course: AssignCourseForm, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("courses.assign")):
    return await assign_course(course, db, current_user)


@courses_router.post("/assign-bulk-courses/{user_id}")
async def assign_bulk_courses_api(user_id: int, course_form: AssignBulkCoursesForm, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("courses.bulk_assign")):                     
    return await assign_bulk_courses(user_id, course_form, db, current_user)


@courses_router.get("/{user_id}/assigned-courses")
async def get_assigned_courses_api(user_id: int, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("courses.get_assigned")):
    return await get_assigned_courses(user_id, db, current_user)


@courses_router.delete("/{user_id}/remove-assigned-courses/{course_id}")
async def remove_assigned_course_api(user_id: int, course_id: int, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("courses.remove_assigned")):
    return await remove_assigned_course(user_id, course_id, db, current_user)


@courses_router.post("/new")
async def new_course_conversation_api(request: Request, course_id: int, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    return await new_conversation(request, course_id, db, current_user)


@courses_router.get("/list-conversation")
async def list_course_conversation_api(request: Request, course_id: int, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    return await get_conversations(request, course_id, db, current_user)


@courses_router.get("/list-conversation/{conversation_id}")
async def get_conversation_api(conversation_id: UUID, request: Request, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    return await get_conversation(conversation_id, request, db, current_user)


@courses_router.post("/{conversation_id}/message")
async def save_message_api(conversation_id: UUID, message: MessageForm, request: Request, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    return await save_message(conversation_id, message, request, db, current_user)


@courses_router.post("/course-chat/{conversation_id}")
async def course_chat_api(
    conversation_id: UUID,
    request: Request,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: Session = Depends(get_current_user),
    _ = Depends(require_compute_access)
):
    return await course_chat(conversation_id, request, body, db, current_user)

@courses_router.post("/format-response")
async def format_response_api(
    response: str = Query(..., title="AI Response to Format"),
    db: Session = Depends(get_db),
    current_user: Session = Depends(get_current_user)
):
    return await format_response(response, db, current_user)

# ai routes
@courses_router.post("/audio-course-rag")
async def audio_course_rag_api(
    body: CourseChatRequest,
    db: Session = Depends(get_db),
    current_user: Session = Depends(get_current_user)
):
    return await audio_course_rag(body, db, current_user)
