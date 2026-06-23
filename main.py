from fastapi.responses import JSONResponse
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from api.auth import auth_router
from api.user_management import user_management_router
from api.roleplay import roleplay_router
from api.model_status import llm_router
from api.roleplay_assistant import roleplay_assistant_router, websocket_endpoint, initialize_ocr, preload_content_generation
from api.evaluation_criteria import eval_criteria_router
from api.precall_plan import precall_plan_router
from api.knowledge_base import file_upload_router
from api.chatbot_conversation import chatbot_conversation_router
from api.courses import courses_router
from api.ai_consumption import ai_consumption_router
from api.default_scenario_images import default_image_router
from api.prompt import prompt_router
from api.default_prompt_icon import default_prompt_icon_router
import configparser
from fastapi.staticfiles import StaticFiles
from middleware import ImpersonationContextMiddleware
from fastapi import APIRouter
import logging

logger = logging.getLogger(__name__)
config = configparser.ConfigParser()
config.read('config.ini')
 
API_PORT = config['fast_api_server']['port']
API_HOST = config['fast_api_server']['host']

ALGORITHM = config['algorithm']['algorithm']
SECRET_KEY = config['secret_key']['key']

 
app = FastAPI(root_path="/api")
app.mount("/static", StaticFiles(directory="uploads"), name="static")
 
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
    expose_headers=["*"],
)

app.add_middleware(ImpersonationContextMiddleware, secret_key=SECRET_KEY, algorithm="HS256")


@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.detail  # This will return your custom error structure
    )
 
main_router = APIRouter()
 
main_router.include_router(
    auth_router,
    prefix='/auth',
    tags=['Auth']
)
 
main_router.include_router(
    user_management_router,
    prefix="/user_management",
    tags=["User Management"]
)
 
main_router.include_router(
    precall_plan_router,
    prefix="/precall-plan",
    tags=["Precall Plan"]
)
 
main_router.include_router(
    roleplay_router,
    prefix="/roleplay",
    tags=["Roleplay"]
)
 
main_router.include_router(
    eval_criteria_router,
    prefix='/eval-criteria',
    tags=['Evaluation Criteria']
)
 
main_router.include_router(
    llm_router,
    prefix="/modelhealth",
    tags=["Health"]
)
 
main_router.include_router(
    roleplay_assistant_router,
    prefix="/roleplayassistant",
    tags=["RolePlayAssistant"]
)
 
main_router.include_router(
    file_upload_router,
    prefix="/knowledgebase",
    tags=["Knowledge Base"]
)
 
main_router.include_router(
    chatbot_conversation_router,
    prefix="/chat",
    tags=["ChatBot Conversation"]
)

main_router.include_router(
    courses_router,
    prefix="/courses",
    tags=["Courses"]
)

main_router.include_router(
    ai_consumption_router,
    prefix="/token",
    tags=["AI Consumption"]
)

main_router.include_router(
    default_image_router,
    prefix="/default-images",
    tags=["Default Scenario Images"]
)

main_router.include_router(
    prompt_router,
    prefix="/prompts",
    tags=["Prompt Management"]
)

main_router.include_router(
    default_prompt_icon_router,
    prefix="/default-images",
    tags=["Default Prompt Icons"]
)
 
app.include_router(main_router)

app.websocket("/ws/audio")(websocket_endpoint)

@app.on_event("startup")
async def startup_event():
    """Initialize heavy resources at startup"""
    logger.info("🚀 Starting application initialization...")
    
    # 1. Initialize OCR (already done)
    initialize_ocr()
    logger.info("OCR initialized")
    
    # 2. Preload content generation resources
    await preload_content_generation()
    logger.info("Content generation resources preloaded")
    
    logger.info("Application startup complete")
 
 
if __name__ == "__main__":
    uvicorn.run("main:app", host=API_HOST, port=int(API_PORT), reload=True)
