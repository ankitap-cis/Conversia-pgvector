from typing import Optional
from pydantic import BaseModel, EmailStr, field_validator

from api.auth.authentication import decrypt_data


class UpdateUser(BaseModel):
    first_name: str
    last_name: str


class SalesRepsForm(BaseModel):
    username: str
    email: EmailStr
    full_name: str
    user_type: str
    assigned_by: Optional[int] = None
    content_creator_access: Optional[bool] = True

    @field_validator("email", mode="before")
    @classmethod
    def lowercase_email(cls, v):
        return v.lower() if isinstance(v, str) else v


class RepresentativeResponse(BaseModel):
    id: int
    username: str
    email: EmailStr
    full_name: Optional[str] = None
    acc_status: Optional[str] = None
    user_type: str
    assigned_by: Optional[int] = None
    content_creator_access: Optional[bool] = True

    class Config:
        from_attributes = True


class OrganizationResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    org_name: str
    acc_status: str
    llm_model: Optional[str] = None
    master_prompt: Optional[str] = None
    evaluation_prompt: Optional[str] = None
    precall_prompt: Optional[str] = None
    chatbot_prompt: Optional[str] = None
    courses_prompt: Optional[str] = None
    email_prompt: Optional[str] = None
    summarizer_prompt: Optional[str] = None
    content_creator_prompt: Optional[str] = None
    field_intelligence_prompt: Optional[str] = None

    @field_validator("username", mode="before")
    @classmethod
    def decrypt_username(cls, v):
        try:
            return decrypt_data(v) if v else v
        except Exception:
            return v


class EditOrganizationForm(BaseModel):
    acc_status: str
    master_prompt: str
    evaluation_prompt: str
    precall_prompt: str
    chatbot_prompt: str
    llm_model: str
    courses_prompt: str
    email_prompt: str
    summarizer_prompt: str
    content_creator_prompt: str
    field_intelligence_prompt: str
    org_name: str


class SessionLogCreateUpdate(BaseModel):
    chat_sessions: Optional[int] = 0
    chat_total_duration: Optional[int] = 0
    role_play_sessions: Optional[int] = 0
    role_play_total_duration: Optional[int] = 0
    pre_call_plan_sessions: Optional[int] = 0


class ImpersonateForm(BaseModel):
    user_id: int


class CompanyContextForm(BaseModel):
    organization_overview: str
    customer_segments: str
    int_user_ext_stakeholder: str
    brand_voice: str
    compliance_guardrails: str
    additional_context: str