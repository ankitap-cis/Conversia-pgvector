from typing import List, Optional
from pydantic import BaseModel


class KnowledgeBaseResponse(BaseModel):
    id:int
    file_name: str
    file_type: str
    file_path: str
    priority: str
    created_at: str
    status: Optional[str] = None
    file_size: Optional[str] = None

    @classmethod
    def from_orm_model(cls, kb_obj):
        readable_date = kb_obj.uploaded_at.strftime("%d/%m/%Y %I:%M %p")
        priority = str(kb_obj.priority) if kb_obj.priority != 0 else "-"
        return cls(
            id=kb_obj.id,
            file_name=f"{kb_obj.name}.{kb_obj.file_type}",
            file_type=kb_obj.file_type,
            file_path=kb_obj.file_path,
            priority=priority,
            created_at=readable_date,
            status=kb_obj.status,
            file_size=kb_obj.file_size
        )


class UploadStatusResponse(BaseModel):
    """Response schema for upload status tracking"""
    file_id: int
    filename: str
    status: str  # pending, uploading, processing, completed, failed
    progress_percent: float
    message: str
    error_reason: Optional[str] = None
    
    class Config:
        from_attributes = True


class SetPriorityForm(BaseModel):
    priority: int


class BulkPriorityForm(BaseModel):
    file_ids: List[int]
    priority: int


class BulkDeletionForm(BaseModel):
    file_ids: List[int]
