"""
audience.py - Audience extraction and instruction generation
"""
import logging
from typing import List, Optional
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

config = configparser.ConfigParser()
config.read('config.ini')
model = config['openAI_config']['model']
enhancement_temperature = float(config['openAI_config'].get('enhancement_temperature', 0.3))
openai_api_key = config['openAI_config'].get('key', None)

logger = logging.getLogger(__name__)

class DemographicDetail(BaseModel):
    model_config = ConfigDict(extra='forbid')
    
    key: str = Field(description="Detail key (e.g., 'age_range', 'platform', 'interest')")
    value: str = Field(description="Detail value")


class AudienceExtraction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    
    audiences: List[str] = Field(
        description="List of distinct audience segments identified"
    )
    
    demographic_details: List[DemographicDetail] = Field(
        description="List of demographic or psychographic details"
    )
    
    confidence: float = Field(
        description="Confidence score between 0.0 and 1.0",
        ge=0.0,
        le=1.0
    )

DEFAULT_AUDIENCE_INSTRUCTION = """
Your response should be clear, accessible, and appropriate for a general audience. Use language that is professional yet approachable, avoiding unnecessary jargon. Structure content for easy comprehension and maintain an inclusive tone that respects diverse backgrounds and perspectives.
"""

async def extract_primary_audience(
    user_input: str,
    openai_api_key: Optional[str] = openai_api_key,
    model: str = model,
    temperature: float = 0.0,
    use_fallback: bool = True
) -> tuple[List[str], List[DemographicDetail]]:
    try:
        log_extraction_start("audience_extraction", user_input, model)
        validated = validate_input(
            user_input,
            "audience_extraction",
            use_fallback,
            (["General audience"], [])
        )
        
        if isinstance(validated, tuple) and use_fallback:
            return validated
        llm = initialize_llm(model, temperature, openai_api_key)
        structured_llm = llm.with_structured_output(
            AudienceExtraction,
            method="json_schema"
        )
        extraction_prompt = PromptTemplate.from_template("""
        You are an expert at analyzing target audience descriptions and extracting distinct audience segments.

        Your task is to identify all relevant audience segments from the user's description **KEEP the profession intact if mentioned**, including:
        - Age groups (with specific ranges if mentioned)
        - Demographics (gender, location, profession, education level)
        - Psychographics (interests, values, lifestyle, behaviors)
        - Platform usage (social media, professional networks)
        - Experience level (beginner, intermediate, expert)
        - Role or position (decision-makers, end-users, influencers)

        Guidelines:
        1. Extract precise audience segments, match keywords if mentioned.
        2. Be specific with age ranges (e.g., "Teenagers (16-19)" not just "Teenagers")
        3. Extract demographic details as key-value pairs (e.g., {{"key": "age_range", "value": "16-19"}})
        4. Use clear, concise labels for each segment

        User Input: {input}

        Example:

        Input: "Instagram using teenagers around 16-19 who are into fashion"
        Output:
        {{
        "audiences": ["Teenagers (16-19)", "Fashion enthusiasts", "Instagram users"],
        "demographic_details": [
            {{"key": "age_range", "value": "16-19"}},
            {{"key": "platform", "value": "Instagram"}},
            {{"key": "interest", "value": "fashion"}}
        ],
        "confidence": 0.92
        }}

        Input: "C-level executives in tech industry, 35-50 years old, based in Bangalore"
        Output:
        {{
        "audiences": ["C-level executives", "Tech industry professionals", "Mid-career professionals (35-50)"],
        "demographic_details": [
            {{"key": "position", "value": "C-level executive"}},
            {{"key": "industry", "value": "Technology"}},
            {{"key": "age_range", "value": "35-50"}},
            {{"key": "location", "value": "Bangalore"}}
        ],
        "confidence": 0.95
        }}
        
        Input: "Doctors"
        Output:
        {{
        "audiences": ["Doctors"],
        "demographic_details": [
            {{"key": "position", "value": "Doctor"}},
            {{"key": "industry", "value": "Healthcare"}},
            {{"key": "age_range", "value": "30-60"}},
            {{"key": "location", "value": "Various"}}
        ],
        "confidence": 0.95
        }}

        Now extract audience segments from the input above.
        """)
        
        chain = extraction_prompt | structured_llm
        
        logger.debug(f"Calling OpenAI for audience extraction with model={model}")
        result: AudienceExtraction = await chain.ainvoke({"input": user_input})
        
        log_extraction_success(
            "audience_extraction",
            {
                "audiences": result.audiences,
                "demographic_count": len(result.demographic_details),
                "confidence": result.confidence
            }
        )
        
        return result.audiences, result.demographic_details
        
    except Exception as e:
        return await handle_openai_error(
            e,
            "audience_extraction",
            (["General audience"], []),
            use_fallback
        )


async def generate_audience_instruction(
    audiences: List[str],
    demographic_details: List[DemographicDetail],
    openai_api_key: Optional[str] = openai_api_key,
    model: str = model,
    temperature: float = enhancement_temperature,
    use_fallback: bool = True
) -> str:
    try:
        logger.info(
            f"Generating audience instruction for: {', '.join(audiences)}",
            extra={"audiences": audiences, "details_count": len(demographic_details)}
        )
        
        if not audiences or len(audiences) == 0:
            logger.warning("Empty audiences list for instruction generation")
            if use_fallback:
                return DEFAULT_AUDIENCE_INSTRUCTION
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Audiences list cannot be empty"
                )
        
        llm = initialize_llm(model, temperature, openai_api_key)
        
        instruction_prompt = PromptTemplate.from_template("""
        You are an expert prompt engineer specializing in audience-tailored communication.

        Your task is to create a clear, actionable system prompt instruction that guides an LLM to communicate effectively with the specified target audience.

        Target Audience Segments: {audiences}
        Demographic Details: {demographic_details}

        Guidelines for creating audience-specific instructions:
        1. Specify appropriate tone, language complexity, and vocabulary level
        2. Reference relevant context, examples, or cultural touchpoints for this audience
        3. Address specific needs, concerns, or interests of this demographic
        4. Specify content structure and format preferences
        5. Note any sensitivities or considerations for this audience
        6. Keep it concise (3-5 sentences, 75-125 words)

        Examples:

        - Teenagers (16-19), Fashion enthusiasts:
        "Your response must be tailored for fashion-conscious teenagers aged 16-19. Use contemporary, engaging language with current fashion terminology and trending references they'll recognize. Keep paragraphs short and scannable, incorporate visual descriptions, and maintain an enthusiastic but authentic tone. Reference social media platforms and influencer culture naturally, and focus on style, self-expression, and affordability."

        - C-level executives, Tech industry:
        "Your response must address C-level technology executives. Use professional, strategic language focused on business outcomes, ROI, and competitive advantage. Be concise and data-driven, leading with key insights and recommendations. Reference industry trends, market dynamics, and innovation imperatives. Respect their time by prioritizing high-impact information and actionable takeaways."

        Now create an audience-specific instruction for the target audience above.

        Output ONLY the instruction text, nothing else.
        """)
        
        details_text = "\n".join([
            f"- {detail.key}: {detail.value}"
            for detail in demographic_details
        ]) if demographic_details else "None specified"
        
        chain = instruction_prompt | llm
        
        result = await chain.ainvoke({
            "audiences": ", ".join(audiences),
            "demographic_details": details_text
        })
        
        instruction = result.content.strip()
        
        if len(instruction) < 50:
            logger.warning(
                f"Generated instruction too short ({len(instruction)} chars), using default",
                extra={"instruction": instruction}
            )
            if use_fallback:
                return DEFAULT_AUDIENCE_INSTRUCTION
        
        logger.info(
            f"Audience instruction generated successfully",
            extra={
                "audiences_count": len(audiences)
            }
        )
        
        return instruction
        
    except Exception as e:
        return await handle_openai_error(
            e,
            "audience_instruction_generation",
            DEFAULT_AUDIENCE_INSTRUCTION,
            use_fallback
        )


async def process_primary_audience(
    user_input: str,
    openai_api_key: Optional[str] = openai_api_key,
    model: str = model,
    use_fallback: bool = True,
    reasoning: bool = False
) -> str:
    try:
        logger.info(
            f"Processing primary audience from input",
            extra={"input_preview": user_input[:150]}
        )
        
        audiences, demographic_details = await extract_primary_audience(
            user_input=user_input,
            openai_api_key=openai_api_key,
            model=model,
            use_fallback=use_fallback
        )
        if reasoning:
            instruction = await generate_audience_instruction(
                audiences=audiences,
                demographic_details=demographic_details,
                openai_api_key=openai_api_key,
                model=model,
                use_fallback=use_fallback
            )
            
            logger.info(
                f"Primary audience processing complete",
                extra={
                    "audiences_count": len(audiences),
                    "demographics_count": len(demographic_details)
                }
            )
        
            return instruction
        else:
            formatted = f"**Target Audience:** {', '.join(audiences)}\n**Demographics:** {demographic_details}"
            return formatted
        
    except HTTPException:
        raise
    except Exception as e:
        return await handle_openai_error(
            e,
            "process_primary_audience",
            DEFAULT_AUDIENCE_INSTRUCTION,
            use_fallback
        )
