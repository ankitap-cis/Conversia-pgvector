from pydantic import BaseModel, field_validator
from typing import List, Optional
from decimal import Decimal


class CourseForm(BaseModel):
    title: str
    audience: str
    description: Optional[str] = None
    additional_info: Optional[str] = None


class CourseResponse(BaseModel):
    id: int
    title: str
    audience: str
    description: Optional[str] = None
    additional_info: Optional[str] = None
    image_url: str
    course_file_url: Optional[str] = None
    course_summary: Optional[str] = None

    class Config:
        from_attributes = True


class AssignCourseForm(BaseModel):
    course_id: int
    sales_rep_ids: List[int]

    class Config:
        from_attributes = True


class AssignBulkCoursesForm(BaseModel):
    course_ids: List[int]

    class Config:
        from_attributes = True


class CourseConversationResponse(BaseModel):
    id: str
    title: str
    last_updated_at: str

    @classmethod
    def from_orm_model(cls, kb_obj):
        readable_date = kb_obj.last_updated_at.strftime("%d/%m/%Y %I:%M %p")
        return cls(
            id=str(kb_obj.id),  
            title=kb_obj.title,
            last_updated_at=readable_date
        )


class CourseMessageResponse(BaseModel):
    id: int
    sender: str
    message: str

    class Config:
        from_attributes = True


class CourseChatRequest(BaseModel):
    message: Optional[str] = None
    course_id: int
    
    @field_validator("message", mode="before")
    @classmethod
    def empty_message_to_none(cls, value):
        if value == "":
            return None
        return value

class MessageCreate(BaseModel):
    sender: str
    message: str
    is_course: Optional[bool] = True  # default to True for course sessions

class CourseSessionCreate(BaseModel):
    messages: List[MessageCreate]  # you can reuse this
    media_type: Optional[str] = "chat"
    avatar_minutes: Optional[Decimal] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
