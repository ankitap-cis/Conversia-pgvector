"""
primary.py - Primary/Most Important Point extraction and enhancement
"""

import logging
from typing import Optional
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from fastapi import HTTPException, status

from .utility import (
    handle_openai_error,
    initialize_llm,
    validate_input,
    log_extraction_start,
    log_extraction_success
)
import configparser

config = configparser.ConfigParser()
config.read('config.ini')

openai_api_key = config['openAI_config'].get('key', None)
model = config['openAI_config'].get('model', 'gpt-4o-mini')
enhancement_temperature = float(config['openAI_config'].get('enhancement_temperature', '0.2'))
logger = logging.getLogger(__name__)


class ImportantPointExtraction(BaseModel):
    important_point: str = Field(
        description="The single most important point, message, or objective (one clear sentence)"
    )
    confidence: float = Field(
        description="Confidence score between 0.0 and 1.0",
        ge=0.0,
        le=1.0
    )

class EnhancedImportantPoint(BaseModel):
    original_point: str = Field(description="Original important point extracted")
    enhanced_instruction: str = Field(
        description="Enhanced system prompt instruction with PRIMARY focus emphasis"
    )

DEFAULT_IMPORTANT_INSTRUCTION = """
**PRIMARY OBJECTIVE:** Your response must align with the user's core objective. This is the single most important consideration that should guide all aspects of your generated content. Every element of your response should contribute toward achieving this central goal.
"""

async def extract_important_point(
    user_input: str,
    openai_api_key: Optional[str] = openai_api_key,
    model: str = model,
    temperature: float = 0.0,
    use_fallback: bool = True
) -> str:
    try:
        log_extraction_start("important_point_extraction", user_input, model)

        validated = validate_input(
            user_input,
            "important_point_extraction",
            use_fallback,
            "Maintain focus on core objectives"
        )
        if validated != user_input.strip() and use_fallback:
            return validated

        llm = initialize_llm(model, temperature, openai_api_key)
        structured_llm = llm.with_structured_output(
            ImportantPointExtraction,
            method="json_schema"
        )

        extraction_prompt = PromptTemplate.from_template("""
        You are an expert at identifying and extracting the single most critical message or objective from user input.

        Your task is to extract THE ONE most important point, message, or objective. This should be:

        1. A single, clear sentence (10-20 words ideal)
        2. The PRIMARY focus or most critical consideration
        3. Actionable and specific, not vague
        4. Written as a clear directive or statement

        If the input contains multiple points, identify which one is MOST important or overarching.

        Guidelines:
        - Remove filler words and unnecessary context
        - Make it direct and clear
        - Focus on the core essence
        - Keep it as ONE sentence (can be compound with "and" if necessary)
        - Preserve specific metrics, targets, or details if mentioned

        User Input: {input}

        Examples:

        Input: "The most critical thing is we want to focus on increasing sales by 50% this quarter"
        Important Point: "Increase sales by 50% this quarter"

        Input: "We need to make sure that above all else, the content resonates with teenagers and gets them excited about our brand"
        Important Point: "Ensure content resonates with and excites teenage audiences about the brand"

        Input: "Priority number one is maintaining data security and user privacy throughout the entire process"
        Important Point: "Maintain data security and user privacy throughout the entire process"

        Now extract the single most important point from the input above.
        """)

        chain = extraction_prompt | structured_llm
        logger.debug(f"Calling OpenAI for important point extraction with model={model}")
        result: ImportantPointExtraction = await chain.ainvoke({"input": user_input})

        log_extraction_success(
            "important_point_extraction",
            {
                "important_point": result.important_point,
                "confidence": result.confidence
            }
        )

        if len(result.important_point.strip()) < 5:
            logger.warning(
                f"Extracted point too short: {result.important_point}",
                extra={"point": result.important_point}
            )
            if use_fallback:
                return "Maintain focus on core objectives"

        return result.important_point

    except Exception as e:
        return await handle_openai_error(
            e,
            "important_point_extraction",
            "Maintain focus on core objectives",
            use_fallback
        )

async def enhance_important_point(
    important_point: str,
    openai_api_key: Optional[str] = openai_api_key,
    model: str = model,
    temperature: float = enhancement_temperature,
    use_fallback: bool = True
) -> str:
    try:
        logger.info(
            f"Enhancing important point with emphasis",
            extra={"important_point": important_point, "model": model}
        )

        validated = validate_input(
            important_point,
            "important_point_enhancement",
            use_fallback,
            DEFAULT_IMPORTANT_INSTRUCTION
        )
        if validated != important_point.strip() and use_fallback:
            return validated

        llm = initialize_llm(model, temperature, openai_api_key)
        structured_llm = llm.with_structured_output(
            EnhancedImportantPoint,
            method="json_schema"
        )

        enhancement_prompt = PromptTemplate.from_template("""
        You are an expert prompt engineer specializing in creating emphatic, high-priority system instructions.

        Your task is to transform the single most important point into a STRONGLY EMPHASIZED system prompt instruction that makes it absolutely clear this is THE PRIMARY focus that supersedes all other considerations.

        Important Point: {important_point}

        Guidelines for creating the enhanced instruction:

        1. Lead with STRONG emphasis markers (e.g., "**PRIMARY OBJECTIVE:**", "***CRITICAL PRIORITY:***", "**MOST IMPORTANT:**")
        2. Use directive, commanding language ("MUST", "is ESSENTIAL", "takes ABSOLUTE PRIORITY")
        3. Make it clear this supersedes other considerations ("above all else", "as the primary focus", "before any other consideration")
        4. Be specific and actionable based on the important point
        5. Keep it 2-4 sentences (60-100 words)
        6. Use capital letters strategically for emphasis (but don't overdo it)
        7. Create urgency and importance without being melodramatic
        8. Make sure it reads as a serious, professional instruction

        Examples:

        Important Point: "Increase sales by 50% this quarter"
        Enhanced: "**PRIMARY OBJECTIVE:** Your response MUST be laser-focused on driving a 50% sales increase this quarter. This is the single most important outcome that takes absolute priority over all other considerations. Every element of your content—messaging, structure, calls-to-action—must directly contribute to this sales growth target."

        Important Point: "Ensure content resonates with and excites teenage audiences"
        Enhanced: "**MOST IMPORTANT:** Your response MUST resonate with and genuinely excite teenage audiences—this is the non-negotiable foundation of success. Before addressing any other goal, ensure your tone, language, references, and style authentically connect with teens aged 13-19. If the content doesn't engage this audience, it has failed its primary mission."

        Important Point: "Maintain data security and user privacy throughout"
        Enhanced: "***CRITICAL PRIORITY:*** Your response MUST maintain absolute data security and user privacy at all times—this is non-negotiable and supersedes all other objectives. Any recommendation, instruction, or content that could compromise security or privacy is strictly forbidden. This requirement takes precedence over convenience, speed, or any other consideration."

        Now create the enhanced, emphasized instruction for the important point above. Set original_point to the input.
        """)

        chain = enhancement_prompt | structured_llm

        logger.debug(f"Calling OpenAI for important point enhancement with model={model}")
        result: EnhancedImportantPoint = await chain.ainvoke({
            "important_point": important_point
        })

        if not result.original_point:
            result.original_point = important_point

        log_extraction_success(
            "important_point_enhancement",
            {
                "original_point": important_point,
                "enhanced_length": len(result.enhanced_instruction)
            }
        )

        if len(result.enhanced_instruction.strip()) < 30:
            logger.warning(
                f"Enhanced instruction too short: {len(result.enhanced_instruction)} chars"
            )
            if use_fallback:
                return DEFAULT_IMPORTANT_INSTRUCTION

        if "**" not in result.enhanced_instruction and "***" not in result.enhanced_instruction:
            logger.warning(
                "Enhanced instruction missing emphasis markers (** or ***)",
                extra={"instruction": result.enhanced_instruction[:100]}
            )

        return result.enhanced_instruction

    except Exception as e:
        return await handle_openai_error(
            e,
            "important_point_enhancement",
            DEFAULT_IMPORTANT_INSTRUCTION,
            use_fallback
        )


async def process_important_point(
    user_input: str,
    openai_api_key: Optional[str] = openai_api_key,
    model: str = model,
    use_fallback: bool = True,
    reasoning: bool = False
) -> str:
    try:
        logger.info(
            f"Processing important point from input",
            extra={"input_preview": user_input[:150]}
        )

        important_point = await extract_important_point(
            user_input=user_input,
            openai_api_key=openai_api_key,
            model=model,
            use_fallback=use_fallback
        )

        logger.info(
            f"Extracted important point: {important_point}",
            extra={"point": important_point}
        )
        if reasoning:
            enhanced = await enhance_important_point(
                important_point=important_point,
                openai_api_key=openai_api_key,
                model=model,
                use_fallback=use_fallback
            )

            logger.info(
                f"Important point processing complete",
                extra={
                    "original_point": important_point,
                }
            )
            return enhanced
        else:
            formatted = f"**Primary Objective:** {important_point}"
            logger.info(
                f"Important point processing complete without reasoning",
                extra={"original_point": important_point}
            )
            return formatted

    except HTTPException:
        raise
    except Exception as e:
        return await handle_openai_error(
            e,
            "process_important_point",
            DEFAULT_IMPORTANT_INSTRUCTION,
            use_fallback
        )
