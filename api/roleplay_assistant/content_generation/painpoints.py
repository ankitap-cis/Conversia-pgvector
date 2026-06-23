"""
painpoints.py - Motivation/Pain points extraction and enhancement
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

config = configparser.ConfigParser()
config.read('config.ini')

openai_api_key = config['openAI_config'].get('key', None)
model = config['openAI_config'].get('model', 'gpt-4o-mini')
enhancement_temperature = float(config['openAI_config'].get('enhancement_temperature', '0.2'))

logger = logging.getLogger(__name__)

class MotivationPointsExtraction(BaseModel):
    points: List[str] = Field(
        description="List of distinct motivation points or pain points"
    )
    
    confidence: float = Field(
        description="Confidence score between 0.0 and 1.0",
        ge=0.0,
        le=1.0
    )

class EnhancedMotivationPoints(BaseModel):
    original_points: List[str] = Field(
        description="Original motivation/pain points"
    )
    
    combined_instruction: str = Field(
        description="Combined instruction integrating all points"
    )

DEFAULT_MOTIVATION_INSTRUCTION = """
Your response should be goal-oriented and results-focused. Prioritize clarity, actionability, and alignment with the user's objectives. Ensure the content drives value and supports the intended outcomes effectively.
"""

async def extract_motivation_points(
    user_input: str,
    openai_api_key: Optional[str] = openai_api_key,
    model: str = model,
    temperature: float = 0.0,
    use_fallback: bool = True
) -> List[str]:
    try:
        log_extraction_start("motivation_extraction", user_input, model)
        
        validated = validate_input(
            user_input,
            "motivation_extraction",
            use_fallback,
            ["General goals"]
        )
        
        if isinstance(validated, list) and use_fallback:
            return validated
        
        llm = initialize_llm(model, temperature, openai_api_key)
        structured_llm = llm.with_structured_output(
            MotivationPointsExtraction,
            method="json_schema"
        )
        
        extraction_prompt = PromptTemplate.from_template("""
        You are an expert at analyzing and structuring motivation points, goals, and pain points from user input.

        Your task is to extract all distinct points from the user's input. Points may be:
        - Goals or objectives the user wants to achieve
        - Challenges or pain points the user wants to address
        - Motivations driving the user's request

        Guidelines:
        1. Extract each distinct point as a separate item
        2. Clean up formatting (remove numbering, bullets, extra whitespace)
        3. Make each point concise but complete (one clear sentence)
        4. Preserve the original intent and meaning
        5. Focus on actionable goals or addressable pain points

        User Input: {input}

        Examples:

        Input: "1. we are trying to achieve boost in sales 2. we are trying to expand influence in teenagers"
        Points: ["Achieve a boost in sales", "Expand influence among teenagers"]

        Input: "Our main challenges are: low engagement rates, difficulty reaching younger demographics, and unclear messaging"
        Points: ["Low engagement rates", "Difficulty reaching younger demographics", "Unclear messaging"]

        Input: "We want to increase brand awareness while solving the problem of high customer churn"
        Points: ["Increase brand awareness", "Reduce high customer churn"]

        Now extract and structure the points from the input above.
        """)
        
        chain = extraction_prompt | structured_llm
        
        logger.debug(f"Calling OpenAI for motivation extraction with model={model}")
        result: MotivationPointsExtraction = await chain.ainvoke({"input": user_input})
        
        log_extraction_success(
            "motivation_extraction",
            {
                "points_count": len(result.points),
                "confidence": result.confidence
            }
        )
        
        return result.points
        
    except Exception as e:
        return await handle_openai_error(
            e,
            "motivation_extraction",
            ["General goals"],
            use_fallback
        )

async def enhance_motivation_points(
    motivation_points: List[str],
    openai_api_key: Optional[str] = openai_api_key,
    model: str = model,
    temperature: float = enhancement_temperature,
    use_fallback: bool = True
) -> str:
    try:
        logger.info(
            f"Enhancing {len(motivation_points)} motivation points",
            extra={"points_count": len(motivation_points)}
        )
        
        if not motivation_points or len(motivation_points) == 0:
            logger.warning("Empty motivation points list for enhancement")
            if use_fallback:
                return DEFAULT_MOTIVATION_INSTRUCTION
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Motivation points list cannot be empty"
                )
        
        llm = initialize_llm(model, temperature, openai_api_key)
        structured_llm = llm.with_structured_output(
            EnhancedMotivationPoints,
            method="json_schema"
        )
        
        enhancement_prompt = PromptTemplate.from_template("""
        You are an expert prompt engineer specializing in transforming business goals, motivations, and pain points into actionable system prompt instructions.

        Your task is to take each motivation/pain point and transform it into a clear, directive system prompt instruction that guides an LLM to prioritize and address these concerns in its generated content.

        Motivation/Pain Points:
        {points_list}

        Guidelines for enhancement:

        1. For GOALS/MOTIVATIONS: Transform into positive, action-oriented directives
        - Original: "Boost sales"
        - Enhanced: "Your response must focus on driving sales outcomes. Emphasize value propositions, benefits, and calls-to-action that encourage purchasing decisions."

        2. For PAIN POINTS: Transform into solution-focused directives
        - Original: "Low engagement rates"
        - Enhanced: "Your response must address engagement challenges. Use compelling hooks, interactive elements, and content structures that maintain reader attention and encourage participation."

        3. Create a COMBINED instruction that integrates all points cohesively
        - 3-5 sentences total
        - Prioritize the most important points
        - Create a unified narrative that addresses all concerns
        - Use transitional language to connect different priorities

        Examples:

        Input Points: ["Boost sales", "Expand influence in teenagers"]
        Combined: "Your response must drive sales growth while specifically appealing to teenage audiences. Employ persuasive techniques such as social proof and compelling benefits, while maintaining an authentic, contemporary tone that resonates with 13-19 year olds. Balance commercial objectives with age-appropriate messaging that feels genuine rather than overtly promotional."

        Input Points: ["Low customer retention", "Unclear value proposition", "Limited brand awareness"]
        Combined: "Your response must simultaneously address retention, value clarity, and brand awareness. Clearly articulate the unique value proposition with specific, measurable benefits while building a memorable brand identity. Focus on long-term customer relationships by demonstrating ongoing commitment and distinctive positioning that sets the brand apart from alternatives."

        Now enhance the motivation/pain points above. Set original_points to the input list.
        """)
        
        points_formatted = "\n".join([f"{i+1}. {point}" for i, point in enumerate(motivation_points)])
        
        chain = enhancement_prompt | structured_llm
        
        logger.debug(f"Calling OpenAI for motivation enhancement with model={model}")
        result: EnhancedMotivationPoints = await chain.ainvoke({
            "points_list": points_formatted
        })
        
        if not result.original_points:
            result.original_points = motivation_points
        
        log_extraction_success(
            "motivation_enhancement",
            {
                "original_count": len(motivation_points),
                "combined_length": len(result.combined_instruction)
            }
        )
        
        if len(result.combined_instruction.strip()) < 30:
            logger.warning(
                f"Combined instruction too short: {len(result.combined_instruction)} chars"
            )
            
            if use_fallback:
                return DEFAULT_MOTIVATION_INSTRUCTION
        
        return result.combined_instruction
        
    except Exception as e:
        return await handle_openai_error(
            e,
            "motivation_enhancement",
            DEFAULT_MOTIVATION_INSTRUCTION,
            use_fallback
        )

async def process_motivation_points(
    user_input: str,
    openai_api_key: Optional[str] = openai_api_key,
    model: str = model,
    use_fallback: bool = True,
    reasoning: bool = False
) -> str:
    try:
        logger.info(
            f"Processing motivation points from input",
            extra={"input_preview": user_input[:150]}
        )
        
        points = await extract_motivation_points(
            user_input=user_input,
            openai_api_key=openai_api_key,
            model=model,
            use_fallback=use_fallback
        )
        
        if reasoning:
            enhanced = await enhance_motivation_points(
                motivation_points=points,
                openai_api_key=openai_api_key,
                model=model,
                use_fallback=use_fallback
            )
            
            logger.info(
                f"Motivation processing complete",
                extra={"points_count": len(points)}
            )
            
            return enhanced
        else:
            formatted = f"**Key Goals:**\n" + "\n".join([f"- {point}" for point in points])
            return formatted
        
    except HTTPException:
        raise
    except Exception as e:
        return await handle_openai_error(
            e,
            "process_motivation_points",
            DEFAULT_MOTIVATION_INSTRUCTION,
            use_fallback
        )
