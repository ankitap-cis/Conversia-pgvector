"""
admin.py - Admin/Organization prompt validation with proper fallbacks
"""

import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError, OperationalError
from fastapi import HTTPException, status


logger = logging.getLogger(__name__)


DEFAULT_SYSTEM_PROMPT = """
You are a helpful AI assistant. Provide clear, accurate, and professional responses to user queries.

Follow these guidelines:
- Be concise and actionable
- Maintain a professional tone
- Provide accurate information
- If unsure, acknowledge limitations
"""


async def get_admin_prompt(
    use_fallback: bool = True,
    system_prompt: Optional[str] = None
) -> str:
    try:
        if system_prompt is None:
            if use_fallback:
                return DEFAULT_SYSTEM_PROMPT
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="System prompt is required but not provided"
                )
        
        if not isinstance(system_prompt, str):
            logger.error(
                f"Invalid system prompt type for org_admin_id={org_admin_id}: {type(system_prompt)}",
                extra={
                    "org_admin_id": org_admin_id,
                    "prompt_type": type(system_prompt).__name__
                }
            )
            
            if use_fallback:
                logger.info(
                    f"Using default fallback prompt for org_admin_id={org_admin_id} (invalid type)",
                    extra={"org_admin_id": org_admin_id}
                )
                return DEFAULT_SYSTEM_PROMPT
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"System prompt must be a string, got {type(system_prompt).__name__}"
                )
        
        cleaned_prompt = system_prompt.strip()
        if not cleaned_prompt:
            
            if use_fallback:
                return DEFAULT_SYSTEM_PROMPT
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="System prompt cannot be empty or contain only whitespace"
                )
        
        if len(cleaned_prompt) > 50000: 
            if use_fallback:
                return DEFAULT_SYSTEM_PROMPT
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"System prompt too long: {len(cleaned_prompt)} chars (max 50000)"
                )
        return cleaned_prompt
        
    except HTTPException:
        raise
        
    except Exception as e:
        if use_fallback:
            return DEFAULT_SYSTEM_PROMPT
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unexpected error occurred while processing system prompt"
            )