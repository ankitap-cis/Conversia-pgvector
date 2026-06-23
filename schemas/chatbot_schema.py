from typing import Optional
from pydantic import BaseModel


class MessageForm(BaseModel):
    role: str
    content: str
    source_file_key: Optional[str] = None

    class Config:
        from_attributes = True


class ChatBotConversationResponse(BaseModel):
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


class ChatBotMessageResponse(BaseModel):
    id: int
    role: str
    content: str
    source_file_key: Optional[str] = None

    class Config:
        from_attributes = True


class ChatInput(BaseModel):
    message: str
