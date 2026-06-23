"""
evidence.py - Key evidence extraction and enhancement (quotes, data, statistics, case studies)
"""

import logging
from typing import Optional, List, Dict, Any
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
model = config['openAI_config'].get('model', 'gpt-4o-mini')
openai_api_key = config['openAI_config'].get('key', None)
enhancement_temperature = config['openAI_config'].getfloat('enhancement_temperature', 0.3)

logger = logging.getLogger(__name__)


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    
    type: str = Field(description="Evidence type (quote, statistic, data, etc.)")
    content: str = Field(description="Evidence content")
    source: str = Field(default="", description="Source or attribution")

class KeyEvidenceExtraction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    
    evidence_items: List[EvidenceItem] = Field(
        description="List of evidence items with type and content"
    )
    
    evidence_types: List[str] = Field(
        description="List of evidence types found (quote, statistic, data, analogy, case_study, etc.)"
    )
    
    priority_level: str = Field(
        description="Priority level: must_cite, high_priority, or reference_when_relevant"
    )
    
    confidence: float = Field(
        description="Confidence score between 0.0 and 1.0",
        ge=0.0,
        le=1.0
    )

class EnhancedKeyEvidence(BaseModel):
    model_config = ConfigDict(extra='forbid')
    
    original_evidence: str = Field(description="Original evidence input")
    enhanced_instruction: str = Field(
        description="Enhanced instruction for using key evidence"
    )

DEFAULT_KEY_EVIDENCE_INSTRUCTION = """
**KEY EVIDENCE:** Incorporate the following evidence, data points, or supporting materials to strengthen your response. Reference this evidence when it directly supports your arguments or adds credibility. Cite accurately and attribute sources appropriately.
"""


async def extract_key_evidence(
    user_input: str,
    openai_api_key: Optional[str] = openai_api_key,
    model: str = model,
    temperature: float = 0.0,
    use_fallback: bool = True
) -> tuple[List[Dict[str, str]], List[str], str]:
    try:
        log_extraction_start("key_evidence_extraction", user_input, model)
        
        validated = validate_input(
            user_input,
            "key_evidence_extraction",
            use_fallback,
            ([{"type": "general", "content": "General supporting evidence", "source": ""}], ["general"], "reference_when_relevant")
        )
        
        if isinstance(validated, tuple) and use_fallback:
            return validated
        
        llm = initialize_llm(model, temperature, openai_api_key)
        structured_llm = llm.with_structured_output(
            KeyEvidenceExtraction,
            method="json_schema"
        )
        
        extraction_prompt = PromptTemplate.from_template("""
        You are an expert at analyzing and categorizing evidence types including quotes, data, statistics, analogies, case studies, and research findings.

        Your task is to extract and structure ALL evidence items from the user's input. Evidence types include:
        - **quote**: Direct quotations from people (include source/attribution if provided)
        - **statistic**: Numerical data, percentages, metrics
        - **data**: Research findings, survey results, data points
        - **analogy**: Comparisons, metaphors used to explain concepts
        - **case_study**: Examples, success stories, real-world applications
        - **research**: Academic or industry research references
        - **expert_opinion**: Professional insights or expert perspectives
        - **testimonial**: Customer or user testimonials
        - **fact**: Verified factual statements

        Guidelines:
        1. Extract EACH distinct piece of evidence as a separate item
        2. Categorize each by type
        3. Preserve exact wording for quotes (verbatim)
        4. Include source/attribution when provided (use empty string "" if not provided)
        5. Extract specific numbers and percentages accurately
        6. Identify all evidence types present
        7. Determine priority level:
        - "must_cite": Critical evidence that MUST be cited (direct quotes, key statistics)
        - "high_priority": Important evidence that should be prominently featured
        - "reference_when_relevant": Supporting evidence to use when applicable

        User Input: {input}

        Examples:

        Input: '"Innovation distinguishes between a leader and a follower" - Steve Jobs. 87% of consumers trust peer recommendations over advertising.'
        Output:
        {{
        "evidence_items": [
            {{"type": "quote", "content": "Innovation distinguishes between a leader and a follower", "source": "Steve Jobs"}},
            {{"type": "statistic", "content": "87% of consumers trust peer recommendations over advertising", "source": ""}}
        ],
        "evidence_types": ["quote", "statistic"],
        "priority_level": "must_cite",
        "confidence": 0.95
        }}

        Input: "Think of AI like a calculator for language - it processes inputs and produces outputs, but the quality depends on what you put in. Studies show 64% adoption rate in enterprises."
        Output:
        {{
        "evidence_items": [
            {{"type": "analogy", "content": "AI is like a calculator for language - it processes inputs and produces outputs, but the quality depends on what you put in", "source": ""}},
            {{"type": "statistic", "content": "64% adoption rate of AI in enterprises", "source": "studies"}}
        ],
        "evidence_types": ["analogy", "statistic"],
        "priority_level": "high_priority",
        "confidence": 0.88
        }}

        Input: "Company X increased revenue by 150% after implementing our solution. Dr. Smith from MIT says this approach is 'groundbreaking for the industry'."
        Output:
        {{
        "evidence_items": [
            {{"type": "case_study", "content": "Company X increased revenue by 150% after implementing the solution", "source": "Company X"}},
            {{"type": "expert_opinion", "content": "This approach is groundbreaking for the industry", "source": "Dr. Smith from MIT"}}
        ],
        "evidence_types": ["case_study", "expert_opinion"],
        "priority_level": "must_cite",
        "confidence": 0.92
        }}

        Now extract and categorize all evidence from the input above.
        """)
        
        chain = extraction_prompt | structured_llm
        
        logger.debug(f"Calling OpenAI for key evidence extraction with model={model}")
        result: KeyEvidenceExtraction = await chain.ainvoke({"input": user_input})
        
        evidence_items_dicts = [
            {
                "type": item.type,
                "content": item.content,
                "source": item.source
            }
            for item in result.evidence_items
        ]
        
        log_extraction_success(
            "key_evidence_extraction",
            {
                "evidence_count": len(evidence_items_dicts),
                "evidence_types": result.evidence_types,
                "priority_level": result.priority_level,
                "confidence": result.confidence
            }
        )
        
        return evidence_items_dicts, result.evidence_types, result.priority_level
        
    except Exception as e:
        return await handle_openai_error(
            e,
            "key_evidence_extraction",
            ([{"type": "general", "content": "General supporting evidence", "source": ""}], ["general"], "reference_when_relevant"),
            use_fallback
        )


async def enhance_key_evidence(
    evidence_items: List[Dict[str, str]],
    evidence_types: List[str],
    priority_level: str,
    openai_api_key: Optional[str] = openai_api_key,
    model: str = model,
    temperature: float = enhancement_temperature,
    use_fallback: bool = True
) -> str:
    try:
        logger.info(
            f"Enhancing key evidence with {len(evidence_items)} items",
            extra={
                "evidence_count": len(evidence_items),
                "evidence_types": evidence_types,
                "priority_level": priority_level
            }
        )
        
        if not evidence_items or len(evidence_items) == 0:
            logger.warning("Empty evidence items list for enhancement")
            if use_fallback:
                return DEFAULT_KEY_EVIDENCE_INSTRUCTION
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Evidence items list cannot be empty"
                )
        
        llm = initialize_llm(model, temperature, openai_api_key)
        structured_llm = llm.with_structured_output(
            EnhancedKeyEvidence,
            method="json_schema"
        )
        
        enhancement_prompt = PromptTemplate.from_template("""
        You are an expert prompt engineer specializing in transforming evidence, quotes, and data into actionable citation and integration instructions.

        Your task is to create a clear instruction that tells an LLM how to effectively use the provided evidence in its response.

        Priority Level: {priority_level}
        Evidence Items:
        {evidence_list}

        Guidelines for enhancement:

        1. For **must_cite** priority:
        - Use strong directive language ("MUST cite", "is REQUIRED")
        - Emphasize accuracy and proper attribution
        - Specify that quotes must be verbatim
        - Example: "**KEY EVIDENCE - REQUIRED CITATIONS:** Your response MUST directly cite the following evidence with proper attribution. Quote Steve Jobs verbatim: 'Innovation distinguishes between a leader and a follower.' Reference the statistic that 87% of consumers trust peer recommendations. These citations are mandatory for credibility."

        2. For **high_priority**:
        - Use "should" language with emphasis
        - Highlight strategic value of evidence
        - Example: "**KEY EVIDENCE:** Your response should prominently feature the following evidence to build credibility and persuasiveness. Leverage the analogy of AI as a calculator for language to make concepts accessible. Reference the 64% enterprise adoption rate to demonstrate market validation."

        3. For **reference_when_relevant**:
        - Use "when applicable" framing
        - Give flexibility in usage
        - Example: "**SUPPORTING EVIDENCE:** Use the following evidence when it naturally supports your arguments. Reference industry research and user feedback where relevant to add depth and credibility, but prioritize core messaging over forcing these references."

        4. Keep it 2-4 sentences (50-100 words)
        5. Specify HOW to integrate (quote verbatim, paraphrase, reference indirectly)
        6. For quotes: emphasize attribution and exact wording
        7. For statistics: emphasize accuracy of numbers
        8. For case studies: emphasize concrete results

        Now create the enhanced instruction for the evidence above. Set original_evidence to a brief summary.
        """)
        
        evidence_formatted = "\n".join([
            f"{i+1}. [{item.get('type', 'unknown')}] {item.get('content', '')}" +
            (f" - {item.get('source', '')}" if item.get('source') else "")
            for i, item in enumerate(evidence_items)
        ])
        
        chain = enhancement_prompt | structured_llm
        
        logger.debug(f"Calling OpenAI for key evidence enhancement with model={model}")
        result: EnhancedKeyEvidence = await chain.ainvoke({
            "priority_level": priority_level,
            "evidence_list": evidence_formatted
        })
        
        log_extraction_success(
            "key_evidence_enhancement",
            {
                "evidence_count": len(evidence_items),
                "instruction_length": len(result.enhanced_instruction)
            }
        )
        
        if len(result.enhanced_instruction.strip()) < 30:
            logger.warning(
                f"Enhanced instruction too short: {len(result.enhanced_instruction)} chars"
            )
            
            if use_fallback:
                return DEFAULT_KEY_EVIDENCE_INSTRUCTION
        
        return result.enhanced_instruction
        
    except Exception as e:
        return await handle_openai_error(
            e,
            "key_evidence_enhancement",
            DEFAULT_KEY_EVIDENCE_INSTRUCTION,
            use_fallback
        )


async def process_key_evidence(
    user_input: str,
    openai_api_key: Optional[str] = openai_api_key,
    model: str = model,
    use_fallback: bool = True,
    reasoning: bool = False
) -> str:
    try:
        logger.info(
            f"Processing key evidence from input",
            extra={"input_preview": user_input[:150]}
        )
        
        evidence_items, evidence_types, priority_level = await extract_key_evidence(
            user_input=user_input,
            openai_api_key=openai_api_key,
            model=model,
            use_fallback=use_fallback
        )
        if reasoning:
            enhanced = await enhance_key_evidence(
                evidence_items=evidence_items,
                evidence_types=evidence_types,
                priority_level=priority_level,
                openai_api_key=openai_api_key,
                model=model,
                use_fallback=use_fallback
            )
            
            logger.info(
                f"Key evidence processing complete",
                extra={
                    "evidence_types": evidence_types,
                    "priority_level": priority_level,
                }
            )
            
            return enhanced
        else:
            formatted = f"**Key Evidence:**\n" + "\n".join([f"- {evidence}" for evidence in evidence_items])
            return formatted
        
    except HTTPException:
        raise
    except Exception as e:
        return await handle_openai_error(
            e,
            "process_key_evidence",
            DEFAULT_KEY_EVIDENCE_INSTRUCTION,
            use_fallback
        )
