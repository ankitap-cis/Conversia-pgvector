from typing import List, Optional
from pydantic import BaseModel, Field

class EvaluationFieldSchema(BaseModel):
    title_area: str
    rating: int = Field(..., ge=1, le=10, description="Ratings must be between 1 and 10") # Must be between 0-10
    weight: float  # Percentage value
    comment: Optional[str]


class EvaluationSchema(BaseModel):
    title: str
    description: Optional[str]
    fields: List[EvaluationFieldSchema]


class EvaluationFieldResponse(BaseModel):
    id: int
    title_area: str
    weight: int
    rating: int
    comment: str


class EvaluationResponse(BaseModel):
    id: int
    title: str
    description: str | None
    evaluation_fields: Optional[List[EvaluationFieldResponse]] = []
