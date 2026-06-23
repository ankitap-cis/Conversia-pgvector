"""
outcomes.py - Desired outcome enhancement
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

class DesiredOutcomeEnhancement(BaseModel):
    original_outcome: str = Field(
        description="The original desired outcome from user"
    )
    enhanced_prompt: str = Field(
        description="Enhanced system prompt instruction to achieve outcome"
    )
    confidence: float = Field(
        description="Confidence score between 0.0 and 1.0",
        ge=0.0,
        le=1.0
    )


DEFAULT_ENHANCED_OUTCOME = """
Your response should be clear, engaging, and aligned with the user's objectives. Focus on delivering value through well-structured content that meets the stated goals. Maintain professionalism while adapting tone and style to best serve the intended purpose and audience.
"""

async def enhance_desired_outcome(
    desired_outcome: str,
    openai_api_key: Optional[str] = openai_api_key,
    model: str = model,
    temperature: float = enhancement_temperature,
    use_fallback: bool = True
) -> str:
    try:
        log_extraction_start("outcome_enhancement", desired_outcome, model)

        validated = validate_input(
            desired_outcome,
            "outcome_enhancement",
            use_fallback,
            DEFAULT_ENHANCED_OUTCOME
        )
        if validated != desired_outcome.strip() and use_fallback:
            return validated

        llm = initialize_llm(model, temperature, openai_api_key)
        structured_llm = llm.with_structured_output(
            DesiredOutcomeEnhancement,
            method="json_schema"
        )

        enhancement_prompt = PromptTemplate.from_template("""
        You are an expert prompt engineer specializing in transforming high-level goals into precise, actionable system prompt instructions.

        Your task is to take the user's desired outcome and create a clear, concrete system prompt instruction that will guide an LLM to achieve that outcome.

        Guidelines for enhancement:

        1. Convert vague goals into specific behavioral directives
        2. Use action-oriented language (e.g., "must", "should", "focus on")
        3. Specify concrete behaviors, not abstract concepts
        4. Keep it concise (2-4 sentences, 50-100 words)
        5. Focus on HOW the LLM should behave to achieve the outcome
        6. Avoid repeating the outcome verbatim - transform it into instructions
        7. Be specific about tone, style, content structure, or persuasive techniques if relevant

        Examples:

        - Desired: "audience should think about purchasing this product"
        Enhanced: "Your response must strategically guide readers toward considering a purchase decision. Use persuasive techniques such as highlighting key benefits, addressing common objections preemptively, and creating a sense of value and urgency. Focus on building desire while maintaining credibility and avoiding aggressive sales tactics."

        - Desired: "make it engaging for developers"
        Enhanced: "Your response must engage a technical developer audience. Use concrete code examples, reference real-world development scenarios, and employ precise technical terminology. Maintain a conversational but technically rigorous tone that respects the reader's expertise while providing actionable insights."

        - Desired: "help users understand complex concepts easily"
        Enhanced: "Your response must break down complex concepts into easily digestible explanations. Use progressive layering (simple to complex), analogies from everyday life, visual descriptions, and concrete examples. Check for understanding at key points and build on previously explained concepts systematically."

        Now enhance this desired outcome:

        Desired Outcome: {desired_outcome}

        Transform this into a clear, actionable system prompt instruction that tells the LLM exactly how to behave to achieve this outcome.
        """)

        chain = enhancement_prompt | structured_llm

        logger.debug(f"Calling OpenAI for outcome enhancement with model={model}")
        result: DesiredOutcomeEnhancement = await chain.ainvoke({
            "desired_outcome": desired_outcome
        })

        log_extraction_success(
            "outcome_enhancement",
            {
                "original_outcome": desired_outcome[:100],
                "enhanced_length": len(result.enhanced_prompt),
                "confidence": result.confidence
            }
        )

        if len(result.enhanced_prompt.strip()) < 20:
            logger.warning(
                f"Enhanced prompt too short: {len(result.enhanced_prompt)} chars",
                extra={"enhanced_prompt": result.enhanced_prompt}
            )
            if use_fallback:
                return DEFAULT_ENHANCED_OUTCOME

        return result.enhanced_prompt

    except Exception as e:
        return await handle_openai_error(
            e,
            "outcome_enhancement",
            DEFAULT_ENHANCED_OUTCOME,
            use_fallback
        )
