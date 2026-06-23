"""
prompt_merger.py - System prompt merging and enhancement orchestrator
"""

import logging
import asyncio
from typing import Optional, Dict, Any, List, Literal
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from fastapi import UploadFile, HTTPException, status
from pydantic import BaseModel, Field
from .admin import get_admin_prompt
from .primary import process_important_point
from .fileprocess import summarize_document,DocumentSummaryResult
from .audience import process_primary_audience
from .intent import generate_intent_prompt
from .outcomes import enhance_desired_outcome
from .painpoints import process_motivation_points
from .supporting import process_supporting_message
from .evidence import process_key_evidence
from .context import process_additional_context
from .documenttype import get_filetype_prompt, get_output_schema
from .utility import initialize_llm, TokenUsageCallback
import configparser
from langchain_core.documents import Document
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.messages import SystemMessage, HumanMessage
from api.roleplay_assistant.content_generation.documenttype import parse_customer_communication
from utils.prompt_loader import inject_company_context
from utils.GKB_retriever import _retrieve_similar_documents
from langchain_core.documents import Document

from .documenttype import get_output_schema, extract_slide_count_from_inputs

logger = logging.getLogger(__name__)

config = configparser.ConfigParser()
config.read('config.ini')

gpt_model = config['openAI_config']['model']
embed_model = config['openAI_config']['embedding_model']
OPENAI_API_KEY = config['openAI_config']['key']
enhancement_temperature = float(config['openAI_config'].get('enhancement_temperature', '0.2'))
content_generation_maxtokens = int(config['openAI_config'].get('content_generation_maxtokens', '20000'))
content_generation_temperature = float(config['openAI_config'].get('content_generation_temperature', '0.4'))
content_generation_model = config['openAI_config'].get('content_generation_model', gpt_model)
content_retrieval_tokens = int(config['openAI_config'].get('content_retrieval_tokens', '2500'))

@dataclass
class PromptComponents:
    admin_prompt: str = ""
    primary_objective: str = ""
    file_context: str = ""
    audience_instruction: str = ""
    intent_instruction: str = ""
    outcome_instruction: str = ""
    motivation_instruction: str = ""
    supporting_instruction: str = ""
    evidence_instruction: str = ""
    additional_context: str = ""
    document_type: str = ""
    retrieved_docs: List[Document] = None
    
    def to_dict(self) -> Dict[str, str]:
        return {
            "admin_prompt": self.admin_prompt,
            "primary_objective": self.primary_objective,
            "file_context": self.file_context,
            "audience_instruction": self.audience_instruction,
            "intent_instruction": self.intent_instruction,
            "outcome_instruction": self.outcome_instruction,
            "motivation_instruction": self.motivation_instruction,
            "supporting_instruction": self.supporting_instruction,
            "evidence_instruction": self.evidence_instruction,
            "additional_context": self.additional_context,
            "document_type": self.document_type
        }

PARSERS = {
    "customer_communication": parse_customer_communication,
    "internal_communication": parse_customer_communication,
}

class EnhancedSystemPrompt(BaseModel):
    system_prompt: str = Field(description="Complete enhanced system prompt")
    metadata: Dict[str, Any] = Field(description="Processing metadata")
    usage_metadata: Dict[str, int] = Field(default_factory=dict, description="Token usage stats")
    output_schema: Optional[type[BaseModel]] = Field(None, description="Pydantic schema for structured output") 

    generated_content: str = Field(description="Final generated content from LLM")
    structured_output: bool = Field(False, description="Whether structured output was used")

PROMPT_ORDER = [
    # "admin_prompt",           
    "document_type",          
    "primary_objective",      
    "file_context",           
    "audience_instruction",   
    "intent_instruction",     
    "outcome_instruction",    
    "motivation_instruction", 
    "evidence_instruction",   
    "supporting_instruction", 
    "additional_context"      
]

async def _safe_execute(
    coro,
    component_name: str,
    fallback_value: str = "",
    max_retries: int = 2
) -> str:
    for attempt in range(max_retries + 1):
        try:
            coro = coro() if callable(coro) else coro
            result = await coro
            logger.debug(f"{component_name} completed", extra={
                "component": component_name,
                "attempt": attempt + 1
            })
            return result
            
        except HTTPException as e:
            if e.status_code == status.HTTP_429_TOO_MANY_REQUESTS and attempt < max_retries:
                backoff = (attempt + 1) * 1.5
                logger.warning(
                    f"Rate limit hit for {component_name}, retrying in {backoff}s",
                    extra={"component": component_name, "attempt": attempt + 1}
                )
                await asyncio.sleep(backoff)
                continue
            
            logger.error(
                f"HTTP error in {component_name}: {e.detail}",
                extra={"component": component_name, "status_code": e.status_code}
            )
            return fallback_value
            
        except Exception as e:
            if attempt < max_retries:
                logger.warning(
                    f"Error in {component_name}, retrying: {str(e)}",
                    extra={"component": component_name, "attempt": attempt + 1, "error": str(e)}
                )
                await asyncio.sleep(1)
                continue
                
            logger.error(
                f"Failed {component_name} after {max_retries} retries: {str(e)}",
                extra={"component": component_name, "error": str(e)},
                exc_info=True
            )
            return fallback_value
    
    return fallback_value

async def merge_system_prompt(
    db,
    current_user,
    system_prompt: str,
    primary_objective: Optional[str] = None,
    audience: Optional[str] = None,
    intent: Optional[str] = None,
    desired_outcome: Optional[str] = None,
    motivation_points: Optional[str] = None,
    supporting_message: Optional[str] = None,
    key_evidence: Optional[str] = None,
    additional_context: Optional[str] = None,
    file: Optional[UploadFile] = None,
    document_type: Literal["presentation", "customer_talk_track", "customer_communication", "internal_communication", "faqs"] = "presentation",
    openai_api_key: Optional[str] = None,
    model: str = gpt_model,
    enable_enhancement: bool = True,
    general_bot = None,
    org_id: Optional[int] = None,
    enable_retrieval: bool = True,
    reasoning: bool = False,
    request_id: str = None,
) -> EnhancedSystemPrompt:
    start_time = datetime.utcnow()

    slide_count: Optional[int] = None
    if document_type == "presentation":
        slide_count = extract_slide_count_from_inputs(
            primary_objective=primary_objective,
            additional_context=additional_context,
            intent=intent,
            desired_outcome=desired_outcome,
            supporting_message=supporting_message,
            motivation_points=motivation_points,
        )
        logger.info(f"Auto-extracted slide_count={slide_count} for presentation")
    
    token_tracker = TokenUsageCallback()
    components = PromptComponents()
    
    try:
        logger.debug("Step 1: Fetching admin prompt...")
        components.admin_prompt = await get_admin_prompt(
            system_prompt=system_prompt,
        )
        
        logger.debug("Step 2: Launching ALL parallel tasks (including file processing)...")
        
        tasks = {}
        
        if file:
            tasks["file_processing"] = _safe_execute(
                lambda: summarize_document(
                    file=file,
                    openai_api_key=openai_api_key,
                    model=model,
                    use_fallback=True,
                    return_detailed=True,
                    enable_retrieval=enable_retrieval,
                    general_bot=general_bot,
                    org_id=org_id,
                    max_retrieved_docs=5
                ),
                "file_processing",
                DocumentSummaryResult(
                    summary="",
                    method_used="fallback",
                    retrieved_docs=[],
                    retrieval_metadata={"status": "failed"}
                )
            )

        elif enable_retrieval:
            kb_query = build_kb_query(
                document_type=document_type,
                primary_objective=primary_objective,
                audience=audience,
                intent=intent,
                desired_outcome=desired_outcome,
                motivation_points=motivation_points,
                supporting_message=supporting_message,
                key_evidence=key_evidence,
                additional_context=additional_context,
            )

            tasks["file_processing"] = _safe_execute(
                lambda: retrieve_kb_only(
                    query=kb_query,
                    general_bot=general_bot,
                    org_id=org_id,
                    max_docs=5,
                ),
                "kb_only_retrieval",
                DocumentSummaryResult(
                    summary="",
                    method_used="kb_only_fallback",
                    retrieved_docs=[],
                    retrieval_metadata={"status": "failed"}
                )
            )
        if primary_objective:
            tasks["primary_objective"] = _safe_execute(
                process_important_point(
                    user_input=primary_objective,
                    openai_api_key=openai_api_key,
                    model=model,
                    use_fallback=True,
                    reasoning=reasoning
                ),
                "primary_objective",
                ""
            )
        
        if audience:
            tasks["audience_instruction"] = _safe_execute(
                process_primary_audience(
                    user_input=audience,
                    openai_api_key=openai_api_key,
                    model=model,
                    use_fallback=True,
                    reasoning=reasoning
                ),
                "audience",
                ""
            )
        
        if intent:
            tasks["intent_instruction"] = _safe_execute(
                generate_intent_prompt(
                    user_input=intent,
                    openai_api_key=openai_api_key,
                    model=model,
                    use_fallback=True
                ),
                "intent",
                ""
            )
        
        if desired_outcome:
            tasks["outcome_instruction"] = _safe_execute(
                enhance_desired_outcome(
                    desired_outcome=desired_outcome,
                    openai_api_key=openai_api_key,
                    model=model,
                    use_fallback=True
                ),
                "outcome",
                ""
            )
        
        if motivation_points:
            tasks["motivation_instruction"] = _safe_execute(
                process_motivation_points(
                    user_input=motivation_points,
                    openai_api_key=openai_api_key,
                    model=model,
                    use_fallback=True,
                    reasoning=reasoning
                ),
                "motivation",
                ""
            )
        
        if supporting_message:
            tasks["supporting_instruction"] = _safe_execute(
                process_supporting_message(
                    user_input=supporting_message,
                    openai_api_key=openai_api_key,
                    model=model,
                    use_fallback=True,
                    reasoning=reasoning
                ),
                "supporting",
                ""
            )
        
        if key_evidence:
            tasks["evidence_instruction"] = _safe_execute(
                process_key_evidence(
                    user_input=key_evidence,
                    openai_api_key=openai_api_key,
                    model=model,
                    use_fallback=True,
                    reasoning=reasoning
                ),
                "evidence",
                ""
            )
        
        if additional_context:
            tasks["additional_context"] = _safe_execute(
                process_additional_context(
                    user_input=additional_context,
                    openai_api_key=openai_api_key,
                    model=model,
                    use_fallback=True,
                    reasoning=reasoning
                ),
                "additional_context",
                ""
            )
        
        if document_type:
            tasks["document_type"] = _safe_execute(
                get_filetype_prompt(
                    file_type=document_type,
                    use_fallback=True,
                    slide_count=slide_count
                ),
                "document_type",
                ""
            )
        
        output_schema = None
        try:
            output_schema = get_output_schema(document_type)
            logger.info(f"Structured output schema loaded for document_type={document_type}")
        except KeyError as e:
            logger.warning(f"No schema found for document_type={document_type}, using unstructured output")

        logger.debug(f"Step 3: Waiting for {len(tasks)} parallel tasks (including file)...")
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        
        for (component_name, _), result in zip(tasks.items(), results):
            if isinstance(result, Exception):
                logger.error(f"Task {component_name} raised exception: {result}")
                continue

            if component_name == "file_processing":
                if isinstance(result, DocumentSummaryResult):
                    components.file_context = result.summary
                    components.retrieved_docs = result.retrieved_docs
                    logger.info(
                        f"File processed with {len(result.retrieved_docs)} retrieved docs",
                        extra=result.retrieval_metadata
                    )
                elif isinstance(result, str):
                    components.file_context = result
                    components.retrieved_docs = []
            else:
                setattr(components, component_name, result)

        if document_type == "presentation" and slide_count and components.document_type:
            components.document_type += (
                f"\n\nSLIDE COUNT REQUIREMENT: Generate exactly {slide_count} content slides "
                f"(excluding the Executive Summary slide)."
            )

        processing_time = (datetime.utcnow() - start_time).total_seconds()
        logger.info(
            f"All components processed in {processing_time:.2f}s",
            extra={
                "components_count": len(tasks),
                "file_processed": file is not None
            }
        )
        
        logger.debug("Step 4: Assembling final prompt...")
        prompt_sections = []
        
        for component_key in PROMPT_ORDER:
            component_value = getattr(components, component_key, "")
            if component_value and component_value.strip():
                prompt_sections.append(component_value.strip())
        
        combined_prompt = "\n\n".join(prompt_sections)
        
        logger.debug("Step 5: Generating content with integrated enhancement and guardrails...")
        try:
            generation_result = await _enhance_with_guardrails(
                db,
                current_user,
                admin_prompt=components.admin_prompt,
                combined_prompt=combined_prompt,
                retrieved_docs=components.retrieved_docs,
                output_schema=output_schema,
                openai_api_key=openai_api_key,
                model=content_generation_model,
                temperature=content_generation_temperature,
                max_tokens=content_generation_maxtokens,
                token_callback=token_tracker,
                request_id=request_id,
                used_uploaded_file=file is not None
            )

            if generation_result is None:
                logger.error("Generation result is None, using fallback")
                generation_result = {
                    "content": "Error: Content generation failed",
                    "structured_output": False
                }
        except Exception as e:
            logger.warning(
                f"Enhancement layer failed, using unenhanced prompt: {str(e)}",
                extra={"error": str(e)}
            )
            generation_result = {
                "content": "Error: Content generation encountered an error",
                "structured_output": False
            }
        total_time = (datetime.utcnow() - start_time).total_seconds()
        metadata = {
            "processing_time_seconds": total_time,
            "components_processed": list(tasks.keys()),
            "total_length": len(combined_prompt),
            "enhancement_applied": enable_enhancement,
            "timestamp": start_time.isoformat(),
            "document_type": document_type,
            "structured_output_enabled": output_schema is not None,
            "file_uploaded": file is not None,
            "retrieval_enabled": enable_retrieval,
            "docs_retrieved": len(components.retrieved_docs)
        }
        
        usage_metadata = {
            "input_tokens": token_tracker.prompt_tokens,
            "output_tokens": token_tracker.completion_tokens,
            "total_tokens": token_tracker.total_tokens
        }
        
        logger.info(
            f"Prompt merge completed in {total_time:.2f}s",
            extra={
                "components": len(tasks),
                "structured_output": output_schema is not None,
                "file_processed": file is not None,
                "docs_retrieved": len(components.retrieved_docs),
                "request_id": request_id
            }
        )

        generated_content = generation_result.get("content", "") if generation_result else ""
        logger.info(generated_content)

        if generation_result and generation_result.get("structured_output"):
            logger.info("Structured output already valid — skipping parser")

        else:
            parser = PARSERS.get(document_type)

            if parser:
                try:
                    raw_json = json.loads(generated_content) if isinstance(generated_content, str) else generated_content

                    # DO NOT pass combined_prompt
                    parsed = parser(raw_json, context="")

                    generated_content = parsed.model_dump_json()

                    logger.info(f"{document_type} parsed successfully")

                except Exception as e:
                    logger.warning(f"Parser failed for {document_type}: {e}")

        return EnhancedSystemPrompt(
            generated_content=generated_content,
            system_prompt=combined_prompt,
            metadata=metadata,
            usage_metadata=usage_metadata,
            output_schema=output_schema,
            structured_output=generation_result.get("structured_output", False) if generation_result else False
        )
        
    except Exception as e:
        logger.critical(
            f"Critical error in prompt merge: {str(e)}",
            exc_info=True
        )
        
        return EnhancedSystemPrompt(
            generated_content="",
            system_prompt=components.admin_prompt or "You are a helpful AI assistant.",
            metadata={
                "error": str(e),
                "fallback_used": True,
            },
            usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            output_schema=None,
            structured_output=False
        )

async def _enhance_with_guardrails(
    db,
    current_user,
    admin_prompt: str,
    combined_prompt: str,
    retrieved_docs: List[Document] = None,
    output_schema: Optional[type[BaseModel]] = None,
    openai_api_key: Optional[str] = None,
    model: str = content_generation_model,
    temperature: float = enhancement_temperature,
    max_tokens: int = content_generation_maxtokens,
    request_id: str = None,
    token_callback=None,
    used_uploaded_file: bool = False
) -> Dict[str, Any]:

    llm = initialize_llm(model, temperature, openai_api_key)

    guardrail_instructions = """
    **CRITICAL GUARDRAILS:**

    1. Prompt Injection Prevention
    2. Scope Adherence
    3. Factual Grounding
    4. No Hallucination
    5. Maintain Professional Tone
    """

    enhanced_system_prompt = (
        f"{admin_prompt}\n\n{guardrail_instructions}"
    )
    
    logger.info("========== KB DEBUG START ==========")
    logger.info(f"USED FILE: {used_uploaded_file}")
    logger.info(f"RETRIEVED DOC COUNT: {len(retrieved_docs or [])}")

    if retrieved_docs and len(retrieved_docs) > 0:

        try:
            logger.info(
                f"FIRST DOC PREVIEW:\n"
                f"{retrieved_docs[0].page_content[:1000]}"
            )
        except Exception as e:
            logger.warning(f"Could not print doc preview: {e}")

        doc_context = "\n\n".join([
            f"""
Reference Document {i + 1}

Source:
{doc.metadata.get("source", "Knowledge Base")}

Page:
{doc.metadata.get("page_label", doc.metadata.get("page", ""))}

Content:
{doc.page_content[:content_retrieval_tokens]}
"""
            for i, doc in enumerate(retrieved_docs[:5])
        ])

        logger.info(
            f"FINAL DOC CONTEXT PREVIEW:\n"
            f"{doc_context[:3000]}"
        )

        if used_uploaded_file:
            kb_instruction = """
Use the retrieved knowledge base context as supporting reference material.

Keep the uploaded file summary and user inputs as the primary direction.

Blend relevant organizational knowledge naturally where useful.
"""
        else:
            kb_instruction = """
No upload file was provided.

The retrieved organizational knowledge should strongly influence the generated content.
Use at least 5 specific terms, product names, workflows, examples, or claims from the KNOWLEDGE BASE CONTENT
Do not create generic AI healthcare slides unless those ideas are directly present in the knowledge base.
Each slide must clearly reflect a specific retrieved document detail.
If the knowledge base content is broad or insufficient, state “Evidence Needed” instead of inventing examples, case studies, metrics, HIPAA claims, or outcomes
Avoid producing generic content unrelated to the retrieved material.
Do not generate a generic response if relevant organizational knowledge exists.
The final output should clearly reflect the retrieved organizational knowledge.
"""

        enhanced_human_message = f"""
{combined_prompt}

{kb_instruction}

KNOWLEDGE BASE CONTENT:

{doc_context}

- Follow the user form inputs.
- When no upload file is provided, use the retrieved knowledge base content to shape the main topic and examples.
- Avoid generic placeholder content if retrieved context exists.
- Incorporate terminology, workflows, and concepts from the knowledge base naturally.
- Do not hallucinate unsupported claims.

Now generate the requested content.
"""

    else:
        logger.info("NO RETRIEVED DOCS FOUND")
        enhanced_human_message = combined_prompt

    logger.info("========== FINAL PROMPT PREVIEW ==========")
    logger.info(enhanced_human_message[:5000])
    logger.info("========== KB DEBUG END ==========")

    from api.user_management.user_management import get_company_context

    company_context = await get_company_context(
        db,
        current_user,
        return_raw=True
    )

    enhanced_human_message = inject_company_context(
        enhanced_human_message,
        company_context,
        current_user.org_name
    )

    messages = [
        SystemMessage(content=enhanced_system_prompt),
        HumanMessage(content=enhanced_human_message)
    ]

    config = {
        "tags": [request_id] if request_id else []
    }

    if token_callback:
        config["callbacks"] = [token_callback]

    try:
        if output_schema:
            logger.info(
                f"Generating structured output with schema: "
                f"{output_schema.__name__}"
            )

            structured_llm = llm.with_structured_output(
                output_schema
            )

            response = await structured_llm.ainvoke(
                messages,
                max_tokens=max_tokens,
                config=config
            )

            generated_content = response.model_dump_json(
                indent=2
            )

            return {
                "content": generated_content,
                "structured_output": True
            }

        else:
            logger.info("Generating unstructured content")

            response = await llm.ainvoke(
                messages,
                max_tokens=max_tokens,
                config=config
            )

            return {
                "content": response.content.strip(),
                "structured_output": False
            }

    except Exception as e:
        logger.error(
            f"Content generation failed: {e}",
            exc_info=True
        )
        raise
    
def build_kb_query(
    document_type: str,
    primary_objective: str = "",
    audience: str = "",
    intent: str = "",
    desired_outcome: str = "",
    motivation_points: str = "",
    supporting_message: str = "",
    key_evidence: str = "",
    additional_context: str = "",
) -> str:

    query_parts = []

    if primary_objective:
        query_parts.append(primary_objective)

    if supporting_message:
        query_parts.append(supporting_message)

    if key_evidence:
        query_parts.append(key_evidence)

    if additional_context:
        query_parts.append(additional_context)

    if motivation_points:
        query_parts.append(motivation_points)

    if audience:
        query_parts.append(
            f"target audience: {audience}"
        )

    if intent:
        query_parts.append(
            f"purpose: {intent}"
        )

    if desired_outcome:
        query_parts.append(
            f"goal: {desired_outcome}"
        )

    query_parts.append(
        f"document type {document_type}"
    )

    final_query = " ".join(query_parts)

    logger.info(
        f"KB QUERY GENERATED: {final_query}"
    )

    return final_query


async def retrieve_kb_only(
    query: str,
    general_bot,
    org_id: int,
    max_docs: int = 5,
) -> DocumentSummaryResult:

    logger.info("========== KB ONLY RETRIEVAL START ==========")
    logger.info(f"KB QUERY: {query}")
    logger.info(f"GENERAL BOT EXISTS: {general_bot is not None}")
    logger.info(f"ORG ID: {org_id}")

    if not query.strip():
        logger.warning("KB retrieval skipped: empty query")
        reason = "missing_query"
    elif general_bot is None:
        logger.warning("KB retrieval skipped: general_bot is None")
        reason = "missing_general_bot"
    else:
        reason = None

    if reason:
        return DocumentSummaryResult(
            summary="",
            method_used="kb_only_skipped",
            retrieved_docs=[],
            retrieval_metadata={
                "status": "skipped",
                "reason": reason
            },
        )

    try:
        retrieved_docs, retrieval_metadata = await _retrieve_similar_documents(
            query=query,
            general_bot=general_bot,
            org_id=org_id,
            max_docs=max_docs,
            mode="content_generation",
        )

        logger.info(f"KB DOCS RETURNED: {len(retrieved_docs)}")
        logger.info(f"KB METADATA: {retrieval_metadata}")

        return DocumentSummaryResult(
            summary="",
            method_used="kb_only_retrieval",
            retrieved_docs=retrieved_docs,
            retrieval_metadata=retrieval_metadata,
        )

    except Exception as e:
        logger.warning(f"KB-only retrieval failed: {e}", exc_info=True)
        return DocumentSummaryResult(
            summary="",
            method_used="kb_only_failed",
            retrieved_docs=[],
            retrieval_metadata={
                "status": "failed",
                "error": str(e),
                "docs_found": 0,
            },
        )