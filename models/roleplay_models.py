from sqlalchemy import JSON, TIMESTAMP, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import relationship
from connection import Base
import sqlalchemy as sa

class TimestampMixin:
    created_at = Column(TIMESTAMP, server_default=func.now())
    last_updated_at = Column(TIMESTAMP, onupdate=func.now(), server_default=func.now())


class Scenario(Base, TimestampMixin):
    __tablename__ = "scenarios"

    id = Column(Integer, primary_key=True)
    admin_id = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"))
    title = Column(String, nullable=False)
    description = Column(Text)
    scenario_image = Column(String)
    scenario_file = Column(String)
    ai_trainer_opening = Column(Text)
    selling_methodology = Column(Text)
    persona_id = Column(Integer, ForeignKey("persona.id", ondelete="SET NULL"))
    evaluation_id = Column(Integer, ForeignKey("evaluation.id", ondelete="SET NULL"))
    ideal_sales_outcome = Column(Text)
    topics_to_cover = Column(Text)
    current_state = Column(Text)
    barriers_to_change = Column(Text)
    critical_questions = Column(Text)
    created_by = Column(String(256))
    last_updated_by = Column(String(256))
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)
    for_personal_use = Column(Boolean, default=False, server_default=sa.false(), nullable=False)
    admin = relationship("User", back_populates="scenarios", foreign_keys=[admin_id])
    persona = relationship("Persona", back_populates="scenarios")
    evaluation = relationship("Evaluation", back_populates="scenario")
    sales_reps = relationship("ScenarioSalesRep", back_populates="scenarios", cascade="all, delete-orphan")
    sessions = relationship("RoleplaySession", back_populates="scenario", cascade="all, delete-orphan")


class Persona(Base, TimestampMixin):
    __tablename__ = "persona"

    id = Column(Integer, primary_key=True)
    avatar_image = Column(String)
    avatar_id = Column(String)
    thumbnail = Column(String, nullable=True)
    role = Column(String, nullable=False)
    primary_goal = Column(Text)
    challenges = Column(Text)
    objections = Column(Text)
    motivations = Column(Text)
    fears = Column(Text)
    communication_style = Column(Text)
    behavioral_tendencies = Column(Text)
    for_personal_use = Column(Boolean, default=False, server_default=sa.false(), nullable=False)
    created_by = Column(String(256))
    last_updated_by = Column(String(256))
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    scenarios = relationship("Scenario", back_populates="persona")

class ScenarioSalesRep(Base, TimestampMixin):
    __tablename__ = "scenario_sales_reps"

    id = Column(Integer, primary_key=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id", ondelete="CASCADE"))
    sales_rep_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"))
    assigned_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"))

    scenarios = relationship("Scenario", back_populates="sales_reps", foreign_keys=[scenario_id])
    sales_rep = relationship("User", back_populates="assigned_scenarios", foreign_keys=[sales_rep_id])
    assigned_by_user = relationship("User", foreign_keys=[assigned_by])

    __table_args__ = (UniqueConstraint("scenario_id", "sales_rep_id", name="uq_scenario_sales_rep"),)


class Evaluation(Base, TimestampMixin):
    __tablename__ = "evaluation"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    description = Column(Text, nullable=True)
    created_by = Column(String(256))
    last_updated_by = Column(String(256))
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    fields = relationship("EvaluationField", back_populates="evaluation", cascade="all, delete-orphan")
    scenario = relationship("Scenario", back_populates="evaluation")

    def __repr__(self):
        return f"<Evaluation(id={self.id}, title='{self.title}')>"


class EvaluationField(Base):
    __tablename__ = "evaluation_fields"

    id = Column(Integer, primary_key=True, index=True)
    title_area = Column(String, index=True)
    rating = Column(Integer)  # Rating (0-10)
    weight = Column(Float)  # Percentage Weight
    comment = Column(Text, nullable=True)
    evaluation_id = Column(Integer, ForeignKey("evaluation.id"))

    evaluation = relationship("Evaluation", back_populates="fields")


class RoleplaySession(Base, TimestampMixin):
    __tablename__ = "roleplay_sessions"
    id = Column(Integer, primary_key=True)
    performer_id = Column(Integer, ForeignKey("user.id"))
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    scenario_id = Column(Integer, ForeignKey("scenarios.id"))
    bot_state_id = Column(String(255))
    created_by = Column(String(256))
    last_updated_by = Column(String(256))

    messages = relationship("RoleplaySessionMessage", back_populates="session", cascade="all, delete-orphan")
    scenario = relationship("Scenario", back_populates="sessions")
    performer = relationship("User", back_populates="roleplay_sessions", foreign_keys=[performer_id])
    organization = relationship("Organization", back_populates="roleplay_sessions", foreign_keys=[organization_id])
    debrief_report = relationship("DebriefReport", back_populates="session", uselist=False)


class RoleplaySessionMessage(Base):
    __tablename__ = "roleplay_session_messages"
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("roleplay_sessions.id"))
    sender = Column(String)  # "user" or "ai"
    message = Column(Text)

    session = relationship("RoleplaySession", back_populates="messages")


class DebriefReport(Base, TimestampMixin):
    __tablename__ = "debrief_reports"
    
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("roleplay_sessions.id"), unique=True)
    scenario_title = Column(String)  # e.g., "Discuss new publication"
    ai_score = Column(Float(precision=2))  # Float with precision up to two decimal places
    pass_score = Column(Integer)
    general_insights = Column(Text)  # list of insight strings
    created_by = Column(String(256))
    last_updated_by = Column(String(256))
    
    session = relationship("RoleplaySession", back_populates="debrief_report", uselist=False)
    skill_scores = relationship("DebriefSkillScore", back_populates="debrief_report", cascade="all, delete-orphan")


class DebriefSkillScore(Base):
    __tablename__ = "debrief_skill_scores"

    id = Column(Integer, primary_key=True)
    debrief_report_id = Column(Integer, ForeignKey("debrief_reports.id"))
    skill_name = Column(String)  # e.g., "Objection Handling"
    score = Column(Integer)      # e.g., 7
    comment = Column(Text)       # e.g., "Handled objections efficiently, but consider anticipating..."

    debrief_report = relationship("DebriefReport", back_populates="skill_scores")
