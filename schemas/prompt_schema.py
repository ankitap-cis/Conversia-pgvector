from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum


class PromptCategoryEnum(str, Enum):
    DISCOVERY = "DISCOVERY"
    MESSAGING = "MESSAGING"
    BUYING_PROCESS = "BUYING_PROCESS"
    CASE_SUPPORT_AND_TRAINING = "CASE_SUPPORT_AND_TRAINING"
    MANAGER_TOOLKIT = "MANAGER_TOOLKIT"


class CreatePromptMasterForm(BaseModel):
    category: PromptCategoryEnum = Field(..., description="Prompt category")
    title: str = Field(..., description="Prompt title", min_length=1, max_length=255)
    description: Optional[str] = Field(None, description="Prompt description")
    prompt_content: str = Field(..., description="Actual prompt content", min_length=1)
    icon: Optional[str] = Field(None, description="Prompt icon")

    class Config:
        from_attributes = True


class UpdatePromptMasterForm(BaseModel):
    category: Optional[PromptCategoryEnum] = Field(None, description="Prompt category")
    title: Optional[str] = Field(None, description="Prompt title", min_length=1, max_length=255)
    description: Optional[str] = Field(None, description="Prompt description")
    prompt_content: Optional[str] = Field(None, description="Actual prompt content", min_length=1)
    icon: Optional[str] = Field(None, description="Prompt icon")

    class Config:
        from_attributes = True


class PromptMasterResponse(BaseModel):
    id: int
    category: PromptCategoryEnum
    title: str
    description: Optional[str] = None
    prompt_content: str

    class Config:
        from_attributes = True


class PromptMasterDetailResponse(BaseModel):
    id: int
    category: PromptCategoryEnum
    title: str
    description: Optional[str] = None
    prompt_content: str

    class Config:
        from_attributes = True


class CreateUserPromptForm(BaseModel):
    category: PromptCategoryEnum = Field(..., description="Prompt category")
    title: str = Field(..., description="Prompt title", min_length=1, max_length=255)
    description: Optional[str] = Field(None, description="Prompt description")
    prompt_content: str = Field(..., description="Actual prompt content", min_length=1)
    master_prompt_id: Optional[int] = Field(None, description="Reference to master prompt")

    class Config:
        from_attributes = True


class UpdateUserPromptForm(BaseModel):
    category: Optional[PromptCategoryEnum] = Field(None, description="Prompt category")
    title: Optional[str] = Field(None, description="Prompt title", min_length=1, max_length=255)
    description: Optional[str] = Field(None, description="Prompt description")
    prompt_content: Optional[str] = Field(None, description="Actual prompt content", min_length=1)
    icon: Optional[str] = Field(None, description="User prompt icon")

    class Config:
        from_attributes = True


class UserPromptResponse(BaseModel):
    id: int
    user_id: int
    master_prompt_id: Optional[int] = None
    category: PromptCategoryEnum
    title: str
    description: Optional[str] = None
    prompt_content: str
    is_deleted: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True
