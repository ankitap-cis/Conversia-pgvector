from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Boolean, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
from connection import Base
from schemas.prompt_schema import PromptCategoryEnum


class PromptMaster(Base):
    __tablename__ = "prompt_master"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(255), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    prompt_content = Column(Text, nullable=False)
    icon = Column(String(256), nullable=True)
    created_by = Column(String(256), nullable=False)
    last_updated_by = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted = Column(Boolean, default=False)


class PromptUser(Base):
    __tablename__ = "prompt_user"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    category = Column(String(255), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    prompt_content = Column(Text, nullable=False)
    icon = Column(String(256), nullable=True)
    icon_source = Column(String(256), nullable=True)
    created_by = Column(String(256), nullable=False)
    last_updated_by = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted = Column(Boolean, default=False)

    # Relationships
    user = relationship("User", back_populates="prompts")
