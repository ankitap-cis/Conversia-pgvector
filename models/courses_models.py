import uuid
from connection import Base
from sqlalchemy import TIMESTAMP, Boolean, Column, DateTime, Integer, String, ForeignKey, Text, UniqueConstraint, UUID, func
from sqlalchemy.orm import relationship
from models.roleplay_models import TimestampMixin


class Course(Base, TimestampMixin):
    __tablename__ = 'courses'

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(100), nullable=False)
    audience = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    additional_info = Column(Text, nullable=True)
    image_url = Column(String(512), nullable=False)
    course_file_url = Column(String(512), nullable=True)
    instructor_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    created_by = Column(Integer, ForeignKey("user.id"), nullable=False)
    last_updated_by = Column(Integer, ForeignKey("user.id"), nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    course_summary = Column(Text, nullable=True)

    instructor = relationship("User", foreign_keys=[instructor_id], back_populates="courses")
    created_by_user = relationship("User", foreign_keys=[created_by])
    last_updated_by_user = relationship("User", foreign_keys=[last_updated_by])
    course_sales_reps = relationship("CourseSalesRep", back_populates="courses", cascade="all, delete-orphan")
    conversation = relationship("CourseConversation", back_populates="course", cascade="all, delete-orphan")


    def __repr__(self):
        return f"<Course(name={self.title}, instructor_id={self.instructor_id})>"


class CourseSalesRep(Base, TimestampMixin):
    __tablename__ = "course_sales_reps"

    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"))
    sales_rep_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"))
    assigned_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"))

    courses = relationship("Course", back_populates="course_sales_reps", foreign_keys=[course_id])
    course_sales_rep = relationship("User", back_populates="assigned_courses", foreign_keys=[sales_rep_id])
    assigned_by_user = relationship("User", foreign_keys=[assigned_by])

    __table_args__ = (UniqueConstraint("course_id", "sales_rep_id", name="uq_course_sales_rep"),)


class CourseConversation(Base, TimestampMixin):
    __tablename__ = "course_conversation"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    # sales_rep_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(512), default="New Chat")
    created_by = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"),  nullable=False)
    last_updated_by = Column(Integer, ForeignKey("user.id"),  nullable=False)

    course = relationship("Course", back_populates="conversation")
    messages = relationship("CourseConvMessage", back_populates="conversation", cascade="all, delete-orphan")
    created_by_user = relationship("User", foreign_keys=[created_by])
    last_updated_by_user = relationship("User", foreign_keys=[last_updated_by])


class CourseConvMessage(Base):
    __tablename__ = "cs_conv_messages"

    id = Column(Integer, primary_key=True)
    cs_conv_id = Column(UUID(as_uuid=True), ForeignKey("course_conversation.id", ondelete="CASCADE"))
    sender = Column(String)  # "user" or "ai"
    message = Column(Text)

    conversation = relationship("CourseConversation", back_populates="messages")