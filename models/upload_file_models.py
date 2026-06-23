from sqlalchemy import  Column, ForeignKey, Integer, String, DateTime
from sqlalchemy.orm import relationship
from connection import Base
from datetime import datetime


class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"

    id = Column(Integer, primary_key=True, index=True)
    file_path = Column(String, nullable=False)
    priority = Column(Integer, nullable=False, default=0)
    uploaded_by = Column(Integer, ForeignKey("user.id"), nullable=False)
    uploaded_at = Column(DateTime, default=datetime.now)
