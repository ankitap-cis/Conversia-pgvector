from decimal import Decimal
from typing import Dict, List, Optional
from pydantic import BaseModel, field_validator
from pydantic import BaseModel, Field


class PersonaForm(BaseModel):
    thumbnail: str
    role: str
    primary_goal: Optional[str] = None
    challenges: Optional[str] = None
    objections: Optional[str] = None
    motivations: Optional[str] = None
    fears: Optional[str] = None
    communication_style: Optional[str] = None
    behavioral_tendencies: Optional[str] = None
    avatar_id: Optional[str] = None,
    for_personal_use: Optional[bool] = False



# class PersonaForm(BaseModel):
#     thumbnail: str = Field(..., description="Persona name (mandatory)")
#     role: str = Field(..., description="Role/job title (mandatory)")

#     primary_goal: Optional[str] = None
#     challenges: Optional[str] = None
#     objections: Optional[str] = None
#     motivations: Optional[str] = None
#     fears: Optional[str] = None
#     communication_style: Optional[str] = None
#     behavioral_tendencies: Optional[str] = None
#     avatar_id: Optional[str] = None

class PersonaResponse(BaseModel):
    id: int
    thumbnail: str | None = None
    role: str
    primary_goal: str | None = None
    challenges: str | None = None
    objections: str | None = None
    motivations: str | None = None
    fears: str | None = None
    communication_style: str | None = None
    behavioral_tendencies: str | None = None
    avatar_id: str | None = None

    class Config:
        from_attributes = True  # Ensures Pydantic can handle ORM models


class ScenarioForm(BaseModel):
    title: str
    description: Optional[str] = None
    ai_trainer_opening: Optional[str] = None
    selling_methodology: Optional[str] = None
    ideal_sales_outcome: Optional[str] = None
    topics_to_cover: Optional[str] = None
    current_state: Optional[str] = None
    barriers_to_change: Optional[str] = None
    critical_questions: Optional[str] = None
    for_personal_use: Optional[bool] = False
    persona_id: int
    evaluation_id: int

# class ScenarioForm(BaseModel):
#     title: str = Field(..., description="Scenario title (mandatory)")
#     description: str = Field(..., description="Scenario description (mandatory)")
#     trainee_mission: str = Field(..., description="Trainee goal (mandatory)")

#     ai_trainer_opening: Optional[str] = None
#     selling_methodology: Optional[str] = None
#     ideal_sales_outcome: Optional[str] = None
#     topics_to_cover: Optional[str] = None
#     current_state: Optional[str] = None
#     barriers_to_change: Optional[str] = None
#     critical_questions: Optional[str] = None
#     persona_id: Optional[int] = None
#     evaluation_id: Optional[int] = None
class ScenarioResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    ai_trainer_opening: Optional[str] = None
    selling_methodology: Optional[str] = None
    ideal_sales_outcome: Optional[str] = None
    topics_to_cover: Optional[str] = None
    current_state: Optional[str] = None
    barriers_to_change: Optional[str] = None
    critical_questions: Optional[str] = None
    persona_id: int
    evaluation_id: Optional[int] = None

    class Config:
        from_attributes = True  # Ensures Pydantic can handle ORM models


class AIExtractedPersona(BaseModel):
    thumbnail: Optional[str] = None
    role: Optional[str] = None
    primary_goal: Optional[str] = None
    challenges: Optional[str] = None
    objections: Optional[str] = None
    motivations: Optional[str] = None
    fears: Optional[str] = None
    communication_style: Optional[str] = None
    behavioral_tendencies: Optional[str] = None


class AIExtractedScenario(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    ai_trainer_opening: Optional[str] = None
    selling_methodology: Optional[str] = None
    ideal_sales_outcome: Optional[str] = None
    topics_to_cover: Optional[str] = None
    current_state: Optional[str] = None
    barriers_to_change: Optional[str] = None
    critical_questions: Optional[str] = None

class ExtractionRequest(BaseModel):
    description: str

    @field_validator("description")
    def clean_input(cls, v):
        if isinstance(v, str):
            return v.replace("\r", "").strip()
        return v

class ExtractionResponse(BaseModel):
    persona: AIExtractedPersona
    scenario: AIExtractedScenario


class AssignScenarioForm(BaseModel):
    scenario_id: int
    sales_rep_ids: List[int]


class AssignBulkScenarioForm(BaseModel):
    scenario_ids: List[int]


class AssignEvaluationCriteriaForm(BaseModel):
    criteria_ids: List[int]


class ConversationCreate(BaseModel):
    scenario_id: int
    user_id: int
    conversation: List[Dict[str, str]]  # List of chat messages


class ConversationResponse(BaseModel):
    id: int
    scenario_id: int
    user_id: int
    conversation: List[Dict[str, str]]


class SupportForm(BaseModel):
    content: str


class RoleplayMessageCreate(BaseModel):
    sender: str  # "user" or "ai"
    message: str


class RoleplaySessionCreate(BaseModel):
    scenario_id: Optional[int] = None
    bot_state_id: Optional[str] = None
    messages: List[RoleplayMessageCreate]
    media_type: Optional[str] = None
    avatar_minutes: Optional[Decimal] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


class RoleplaySessionResponse(BaseModel):
    id: int
    performer_id: int
    organization_id: int
    scenario_id: int
    messages: List[RoleplayMessageCreate]

    class Config:
        from_attributes = True  # Ensures Pydantic can handle ORM models


class SkillScore(BaseModel):
    name: str
    score: int
    comment: str

class DebriefReportSchema(BaseModel):
    scenario_title: str
    ai_score: float
    pass_score: float
    general_insights: str
    skill_scores: List[SkillScore]

class SpeechRequest(BaseModel):
    text: str
    voice: str = "sage"
    format: str = "mp3"
    isspeak: bool = True
 

class CreateScenarioWithPersona(BaseModel):
    persona: PersonaForm
    scenario: ScenarioForm