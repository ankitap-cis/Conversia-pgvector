"""
documenttype.py - Document type prompt retrieval with structured output models
"""

import logging
import json
from typing import Dict, Optional, Literal, List, Annotated, Union, Any
from pathlib import Path
from fastapi import HTTPException, status
import aiofiles
from pydantic import BaseModel, Field, ConfigDict
import configparser
import asyncio
from enum import Enum
from datetime import date
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator


config = configparser.ConfigParser()
config.read('config.ini')
document_prompt_path = config['openAI_config'].get(
    'document_prompt_path')


logger = logging.getLogger(__name__)

_prompt_cache: Optional[dict] = None
_cache_loaded = False
_cache_loading_lock = asyncio.Lock()

DEFAULT_SLIDE_COUNT = 10
MIN_SLIDE_COUNT = 3
MAX_SLIDE_COUNT = 14

DEFAULT_FILE_PROMPT = """
You are a helpful AI assistant generating a document. Analyze the content and provide clear, accurate responses based on the information provided.

Guidelines:
- Extract key information accurately
- Maintain professional tone
- Provide structured responses
- Acknowledge limitations if information is unclear
"""

def extract_slide_count_from_inputs(
    primary_objective: Optional[str] = None,
    additional_context: Optional[str] = None,
    intent: Optional[str] = None,
    desired_outcome: Optional[str] = None,
    supporting_message: Optional[str] = None,
    motivation_points: Optional[str] = None,
) -> int:
    """
    Auto-detect a requested slide count from any of the user-supplied input fields.
    Scans all text fields for patterns like '10 slides', '8-slide deck', 'twelve slides', etc.
    Falls back to DEFAULT_SLIDE_COUNT (10) if nothing is found.
    Returns a value clamped to [MIN_SLIDE_COUNT, MAX_SLIDE_COUNT].
    """
    import re

    word_to_num = {
        "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
        "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
        "thirteen": 13, "fourteen": 14,
    }

    digit_pattern = re.compile(
        r'\b(\d{1,2})\s*[-\s]?\s*slides?\b|\b(\d{1,2})\s*[-\s]slide\b',
        re.IGNORECASE
    )
    word_pattern = re.compile(
        r'\b(' + '|'.join(word_to_num.keys()) + r')\s*[-\s]?\s*slides?\b',
        re.IGNORECASE
    )

    fields = [
        primary_objective, additional_context, intent,
        desired_outcome, supporting_message, motivation_points,
    ]
    combined_text = " ".join(f for f in fields if f)

    match = digit_pattern.search(combined_text)
    if match:
        raw = int(match.group(1) or match.group(2))
        return max(MIN_SLIDE_COUNT, min(MAX_SLIDE_COUNT, raw))

    match = word_pattern.search(combined_text)
    if match:
        raw = word_to_num[match.group(1).lower()]
        return max(MIN_SLIDE_COUNT, min(MAX_SLIDE_COUNT, raw))

    return DEFAULT_SLIDE_COUNT

# Pydantic Output Structures for Each Document Type

class StrictConfig:
    extra = "forbid"

# ===== PRESENTATION =====
class VisualRecommendation(BaseModel):
    type: str = Field(description="Visual type (e.g., chart, image, diagram, icon)")
    what_to_show: str = Field(description="Specific content to display")

class SpeakersNote(BaseModel):
    core_message: str = Field(description="Key message (1-2 sentences)")
    narration: str = Field(description="Detailed speaking points in less than 75 words")
    transition_to_next: str = Field(description="Bridge to next slide")

class SlideContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    slide_number: int = Field(description="Slide number in sequence")
    title: str = Field(description="Slide title (5-10 words)")
    on_slide_content: List[str] = Field(description="3-5 bullet points per slide", min_length=3, max_length=5)
    visual_recommendation: VisualRecommendation
    speakers_note: SpeakersNote

class ExecutiveSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    slide_number: int = Field(description="Final slide number")
    title: Literal["Executive Summary"] = Field(default="Executive Summary")
    content: str = Field(description="Provide the executive summary in points in about 300 words separated by \n\n.")

class PresentationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    presentation_title: str = Field(description="Main presentation title")
    branding_guidelines: Optional[str] = Field(default=None, description="Branding notes to follow")
    slide_count: int = Field(
        description=f"Exact number of content slides (excluding Executive Summary). Must match the SLIDE COUNT REQUIREMENT in the prompt. Range: {MIN_SLIDE_COUNT}–{MAX_SLIDE_COUNT}.",
        ge=MIN_SLIDE_COUNT,
        le=MAX_SLIDE_COUNT,
    )
    slides: List[SlideContent] = Field(
        description="List of content slides (1 to slide_count)",
        min_length=MIN_SLIDE_COUNT,
        max_length=MAX_SLIDE_COUNT,
    )
    slides: List[SlideContent] = Field(
        description="List of content slides (1 to slide_count)",
        min_length=1,
        max_length=14 
    )
    executive_summary: ExecutiveSummary = Field(description="Final Executive Summary slide")

    # ===== CUSTOMER TALK TRACK =====
class QuestionCategory(str, Enum):
    DISCOVERY = "Discovery"
    PROBLEMS = "Problems"
    IMPACT = "Impact"
    PRIORITY = "Priority"

class KeyMessageBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    point: str = Field(description="Core claim (1-2 sentences under 30 words)")
    proof: Optional[str] = Field(None, min_length=10, description="Supporting evidence if available(under 25 words)")
    bridge: str = Field(description="Transition question or connector(under 25 words)")

class ObjectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objection: str = Field(min_length=5, description="Common objection")
    acknowledge: str = Field(min_length=10, description="Validation of concern (1-2 sentences, under 25 words)")
    reframe: str = Field(min_length=10, description="Perspective shift (1-2 sentences, under 25 words)")
    proof: Optional[str] = Field(None, description="Supporting evidence if available(under 25 words)")
    reengage_question: str = Field(min_length=5, description="Dialogue-returning question under 25 words")

class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audience_situation: str = Field(description="25 words or less: Audience and situation")
    conversation_objective: str = Field(description="25 words or less: Conversation intent")
    core_message: str = Field(description="25 words or less: Single sentence value proposition")

class CloseOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recap: str = Field(description="2-sentence summary reflecting customer input")
    next_step: str = Field(description="Specific proposed action")

class CustomerTalkTrackOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    snapshot: Snapshot = Field(description="Strategic conversation context")
    openers: List[str] = Field(
        description="3 distinct openers (1-2 sentences each under 35 words)", 
        min_items=3, 
        max_items=3
    )
    engaging_questions: List[str] = Field(
        description="4-8 questions (each under 25 words) across discovery stages", 
        min_items=4, 
        max_items=8
    )
    key_messages: List[KeyMessageBlock] = Field(
        description="3 main supporting message blocks", 
        min_items=3, 
        max_items=3
    )
    objections: List[ObjectionResponse] = Field(
        description="Top 5 objections with full response framework", 
        min_items=5, 
        max_items=5
    )
    close_options: List[CloseOption] = Field(
        description="2 closing options with recap + next step", 
        min_items=2, 
        max_items=2
    )

# ===== CUSTOMER COMMUNICATION =====

class FAQResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(description="Frequently asked question")
    answer: str = Field(description="Standard answer")


class CustomerCommunicationOutput(BaseModel):
    """
    Flat output for customer_communication.
    The AI returns a single rendered_html string covering the full document —
    email, flyer, brochure, letter, or any other format — so the frontend
    simply renders it with dangerouslySetInnerHTML. No format routing needed.
    """
    model_config = ConfigDict(extra="forbid")

    document_title: str = Field(
        ..., description="Human-readable title for this communication in less than 30 words"
    )
    communication_context: str = Field(
        ..., description="One sentence: audience, situation, and purpose"
    )
    document_format: str = Field(
        ...,
        description=(
            "One of: email, flyer, brochure, letter, quote_follow_up, "
            "event_invitation, post_event_follow_up, policy_process_update, "
            "product_update, educational"
        ),
    )
    key_messages: Optional[List[str]] = Field(
        default=None, description="3-5 core messages distilled from the communication"
    )
    rendered_html: str = Field(
        ...,
        description=(
            "Complete self-contained HTML string of the full document. "
            "Uses only inline styles. No external CSS. No class names. "
            "Frontend renders this directly with dangerouslySetInnerHTML."
        ),
    )
    subject_line_options: Optional[List[str]] = Field(
        default=None,
        description="2 subject line strings for email-type formats; null for print formats",
    )
    compliance_and_disclaimers: str = Field(
        default="",
        description="Required disclaimer text; already included in rendered_html but kept here for reference",
    )
    required_to_finalize: Optional[List[str]] = Field(
        default=None,
        description="Missing facts blocking final readiness; null if complete",
    )
    faq_responses: Optional[List[FAQResponse]] = Field(
        default=None, description="FAQs if relevant; null otherwise"
    )


def parse_customer_communication(raw_json: dict, context: str) -> CustomerCommunicationOutput:
    """Safe parser for customer communication JSON. Falls back to a plain HTML wrapper on failure."""
    try:
        output = CustomerCommunicationOutput.model_validate(raw_json)

        # Ensure title is not too long
        def truncate_title(title: str, max_words: int = 18) -> str:
            return " ".join(title.split()[:max_words])

        output = output.model_copy(
            update={"document_title": truncate_title(output.document_title)}
        )

        return output  # FIXED indentation

    except Exception as e:
        logger.error(f"Customer comm parsing failed: {e}. Generating fallback HTML.")

        raw_text = (
            raw_json.get("rendered_html")
            or raw_json.get("message_body")
            or str(raw_json)
        )

        fallback_html = (
            f'<p style="font-family:Arial,sans-serif;font-size:14px;color:#333;">'
            f'{raw_text}</p>'
            f'<p style="font-family:Arial,sans-serif;font-size:11px;color:#e07b00;'
            f'border-top:1px solid #eee;padding-top:8px;margin-top:16px;">'
            f'<strong>Note:</strong> Parsing failed — manual review required.</p>'
        )

        return CustomerCommunicationOutput(
            document_title="Customer Communication",  # ✅ FIXED string
            communication_context="Raw text fallback — could not parse structured response",
            document_format="email",
            key_messages=None,
            rendered_html=fallback_html,
            subject_line_options=None,
            compliance_and_disclaimers="",
            required_to_finalize=["Parsing failed — manual review required"],
            faq_responses=None,
        )
# ===== INTERNAL COMMUNICATION =====

class InternalFAQItem(BaseModel):
    """A single Q&A pair used in intranet posts and manager cascades."""
    model_config = ConfigDict(extra="forbid")

    question: str
    answer: str


# ==========================
# Per-channel deliverable models
# (mirrors the customer comm pattern)
# ==========================

class InternalCommunicationOutput(BaseModel):
    """
    Flat output for internal communication (same philosophy as customer_comm).

    The AI returns ONE rendered_html string — frontend just renders it.
    No routing logic needed.
    """

    model_config = ConfigDict(extra="forbid")

    document_title: str = Field(
        ..., description="Internal communication title (under 30 words)"
    )

    communication_context: str = Field(
        ..., description="One sentence: audience, situation, purpose"
    )

    document_format: str = Field(
        ...,
        description=(
            "One of: email, slack, intranet, flyer, brochure, "
            "manager_cascade, announcement, update, training"
        ),
    )

    key_messages: Optional[List[str]] = Field(
        default=None,
        description="3-5 key internal messages"
    )

    rendered_html: str = Field(
        ...,
        description=(
            "FULL HTML output. Inline styles only. "
            "Format must match document_format."
        ),
    )

    subject_line_options: Optional[List[str]] = Field(
        default=None,
        description="Only for email-type formats"
    )

    required_to_finalize: Optional[List[str]] = Field(
        default=None,
        description="Missing info if any"
    )

    faq_block: Optional[List[InternalFAQItem]] = Field(
        default=None
    )


# ===== FAQ DOCUMENT =====
class FAQAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    direct_answer: str = Field(..., description="Plain text direct answer (NO bullets/asterisks, under 25 words)")
    supporting_details: List[str] = Field(..., description="3-6 supporting details (plain text, NO bullets/asterisks)", min_items=3, max_items=6)
    evidence_flags: Optional[List[str]] = Field(
        default_factory=list, 
        description="Internal use only. Do not include in output."
    )
    @field_validator('direct_answer', 'supporting_details', mode='before')
    @classmethod
    def strip_bullets(cls, v):
        if isinstance(v, str):
            return v.lstrip('•*- ').strip()
        return v

class FAQItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    question_id: str = Field(..., description="Unique identifier (e.g., 'product_basics_1')")
    question: str = Field(..., description="Real customer question (under 15 words ideal)")
    answer: FAQAnswer = Field(..., description="Structured answer with direct + supporting bullets")
    sources_used: List[str] = Field(
    ..., 
    description="Numbered list of ALL sources used (no inline citations needed)",
    min_items=1
    )

class FAQCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    name: str = Field(..., description="Category name (e.g., 'Product Basics')")
    description: Optional[str] = Field(None, description="Brief category context")
    questions: List[FAQItem] = Field(..., description="Questions in this category", min_items=2, max_items=5)

class FAQOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    document_title: str = Field(...)
    target_audience: str = Field(...)
    last_updated: str = Field(default_factory=lambda: date.today().isoformat())
    version: str = Field(default="1.0")
    table_of_contents: str = Field(...)
    categories: List[FAQCategory] = Field(..., min_items=4, max_items=8)
    
    # NEW - Clean source list at end

# Document Type Registry

DOCUMENT_TYPE_SCHEMAS = {
    "presentation": PresentationOutput,
    "customer_talk_track": CustomerTalkTrackOutput,
    "customer_communication": CustomerCommunicationOutput,
    "internal_communication": InternalCommunicationOutput,
    "faqs": FAQOutput
}

async def preload_document_prompts(prompts_file_path: str = document_prompt_path):
    global _prompt_cache, _cache_loaded
    async with _cache_loading_lock:
        if _cache_loaded:
            logger.info("Document prompts already loaded")
            return
        
        try:
            logger.info(f"Preloading document prompts from {prompts_file_path}")
            
            if not Path(prompts_file_path).exists():
                logger.warning(f"Prompts file not found: {prompts_file_path}, will use fallback")
                return
            
            async with aiofiles.open(prompts_file_path, mode='r', encoding='utf-8') as f:
                content = await f.read()
            
            _prompt_cache = json.loads(content)
            _cache_loaded = True
            
            logger.info(
                f"Document prompts preloaded successfully",
                extra={
                    "prompts_file_path": prompts_file_path,
                    "prompt_types_loaded": len(_prompt_cache.get("document_type_prompts", {}))
                }
            )
        except Exception as e:
            logger.error(f"Failed to preload document prompts: {e}", exc_info=True)

def get_output_schema(file_type: str) -> type[BaseModel]:
    normalized_type = file_type.lower().strip().replace(" ", "_").replace("-", "_")
    
    if normalized_type not in DOCUMENT_TYPE_SCHEMAS:
        raise KeyError(f"No output schema defined for document type: {file_type}")
    
    return DOCUMENT_TYPE_SCHEMAS[normalized_type]

def get_schema_instruction(file_type: str) -> str:
    try:
        schema_class = get_output_schema(file_type)
        schema_json = schema_class.model_json_schema()
        
        return f"""

IMPORTANT: Your output must conform to the following JSON schema structure:

{json.dumps(schema_json, indent=2)}

Generate your response as valid JSON matching this schema exactly. All required fields must be present.
"""
    except KeyError:
        return ""

# Prompt Retrieval (Existing Logic)

_prompt_cache: Optional[dict] = None
_cache_loaded = False

async def get_filetype_prompt(
    file_type: Literal["presentation", "customer_talk_track", "customer_communication", "internal_communication", "faqs"],
    prompts_file_path: str = document_prompt_path,
    use_fallback: bool = True,
    reload_cache: bool = False,
    include_schema: bool = True,
    slide_count: Optional[int] = None
) -> str:
    global _prompt_cache, _cache_loaded
    
    normalized_type = file_type.lower().strip().replace(" ", "_").replace("-", "_")
    try:
        logger.info(
            f"Fetching prompt for file_type='{file_type}' (normalized: '{normalized_type}')",
            extra={"file_type": file_type, "normalized_type": normalized_type}
        )
        

        if _cache_loaded and not reload_cache and _prompt_cache:
            logger.debug("Using preloaded prompt cache (fast path)")

        elif not _cache_loaded or reload_cache or _prompt_cache is None:
            async with _cache_loading_lock:
                if not _cache_loaded or reload_cache:
                    await preload_document_prompts(prompts_file_path)
            logger.info(
                f"Loading prompts from file: {prompts_file_path}",
                extra={"prompts_file_path": prompts_file_path}
            )
            
            if not Path(prompts_file_path).exists():
                logger.error(
                    f"Prompts file not found: {prompts_file_path}",
                    extra={"prompts_file_path": prompts_file_path}
                )
                
                if use_fallback:
                    logger.warning(
                        f"File not found - using default fallback prompt for file_type='{file_type}'",
                        extra={"file_type": file_type}
                    )
                    return DEFAULT_FILE_PROMPT
                else:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Document prompts configuration file not found: {prompts_file_path}"
                    )
            
            try:
                async with aiofiles.open(prompts_file_path, mode='r', encoding='utf-8') as f:
                    content = await f.read()
                _prompt_cache = json.loads(content)
                _cache_loaded = True
                
                logger.info(
                    f"Successfully loaded prompts from {prompts_file_path}",
                    extra={
                        "prompts_file_path": prompts_file_path,
                        "prompt_types_loaded": len(_prompt_cache.get("document_type_prompts", {}))
                    }
                )
            except json.JSONDecodeError as e:
                logger.error(
                    f"Invalid JSON in prompts file {prompts_file_path}: {str(e)}",
                    extra={"prompts_file_path": prompts_file_path, "error": str(e)},
                    exc_info=True
                )
                
                if use_fallback:
                    logger.warning(
                        f"JSON parse error - using default fallback prompt for file_type='{file_type}'",
                        extra={"file_type": file_type}
                    )
                    return DEFAULT_FILE_PROMPT
                else:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Invalid document prompts configuration file format"
                    )
        
        if not _prompt_cache or "document_type_prompts" not in _prompt_cache:
            logger.error(
                f"'document_type_prompts' key not found in prompts file",
                extra={"prompts_file_path": prompts_file_path}
            )
            
            if use_fallback:
                logger.warning(
                    f"Invalid structure - using default fallback prompt for file_type='{file_type}'",
                    extra={"file_type": file_type}
                )
                return DEFAULT_FILE_PROMPT
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Invalid document prompts configuration structure"
                )
        
        document_prompts = _prompt_cache["document_type_prompts"]
        
        if normalized_type not in document_prompts:
            logger.warning(
                f"File type '{normalized_type}' not found in prompts configuration. "
                f"Available types: {list(document_prompts.keys())}",
                extra={
                    "file_type": file_type,
                    "normalized_type": normalized_type,
                    "available_types": list(document_prompts.keys())
                }
            )
            
            if use_fallback:
                logger.info(
                    f"File type not found - using default fallback prompt for file_type='{file_type}'",
                    extra={"file_type": file_type}
                )
                return DEFAULT_FILE_PROMPT
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Document type '{file_type}' not found. Available types: {list(document_prompts.keys())}"
                )
        
        prompt = document_prompts[normalized_type]
        
        if not prompt or not prompt.strip():
            logger.warning(
                f"Empty prompt found for file_type='{normalized_type}'",
                extra={"file_type": file_type, "normalized_type": normalized_type}
            )
            
            if use_fallback:
                logger.info(
                    f"Empty prompt - using default fallback prompt for file_type='{file_type}'",
                    extra={"file_type": file_type}
                )
                return DEFAULT_FILE_PROMPT
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Prompt for document type '{file_type}' is empty"
                )
        
        final_prompt = prompt
        if include_schema:
            try:
                schema_instruction = get_schema_instruction(normalized_type)
                final_prompt = f"{prompt}\n\n{schema_instruction}"
                logger.info(
                    f"Added structured output schema for file_type='{normalized_type}'",
                    extra={"file_type": normalized_type}
                )
            except KeyError as e:
                logger.warning(
                    f"No schema available for file_type='{normalized_type}', using prompt only",
                    extra={"file_type": normalized_type, "error": str(e)}
                )
        
        logger.info(
            f"Successfully fetched prompt for file_type='{normalized_type}'",
            extra={
                "file_type": file_type,
                "normalized_type": normalized_type,
                "schema_included": include_schema
            }
        )

        if slide_count is not None and normalized_type == "presentation":
            slide_instruction = (
                f"\n\nSLIDE COUNT REQUIREMENT: Generate exactly {slide_count} content slides "
                f"(excluding the Executive Summary slide)."
            )
            final_prompt = final_prompt + slide_instruction

        return final_prompt
        
    except HTTPException:
        raise
        
    except Exception as e:
        logger.critical(
            f"Unexpected error fetching prompt for file_type='{file_type}': {str(e)}",
            extra={"file_type": file_type, "error": str(e)},
            exc_info=True
        )
        
        if use_fallback:
            logger.info(
                f"Unexpected error - using default fallback prompt for file_type='{file_type}'",
                extra={"file_type": file_type}
            )
            return DEFAULT_FILE_PROMPT
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unexpected error occurred while fetching document prompt"
            )