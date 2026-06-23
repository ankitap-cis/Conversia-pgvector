from fastapi import APIRouter, Depends, Request
from requests import Session
from uuid import UUID
from connection import get_db
from schemas.chatbot_schema import MessageForm
from utils.utils import get_current_user
from .chatbot_conversation import new_conversation, save_message, get_conversations, get_conversation


chatbot_conversation_router = APIRouter()


@chatbot_conversation_router.post("/new")
async def new_conversation_api(request: Request, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    return await new_conversation(request, None, db, current_user)


@chatbot_conversation_router.get("/list-conversations")
async def get_conversations_api(request: Request, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    return await get_conversations(request, None, db, current_user)


@chatbot_conversation_router.get("/list-conversations/{conversation_id}")
async def get_conversation_api(conversation_id: UUID, request: Request, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    return await get_conversation(conversation_id, request, db, current_user)


@chatbot_conversation_router.post("/{conversation_id}/message")
async def save_message_api(conversation_id: UUID, message: MessageForm, request: Request, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    return await save_message(conversation_id, message, request, db, current_user)
