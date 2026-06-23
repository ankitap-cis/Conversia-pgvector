"""
context.py - Additional context extraction and enhancement
"""

import logging
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, ConfigDict
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
import json


config = configparser.ConfigParser()
config.read('config.ini')
model = config['openAI_config']['model']
openai_api_key = config['openAI_config'].get('key', None)
enhancement_temperature = float(config['openAI_config'].get('enhancement_temperature', 0.3))


logger = logging.getLogger(__name__)

class ContextItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    
    category: str = Field(description="Context category")
    values: List[str] = Field(description="List of values for this category")

class AdditionalContextExtraction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    context_items: List[ContextItem] = Field(
        description="Dictionary of context categories with their values"
    )
    
    confidence: float = Field(
        description="Confidence score between 0.0 and 1.0",
        ge=0.0,
        le=1.0
    )

class EnhancedAdditionalContext(BaseModel):
    original_context: str = Field(description="Original context input")
    combined_instruction: str = Field(
        description="Combined instruction integrating all context categories"
    )

DEFAULT_ADDITIONAL_CONTEXT_INSTRUCTION = """
**ADDITIONAL CONTEXT:** Consider the following additional guidelines and context when generating your response. Apply these directives where they enhance quality or align with stated objectives, while maintaining consistency with primary instructions.
"""

async def extract_additional_context(
    user_input: str,
    openai_api_key: Optional[str] = openai_api_key,
    model: str = model,
    temperature: float = 0.0,
    use_fallback: bool = True
    ) -> tuple[Dict[str, List[str]], List[str]]: 
    try:
        log_extraction_start("additional_context_extraction", user_input, model)
        validated = validate_input(
            user_input,
            "additional_context_extraction",
            use_fallback,
            ({"general": ["General additional context"]}, ["general"])
        )
        if isinstance(validated, tuple) and use_fallback:
            return validated
        
        llm = initialize_llm(model, temperature, openai_api_key)
        structured_llm = llm.with_structured_output(
            AdditionalContextExtraction,
            method="json_schema"
        )
        
        extraction_prompt = PromptTemplate.from_template("""
        You are an expert at analyzing and categorizing additional context, directives, and instructions from user input.

        Your task is to extract and structure ALL additional context into appropriate categories. Common categories include:

        **STANDARD CATEGORIES:**
        - **tone**: Tone directives (e.g., authoritative, friendly, formal, casual, professional, conversational)
        - **style**: Writing style (e.g., concise, detailed, narrative, technical, simple, academic)
        - **keyphrases**: Specific phrases, terms, or keywords to include/emphasize in response
        - **constraints**: Limitations or restrictions (e.g., word count, avoid certain topics, time limits)
        - **format**: Formatting requirements (e.g., bullet points, numbered lists, paragraphs, sections)
        - **length**: Length specifications (e.g., short, detailed, 500 words, 2 paragraphs)
        - **terminology**: Specific terminology to use or avoid
        - **perspective**: Point of view (e.g., first-person, third-person, we/you language)
        - **examples**: Requirements for examples, case studies, or illustrations
        - **citations**: Citation or reference requirements
        - **emphasis**: What to emphasize or prioritize
        - **avoid**: Things to avoid or de-emphasize
        - **other**: Any other directives that don't fit above categories

        Guidelines:
        1. Extract each distinct directive or piece of context
        2. Categorize into appropriate buckets (can have multiple categories)
        3. For lists (like keyphrases), extract each item separately
        4. Preserve specific wording for keyphrases, terms, and quotes
        5. Identify which categories should take priority
        6. Use "other" category with descriptive key if no standard category fits

        User Input: {input}

        Examples:

        Input: "Overall you need to be authoritative and data-oriented. Keyphrases to include: 'Sales increase by 80%', 'Digital transformation success'"
        Context Items: {{
        "tone": ["authoritative", "data-oriented"],
        "keyphrases": ["Sales increase by 80%", "Digital transformation success"]
        }}

        Input: "Write in a conversational style, maximum 300 words. Avoid technical jargon. Include at least 2 real-world examples."
        Context Items: {{
        "style": ["conversational"],
        "length": ["maximum 300 words"],
        "avoid": ["technical jargon"],
        "examples": ["include at least 2 real-world examples"]
        }}

        Input: "Use first-person perspective. Emphasize customer success stories. Terms to use: 'game-changer', 'industry-leading'. Keep it under 5 paragraphs."
        Context Items: {{
        "perspective": ["first-person"],
        "emphasis": ["customer success stories"],
        "terminology": ["game-changer", "industry-leading"],
        "format": ["under 5 paragraphs"]
        }}

        Now extract and categorize all additional context from the input above.
        """)
        
        chain = extraction_prompt | structured_llm
        
        logger.debug(f"Calling OpenAI for additional context extraction with model={model}")
        result: AdditionalContextExtraction = await chain.ainvoke({"input": user_input})
        
        context_items_dict: Dict[str, List[str]] = {}
        for item in result.context_items:
            if item.category not in context_items_dict:
                context_items_dict[item.category] = []
            context_items_dict[item.category].extend(item.values)
        
        categories_found = list(context_items_dict.keys())
        
        log_extraction_success(
            "additional_context_extraction",
            {
                "categories_count": len(categories_found),
                "categories": categories_found,
                "confidence": result.confidence
            }
        )
        
        return context_items_dict, categories_found
        
    except Exception as e:
        return await handle_openai_error(
            e,
            "additional_context_extraction",
            ({"general": ["General additional context"]}, ["general"]),
            use_fallback
        )

async def enhance_additional_context(
    context_items: Dict[str, Any],
    categories_found: List[str],
    openai_api_key: Optional[str] = openai_api_key,
    model: str = model,
    temperature: float = enhancement_temperature,
    use_fallback: bool = True
) -> str:
    try:
        logger.info(
            f"Enhancing {len(categories_found)} context categories",
            extra={"categories_count": len(categories_found), "categories": categories_found}
        )
        
        if not context_items or len(context_items) == 0:
            logger.warning("Empty context items for enhancement")
            if use_fallback:
                return DEFAULT_ADDITIONAL_CONTEXT_INSTRUCTION
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Context items cannot be empty"
                )
        
        llm = initialize_llm(model, temperature, openai_api_key)
        structured_llm = llm.with_structured_output(
            EnhancedAdditionalContext,
            method="json_schema"
        )
        
        enhancement_prompt = PromptTemplate.from_template("""
        You are an expert prompt engineer. Create a cohesive, integrated instruction that combines all the following context categories into a unified additional context section for a system prompt.

        Context Categories and Values:
        {context_formatted}

        Guidelines:
        1. Create a unified instruction (3-5 sentences, 80-120 words)
        2. Start with "**ADDITIONAL CONTEXT:**" header
        3. Group related directives together logically
        4. Maintain all specific details (keyphrases, terminology, constraints)
        5. Use clear structure with categories labeled if needed
        6. Balance comprehensiveness with conciseness
        7. Prioritize constraints and must-follow directives first
        8. Frame optional/stylistic elements as "where applicable" or "when relevant"

        Examples:

        Input Categories:
        **TONE:** authoritative, data-oriented
        **KEYPHRASES:** "Sales increase by 80%", "Digital transformation"
        Combined: "**ADDITIONAL CONTEXT:** Your tone should be authoritative and data-oriented. Incorporate the key phrases 'Sales increase by 80%' and 'Digital transformation' naturally where relevant to reinforce central messaging."

        ---

        Input Categories:
        **STYLE:** conversational
        **LENGTH:** maximum 300 words
        **AVOID:** technical jargon
        **EXAMPLES:** include at least 2 real-world examples
        Combined: "**ADDITIONAL CONTEXT:** Write in a conversational style, keeping your response under 300 words maximum. Avoid technical jargon throughout. Include at least 2 real-world examples to illustrate concepts and make them tangible for the audience."

        ---

        Input Categories:
        **PERSPECTIVE:** first-person
        **EMPHASIS:** customer success stories
        **TERMINOLOGY:** "game-changer", "industry-leading"
        **FORMAT:** under 5 paragraphs
        Combined: "**ADDITIONAL CONTEXT:** Write from a first-person perspective, structuring your response in under 5 paragraphs. Place special emphasis on customer success stories as the core narrative. Use the terminology 'game-changer' and 'industry-leading' to position offerings effectively."

        Now create the combined instruction integrating all categories above. Set original_context to a brief summary.
        """)
        context_formatted = json.dumps(context_items, indent=2)
        chain = enhancement_prompt | structured_llm
        logger.debug(f"Calling OpenAI for additional context enhancement with model={model}")
        result: EnhancedAdditionalContext = await chain.ainvoke({
            "context_formatted": context_formatted
        })
        log_extraction_success(
            "additional_context_enhancement",
            {
                "categories_count": len(categories_found),
                "combined_length": len(result.combined_instruction)
            }
        )
        
        if len(result.combined_instruction.strip()) < 30:
            logger.warning(
                f"Combined instruction too short: {len(result.combined_instruction)} chars"
            )
            
            if use_fallback:
                return DEFAULT_ADDITIONAL_CONTEXT_INSTRUCTION
        
        return result.combined_instruction
        
    except Exception as e:
        return await handle_openai_error(
            e,
            "additional_context_enhancement",
            DEFAULT_ADDITIONAL_CONTEXT_INSTRUCTION,
            use_fallback
        )

async def process_additional_context(
    user_input: str,
    openai_api_key: Optional[str] = openai_api_key,
    model: str = model,
    use_fallback: bool = True,
    reasoning: bool = False
) -> str:
    try:
        logger.info(
            f"Processing additional context from input",
            extra={"input_preview": user_input[:150]}
        )
        
        context_items, categories_found = await extract_additional_context(
            user_input=user_input,
            openai_api_key=openai_api_key,
            model=model,
            use_fallback=use_fallback
        )
        if reasoning:
            enhanced = await enhance_additional_context(
                context_items=context_items,
                categories_found=categories_found,
                openai_api_key=openai_api_key,
                model=model,
                use_fallback=use_fallback
            )
            
            logger.info(
                f"Additional context processing complete",
                extra={
                    "categories_count": len(categories_found),
                }
            )
        
            return enhanced
        else:
            formatted = f"**Additional Context:** {context_items}"
            return formatted
    except HTTPException:
        raise
    except Exception as e:
        return await handle_openai_error(
            e,
            "process_additional_context",
            DEFAULT_ADDITIONAL_CONTEXT_INSTRUCTION,
            use_fallback
        )
