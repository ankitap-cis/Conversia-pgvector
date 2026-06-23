from decimal import Decimal
from sqlalchemy import TIMESTAMP, BigInteger, Column, ForeignKey, Integer, Numeric, String, Boolean, Text, UniqueConstraint, text
from sqlalchemy.orm import relationship
from sqlalchemy import Sequence
from sqlalchemy.dialects.postgresql import JSONB
from connection import Base
from models.roleplay_models import ScenarioSalesRep
from models.precall_plan_models import KnowledgeBase  # using for circular imports for creating superadmin
from models.courses_models import Course, CourseSalesRep  # using for circular imports for creating superadmin
from models.rbac_models import Role
from sqlalchemy.ext.hybrid import hybrid_property

class User(Base):
    __tablename__ = "user"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    username = Column(String(256),unique=True, nullable=False)
    email = Column(String(256), unique=True, index=True)
    password = Column(String(256), nullable=False)
    user_type = Column(String(256), nullable=False)
    field_manager_id = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)

    archive = Column(Boolean, default=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text('now()'), nullable=False)
    created_by = Column(String(256), nullable=False)
    content_creator_access = Column(Boolean, default=True, nullable=False)
    last_updated_at = Column(TIMESTAMP(timezone=True), server_default=text('now()'), nullable=False)
    last_updated_by = Column(String(256), nullable=False)

    # One-to-One Relationship with Profile
    profile = relationship("Profile", back_populates="user", uselist=False, cascade="all, delete")

    # Organization that the user belongs to
    organization = relationship("Organization", back_populates="users", foreign_keys=[organization_id])

    # Organization created by the user (manager)
    created_organization = relationship("Organization", back_populates="admin_user", foreign_keys='Organization.admin_id', uselist=False)

     # One-to-many relationship
    scenarios = relationship("Scenario", back_populates="admin", cascade="all, delete-orphan")

    assigned_scenarios = relationship("ScenarioSalesRep", back_populates="sales_rep", foreign_keys=[ScenarioSalesRep.sales_rep_id])

    knowledge_bases = relationship("KnowledgeBase", back_populates="admin")

    summary = relationship("SessionLog", back_populates="user", uselist=False)

    roleplay_sessions = relationship("RoleplaySession", back_populates="performer", cascade="all, delete-orphan")

    courses = relationship("Course", back_populates="instructor", foreign_keys="[Course.instructor_id]", cascade="all, delete-orphan")

    assigned_courses = relationship("CourseSalesRep", back_populates="course_sales_rep", foreign_keys=[CourseSalesRep.sales_rep_id])

    roles = relationship("Role", secondary="user_roles", back_populates="users")
    user_roles = relationship("UserRole", back_populates="user", cascade="all, delete-orphan")
    field_manager = relationship("User", remote_side=[id], backref="sales_reps")
    prompts = relationship("PromptUser", back_populates="user", cascade="all, delete-orphan")

class Profile(Base):
    __tablename__ = "profile"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), unique=True, nullable=False)
    full_name = Column(String(256))
    city = Column(String(256))
    country = Column(String(256))
    phone = Column(Integer)
    acc_status = Column(String(256), default="Inactive")
    created_at = Column(TIMESTAMP(timezone=True), server_default=text('now()'), nullable=False)
    created_by = Column(String(256), nullable=False)
    last_updated_at = Column(TIMESTAMP(timezone=True), server_default=text('now()'), nullable=False)
    last_updated_by = Column(String(256), nullable=False)

    # Relationship back to User
    user = relationship("User", back_populates="profile")


org_id_seq = Sequence('org_id_seq', start=1001)

class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, org_id_seq, primary_key=True, server_default=org_id_seq.next_value())
    admin_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), unique=True, nullable=False)
    org_name = Column(String(256), nullable=True)
    master_prompt = Column(Text, nullable=True)
    evaluation_prompt = Column(Text, nullable=False)
    precall_prompt = Column(Text, nullable=True)
    chatbot_prompt = Column(Text, nullable=True)
    courses_prompt = Column(Text, nullable=True)
    email_prompt = Column(Text, nullable=True)
    summarizer_prompt = Column(Text, nullable=True)
    content_creator_prompt = Column(Text, nullable=True)
    field_intelligence_prompt = Column(Text, nullable=True)
    llm_model = Column(String, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text('now()'), nullable=False)
    created_by = Column(String, nullable=False)
    last_updated_at = Column(TIMESTAMP(timezone=True), server_default=text('now()'), nullable=False)
    last_updated_by = Column(String, nullable=False)

    # Admin user who created the organization
    admin_user = relationship("User", back_populates="created_organization", foreign_keys=[admin_id])

    # All users belonging to this organization (manager + sales)
    users = relationship("User", back_populates="organization", foreign_keys='User.organization_id')

    roleplay_sessions = relationship("RoleplaySession", back_populates="organization", cascade="all, delete-orphan")


class SessionLog(Base):
    __tablename__ = "session_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user.id"), unique=True)  # Ensure one row per user
    name = Column(String, nullable=False)
    chat_sessions = Column(Integer, default=0)
    chat_total_duration = Column(Integer, default=0)  # store duration in minutes
    role_play_sessions = Column(Integer, default=0)
    role_play_total_duration = Column(Integer, default=0)  # in minutes
    pre_call_plan_sessions = Column(Integer, default=0)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text('now()'), nullable=False)
    created_by = Column(String, nullable=False)
    last_updated_at = Column(TIMESTAMP(timezone=True), server_default=text('now()'), nullable=False)
    last_updated_by = Column(String, nullable=False)

    user = relationship("User", back_populates="summary")

    @hybrid_property
    def duration_minutes(self):
        return (self.end_time - self.start_time).total_seconds() / 60


class ImpersonationLog(Base):
    __tablename__ = "impersonation_logs"

    id = Column(Integer, primary_key=True, index=True)
    actor_email = Column(String, nullable=False)     # Superadmin
    subject_email = Column(String, nullable=False)   # Impersonated user
    action = Column(String, nullable=False)          # e.g. GET /courses
    message = Column(String, nullable=True)
    timestamp = Column(TIMESTAMP(timezone=True), server_default=text('now()'), nullable=False)


class GlobalCreditSetting(Base):
    __tablename__ = "global_credit_settings"

    id = Column(Integer, primary_key=True, index=True)
    monthly_compute_credit = Column(Integer, nullable=False, default=1000)
    monthly_avatar_credit = Column(Integer, nullable=False, default=300)
    input_tokens_per_credit = Column(Integer, nullable=False, default=1000000)
    output_tokens_per_credit = Column(Integer, nullable=False, default=125000)
    stt_minutes_per_credit = Column(Integer, nullable=False, default=60)
    tts_minutes_per_credit = Column(Integer, nullable=False, default=120)
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text('now()'), nullable=False)
    created_by = Column(String, nullable=False)


class AdminAuditLogs(Base):
    __tablename__ = "admin_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    actor_id = Column(Integer, ForeignKey("user.id"), nullable=True)
    actor_role = Column(String, nullable=False)
    action_type = Column(String, nullable=False) # EDIT_GLOBAL_CAPS, SUSPEND_COMPUTE, etc
    target_type = Column(String, nullable=False) # USER, GLOBAL, ORG
    target_id = Column(Integer, nullable=True) #user_id / org_id (nullable for global)
    message = Column(String, nullable=False)
    audit_metadata = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text('now()'), nullable=False)


class UserMonthlyCredit(Base):
    __tablename__ = "user_monthly_credits"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(ForeignKey("user.id"), nullable=False)

    # Billing window
    start_date = Column(TIMESTAMP(timezone=True), nullable=False)
    end_date = Column(TIMESTAMP(timezone=True), nullable=False)

    # Snapshot from global
    compute_credit_allocated = Column(Numeric(20, 6), nullable=False)
    avatar_credit_allocated = Column(Numeric(20, 6), nullable=False)

    # From previous month
    rollover_compute_credit = Column(Numeric(20, 6), default=0)
    rollover_avatar_credit = Column(Numeric(20, 6), default=0)

    # Bonus added by admin
    bonus_compute_credit = Column(Numeric(20, 6), default=0)
    bonus_avatar_credit = Column(Numeric(20, 6), default=0)

    # Runtime usage
    compute_credit_used = Column(Numeric(20, 6), default=0)
    avatar_credit_used = Column(Numeric(20, 6), default=0)

    compute_access = Column(Boolean, default=True)
    avatar_access = Column(Boolean, default=True)

     # Token usage
    input_tokens_used = Column(BigInteger, default=0)
    output_tokens_used = Column(BigInteger, default=0)

    # Speech usage (minutes)
    stt_minutes_used = Column(Numeric(10, 2), default=Decimal("0"))
    tts_minutes_used = Column(Numeric(10, 2), default=Decimal("0"))

    is_active = Column(Boolean, default=True)

    compute_warning_sent = Column(Boolean, default=False)
    compute_suspended_sent = Column(Boolean, default=False)

    avatar_warning_sent = Column(Boolean, default=False)
    avatar_suspended_sent = Column(Boolean, default=False)

    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("user_id", "start_date", name="unique_user_month"),
    )

    @property
    def remaining_compute_credit(self):
        return (
            self.compute_credit_allocated
            + self.rollover_compute_credit
            + self.bonus_compute_credit
            - self.compute_credit_used
        )

    @property
    def remaining_avatar_credit(self):
        return (
            self.avatar_credit_allocated
            + self.rollover_avatar_credit
            + self.bonus_avatar_credit
            - self.avatar_credit_used
        )


class CompanyContext(Base):
    __tablename__ = "company_context"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    organization_overview = Column(Text, nullable=False)
    customer_segments = Column(Text, nullable=False)
    int_user_ext_stakeholder = Column(Text, nullable=False)
    brand_voice = Column(Text, nullable=False)
    compliance_guardrails = Column(Text, nullable=False)
    additional_context = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text('now()'), nullable=False)
    created_by = Column(String, nullable=False)
    last_updated_at = Column(TIMESTAMP(timezone=True), server_default=text('now()'), nullable=False)
    last_updated_by = Column(String, nullable=False)

    def __repr__(self):
        return f"<CompanyContext(id={self.id}, organization_overview='{self.organization_overview}')>"