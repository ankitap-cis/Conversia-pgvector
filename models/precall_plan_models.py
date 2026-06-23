import enum
from sqlalchemy import JSON, TIMESTAMP, Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, func, UniqueConstraint, UUID
from sqlalchemy.orm import relationship
from connection import Base
from models.roleplay_models import TimestampMixin
import uuid

class FieldTypeEnum(enum.Enum):
    text = "text"
    textarea = "textarea"
    file = "file"


class PreCallPlanForm(Base, TimestampMixin):
    __tablename__ = "precall_plan_forms"

    id = Column(Integer, primary_key=True)
    file_path = Column(String)
    admin_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, unique=True)
    created_by = Column(Integer, nullable=True)
    last_updated_by = Column(Integer, nullable=True)

    precall_plan_form_field = relationship("PreCallPlanFormField", back_populates="precall_plan_form", cascade="all, delete")
    responses = relationship("PreCallPlanFormResponse", back_populates="precall_plan_form", cascade="all, delete")


class PreCallPlanFormField(Base):
    __tablename__ = "precall_plan_form_fields"

    id = Column(Integer, primary_key=True)
    form_id = Column(Integer, ForeignKey("precall_plan_forms.id", ondelete="CASCADE"))
    field_name = Column(String(255), nullable=False)
    field_type = Column(Enum(FieldTypeEnum), nullable=False)
    is_required = Column(Boolean, default=False)
    order_index = Column(Integer, default=0)

    precall_plan_form = relationship("PreCallPlanForm", back_populates="precall_plan_form_field")


class PreCallPlanFormResponse(Base):
    __tablename__ = "precall_plan_form_responses"

    id = Column(Integer, primary_key=True)
    form_id = Column(Integer, ForeignKey("precall_plan_forms.id", ondelete="CASCADE"))
    user_id = Column(Integer, nullable=True)
    response_data = Column(JSON, nullable=False)  # Stores dynamic response
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())

    precall_plan_form = relationship("PreCallPlanForm", back_populates="responses")


class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"
 
    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    name = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    priority = Column(Integer, nullable=False)
    uploaded_by = Column(String, nullable=False)
    uploaded_at = Column(TIMESTAMP, server_default=func.now())

    status = Column(String, nullable=True, default="pending")  # pending, processing, completed, failed
    reason = Column(String, nullable=True)  # Reason for failure if status is failed
    file_size = Column(String, nullable=True)  # Store file size as a string for better readability
    
    session_id = Column(UUID(as_uuid=True), default=uuid.uuid4,nullable=True) # For tracking upload sessions, especially for multi-file uploads

    admin = relationship("User", back_populates="knowledge_bases", passive_deletes=True)
