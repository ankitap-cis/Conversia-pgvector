from typing import Optional
from pydantic import BaseModel, EmailStr, Field, field_validator
 
 
class RegisterationSchema(BaseModel):
    username: str
    full_name: str
    email: EmailStr
    password: str
    org_name: str
    master_prompt: Optional[str] = None
    evaluation_prompt: Optional[str] = None
    precall_prompt: Optional[str] = None
    chatbot_prompt: Optional[str] = None
    courses_prompt: Optional[str] = None
    email_prompt: Optional[str] = None
    summarizer_prompt: Optional[str] = None
    content_creator_prompt: Optional[str] = None
    field_intelligence_prompt: Optional[str] = None
    llm_model: Optional[str] = None
 
    @field_validator("email", mode="before")
    @classmethod
    def lowercase_email(cls, v):
        return v.lower() if isinstance(v, str) else v
 
 
class LoginSchema(BaseModel):
    email: EmailStr = Field(..., example="divyansh.s@cisinlabs.com")
    password: str = Field(..., example="Asqwe123#")
    remember_me: Optional[bool] = False
 
    @field_validator("email", mode="before")
    @classmethod
    def lowercase_email(cls, v):
        return v.lower() if isinstance(v, str) else v
 
 
class User(BaseModel):
    email: EmailStr
 
 
class UserInDB(User):
    id: int
    organization_id: Optional[int] = None
    org_name: Optional[str] = None
    name: Optional[str] = None
    full_name: Optional[str] = None
    email: EmailStr
    hashed_password: str
    user_type: str
    archive: bool
    acc_status: str
    content_creator_access: Optional[bool] = True
 
 
class Token(BaseModel):
    access_token: str
    token_type: str
 
 
class PasswordResetRequest(BaseModel):
    email: str
 
    @field_validator("email", mode="before")
    @classmethod
    def lowercase_email(cls, v):
        return v.lower() if isinstance(v, str) else v
 
 
class PasswordReset(BaseModel):
    token: str
    new_password: str
 
 
class ChangePass(BaseModel):
    current_password : str
    new_password : str
    confirm_new_password : str
 
 
class GenerateRefreshAndAccessTokenSchema(BaseModel):
    current_refresh_token: str


class CreditForm(BaseModel):
    monthly_compute_credit: int
    monthly_avatar_credit: int
    input_tokens_per_credit: int
    output_tokens_per_credit: int
    stt_minutes_per_credit: int
    tts_minutes_per_credit: int
