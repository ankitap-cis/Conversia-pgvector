from pathlib import Path
import shutil
from typing import Dict, List, Optional
import json
import configparser
from langchain_chroma import Chroma
from logger import *
from langchain.schema import SystemMessage, HumanMessage
from fastapi import HTTPException, UploadFile, status
from langchain_core.prompts import FewShotPromptTemplate, PromptTemplate
from api.roleplay_assistant.rolplaybot import bot
from typing import List
from langchain_openai import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
# from api.roleplay_assistant.general_chatbot import GeneralChatBot
from models.roleplay_models import Scenario, Evaluation
from datetime import datetime
import os
from langchain_openai import ChatOpenAI
from utils.token_consumption import embedding_token_count
from utils.file_loaders import *
from pydantic import BaseModel, Field, create_model, ConfigDict
from typing import Dict, Type
from pydantic import ValidationError
from utils.token_consumption import TokenUsageCallback 
token_callback = TokenUsageCallback()

# bot = GeneralChatBot()

config = configparser.ConfigParser()
config.read("config.ini")
OPENAI_API_KEY = config['openAI_config']['key']
embed_model = config['openAI_config']['embedding_model']
OPENAI_API_KEY = config['openAI_config']['key']
gpt_model = config['openAI_config']['model']

class SalesCriterionScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: int = Field(..., ge=1, le=10, description="Score from 1-10")
    explanation: str = Field(..., description="Brief explanation of the score")


class CoachingAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(..., max_length=120)
    example_phrase: str = Field(..., max_length=250)

class OverallFeedbackBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall_score: float = Field(..., ge=1, le=10)

    top_three_coaching_actions: List[CoachingAction] = Field(
        ...,
        min_length=3,
        max_length=3
    )

    missed_opportunities: List[str] = Field(
        ...,
        min_length=2,
        max_length=2
    )

    next_simulation_focus: List[str] = Field(
        ...,
        min_length=1,
        max_length=2
    )


def render_feedback_html(feedback: OverallFeedbackBlock) -> str:
    html = ""
    html += "<b>Top three coaching actions</b><br>"
    for action in feedback.top_three_coaching_actions:
        html += f"• {action.action}<br>"
        html += f"&nbsp;&nbsp;<i>Example:</i> \"{action.example_phrase}\"<br>"

    html += "<br><b>Missed opportunities</b><br>"
    for missed in feedback.missed_opportunities:
        html += f"• {missed}<br>"

    html += "<br><b>Next simulation focus</b><br>"
    for focus in feedback.next_simulation_focus:
        html += f"• {focus}<br>"

    return html



def create_sales_evaluation_model(criteria: List[str]) -> Type[BaseModel]:
    fields = {}

    for criterion in criteria:
        normalized = (
            criterion.lower()
            .strip()
            .replace(" ", "_")
            .replace("-", "_")
        )

        fields[normalized] = (
            SalesCriterionScore,
            Field(..., description=f"Evaluation for {criterion}")
        )

    fields["overall_feedback"] = (
        OverallFeedbackBlock,
        Field(..., description="Overall structured coaching feedback")
    )

    return create_model(
        "SalesEvaluationOutput",
        __config__=ConfigDict(extra="forbid"),
        **fields
    )


class SalesEvaluator:
    def __init__(self, bot, evaluation_criteria: List[str]):

        if not evaluation_criteria or len(evaluation_criteria) == 0:
            logger.error(f"Evaluation list must not be empty.")
            raise HTTPException(
                status_code= status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "failure",
                    "message": "Evaluation criteria list must not be empty.",
                    "data": None
                }
            )

        self.bot = ChatOpenAI(
            model = gpt_model,
            openai_api_key=OPENAI_API_KEY,
            temperature=0.1,
            top_p=0.1,
            presence_penalty=0,
            seed=420
        )
        self.criteria = evaluation_criteria
        self.prompt_template = self._init_prompt_template()

    def ensure_writable(self, path: str):
        """
        Ensure the directory exists, set permissions recursively, 
        and create an empty 'chroma.sqlite3' file if missing.
        """
        # Ensure directory exists
        os.makedirs(path, exist_ok=True)

        # Recursively set permissions (dirs: 777, files: 666)
        for root, dirs, files in os.walk(path):
            for d in dirs:
                os.chmod(os.path.join(root, d), 0o777)
            for f in files:
                os.chmod(os.path.join(root, f), 0o666)

        os.chmod(path, 0o777)

        # Create chroma.sqlite3 if not present
        db_file = os.path.join(path, "chroma.sqlite3")
        if not os.path.exists(db_file):
            open(db_file, "a").close()  # creates empty file
            os.chmod(db_file, 0o666)


    async def add_file_to_vectorstore(
        self,
        file: UploadFile,
        org_id: int,
        scenario_id: str,
        replace_existing: bool = False,
        embed_model: str = embed_model
    ):
        try:
            persist_dir = f"./vectorstores/{org_id}/scenario_uploads/{scenario_id}"
            collection_name = f"scenario_{scenario_id}"

            self.ensure_writable(persist_dir)

            embeddings = OpenAIEmbeddings(openai_api_key=OPENAI_API_KEY, model=embed_model)
            vectorstore = Chroma(
                collection_name=collection_name,
                persist_directory=persist_dir,
                embedding_function=embeddings
            )

            # If replacing, delete only vectors for this scenario
            if replace_existing:
                vectorstore.delete(where={"scenario_id": str(scenario_id)})

            await file.seek(0)

            # Save uploaded file temporarily
            file_path = f"/tmp/{file.filename}"
            with open(file_path, "wb") as f:
                f.write(await file.read())

            ext = Path(file.filename).suffix.lower().lstrip(".")
            documents = []

            documents = await process_document(
                source=file_path,
                filename=file.filename,
                enable_ocr=True,
                ocr_language="eng",
                ocr_dpi=300,
                return_documents=True 
            )
            if not documents:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Failed to extract content from {file.filename}"
                )
            # --- Split into chunks ---
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
            chunked_documents = []
            for doc in documents:
                chunked_documents.extend(
                    text_splitter.create_documents(
                        texts=[doc.page_content],
                        metadatas=[{
                            "scenario_id": str(scenario_id),
                            "org_id": str(org_id),
                            "doc_type": "roleplay_file",
                            "filename": file.filename,
                            "timestamp": datetime.now().isoformat()
                        }]
                    )
                )

            texts_to_embed = [doc.page_content for doc in chunked_documents]
            usage_metadata = embedding_token_count(texts_to_embed, embed_model)

            # --- Add docs to vectorstore ---
            if chunked_documents:
                vectorstore.add_documents(chunked_documents)

            return {"status": "success", "chunks_added": len(chunked_documents), "usage_metadata": usage_metadata if usage_metadata else None}

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to add file: {e}")


    async def delete_scenario_file(self, org_id: int, scenario_id: int):
        """
        Safely deletes all indexed documents for a specific scenario without corrupting Chroma.
        Only deletes vectors, not the database file.
        """
        try:
            persist_dir = f"./vectorstores/{org_id}/scenario_uploads/{scenario_id}"
            collection_name = f"scenario_{scenario_id}"
            self.ensure_writable(persist_dir)

            db_path = os.path.join(persist_dir, "chroma.sqlite3")
            if not os.path.exists(db_path):
                return {"status": "success", "message": "No index database found for this scenario"}

            embeddings = OpenAIEmbeddings(openai_api_key=OPENAI_API_KEY, model=embed_model)
            vectorstore = Chroma(
                collection_name=collection_name,
                persist_directory=persist_dir,
                embedding_function=embeddings,
            )

            # Delete only scenario vectors
            vectorstore.delete(where={"scenario_id": str(scenario_id)})

            return {"status": "success", "message": "Scenario vectors deleted successfully"}

        except Exception as e:
            return {"status": "failure", "message": f"Failed to delete scenario vectors: {str(e)}"}


    def _init_prompt_template(self):
            examples = []
            example_prompt = PromptTemplate.from_template("""
            Conversation:
            {conversation}
            """)

            self.output_model = create_sales_evaluation_model(self.criteria)
            raw_schema = self.output_model.model_json_schema()
            self.schema_str = json.dumps(raw_schema, indent=2)

            return FewShotPromptTemplate(
                examples=examples,
                example_prompt=example_prompt,
                prefix="""
                    You are a strict, unbiased sales roleplay evaluator.

                    CRITICAL RULES:
                    - Evaluate ONLY the USER messages.
                    - Be realistic. Do NOT inflate scores.
                    - Keep feedback respectful and practical.
                    - Short sentences. One idea per sentence.

                    Your output MUST be valid JSON.
                    No markdown. No backticks. No comments.

                    IMPORTANT:
                    Your response MUST follow this JSON schema exactly:

                    {schema}

                    The 'overall_feedback' object must contain:

                    - overall_score (1-10)
                    - top_three_coaching_actions (exactly 3 objects with action + example_phrase)
                    - missed_opportunities (exactly 2 bullets)
                    - next_simulation_focus (1–2 short sentences)
                    - example_phrase MUST be under 150 characters.

                    No HTML formatting.
                    Return pure JSON only.
                    """,
                suffix="""
                    Evaluate ONLY the user's messages below:

                    Criteria:
                    {criteria_list}

                    Conversation:
                    {chat_text}

                    Respond strictly as JSON matching the schema.
                    """,
                input_variables=["criteria_list", "chat_text", "schema"]
            )

    def format_chat_history(self, chat_history: List[Dict[str, str]]) -> str:
        formatted = ""
        for msg in chat_history:
            role = "User" if msg["type"] == "human" else "Assistant"
            content = msg.get("content", "").strip()
            formatted += f"{role}: {content}\n"
        return formatted.strip()

 
    def generate_prompt(self, chat_text: str) -> str:
        if not self.criteria:
            logger.error("Evaluation cannot proceed without criteria.")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "failure",
                    "message": "Evaluation cannot proceed without criteria.",
                    "data": None
                }
            )

        criteria_list = "\n".join([f"{i+1}. {c.strip()}" for i, c in enumerate(self.criteria)])
        try:
            return self.prompt_template.format_prompt(
                criteria_list=criteria_list,
                chat_text=chat_text,
                schema=self.schema_str
            ).to_string()
        except Exception as e:
            logger.error(f"Prompt generation error: {e}")
            raise HTTPException(
                status_code=500,
                detail={
                    "message": f"Prompt template formatting error: {str(e)}"
                }
            )

    def evaluate(
        self, evaluation_prompt: str, thread_id: str, scenario_name: str, chat_history: Optional[List[Dict]] = None) -> Dict:
        """
        Evaluate chat history for a given scenario.
        Can use bot memory or injected chat_history.
        """

        # Pick chat history source
        if chat_history is not None:
            # Already pre-fetched from DB
            final_chat_history = chat_history
        elif self.bot and thread_id in self.bot.memories:
            memory = self.bot.memories[thread_id]
            final_chat_history = [
                {
                    "type": "human" if msg.type == "human" else "ai",
                    "content": msg.content
                }
                for msg in memory.chat_memory.messages
            ]
        else:
            raise ValueError("No chat history available (neither DB nor bot memory).")

        if not isinstance(final_chat_history, list) or not final_chat_history:
            raise ValueError("Chat history is empty.")

        # Format chat history for LLM
        formatted_history = self.format_chat_history(final_chat_history)
        prompt = self.generate_prompt(formatted_history)

        # Call LLM
        response = self.bot.invoke([
            SystemMessage(content=evaluation_prompt),
            HumanMessage(content=prompt)
        ],
        config={"callbacks": [token_callback]}                    
        )

        if isinstance(response, dict):
            content = response.get("content") or response.get("text") or str(response)
        else:
            content = response.content

        try:
            parsed = self.output_model.model_validate_json(content)
        except ValidationError as e:
            logger.error(f"Validation failed: {e}")
            cleaned = content.strip().strip("```").strip("json")
            parsed = self.output_model.model_validate_json(cleaned)


        evaluation_dict = parsed.model_dump()
        feedback_html = render_feedback_html(parsed.overall_feedback)
        skill_scores = []
        for key, value in evaluation_dict.items():
            if key == "overall_feedback":
                continue

            skill_scores.append({
                "name": key.replace("_", " ").title(),
                "score": int(value["score"]),
                "comment": str(value["explanation"])
            })
        evaluation_dict["overall_feedback"]["html"] = feedback_html       
        # 5. Return structured result
        return  {
            "evaluation": evaluation_dict,  # REQUIRED by frontend transformEvaluation
            "scenario_title": str(scenario_name),
            "ai_score": float(parsed.overall_feedback.overall_score),
            "pass_score": float(0),
            "general_insights": str(feedback_html),
            "skill_scores": skill_scores
        }, token_callback

async def admin_scenariofile_to_vectordb(
    db: Session,
    current_user,
    scenario_doc
):
    """
    Fetch superadmin-created scenario, validate evaluation,
    and add scenario document to vectorstore.
    """

    # Fetch scenario created by superadmin
    scenario = (
        db.query(Scenario)
        .filter(Scenario.created_by == "superadmin@maiinator.com")
        .first()
    )

    if not scenario:
        logger.warning("No scenario found created by superadmin")
        return

    # Validate evaluation existence
    evaluation = (
        db.query(Evaluation)
        .filter(
            Evaluation.id == scenario.evaluation_id,
            Evaluation.created_by == current_user.email
        )
        .first()
    )

    if not evaluation:
        logger.warning(f"Evaluation ID {scenario.evaluation_id} does not exist.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "status": "failure",
                "message": f"Evaluation ID {scenario.evaluation_id} does not exist.",
                "data": None
            }
        )

    # Extract evaluation titles
    evaluation_titles = [field.title_area for field in evaluation.fields]

    # Add document to vectorstore (only if it's a file-like object)
    if scenario_doc and not isinstance(scenario_doc, str):
        await scenario_doc.seek(0)

        evaluator = SalesEvaluator(
            bot=None,
            evaluation_criteria=evaluation_titles
        )

        await evaluator.add_file_to_vectorstore(
            scenario_doc,
            current_user.organization_id,
            scenario.id
        )

        logger.info(
            f"Scenario {scenario.id} added to vectorstore for org {current_user.organization_id}"
        )
