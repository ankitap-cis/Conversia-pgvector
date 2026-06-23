import uuid
from sqlalchemy import TIMESTAMP, UUID, CheckConstraint, Column, ForeignKey, Integer, String, Text, func
from connection import Base
from .roleplay_models import TimestampMixin


class ChatBotConversation(Base, TimestampMixin):
    __tablename__ = "chatbot_conversation"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"))
    title = Column(String)
    created_by = Column(String, nullable=False)
    last_updated_by = Column(String, nullable=False)

    def __repr__(self):
        return (
            f"<ChatBotConversation(id={self.id}, title='{self.title}', "
            f"user_id={self.user_id}, created_at='{self.created_at}')>"
        )

class ChatBotMessages(Base, TimestampMixin):
    __tablename__ = "chatbot_messages"
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("chatbot_conversation.id", ondelete="CASCADE"))
    role = Column(String, CheckConstraint("role IN ('user', 'assistant')"), nullable=False)
    content = Column(Text, nullable=False)
    source_file_key = Column(String, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    created_by = Column(String, nullable=False)

    def __repr__(self):
        return (
            f"<ChatBotMessages(conversation_id={self.conversation_id}, role='{self.role}', "
            f"created_by='{self.created_by}', created_at={self.created_at})>"
        )
