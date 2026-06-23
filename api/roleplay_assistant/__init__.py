from decimal import Decimal
import email
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form, WebSocket, WebSocketDisconnect, Depends, status
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Optional, Literal
import asyncio
from pathlib import Path
import uuid
from api.ai_consumption.ai_token_credit import deduct_ai_credits, deduct_avatar_minutes
from api.ai_consumption.superadmin_token_dashboard import require_avatar_access, require_compute_access
from api.chatbot_conversation.chatbot_conversation import save_message
from api.roleplay_assistant.assistant import SalesEvaluator
from api.evaluation_criteria.evaluation_criteria import get_criteria_from_db
from sqlalchemy.orm import Session
from api.roleplay_assistant.general_chatbot import GeneralChatBot
from connection import get_db
from models.roleplay_models import Scenario
from schemas.roleplay_schema import SpeechRequest
from utils.utils import get_current_user, get_current_user_ws
from schemas.precall_plan_schema import PrecallPlanAIListResponse
from api.roleplay_assistant.rolplaybot import bot, RolePlaybot
from api.roleplay_assistant.features.field_intelligence_service import field_intel_bot
from api.roleplay_assistant.features.precall_plan_service import generate_precall_plan_logic
from models.users import Organization, User
from schemas.chatbot_schema import ChatInput
from models.conversation_models import ChatBotConversation
from logger import *
from types import SimpleNamespace
from threading import Lock
import configparser
from typing import Optional
import fitz
import docx2txt
import textract
import io
from threading import Lock
from functools import lru_cache
from .features.summarizer import generate_summary_logic
import redis
import json
import requests
from openai import AsyncOpenAI
import threading
from api.roleplay_assistant.features.speech_to_text import TranscriptionService
from api.roleplay_assistant.features.email_service import email_coach_bot
from api.roleplay_assistant.roleplay_extraction import extraction_bot
import uuid
from schemas.roleplay_schema import RoleplaySessionCreate, ExtractionRequest
from utils.file_loaders import *
from .content_generation.generation import merge_system_prompt
from .content_generation.utility import *
from .content_generation.documenttype import preload_document_prompts
from .content_generation.cache import warm_llm_cache
from utils.speech_usage import SpeechToTextUsage
from mutagen.mp3 import MP3
from utils.prompt_loader import inject_company_context
from schemas.course_schema import CourseSessionCreate
from langchain_openai import OpenAIEmbeddings
from langchain.vectorstores import Chroma 

audio_buffer = io.BytesIO()
buffer_lock = threading.Lock()

config = configparser.ConfigParser()
config.read('config.ini')

gpt_model = config['openAI_config']['model']
openai_api_key = config['openAI_config']['key']
content_generation_temperature = config['openAI_config'].getfloat('content_generation_temperature', fallback=0.4)
content_generation_maxtokens = config['openAI_config'].getint('content_generation_maxtokens', fallback=20000)
enhancement_temperature = config['openAI_config'].getfloat('enhancement_temperature', fallback=0.3)
content_generation_model = config['openAI_config'].get('content_generation_model', 'gpt-5.1')
transcription_model = config['openAI_config'].get('transcription_model', 'whisper-1')

general_bot = GeneralChatBot()

roleplay_assistant_router = APIRouter()
openai_client = AsyncOpenAI(api_key=openai_api_key)

redis_client = redis.Redis(
    host=config.get('redis_config', 'host', fallback='localhost'),
    port=config.getint('redis_config', 'port', fallback=6379),
    db=config.getint('redis_config', 'db', fallback=1),  # Different DB for bot state
    decode_responses=False
)

_easyocr_reader = None

def initialize_ocr():
    global _easyocr_reader
    if OCRConfig.ENABLE_EASYOCR and _easyocr_reader is None:
        try:
            import easyocr
            _easyocr_reader = easyocr.Reader(['en'], gpu=False)
            logger.info("EasyOCR reader pre-initialized")
        except Exception as e:
            logger.error(f"Failed to initialize EasyOCR: {e}")
 
 
def set_bot(session_id: str, bot: RolePlaybot):
    """Store bot state in Redis."""
    try:
        state = bot.get_state()
        redis_client.set(
            f"bot_state:{session_id}", 
            json.dumps(state),
            ex=86400  # 24 hour expiry
        )
        logger.info(f"Bot state saved for session: {session_id}")
    except Exception as e:
        logger.error(f"Failed to save bot state: {e}")
        raise
 
def get_bot(session_id: str) -> Optional[RolePlaybot]:
    """Retrieve bot state from Redis with validation."""
    try:
        data = redis_client.get(f"bot_state:{session_id}")
        if not data:
            logger.warning(f"No bot state found for {session_id}")
            return None
        
        state = json.loads(data.decode('utf-8'))
        
        # Validate required keys (removed 'app' since it's recreated)
        required_keys = ['llm_provider', 'system_prompt']
        missing_keys = [k for k in required_keys if k not in state]
        if missing_keys:
            logger.error(f"Missing required keys for {session_id}: {missing_keys}")
            return None
        
        bot = RolePlaybot.from_state(state)
        
        # Final validation
        if not bot or not hasattr(bot, 'app') or bot.app is None:
            logger.warning(f"Bot restoration failed for {session_id}")
            return None
        
        logger.info(f"Bot loaded successfully for {session_id}")
        return bot
        
    except (json.JSONDecodeError, KeyError, Exception) as e:
        logger.error(f"Failed to load bot state for {session_id}: {str(e)}")
        return None
 

def delete_bot(session_id: str):
    """Delete bot state from Redis."""
    try:
        redis_client.delete(f"bot_state:{session_id}")
        logger.info(f"Bot state deleted for session: {session_id}")
    except Exception as e:
        logger.error(f"Failed to delete bot state: {e}")


class ChatRequest(BaseModel):
    message: str
    stream: bool = False


class ChatResponse(BaseModel):
    message: str


class CustomQueryRequest(BaseModel):
    query: str


def get_scenario_document_chunks(org_id: int, scenario_id: int, limit: int = 20):
    persist_dir = f"./vectorstores/{org_id}/scenario_uploads/{scenario_id}"
    collection_name = f"scenario_{scenario_id}"

    embeddings = OpenAIEmbeddings(
        openai_api_key=OPENAI_API_KEY,
        model=embed_model
    )

    vectorstore = Chroma(
        collection_name=collection_name,
        persist_directory=persist_dir,
        embedding_function=embeddings
    )

    results = vectorstore.get(
        where={"scenario_id": str(scenario_id)},
        limit=limit
    )

    docs = results.get("documents", [])

    return "\n\n".join(docs) if docs else None


@roleplay_assistant_router.post("/setup")
async def setup_roleplay(
    scenario_id: Optional[int] = Form(None),
    personality_prompt: str = Form(""),
    scenario_prompt: str = Form(""),
    db: Session = Depends(get_db),
    current_user: Session = Depends(get_current_user)
):
    try:
        session_id = f"{uuid.uuid4().hex[:12]}"
        scenario_id = scenario_id
        system_prompt = None
        scenario_document_description = None
        
        # Get organization's master prompt
        if current_user.user_type == "org_admin":
            organization = db.query(Organization).filter(
                Organization.admin_id == current_user.id
            ).first()
            if organization:
                system_prompt = organization.master_prompt
        elif current_user.user_type == "sales_reps":
            if not current_user.organization_id:
                return None
            organization = db.query(Organization).filter(
                Organization.id == current_user.organization_id
            ).first()
            if organization:
                system_prompt = organization.master_prompt


        if scenario_id:
            scenario_document_description = get_scenario_document_chunks(
                org_id=current_user.organization_id,
                scenario_id=scenario_id,
                limit=20
            )

        # Create new bot instance
        bot = RolePlaybot(
            llm_provider="openai",
            llm_model_name=gpt_model,
            storage_dir="./chatdata"
        )
        
        if system_prompt:
            bot.custom_query = system_prompt

        # Setup personality and scenario
        personality = bot.create_personality(personality_prompt)
        scenario = bot.create_scenario(scenario_prompt)
        bot.thread_id = session_id
 
        # Save to Redis
        set_bot(session_id, bot)

        logger.info(f"Roleplay setup done successfully for {session_id}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Roleplay setup done successfully",
                "data": {
                    "session_id": session_id,
                    "personality": personality,
                    "scenario": scenario,
                    "system_prompt": bot.system_prompt,
                    "scenario_document_description": scenario_document_description
                }
            }
        )

    except Exception as e:
        logger.error(f"Setup error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": f"Setup Error: {str(e)}",
                "data": None
            }
        )


@roleplay_assistant_router.post("/chat/{scenario_id}/{session_id}", response_model=ChatResponse)
async def chat(
    scenario_id: int,
    session_id: str,
    request: ChatRequest,
    db: Session = Depends(get_db),
    current_user: Session = Depends(get_current_user),
    _ = Depends(require_compute_access)
):
    try:
        # Fetch the user's bot from Redis
        bot = get_bot(session_id)
        if not bot:
            logger.info(f"Recreating bot for {session_id} (scenario_id={scenario_id})")
            bot = RolePlaybot(
                llm_provider="openai",
                llm_model_name=gpt_model,
                storage_dir="./chatdata"
            )            
            # Safe scenario loading
            scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
            if scenario:
                scenario_prompt = (
                    f"Title: {scenario.title or ''}\n"
                    f"Description: {scenario.description or ''}"
                )
                logger.info(f"Using scenario_prompt: {scenario_prompt[:100]}...")
                bot.create_scenario(scenario_prompt)
                bot.active_scenario_id = str(scenario_id)
            
            # Org master prompt (same as setup)
            system_prompt = None
            org = None
            if current_user.user_type == "org_admin":
                org = db.query(Organization).filter(Organization.admin_id == current_user.id).first()
                system_prompt = org.master_prompt if org else None
            elif current_user.user_type == "sales_reps" and current_user.organization_id:
                org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
                system_prompt = org.master_prompt if org else None
            
            if system_prompt:
                bot.custom_query = system_prompt
            
            bot.thread_id = session_id
            set_bot(session_id, bot)
        
        # 3. Validate bot is functional
        if not hasattr(bot, 'app') or bot.app is None:
            logger.error(f"Bot app missing for {session_id} - rebuilding")
            bot.update_system_prompt()

        from api.user_management.user_management import get_company_context

        company_context = await get_company_context(db, current_user, return_raw=True)
        final_prompt = inject_company_context(bot.custom_query, company_context, current_user.org_name)

        # 4. Handle streaming vs non-streaming
        if request.stream:
            async def generate_stream():
                token_queue = asyncio.Queue()
                
                async def stream_callback(token):
                    await token_queue.put(token)

                chat_task = asyncio.create_task(
                    bot.astream_chat(request.message, stream_callback)
                )
                
                try:
                    # Stream tokens OR wait for task completion
                    while not chat_task.done():
                        try:
                            token = await asyncio.wait_for(token_queue.get(), timeout=1.0)
                            yield f"data: {json.dumps({'token': token})}\n\n"
                        except asyncio.TimeoutError:
                            continue  # No token yet, check task status
                    
                    # Wait for final result
                    complete_response = await chat_task
                    yield f"data: {json.dumps({'complete': True, 'full_response': complete_response})}\n\n"
                    
                except Exception as e:
                    # Cancel task on error
                    chat_task.cancel()
                    try:
                        await chat_task
                    except asyncio.CancelledError:
                        pass
                    logger.error(f"Stream error: {e}")
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"
                finally:
                    set_bot(session_id, bot)
            
            return StreamingResponse(generate_stream(), media_type="text/event-stream")

        else:
            # Non-streaming chat
            response, usage_metadata = bot.chat(
                request.message,
                system_prompt=final_prompt,
                thread_id=session_id,
                scenario_id=str(scenario_id),
                org_id=current_user.organization_id,
                session_id=session_id
            )
            
            # Update bot state in Redis
            set_bot(session_id, bot)

            await deduct_ai_credits(
                db=db,
                user_id=current_user.id,
                input_tokens=usage_metadata.prompt_tokens if usage_metadata else 0,
                output_tokens=usage_metadata.completion_tokens if usage_metadata else 0,
                stt_minutes=0.0,
                tts_minutes=0.0
            )          

            logger.info(f"Chat completed for session: {session_id}")
            
            return {"message": response,
                    "usage_metadata": usage_metadata if usage_metadata else None
                    }

    except redis.ConnectionError as e:
        logger.error(f"Redis connection error: {str(e)}")
        raise HTTPException(
            status_code=503,
            detail={
                "status": "failure",
                "message": "Chat history service unavailable",
                "data": None
            }
        )
    except Exception as e:
        logger.error(f"Chat error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "failure",
                "message": str(e),
                "data": None
            }
        )


@roleplay_assistant_router.post("/speech")
async def speech(
    request: SpeechRequest,
    db: Session = Depends(get_db),
    current_user: Session = Depends(get_current_user)
):
    try:
        if not request.text or not request.voice or not request.format:
            raise HTTPException(
                status_code=400,
                detail={"status": "failure", "message": "Missing required fields in request.", "data": None}
            )
 
        session_id = str(current_user.email)
 
        redis_key = f"isspeak:{session_id}"
 
        # Set the flag in Redis
        if request.isspeak:
            if redis_client.get(redis_key) == b"1":
                redis_client.set(redis_key, "0")
            redis_client.set(redis_key, "1")
        else:
            redis_client.set(redis_key, "0")

        if redis_client.get(redis_key) != b"1":
            return StreamingResponse((chunk for chunk in []), media_type="audio/mpeg")
 
        async def generate_audio():
            audio_buffer = b""

            try:
                async with openai_client.audio.speech.with_streaming_response.create(
                    model="gpt-4o-mini-tts",
                    voice=request.voice,
                    input=request.text,
                    response_format=request.format,
                    instructions="You should not tell anything "
                ) as response:

                    async for chunk in response.iter_bytes(chunk_size=4096):
                        if redis_client.get(redis_key) != b"1":
                            break

                        audio_buffer += chunk
                        yield chunk

                # Extract MP3 duration (exact)
                if request.format == "mp3":
                    audio = MP3(io.BytesIO(audio_buffer))
                    duration_seconds = audio.info.length
                else:
                    # fallback for wav
                    import wave
                    wav_file = wave.open(io.BytesIO(audio_buffer), "rb")
                    frames = wav_file.getnframes()
                    rate = wav_file.getframerate()
                    duration_seconds = frames / float(rate)

                tts_minutes = Decimal(str(round(duration_seconds / 60, 6)))

                await deduct_ai_credits(
                    db=db,
                    user_id=current_user.id,
                    input_tokens=0,
                    output_tokens=0,
                    tts_minutes=tts_minutes
                )

            except Exception as e:
                logger.error(f"TTS Error: {e}")
                yield b'API error: {e}'

        media_type = (
            "audio/mpeg" if request.format == "mp3"
            else "audio/wav" if request.format == "wav"
            else "audio/pcm"
        )

        return StreamingResponse(generate_audio(), media_type=media_type)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"status": "failure", "message": str(e), "data": None}
        )


@roleplay_assistant_router.post("/upload-documents")
async def upload_documents(files: List[UploadFile] = File(...)):
    """
    Upload documents separately for the active scenario.
    """
    try:
        document_paths = []
        upload_dir = Path("./uploads")
        upload_dir.mkdir(exist_ok=True)

        for file in files:
            if file.filename and file.filename.strip():
                file_extension = Path(file.filename).suffix
                unique_filename = f"{uuid.uuid4().hex}{file_extension}"
                file_path = upload_dir / unique_filename

                with open(file_path, "wb") as buffer:
                    buffer.write(await file.read())

                document_paths.append(str(file_path))

        # Attach to scenario if exists
        if document_paths and bot.active_scenario_id:
            vectorstore = bot.scenario_handler.process_documents(
                document_paths, bot.active_scenario_id
            )
            bot.active_scenario.setdefault("documents", []).extend(document_paths)

        return {
            "status": "success",
            "message": "Documents uploaded successfully",
            "data": {"document_paths": document_paths},
        }

    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Upload error: {str(e)}")


@roleplay_assistant_router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            request_data = json.loads(data)
            user_message = request_data.get("message", "")
            
            if not user_message:
                await websocket.send_json({"error": "No message provided"})
                continue
            async def stream_callback(token):
                await websocket.send_json({"token": token})
            response = await bot.astream_chat(user_message, stream_callback)
            await websocket.send_json({"complete": True, "full_response": response})
    except WebSocketDisconnect:
        logger.error(f"WebSocket disconnected")

    except Exception as e:
        logger.error(f"Error in websocket chat{str(e)}")
        raise HTTPException(
            status_code= status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Error in websocket chat",
                "data": None
            }
        )


@roleplay_assistant_router.post("/clear")
async def clear_memory():
    try:
        bot.clear_memory()

        logger.info(f"Chat history cleared successfully.")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Chat history cleared",
                "data": None    
            }
        )

    except Exception as e:
        logger.error(f"Failed to create memory {str(e)}")
        raise HTTPException(
            status_code= status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Failed to create memory",
                "data": None
            }
        )


@roleplay_assistant_router.get("/chat-history")
async def get_chat_history(thread_id: str | None = None):
    try:
        # fall back to whatever thread the user is in
        thread_id = thread_id or bot.active_scenario_id or "default"

        # MemorySaver keeps a checkpoint for each thread; recover it
        state = bot.app.get_state({"configurable": {"thread_id": thread_id}})
        messages = state.values.get("messages", []) if state else []

        chat_history = [
            {
                "type": "human" if msg.type == "human" else "ai",
                "content": msg.content
            }
            for msg in messages
        ]

        logger.info(f"Chat history fetched successfully.")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Chat history fetched successfully.",
                "data":{ "chat_history" : chat_history,
                        "total_messages": len(chat_history)
                    }          
                }
            )

    except Exception as e:
        logger.error(f"Failed to retrieve chat history.{str(e)}")
        raise HTTPException(
            status_code= status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Failed to retrieve chat history.",
                "data": None
            }
        )


@roleplay_assistant_router.get("/chat-history-evaluation/{scenario_id}/{session_id}/{bot_state_id}")
async def get_chat_history_evaluation(
    bot_state_id: str,
    scenario_id: int,
    session_id: int,
    db: Session = Depends(get_db),
    current_user: Session = Depends(get_current_user),
    _ = Depends(require_compute_access)
):
    try:
        from api.roleplay.roleplay_session import get_roleplay_session
        response = await get_roleplay_session(session_id, db, current_user)

        session_content = response.body.decode("utf-8")
        session_json = json.loads(session_content)

        if not session_json.get("data") or not session_json["data"].get("messages"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"status": "failure", "message": "No chat history found", "data": None}
            )

        chat_history = [
            {
                "type": "human" if msg["sender"] == "user" else "ai",
                "content": msg["message"]
            }
            for msg in session_json["data"]["messages"]
        ]

        scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
        scenario_name = scenario.title if scenario else "Unknown Scenario"

        evaluation_prompt = None

        if current_user.user_type in [
            "org_admin",
            "content_creator",
            "exec_viewer",
            "field_manager",
            "sales_reps"
        ]:
            if not current_user.organization_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "status": "failure",
                        "message": "Organization not found for user"
                    }
                )

            organization = (
                db.query(Organization)
                .filter(Organization.id == current_user.organization_id)
                .first()
            )

            if organization:
                evaluation_prompt = (
                    organization.evaluation_prompt
                    or organization.master_prompt
                )

        evaluation_criteria = get_criteria_from_db(scenario_id, db)
        evaluator = SalesEvaluator(
            bot=get_bot(bot_state_id),
            evaluation_criteria=evaluation_criteria
        )

        result, token_callback = evaluator.evaluate(
            evaluation_prompt,
            thread_id=(bot_state_id),
            scenario_name=scenario_name,
            chat_history=chat_history
        )

        usage_metadata = {
            "input_tokens": getattr(token_callback, "prompt_tokens", 0) or 0,
            "output_tokens": getattr(token_callback, "completion_tokens", 0) or 0,
            "total_tokens": getattr(token_callback, "total_tokens", 0) or 0
        }
        await deduct_ai_credits(
            db,
            current_user.id,
            input_tokens=usage_metadata["input_tokens"],
            output_tokens=usage_metadata["output_tokens"],
            stt_minutes=0.0,
            tts_minutes=0.0
        )

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "success", "message": "Chat history evaluated successfully.", "data": result}
        )

    except Exception as e:
        logger.error(f"Evaluation Failed {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failure", "message": "Evaluation Failed", "data": None}
        )

# formatter function for precall_plan to generate the output in html
def extract_text_from_file(filename: str, file_bytes: bytes) -> Optional[str]:
    ext = filename.rsplit(".", 1)[-1].lower()

    try:
        if ext == "pdf":
            with fitz.open(stream=file_bytes, filetype="pdf") as doc:
                return "\n".join(page.get_text() for page in doc)

        elif ext == "txt":
            return file_bytes.decode("utf-8")

        elif ext == "docx":
            # Use docx2txt
            file_stream = io.BytesIO(file_bytes)
            return docx2txt.process(file_stream)

        elif ext in ["doc", "ppt", "pptx"]:
            # Use textract for legacy Office files and PPT
            # Requires `libmagic` and `antiword`/`catppt` on system
            return textract.process(io.BytesIO(file_bytes)).decode("utf-8")

    except Exception as e:
        logger.error(f"Failed to extract file text: {e}")
        return ""


@roleplay_assistant_router.post("/generate-precall-plan", response_model=PrecallPlanAIListResponse)
async def generate_precall_plan(
    input_data: str = Form(...),
    file: Optional[UploadFile] = File(None),
    files: Optional[List[UploadFile]] = File(None, description="List of files for summarization (max 5)"),
    db: Session = Depends(get_db),
    current_user: Session = Depends(get_current_user),
    _ = Depends(require_compute_access)
):
    try:
        DEFAULT_PRECALL_PROMPT = """
        Please generate a clinically sound and business-relevant Pre-call Plan tailored to a sales rep. 
        Use professional tone, tight structure, and ensure content reflects insights, objections, and value points from the uploaded file.
        """
        precall_plan_prompt = None  # Initialize early

        if current_user.user_type in ["org_admin", "content_creator", "exec_viewer", "field_manager"]:
            organization = db.query(Organization).filter(Organization.admin_id == current_user.id).first()
            if organization:
                precall_plan_prompt = organization.precall_prompt

        elif current_user.user_type == "sales_reps":
            user_record = db.query(User).filter(User.id == current_user.id).first()
            if not user_record or not user_record.created_by:
                return None
            created_by_email = user_record.created_by
            creator_user = db.query(User).filter(User.email == created_by_email).first()
            if creator_user:
                organization = db.query(Organization).filter(Organization.admin_id == creator_user.id).first()
                if organization:
                    precall_plan_prompt = organization.precall_prompt

        # Fallback to default prompt if none is configured
        precall_plan_prompt = (precall_plan_prompt or DEFAULT_PRECALL_PROMPT).strip()

        from api.user_management.user_management import get_company_context

        company_context = await get_company_context(db, current_user, return_raw=True)
        precall_plan_prompt = inject_company_context(precall_plan_prompt, company_context, current_user.org_name)

        logger.info("Generating pre call plan.")

        try:
            parsed_input: dict = json.loads(input_data)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON in input_data")

        doc_text = ""

        if file and file.filename:
            try:
                file_bytes = await file.read()
                doc_text = await process_document(
                    source=file_bytes,
                    filename=file.filename,
                    return_documents=False,
                    enable_ocr=True
                ) or ""
                logger.info(f"Processed document: {file.filename}")
            except Exception as e:
                logger.error(f"Error processing document: {e}", exc_info=True)

        screenshot_texts = []

        if files:
            if len(files) > 5:
                raise HTTPException(
                    status_code=400,
                    detail="Maximum 5 screenshots allowed."
                )

            for img in files:
                try:
                    img_bytes = await img.read()

                    text = await process_document(
                        source=img_bytes,
                        filename=img.filename,
                        return_documents=False,
                        enable_ocr=True
                    )

                    if text:
                        screenshot_texts.append(f"[Screenshot]\n{text}")
                    logger.info(f"Processed screenshot: {img.filename}")
                except Exception as e:
                    logger.error(f"Error processing screenshot: {e}", exc_info=True)

        additional_context = parsed_input.get("additionalContext", "")
        combined_uploaded_text = "\n\n".join(
            filter(None, [
                additional_context,
                doc_text,
                "\n\n".join(screenshot_texts)
            ])

        )

        data, usage_metadata = generate_precall_plan_logic(parsed_input, precall_plan_prompt,  current_user.organization_id, combined_uploaded_text)
        await deduct_ai_credits(
            db=db,
            user_id=current_user.id,
            input_tokens=usage_metadata['input_tokens'] if usage_metadata else 0,
            output_tokens=usage_metadata['output_tokens'] if usage_metadata else 0,
            stt_minutes=0.0,
            tts_minutes=0.0
        )
        
        logger.info("Pre call plan generated successfully.")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Pre call plan generated successfully.",
                "data": data,
                "usage_metadata": usage_metadata if usage_metadata else None,
                 "input_summary": {
                    "doc_processed": bool(doc_text),
                    "screenshots_processed": len(screenshot_texts),
                    "has_additional_context": bool(additional_context)
                }
            }
        )

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "status": "failure",
                "message": "Invalid JSON format in input data",
                "data": None
            }
        )

    except Exception as e:
        logger.error(f"Error generating pre call plan: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Error generating pre call plan",
                "data": None
            }
        )

_general_bot_lock = Lock()

@lru_cache(maxsize=100)
def _cached_general_bot(user_id: str, org_id: int = None) -> GeneralChatBot:
    return GeneralChatBot(storage_dir=f"./chatdata/{user_id}", org_id=org_id)

def get_general_bot(user_id: str, org_id: int = None) -> GeneralChatBot:
    with _general_bot_lock:
        return _cached_general_bot(user_id, org_id)

@roleplay_assistant_router.post("/general-chat/{conversation_id}")
async def general_chat(
    conversation_id: str, 
    request: Request, 
    input: ChatInput, 
    db: Session = Depends(get_db), 
    current_user: Session = Depends(get_current_user),
    _ = Depends(require_compute_access)
):
    try:
        logger.info(f"Received general chat input: {input.message}")
        chatbot_prompt = "You are an assistant."
        
        # Get organization's chatbot prompt
        organization = None
        if current_user.user_type in ["org_admin", "content_creator", "exec_viewer", "field_manager"]:
            organization = db.query(Organization).filter(
                Organization.admin_id == current_user.id
            ).first()
            if organization:
                chatbot_prompt = organization.chatbot_prompt
        elif current_user.user_type == "sales_reps":
            user_record = db.query(User).filter(User.id == current_user.id).first()
            if not user_record or not user_record.created_by:
                return JSONResponse(
                    status_code=400, 
                    content={"message": "Sales rep's creator not found."}
                )
            creator_user = db.query(User).filter(
                User.email == user_record.created_by
            ).first()
            if creator_user:
                organization = db.query(Organization).filter(
                    Organization.admin_id == creator_user.id
                ).first()
                if organization:
                    chatbot_prompt = organization.chatbot_prompt

        # Get bot instance (cached by user_id)
        general_bot = get_general_bot(str(current_user.id), organization.id if organization else None)
        await general_bot.load_history_from_db(conversation_id, db)
        from api.user_management.user_management import get_company_context

        company_context = await get_company_context(db, current_user, return_raw=True)
        system_prompt = inject_company_context(chatbot_prompt, company_context, current_user.org_name)

        # Chat with Redis history (session_id = conversation_id)
        response_data = general_bot.chat(
            message=input.message, 
            session_id=conversation_id,  # Redis will store history per conversation
            system_prompt=system_prompt ,
            org_id=organization.id if organization else None
        )

        # Save to database
        message = SimpleNamespace(
            role="assistant", 
            content=response_data["answer"], 
            source_file_key=response_data["file_path_and_name"]
        )
        usage_metadata = response_data.get('usage_metadata', {})
        await deduct_ai_credits(
            db=db,
            user_id=current_user.id,
            input_tokens=usage_metadata.get('input_tokens', 0),
            output_tokens=usage_metadata.get('output_tokens', 0),
            stt_minutes=0.0,
            tts_minutes=0.0
        )
        
        await save_message(conversation_id, message, request, db, current_user)
        general_bot.add_assistant_message_to_redis(conversation_id, response_data["answer"])

        # Update conversation title if needed
        conversation = db.query(ChatBotConversation).filter(
            ChatBotConversation.id == conversation_id
        ).first()
        if conversation and conversation.title == "New Chat":
            generated_title = general_bot.generate_chat_title(
                input.message, 
                response_data["answer"], 
                general_bot.llm
            )
            conversation.title = generated_title
            db.commit()

        logger.info(f"General chat completed for conversation: {conversation_id}")

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Response generated successfully",
                "data": response_data["answer"],
                "file_path_and_name": response_data["file_path_and_name"],
            }
        )

    except Exception as e:
        logger.error(f"Error during general chat: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Error generating response",
                "data": None
            }
        )


@roleplay_assistant_router.post("/generate-email")
async def generate_email(
    combined_input: str = Form(..., description="Specify all email details in natural language."),
    file: UploadFile = File(None, description="Optional file for additional context"),
    files: Optional[List[UploadFile]] = File(None, description="Optional multiple files for additional context"),
    current_user: Session = Depends(get_current_user),
    db: Session = Depends(get_db),
    _ = Depends(require_compute_access)
):
    try:
        email_prompt = "You are an expert email writer. Generate professional emails based on user requirements."
        if not current_user.organization_id and current_user.user_type == "sales_reps":
            user_record = db.query(User).filter(User.id == current_user.id).first()
            if not user_record or not user_record.created_by:
                return JSONResponse(status_code=400, content={"message": "Sales rep's creator not found."})
            creator_user = db.query(User).filter(User.email == user_record.created_by).first()
            if creator_user:
                current_user.organization_id = creator_user.organization_id
        # Fetch organization-specific prompt if exists
        if current_user.organization_id:
            organization = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
            if organization and organization.email_prompt:
                email_prompt = organization.email_prompt
        # Validate required input
        if not combined_input.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "failure",
                    "message": "Input is required. Please specify at least your role and audience.",
                    "data": {
                        "example": "I am a sales manager writing to potential clients. Key points: pricing, demo schedule.",
                        "minimum_required": ["role", "audience"],
                        "optional_fields": ["subject", "tone", "key_points", "deadline", "priority", "call_to_action", "length"]
                    }
                }
            )

        # Prepare input data
        parsed_input = {"combined_input": combined_input.strip()}

        # Handle single file (backward compatibility)
        # Default values when no files are uploaded
        uploaded_texts = []
        uploaded_text = ""

        # Handle single file (backward compatibility)
        if file and file.filename:
            files = [file] if not files else files + [file]

        # Process multiple files
        if files:
            try:
                async def process_single_file(f: UploadFile):
                    try:
                        file_bytes = await f.read()
                        text = await process_document(
                            source=file_bytes,
                            filename=f.filename,
                            enable_ocr=True,
                            ocr_language="eng",
                            ocr_dpi=300,
                            return_documents=False
                        )
                        return text or ""
                    except Exception as e:
                        logger.error(f"Error processing file {f.filename}: {e}")
                        return ""

                # Run in parallel
                results = await asyncio.gather(
                    *[process_single_file(f) for f in files],
                    return_exceptions=True
                )

                # Filter valid results
                uploaded_texts = [
                    r for r in results if isinstance(r, str) and r.strip()
                ]

            except Exception as e:
                logger.error(f"Error processing multiple files: {e}", exc_info=True)

        from api.user_management.user_management import get_company_context
        company_context = await get_company_context(db, current_user, return_raw=True)
        email_prompt = inject_company_context(email_prompt, company_context, current_user.org_name)


        # Combine all extracted text
        uploaded_text = "\n\n".join(uploaded_texts)

        email_content, token_callback = await email_coach_bot.generate_email_logic(
            parsed_input=parsed_input,
            uploaded_text=uploaded_text,
            email_prompt=email_prompt,
            user_id=current_user.id,
            organization_id=current_user.organization_id,
            org_name=current_user.org_name,
            general_bot=get_general_bot(str(current_user.id), current_user.organization_id)
        )
        usage_metadata = {
            "input_tokens": token_callback.prompt_tokens if token_callback else 0,
            "output_tokens": token_callback.completion_tokens if token_callback else 0,
            "total_tokens": token_callback.total_tokens if token_callback else 0
        }

        await deduct_ai_credits(db, current_user.id, usage_metadata["input_tokens"], usage_metadata["output_tokens"])

        logger.info("Email generated successfully")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Email generated successfully.",
                "data": {
                    "email": email_content,
                    "input_summary": {
                        "original_input": combined_input,
                        "file_processed": bool(uploaded_text),
                        "file_name": file.filename if file and file.filename else None
                    },
                    "usage_metadata": usage_metadata
                }
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in generate_email endpoint: {e}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"status": "failure", "message": "Internal server error."}
        )


@roleplay_assistant_router.post("/generate-summary")
async def generate_summary(
    summary_request: Optional[str] = Form(None, description="Describe who you are, how you'll use the summary, and desired output format"),
    additional_context: str = Form("", description="Any additional optional context"),
    files: Optional[List[UploadFile]] = File(None, description="List of files for summarization (max 5)"),
    file: UploadFile = File(None, description="Optional file for summarization"),
    current_user: Session = Depends(get_current_user),
    db: Session = Depends(get_db),
    _ = Depends(require_compute_access)
):
    try:
        # Default summarizer prompt
        summarizer_prompt = "You are an expert summarizer. Generate clear and structured summaries based on user requirements."

        # Handle org-specific prompts if they exist

        if not current_user.organization_id and current_user.user_type == "sales_reps":
            user_record = db.query(User).filter(User.id == current_user.id).first()
            if not user_record or not user_record.created_by:
                return JSONResponse(status_code=400, content={"message": "Sales rep's creator not found."})
            creator_user = db.query(User).filter(User.email == user_record.created_by).first()
            if creator_user:
                current_user.organization_id = creator_user.organization_id

        if current_user.organization_id:
            organization = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
            if organization and organization.summarizer_prompt:
                summarizer_prompt = organization.summarizer_prompt

        # Validate required input
        if not summary_request.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "failure",
                    "message": "'summary_request' field is required.",
                    "data": {
                        "minimum_required": ["summary_request"],
                        "optional_fields": ["additional_context", "file"]
                    }
                }
            )

        # Extract text from uploaded file
        uploaded_text = ""
        if file and file.filename:
            try:
                file_bytes = await file.read()
                uploaded_text = await process_document(
                    source=file_bytes,
                    filename=file.filename,
                    enable_ocr=True,
                    ocr_language="eng",
                    ocr_dpi=300,
                    return_documents=False  # Returns plain text string
                )

                logger.info(f"Processed document: {file.filename}")

                if not uploaded_text:
                    uploaded_text = ""
                    
            except Exception as file_error:
                logger.error(f"Error extracting file: {str(file_error)}", exc_info=True)
                uploaded_text = ""

        screenshot_texts = []

        if files:
            for f in files:
                try:
                    file_bytes = await f.read()
                    text = await process_document(
                        source=file_bytes,
                        filename=f.filename,
                        enable_ocr=True,
                        ocr_language="eng",
                        ocr_dpi=300,
                        return_documents=False
                    )

                    if text:
                        screenshot_texts.append(f"[Screenshot: {f.filename}]\n{text}")

                except Exception as e:
                    logger.error(f"Error processing file {f.filename}: {e}", exc_info=True)

        combined_context = "\n\n".join(
            filter(None, [
                additional_context.strip(),
                uploaded_text,
                "\n\n".join(screenshot_texts)
            ])
        )

        # Prepare structured input
        parsed_input = {
            "summary_request": summary_request.strip(),
            "additional_context": combined_context
        }
        from api.user_management.user_management import get_company_context

        company_context = await get_company_context(db, current_user, return_raw=True)
        summarizer_prompt = inject_company_context(summarizer_prompt, company_context, current_user.org_name)

        # Generate summary content
        summary_content = await generate_summary_logic(parsed_input, summarizer_prompt, current_user.id, current_user.organization_id)
        usage_metadata = summary_content[1]
        await deduct_ai_credits(db, current_user.id, usage_metadata["input_tokens"], usage_metadata["output_tokens"])
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Summary generated successfully.",
                "data": {
                    "summary": summary_content,
                    "input_summary": parsed_input,
                    "summary_request": summary_request,
                    "additional_context": additional_context,
                    "file_processed": bool(uploaded_text),
                    "screenshots_processed": len(screenshot_texts)
                }
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating summary: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Error generating summary",
                "data": None
            }
        )

@roleplay_assistant_router.post("/generate-ephemeral-key")
async def generate_ephemeral_key(
    expires_seconds: int = 600,
    model: str = "gpt-realtime-1.5",
    instructions: str = "You are a friendly assistant."
):
    url = "https://api.openai.com/v1/realtime/client_secrets"
    
    payload = {
        "expires_after": {
            "anchor": "created_at",
            "seconds": expires_seconds
        },
        "session": {
            "type": "realtime",
            "model": model,
            "instructions": instructions
        }
    }
    headers = {
        "Authorization": f"Bearer {openai_api_key}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=response.json()
        )
    except requests.RequestException as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
        
        
async def websocket_endpoint(
    client_websocket: WebSocket,
    db: Session = Depends(get_db)
):
    token = client_websocket.query_params.get("token")

    if not token:
        await client_websocket.close(code=1008)
        return

    current_user = await get_current_user_ws(token, db)

    if not current_user:
        logger.warning(f"Auth failed for token: {token[:20]}...")
        await client_websocket.close(code=1008)
        return

    # Accept ONLY after successful auth
    await client_websocket.accept()
    logger.info(f"WebSocket connected for user: {current_user.email}")

    transcription_service = TranscriptionService(
        api_key=openai_api_key,
        model=gpt_model
    )

    usage_tracker = SpeechToTextUsage(model=gpt_model)

    # Optional: start session timer immediately
    usage_tracker.start_session()

    try:
        usage = await transcription_service.handle_transcription(
            client_websocket,
            usage_tracker
        )

    except WebSocketDisconnect as e:
        logger.info(
            f"Client disconnected: {current_user.email}, code={e.code}"
        )

    except Exception as e:
        logger.error(
            f"Unexpected WebSocket error for {current_user.email}: {e}"
        )

    finally:

        try:
            if client_websocket.client_state != client_websocket.client_state.DISCONNECTED:
                await client_websocket.close()
        except Exception:
            pass

        try:
            if current_user and usage:
                logger.info(f"STT usage for user {current_user.email}: {usage}")

                audio_seconds = Decimal(str(usage.get("audio_seconds", 0)))
                audio_minutes = Decimal(str(usage.get("audio_minutes", 0)))

                print(f"🎙 Audio seconds: {audio_seconds}")
                print(f"🎙 Audio minutes: {audio_minutes}")

                if audio_minutes > 0:
                    await deduct_ai_credits(
                        db,
                        current_user.id,
                        input_tokens=0.0,
                        output_tokens=0.0,
                        stt_minutes=audio_minutes,
                        tts_minutes=0.0
                    )

        except Exception as billing_error:
            logger.error(
                f"Billing error for {current_user.email}: {billing_error}"
            )

        logger.info(f"WebSocket session closed for {current_user.email}")


@roleplay_assistant_router.post("/submit-session-history/{bot_state_id}")
async def submit_session_history_api(
    bot_state_id: str,
    session_data: RoleplaySessionCreate,
    db: Session = Depends(get_db),
    current_user: Session = Depends(get_current_user)
):
    print("Avatar minutes:", session_data.avatar_minutes)
    """
    Submit session history (chat, audio, or video) and append to Redis.
    media_type flag determines the source (optional).
    """
    # Default to "chat" if media_type is not provided
    media_type = session_data.media_type or "chat"
    if media_type == "audio":
        await require_compute_access(db=db, current_user=current_user)

    elif media_type == "video":
        await require_avatar_access(db=db, current_user=current_user)
    
    logger.info(f"Submitting {media_type} history for bot_state_id: {bot_state_id}, user: {current_user.email}")

    if session_data.avatar_minutes:
        await deduct_avatar_minutes(
            db,
            current_user.id,
            session_data.avatar_minutes
        )

    if session_data.input_tokens and session_data.output_tokens:
        await deduct_ai_credits(
            db,
            current_user.id,
            input_tokens=session_data.input_tokens,
            output_tokens=session_data.output_tokens,
            stt_minutes=0.0,
            tts_minutes=0.0
        )

    try:
        bot = get_bot(bot_state_id)
        if not bot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": f"Bot state not found for {bot_state_id}",
                    "data": None
                }
            )
        
        history = bot._get_redis_history(bot_state_id)
        
        # Add all messages regardless of media_type
        for msg in session_data.messages:

            if msg.sender == "user":
                history.add_user_message(msg.message)
            elif msg.sender == "assistant":
                history.add_ai_message(msg.message)
        
        logger.info(f"{media_type.capitalize()} history ({len(session_data.messages)} messages) saved to Redis for thread: {bot_state_id}")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": f"{media_type.capitalize()} history appended successfully",
                "data": {
                    "bot_state_id": bot_state_id,
                    "messages_added": len(session_data.messages),
                    "media_type": media_type
                }
            }
        )
    
    except HTTPException:
        raise
    except redis.ConnectionError as e:
        logger.error(f"Redis connection lost: {e}")
        raise HTTPException(status_code=503, detail="Service unavailable")
    except Exception as e:
        logger.error(f"Error submitting {media_type} history: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to submit {media_type} history")


@roleplay_assistant_router.post("/submit-course-history")
async def submit_course_session_history(
    course_session_id: str,
    session_data: CourseSessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Save course session messages (chat/audio) to DB
    """

    try:
        media_type = session_data.media_type or "chat"

        if media_type == "audio":
            await require_compute_access(db=db, current_user=current_user)

        logger.info(
            f"Submitting {media_type} history for session_id: {course_session_id}, user: {current_user.email}"
        )

        if session_data.avatar_minutes:
            await deduct_avatar_minutes(
                db,
                current_user.id,
                session_data.avatar_minutes
            )

        if session_data.input_tokens and session_data.output_tokens:
            await deduct_ai_credits(
                db,
                current_user.id,
                input_tokens=session_data.input_tokens,
                output_tokens=session_data.output_tokens,
                stt_minutes=0.0,
                tts_minutes=0.0
            )

        valid_messages = [
            msg for msg in session_data.messages
            if msg.message and msg.message.strip()
        ]

        if not valid_messages:
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "success",
                    "message": "No valid messages to save",
                    "data": {
                        "course_session_id": course_session_id,
                        "messages_added": 0
                    }
                }
            )

        logger.info(f"Valid messages count: {len(valid_messages)}")

        for msg in valid_messages:
            msg.is_course = True
            await save_message(
                conversation_id=course_session_id,
                message=msg,
                db=db,
                current_user=current_user
            )

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": f"{media_type.capitalize()} history saved successfully",
                "data": {
                    "course_session_id": course_session_id,
                    "messages_added": len(valid_messages),
                    "media_type": media_type
                }
            }
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Error submitting {media_type} history: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to submit {media_type} history"
        )


async def preload_content_generation():
    logger.info("Preloading content generation resources...")
    # 1. Preload document prompts (async)
    await preload_document_prompts()
    # 2. Warm LLM cache with common temperatures
    temperatures = [
        0.0,
        enhancement_temperature, 
        content_generation_temperature,
    ]
    warm_llm_cache(gpt_model, temperatures, openai_api_key)
    
    logger.info("Content generation resources preloaded")

@roleplay_assistant_router.post("/generate-content")
@retry_on_openai_error(max_retries=3, backoff_base=2.0) 
async def generate_content(
    primary_objective: Optional[str] = Form(None, description="Most important goal/message"),
    audience: Optional[str] = Form(None, description="Target audience description"),
    intent: str = Form(..., description="Communication intent/purpose"),
    desired_outcome: str = Form(..., description="Desired outcome"),
    motivation_points: Optional[str] = Form(None, description="Goals/pain points"),
    supporting_message: Optional[str] = Form(None, description="Supporting facts"),
    key_evidence: Optional[str] = Form(None, description="Evidence, quotes, data"),
    additional_context: Optional[str] = Form(None, description="Additional guidelines"),
    document_type: Literal["presentation", "customer_talk_track", "customer_communication", "internal_communication", "faqs"] = "presentation",
    file: Optional[UploadFile] = File(None, description="Optional reference file"),
    reasoning: Optional[bool] = Form(False, description="Enable reasoning enhancement"),
    retrieval: Optional[bool] = Form(True, description="Enable document retrieval"),
    db: Session = Depends(get_db),
    current_user: Session = Depends(get_current_user),
     _ = Depends(require_compute_access)
):
    request_id = str(uuid.uuid4())
    organization = None
    reasoning = False
    org_id = int(current_user.organization_id) if current_user.organization_id else None
    reasoning = False
    if current_user.user_type in ["org_admin", "content_creator", "exec_viewer"]:
        organization = (
            db.query(Organization)
            .filter(Organization.admin_id == current_user.id)
            .first()
        )
        
    admin_prompt = None
    
    if organization:
        admin_prompt = organization.content_creator_prompt

    logger.info(
        f"Content generation request initiated",
        extra={
            "request_id": request_id,
            "has_file": file is not None,
            "document_type": document_type,
        }
    )
    try:
        general_bot_instance = None
        enable_retrieval = retrieval
        if enable_retrieval:
            try:
                user_id = f"content_gen_{request_id[:8]}"
                general_bot_instance = get_general_bot(user_id, org_id)
                logger.info(f"GeneralChatBot initialized for retrieval (org_id={org_id})")
            except Exception as bot_error:
                logger.warning(f"Failed to initialize GeneralChatBot: {bot_error}")

        from api.user_management.user_management import get_company_context

        company_context = await get_company_context(db, current_user, return_raw=True)
        organization = company_context

        admin_prompt = inject_company_context(admin_prompt, organization, current_user.org_name) if admin_prompt else None

        logger.info(f"CONTENT GEN enable_retrieval={enable_retrieval}")
        logger.info(f"CONTENT GEN general_bot exists={general_bot_instance is not None}")
        logger.info(f"CONTENT GEN org_id={org_id}")
        logger.info(f"CONTENT GEN file exists={file is not None}")


        result = await merge_system_prompt(
            system_prompt=admin_prompt,
            primary_objective=primary_objective,
            audience=audience,
            intent=intent,
            desired_outcome=desired_outcome,
            motivation_points=motivation_points,
            supporting_message=supporting_message,
            key_evidence=key_evidence,
            additional_context=additional_context,
            file=file,
            document_type=document_type.lower() if document_type else None,
            openai_api_key=openai_api_key,
            model=content_generation_model,
            enable_enhancement=True,
            general_bot=general_bot_instance,
            org_id=org_id,
            enable_retrieval=enable_retrieval,
            reasoning=reasoning,
            request_id=request_id,
            db=db,
            current_user=current_user
        )
        logger.info(
            f"Content generated successfully",
            extra={
                "request_id": request_id,
                "processing_time": result.metadata.get("processing_time_seconds"),
                "structured_output": result.structured_output
            }
        )
        usage_metadata=result.usage_metadata

        await deduct_ai_credits(
            db=db,
            user_id=current_user.id,
            input_tokens=usage_metadata['input_tokens'] if usage_metadata else 0,
            output_tokens=usage_metadata['output_tokens'] if usage_metadata else 0,
            stt_minutes=0.0,
            tts_minutes=0.0
        )


        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Content generated successfully",
                "request_id": request_id,
                "data": {
                    "content": result.generated_content,
                    "document_type": document_type,
                    "structured_output": result.structured_output,
                    "metadata": {
                        "model": content_generation_model,
                        "temperature": content_generation_temperature,
                        "output_schema": result.output_schema.__name__ if result.output_schema else None,
                        "docs_retrieved": result.metadata.get("docs_retrieved", 0),
                        "processing_time_seconds": result.metadata.get("processing_time_seconds")
                    }
                },
                "usage_metadata": usage_metadata
            }
        )
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(
            f"Critical error in content generation",
            extra={
                "request_id": request_id,
                "error": str(e)
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Error generating content. Please try again.",
                "request_id": request_id,
                "error_type": type(e).__name__
            }
        )
        

from fastapi import Form, File, UploadFile, HTTPException, status
from typing import List, Optional
import json

@roleplay_assistant_router.post("/extract")
async def extract_fields(
    description: str = Form(...),
    file: Optional[UploadFile] = File(None),
    files: Optional[List[UploadFile]] = File(None, description="Max 5 images"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _ = Depends(require_compute_access)
):
    try:
        from api.user_management.user_management import get_company_context

        company_context = await get_company_context(
            db, current_user, return_raw=True
        )

        doc_text = ""

        if file and file.filename:
            try:
                file_bytes = await file.read()
                doc_text = await process_document(
                    source=file_bytes,
                    filename=file.filename,
                    return_documents=False,
                    enable_ocr=True
                ) or ""
            except Exception as e:
                logger.error(f"Error processing document: {e}", exc_info=True)

        screenshot_texts = []

        if files:
            if len(files) > 5:
                raise HTTPException(
                    status_code=400,
                    detail="Maximum 5 files allowed"
                )

            for img in files:
                try:
                    img_bytes = await img.read()

                    text = await process_document(
                        source=img_bytes,
                        filename=img.filename,
                        return_documents=False,
                        enable_ocr=True
                    )

                    if text:
                        screenshot_texts.append(f"[Screenshot]\n{text}")

                except Exception as e:
                    logger.error(f"Error processing file: {e}", exc_info=True)

        combined_context = f"""
USER DESCRIPTION:
{description}

DOCUMENT CONTENT:
{doc_text}

SCREENSHOTS OCR:
{" ".join(screenshot_texts)}
"""

        result, token_usage = await extraction_bot.extract(
            description=combined_context,
            company_context=company_context
        )

        input_tokens = 0
        output_tokens = 0

        if token_usage:
            input_tokens = token_usage.get("input_tokens") or token_usage.get("prompt_tokens") or 0
            output_tokens = token_usage.get("output_tokens") or token_usage.get("completion_tokens") or 0

        await deduct_ai_credits(
            db=db,
            user_id=current_user.id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stt_minutes=0.0,
            tts_minutes=0.0
        )

        return {
            "status": "success",
            "data": result
        }

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "status": "failure",
                "message": "Invalid JSON format in input data",
                "data": None
            }
        )

    except Exception as e:
        logger.error(f"Error extracting fields: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Error extracting fields. Please try again.",
                "data": None
            }
        )


@roleplay_assistant_router.post("/field-intelligence-services")
async def field_intelligence_services(
    research_target: str = Form(...),
    objective: str = Form(...),
    files: Optional[List[UploadFile]] = File(
        None,
        description="List of files for summarization (max 5)"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _=Depends(require_compute_access)
):
    try:

        DEFAULT_FIELD_INTEL_PROMPT = """ You are a web search assistant specialized in gathering field intelligence for sales teams. Your task is to research the provided target and objective, and return relevant insights, data, and context that can help the user achieve their goal. Focus on finding actionable information such as recent news, company updates, industry trends, competitor analysis, and any other relevant details that can provide a comprehensive understanding of the target. Format your response in a clear and organized manner, highlighting key findings and insights that would be valuable for a sales professional preparing for outreach or meetings. """

        field_intelligence_prompt = None

        if current_user.user_type in ["org_admin", "content_creator", "exec_viewer", "field_manager"]:
            organization = db.query(Organization).filter(Organization.admin_id == current_user.id).first()
            if organization:
                field_intelligence_prompt = organization.field_intelligence_prompt

        elif current_user.user_type == "sales_reps":
            user_record = db.query(User).filter(User.id == current_user.id).first()
            if not user_record or not user_record.created_by:
                return None
            created_by_email = user_record.created_by
            creator_user = db.query(User).filter(User.email == created_by_email).first()
            if creator_user:
                organization = db.query(Organization).filter(Organization.admin_id == creator_user.id).first()
                if organization:
                    field_intelligence_prompt = organization.field_intelligence_prompt

        # Fallback to default prompt if none is configured
        field_intelligence_prompt = (field_intelligence_prompt or DEFAULT_FIELD_INTEL_PROMPT).strip()


        from api.user_management.user_management import get_company_context

        company_context = await get_company_context(db, current_user, return_raw=True)
        field_intelligence_prompt = inject_company_context(field_intelligence_prompt, company_context, current_user.org_name)

        uploaded_file_texts = []

        if files:
            if len(files) > 5:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "status": "failure",
                        "message": "Maximum 5 files allowed.",
                        "data": None
                    }
                )

            for uploaded_file in files:
                try:
                    file_bytes = await uploaded_file.read()

                    text = await process_document(
                        source=file_bytes,
                        filename=uploaded_file.filename,
                        return_documents=False,
                        enable_ocr=True
                    )

                    if text:
                        uploaded_file_texts.append(
                            f"[Uploaded File: {uploaded_file.filename}]\n{text}"
                        )

                    logger.info(
                        f"Processed field intelligence file: {uploaded_file.filename}"
                    )

                except Exception as e:
                    logger.error(
                        f"Error processing field intelligence file {uploaded_file.filename}: {e}",
                        exc_info=True
                    )

        combined_uploaded_text = "\n\n".join(uploaded_file_texts)

        additional_context = f"""
COMPANY CONTEXT:
{field_intelligence_prompt}

UPLOADED FILE CONTEXT:
{combined_uploaded_text}
"""

        result, token_callback = await field_intel_bot.generate(
            research_target=research_target,
            objective=objective,
            additional_context=additional_context
        )

        input_tokens = 0
        output_tokens = 0

        if token_callback:
            input_tokens = getattr(token_callback, "prompt_tokens", 0)
            output_tokens = getattr(token_callback, "completion_tokens", 0)

        await deduct_ai_credits(
            db=db,
            user_id=current_user.id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stt_minutes=0.0,
            tts_minutes=0.0
        )

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Field intelligence generated successfully.",
                "data": result,
                "usage_metadata": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens
                },
                "input_summary": {
                    "files_processed": len(uploaded_file_texts),
                    "has_company_context": bool(company_context)
                }
            }
        )

    except HTTPException as http_exc:
        raise http_exc

    except Exception as e:
        logger.error(
            f"Error in field intelligence services: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Error providing field intelligence. Please try again.",
                "data": None
            }
        )