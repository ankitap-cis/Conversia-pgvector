"""
intent.py - Intent/Purpose extraction and prompt generation
"""

import logging
from typing import List, Optional
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
logger = logging.getLogger(__name__)
config = configparser.ConfigParser()
config.read('config.ini')

openai_api_key = config['openAI_config'].get('key', None)
model = config['openAI_config'].get('model', 'gpt-4o-mini')
enhancement_temperature = float(config['openAI_config'].get('enhancement_temperature', '0.2'))

class IntentExtraction(BaseModel):
    intents: List[str] = Field(
        description="List of intents expressed in user's input"
    )
    primary_intent: str = Field(
        description="The primary/dominant intent"
    )
    confidence: float = Field(
        description="Confidence score between 0.0 and 1.0",
        ge=0.0,
        le=1.0
    )


INTENT_PROMPTS = {
    "informative": "Your response must have an informative intent. Focus on providing clear, accurate, and well-structured factual information. Prioritize clarity and comprehensiveness without attempting to persuade or inspire. Present facts objectively and explain concepts thoroughly.",
    
    "persuasive": "Your response must have a persuasive intent. Present compelling arguments and supporting evidence that guide the reader toward a specific position or action. Use rhetorical techniques, data, and logical reasoning to build a convincing case while maintaining credibility and respecting the audience's intelligence.",
    
    "educational": "Your response must have an educational intent. Structure content to facilitate learning and understanding. Use progressive difficulty, provide examples, check for comprehension points, and encourage active engagement. Break down complex concepts into digestible parts and reinforce key takeaways.",
    
    "train": "Your response must have a training intent. Provide step-by-step guidance, practical exercises, and hands-on examples. Focus on skill development and application. Include checkpoints for understanding, progressive challenges, and real-world scenarios that allow practice and mastery.",
    
    "reassurance": "Your response must have a reassuring intent. Acknowledge concerns empathetically and provide grounded, realistic comfort. Use calm, supportive language that validates feelings while offering practical solutions or perspectives. Build confidence without making unrealistic promises.",
    
    "inspire": "Your response must have an inspiring intent. Use motivating, forward-looking language that encourages action, creativity, or personal growth. Share compelling visions and examples while remaining authentic and concrete. Avoid empty platitudes; focus on actionable inspiration that resonates emotionally and practically.",
    
    "analytical": "Your response must have an analytical intent. Provide deep, critical examination of the topic. Break down components, identify patterns, evaluate relationships, and draw insightful conclusions. Use logical reasoning, data analysis, and systematic thinking to uncover meaningful insights.",
    
    "directive": "Your response must have a directive intent. Provide clear, actionable instructions and guidance. Use imperative language, specify exact steps, and eliminate ambiguity. Focus on what needs to be done, when, and how, ensuring the reader can execute immediately.",
    
    "collaborative": "Your response must have a collaborative intent. Foster dialogue, invite input, and build on shared ideas. Use inclusive language, acknowledge multiple perspectives, and create space for co-creation. Frame content as part of an ongoing conversation rather than a final answer.",
    
    "entertaining": "Your response must have an entertaining intent. Engage the audience with compelling storytelling, humor, or creative presentation. Maintain interest through pacing, variety, and unexpected elements while still delivering substantive value. Balance enjoyment with purpose.",
    
    "comparative": "Your response must have a comparative intent. Systematically evaluate and contrast multiple options, approaches, or perspectives. Highlight similarities, differences, advantages, and trade-offs. Provide balanced analysis that helps readers make informed decisions.",
    
    "problem_solving": "Your response must have a problem-solving intent. Identify the core issue, analyze root causes, and present actionable solutions. Use structured problem-solving frameworks, consider multiple approaches, and prioritize practical, implementable fixes.",
    
    "exploratory": "Your response must have an exploratory intent. Investigate possibilities, raise thought-provoking questions, and consider multiple angles without rushing to conclusions. Encourage curiosity and open-minded inquiry while mapping out the landscape of ideas.",
    
    "other": "Your response should adapt its intent to best match the user's needs. Use a balanced, helpful tone that combines clarity, accuracy, and engagement. Remain flexible and context-aware, adjusting your approach based on the specific requirements of the query."
}

DEFAULT_INTENT = "informative"
DEFAULT_INTENT_PROMPT = INTENT_PROMPTS[DEFAULT_INTENT]


async def extract_intent(
    user_input: str,
    openai_api_key: Optional[str] = openai_api_key,
    model: str = model,
    temperature: float = 0.0,
    use_fallback: bool = True
) -> str:
    try:
        log_extraction_start("intent_extraction", user_input, model)

        validated = validate_input(
            user_input,
            "intent_extraction",
            use_fallback,
            DEFAULT_INTENT
        )
        if validated != user_input.strip() and use_fallback:
            return validated

        llm = initialize_llm(model, temperature, openai_api_key)
        structured_llm = llm.with_structured_output(
            IntentExtraction,
            method="json_schema"
        )

        extraction_prompt = PromptTemplate.from_template("""
        You are an expert at analyzing communication intent. Given the user's input, identify all intents or purposes expressed.

        Common intent categories include:

        - informative: sharing facts, explaining concepts
        - persuasive: convincing, arguing for a position
        - educational: teaching, facilitating learning
        - train: skill development, hands-on instruction
        - reassurance: comforting, addressing concerns
        - inspire: motivating, encouraging action
        - analytical: examining, breaking down concepts
        - directive: giving instructions, commanding action
        - collaborative: building together, inviting dialogue
        - entertaining: engaging, amusing
        - comparative: evaluating options, contrasting
        - problem_solving: addressing issues, finding solutions
        - exploratory: investigating possibilities, questioning
        - other: any intent not fitting above categories

        Analyze this input and extract:

        1. All intents present (can be multiple)
        2. The PRIMARY/dominant intent
        3. Your confidence in this analysis (0.0 to 1.0)

        User Input: {input}

        Be specific and accurate. If the intent is clear, use specific categories. If mixed or unclear, list multiple intents.
        """)

        chain = extraction_prompt | structured_llm

        logger.debug(f"Calling OpenAI for intent extraction with model={model}")
        result: IntentExtraction = await chain.ainvoke({"input": user_input})

        normalized_primary = result.primary_intent.lower().strip().replace(" ", "_").replace("-", "_")

        log_extraction_success(
            "intent_extraction",
            {
                "intents": result.intents,
                "primary_intent": normalized_primary,
                "confidence": result.confidence
            }
        )

        return normalized_primary

    except Exception as e:
        return await handle_openai_error(
            e,
            "intent_extraction",
            DEFAULT_INTENT,
            use_fallback
        )


async def generate_intent_prompt(
    user_input: str,
    openai_api_key: Optional[str] = openai_api_key,
    model: str = model,
    use_fallback: bool = True
) -> str:
    try:
        primary_intent = await extract_intent(
            user_input=user_input,
            openai_api_key=openai_api_key,
            model=model,
            use_fallback=use_fallback
        )

        intent_prompt = INTENT_PROMPTS.get(primary_intent, INTENT_PROMPTS["other"])

        logger.info(
            f"Generated intent prompt for primary_intent='{primary_intent}'",
            extra={
                "primary_intent": primary_intent,
            }
        )

        return intent_prompt

    except HTTPException:
        raise
    except Exception as e:
        return await handle_openai_error(
            e,
            "generate_intent_prompt",
            DEFAULT_INTENT_PROMPT,
            use_fallback
        )