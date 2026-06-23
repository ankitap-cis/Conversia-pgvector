from pydantic import BaseModel
from typing import Dict, List, Optional, Literal


class FormField(BaseModel):
    field_name: str
    field_type: Literal["text", "textarea", "file"]
    is_required: bool = False
    order_index: int


class CreatePreCallForm(BaseModel):
    fields: List[FormField]


class PrecallPlanFieldResponse(BaseModel):
    field_name: str
    field_type: str
    is_required: bool
    order_index: int


class PrecallPlanResponse(BaseModel):
    id: int
    file_path: Optional[str] = None
    precall_plan_fields: Optional[List[PrecallPlanFieldResponse]] = []


class PrecallPlanAIResponse(BaseModel):
    recap_objective_profile_pain: str
    open_ended_questions: str
    top_3_messages: str
    relevant_anecdotes_metaphor: str
    insights_and_trends: str
    potential_action_items: str


class PrecallPlanAIListResponse(BaseModel):
    status: str
    message: str
    data: List[PrecallPlanAIResponse]
    organization_id: int


class Section(BaseModel):
    title: str
    content: str

class SectionList(BaseModel):
    sections: List[Section]


class CriteriaItem(BaseModel):
    score: int
    explanation: str


class OverallFeedback(BaseModel):
    overall_score: float
    general_feedback: str


class EvaluationPayload(BaseModel):
    evaluation: Dict[str, CriteriaItem]
    overall_feedback: OverallFeedback
