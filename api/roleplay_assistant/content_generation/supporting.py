"""
supporting.py - Supporting message/facts extraction and enhancement
"""

import logging
from typing import Optional, List
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


class SupportingMessageExtraction(BaseModel):
    key_facts: List[str] = Field(
        description="List of key facts, insights, or supporting information"
    )
    message_type: str = Field(
        description="Type: product_info, market_insights, context, evidence, or mixed"
    )
    relevance_score: float = Field(
        description="Relevance score between 0.0 and 1.0",
        ge=0.0,
        le=1.0
    )


class EnhancedSupportingMessage(BaseModel):
    original_message: str = Field(description="Original supporting message")
    enhanced_instruction: str = Field(
        description="Enhanced instruction for leveraging supporting information"
    )


DEFAULT_SUPPORTING_INSTRUCTION = """
**SUPPORTING CONTEXT:** Use the following background information to enrich your response when relevant. Incorporate these facts and insights naturally to add credibility, specificity, and depth. Reference this context where it strengthens your messaging, but avoid forcing it if not applicable.
"""


async def extract_supporting_message(
    user_input: str,
    openai_api_key: Optional[str] = openai_api_key,
    model: str = model,
    temperature: float = 0.0,
    use_fallback: bool = True
) -> tuple[List[str], str]:
    try:
        log_extraction_start("supporting_message_extraction", user_input, model)

        validated = validate_input(
            user_input,
            "supporting_message_extraction",
            use_fallback,
            (["General supporting context"], "context")
        )
        if isinstance(validated, tuple) and use_fallback:
            return validated

        llm = initialize_llm(model, temperature, openai_api_key)
        structured_llm = llm.with_structured_output(
            SupportingMessageExtraction,
            method="json_schema"
        )

        extraction_prompt = PromptTemplate.from_template("""
        You are an expert at analyzing and structuring supporting information, facts, and context from user input.

        Your task is to extract key facts, insights, or supporting information from the user's message. This supporting information might include:

        - Product features or characteristics
        - Market trends or consumer behavior insights
        - Statistical data or research findings
        - Industry context or background information
        - Competitive landscape details
        - Cultural or demographic insights
        - Evidence supporting claims or arguments

        Guidelines:

        1. Extract each distinct fact, insight, or piece of information as a separate item
        2. Clean up and clarify each fact (proper grammar, complete thoughts)
        3. Remove redundancy and combine related facts
        4. Preserve specific details (numbers, demographics, locations)
        5. Make facts standalone and clear without requiring original context
        6. Identify the type of supporting message

        Message Types:
        - product_info: Features, specifications, product characteristics
        - market_insights: Trends, consumer behavior, preferences
        - context: Background information, industry context
        - evidence: Data, statistics, research findings, proof points
        - mixed: Combination of above types

        User Input: {input}

        Examples:

        Input: "Collared t-shirts are popular among teen boys in India these days. They prefer bright colors and branded logos."
        Key Facts: ["Collared t-shirts are popular among teenage boys in India", "Teen boys prefer bright colors in their clothing", "Teen boys prefer clothing with branded logos"]
        Type: "market_insights"

        Input: "Our product has 99.9% uptime, processes 10M transactions daily, and supports 50+ integrations with enterprise tools"
        Key Facts: ["Product maintains 99.9% uptime reliability", "System processes 10 million transactions daily", "Platform supports 50+ enterprise tool integrations"]
        Type: "product_info"

        Input: "Research shows 73% of millennials prefer brands with sustainability commitments. Gen Z particularly values transparency in supply chains."
        Key Facts: ["73% of millennials prefer brands with sustainability commitments", "Gen Z consumers highly value transparency in supply chains"]
        Type: "evidence"

        Now extract and structure the key facts from the input above.
        """)

        chain = extraction_prompt | structured_llm

        logger.debug(f"Calling OpenAI for supporting message extraction with model={model}")
        result: SupportingMessageExtraction = await chain.ainvoke({"input": user_input})

        log_extraction_success(
            "supporting_message_extraction",
            {
                "facts_count": len(result.key_facts),
                "message_type": result.message_type,
                "relevance_score": result.relevance_score
            }
        )

        return result.key_facts, result.message_type

    except Exception as e:
        return await handle_openai_error(
            e,
            "supporting_message_extraction",
            (["General supporting context"], "context"),
            use_fallback
        )

async def enhance_supporting_message(
    key_facts: List[str],
    message_type: str = "mixed",
    openai_api_key: Optional[str] = openai_api_key,
    model: str = model,
    temperature: float = enhancement_temperature,
    use_fallback: bool = True
) -> str:
    try:
        logger.info(
            f"Enhancing supporting message with {len(key_facts)} facts",
            extra={"facts_count": len(key_facts), "message_type": message_type}
        )

        if not key_facts or len(key_facts) == 0:
            logger.warning("Empty key facts list for supporting message enhancement")
            if use_fallback:
                return DEFAULT_SUPPORTING_INSTRUCTION
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Key facts list cannot be empty"
                )

        llm = initialize_llm(model, temperature, openai_api_key)
        structured_llm = llm.with_structured_output(
            EnhancedSupportingMessage,
            method="json_schema"
        )

        enhancement_prompt = PromptTemplate.from_template("""
        You are an expert prompt engineer specializing in transforming supporting facts and context into actionable system prompt instructions.

        Your task is to take key facts and create a clear instruction that tells an LLM how to effectively incorporate this supporting information into its response.

        Message Type: {message_type}

        Key Facts:
        {facts_list}

        Guidelines for enhancement:

        1. Create a cohesive instruction (3-5 sentences, 60-100 words)
        2. Start with "**SUPPORTING CONTEXT:**" or similar header
        3. Specify HOW to use these facts (when to reference, how to integrate)
        4. Emphasize natural incorporation (don't force facts if not relevant)
        5. Highlight credibility, specificity, and depth benefits
        6. Make it clear this is supporting, not primary content

        Examples:

        Input Facts: ["Collared t-shirts popular among Indian teen boys", "Prefer bright colors", "Prefer branded logos"]
        Enhanced: "**SUPPORTING CONTEXT:** Your response should acknowledge that collared t-shirts are currently popular among teenage boys in India, who favor bright colors and branded logos. Integrate these market insights naturally when discussing product positioning, design choices, or target audience preferences. Use these facts to add specificity and demonstrate market awareness, but prioritize them appropriately relative to core messaging."

        Input Facts: ["99.9% uptime", "10M daily transactions", "50+ integrations"]
        Enhanced: "**SUPPORTING CONTEXT:** Reference the following technical specifications when they strengthen your arguments: 99.9% uptime reliability, 10 million daily transaction capacity, and 50+ enterprise tool integrations. Cite these metrics to build credibility around performance, scalability, and flexibility claims. Use specific numbers to make abstract benefits concrete and memorable."

        Now create the enhanced instruction for the facts above. Set original_message to a brief summary of the facts.
        """)

        facts_formatted = "\n".join([f"{i+1}. {fact}" for i, fact in enumerate(key_facts)])

        chain = enhancement_prompt | structured_llm

        logger.debug(f"Calling OpenAI for supporting message enhancement with model={model}")
        result: EnhancedSupportingMessage = await chain.ainvoke({
            "message_type": message_type,
            "facts_list": facts_formatted
        })

        log_extraction_success(
            "supporting_message_enhancement",
            {
                "facts_count": len(key_facts),
                "instruction_length": len(result.enhanced_instruction)
            }
        )

        if len(result.enhanced_instruction.strip()) < 30:
            logger.warning(
                f"Enhanced instruction too short: {len(result.enhanced_instruction)} chars"
            )
            if use_fallback:
                return DEFAULT_SUPPORTING_INSTRUCTION

        return result.enhanced_instruction

    except Exception as e:
        return await handle_openai_error(
            e,
            "supporting_message_enhancement",
            DEFAULT_SUPPORTING_INSTRUCTION,
            use_fallback
        )


async def process_supporting_message(
    user_input: str,
    openai_api_key: Optional[str] = openai_api_key,
    model: str = model,
    use_fallback: bool = True,
    reasoning: bool = False
) -> str:
    try:
        logger.info(
            f"Processing supporting message from input",
            extra={"input_preview": user_input[:150]}
        )

        key_facts, message_type = await extract_supporting_message(
            user_input=user_input,
            openai_api_key=openai_api_key,
            model=model,
            use_fallback=use_fallback
        )

        if reasoning:
            enhanced = await enhance_supporting_message(
                key_facts=key_facts,
                message_type=message_type,
                openai_api_key=openai_api_key,
                model=model,
                use_fallback=use_fallback
            )

            logger.info(
                f"Supporting message processing complete",
                extra={"message_type": message_type, "facts_count": len(key_facts)}
            )
            return enhanced
        else:
            formatted = f"**Supporting Context:**\n" + "\n".join([f"- {fact}" for fact in key_facts])
            return formatted

    except HTTPException:
        raise
    except Exception as e:
        return await handle_openai_error(
            e,
            "process_supporting_message",
            DEFAULT_SUPPORTING_INSTRUCTION,
            use_fallback
        )
