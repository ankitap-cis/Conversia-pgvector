from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from api.model_status.health import LLMService

llm_router = APIRouter()

@llm_router.get('/status')
async def llm_health(llm_service : LLMService = Depends()):
    try:
        status = await llm_service.check_health()
        return {"status": "OK" if status else "error"}
    except Exception:
        return {"status": "error"}