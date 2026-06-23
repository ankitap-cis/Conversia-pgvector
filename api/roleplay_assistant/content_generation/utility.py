"""
utility.py - Shared utilities and common functions for all processing modules
"""

import logging
from typing import Optional, Any, Callable
from pydantic import BaseModel, Field
from functools import wraps
from langchain_openai import ChatOpenAI
from openai import OpenAIError, APIError, RateLimitError, APIConnectionError, LengthFinishReasonError
from fastapi import HTTPException, status
import configparser
from utils.token_consumption import *
from .cache import get_cached_llm
import asyncio

config = configparser.ConfigParser()
config.read('config.ini')

gpt_model = config['openAI_config']['model']
embed_model = config['openAI_config']['embedding_model']
OPENAI_API_KEY = config['openAI_config']['key']
logger = logging.getLogger(__name__)

class BaseExtractionResult(BaseModel):
    confidence: float = Field(
        description="Confidence score between 0.0 and 1.0",
        ge=0.0,
        le=1.0
    )

def retry_on_openai_error(max_retries: int = 3, backoff_base: float = 2.0):
    """
    Decorator to retry OpenAI API calls with exponential backoff.
    
    Handles:
    - RateLimitError (429)
    - APIConnectionError (503)
    - APIError (502)
    - LengthFinishReasonError (token limit exceeded)
    - General OpenAIError
    
    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        backoff_base: Base multiplier for exponential backoff (default: 2.0)
    """

    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                    
                except LengthFinishReasonError as e:
                    logger.error(
                        f"Token limit exceeded in {func.__name__} (attempt {attempt + 1}/{max_retries})",
                        extra={
                            "function": func.__name__,
                            "attempt": attempt + 1,
                            "error": str(e),
                            "completion_tokens": e.completion.usage.completion_tokens if hasattr(e, 'completion') else None,
                            "prompt_tokens": e.completion.usage.prompt_tokens if hasattr(e, 'completion') else None
                        }
                    )
                    raise HTTPException(
                        status_code=status.HTTP400_BAD_REQUEST,
                        detail={
                            "error": "Token limit exceeded",
                            "message": "The response was cut off due to token limits. Please reduce input size or increase max_tokens.",
                            "completion_tokens": e.completion.usage.completion_tokens if hasattr(e, 'completion') else None,
                            "prompt_tokens": e.completion.usage.prompt_tokens if hasattr(e, 'completion') else None
                        }
                    )
                
                except RateLimitError as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        backoff = backoff_base ** attempt
                        logger.warning(
                            f"Rate limit hit in {func.__name__}, retrying in {backoff}s (attempt {attempt + 1}/{max_retries})",
                            extra={"function": func.__name__, "attempt": attempt + 1, "backoff": backoff}
                        )
                        await asyncio.sleep(backoff)
                    else:
                        logger.error(
                            f"Rate limit error in {func.__name__} after {max_retries} attempts",
                            extra={"function": func.__name__, "error": str(e)}
                        )
                        raise HTTPException(
                            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="Rate limit exceeded. Please try again later."
                        )
                
                except APIConnectionError as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        backoff = backoff_base ** attempt
                        logger.warning(
                            f"Connection error in {func.__name__}, retrying in {backoff}s (attempt {attempt + 1}/{max_retries})",
                            extra={"function": func.__name__, "attempt": attempt + 1, "backoff": backoff}
                        )
                        await asyncio.sleep(backoff)
                    else:
                        logger.error(
                            f"Connection error in {func.__name__} after {max_retries} attempts",
                            extra={"function": func.__name__, "error": str(e)}
                        )
                        raise HTTPException(
                            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Unable to connect to OpenAI API. Please try again."
                        )
                
                except APIError as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        backoff = backoff_base ** attempt
                        logger.warning(
                            f"API error in {func.__name__}, retrying in {backoff}s (attempt {attempt + 1}/{max_retries})",
                            extra={"function": func.__name__, "attempt": attempt + 1, "backoff": backoff}
                        )
                        await asyncio.sleep(backoff)
                    else:
                        logger.error(
                            f"API error in {func.__name__} after {max_retries} attempts",
                            extra={"function": func.__name__, "error": str(e)}
                        )
                        raise HTTPException(
                            status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="OpenAI API error occurred"
                        )
                
                except OpenAIError as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        backoff = backoff_base ** attempt
                        logger.warning(
                            f"OpenAI error in {func.__name__}, retrying in {backoff}s (attempt {attempt + 1}/{max_retries})",
                            extra={"function": func.__name__, "attempt": attempt + 1, "backoff": backoff}
                        )
                        await asyncio.sleep(backoff)
                    else:
                        logger.error(
                            f"OpenAI error in {func.__name__} after {max_retries} attempts",
                            extra={"function": func.__name__, "error": str(e)}
                        )
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Error communicating with OpenAI"
                        )
            
            if last_exception:
                raise last_exception
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator

async def handle_openai_error(
    error: Exception,
    operation_name: str,
    fallback_value: Any,
    use_fallback: bool = True
) -> Any:
    if isinstance(error, RateLimitError):
        logger.error(
            f"Rate limit error during {operation_name}: {str(error)}",
            extra={"error": str(error), "operation": operation_name},
            exc_info=True
        )
        if use_fallback:
            logger.info(f"Rate limit error - using fallback for {operation_name}")
            return fallback_value
        else:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again later."
            )
    
    elif isinstance(error, APIConnectionError):
        logger.error(
            f"API connection error during {operation_name}: {str(error)}",
            extra={"error": str(error), "operation": operation_name},
            exc_info=True
        )
        if use_fallback:
            logger.info(f"Connection error - using fallback for {operation_name}")
            return fallback_value
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to connect to OpenAI API. Please try again."
            )
    
    elif isinstance(error, APIError):
        logger.error(
            f"API error during {operation_name}: {str(error)}",
            extra={"error": str(error), "operation": operation_name},
            exc_info=True
        )
        if use_fallback:
            logger.info(f"API error - using fallback for {operation_name}")
            return fallback_value
        else:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="OpenAI API error occurred"
            )
    
    elif isinstance(error, OpenAIError):
        logger.error(
            f"OpenAI error during {operation_name}: {str(error)}",
            extra={"error": str(error), "operation": operation_name},
            exc_info=True
        )
        if use_fallback:
            logger.info(f"OpenAI error - using fallback for {operation_name}")
            return fallback_value
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error communicating with OpenAI"
            )
    
    else:
        logger.critical(
            f"Unexpected error during {operation_name}: {str(error)}",
            extra={"error": str(error), "operation": operation_name},
            exc_info=True
        )
        if use_fallback:
            logger.info(f"Unexpected error - using fallback for {operation_name}")
            return fallback_value
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unexpected error during {operation_name}"
            )

def initialize_llm(
    model: str = gpt_model,
    temperature: float = 0.0,
    openai_api_key: str = OPENAI_API_KEY
) -> ChatOpenAI:
    return get_cached_llm(model, temperature, openai_api_key)

def validate_input(
    user_input: str,
    operation_name: str,
    use_fallback: bool = True,
    fallback_value: Any = None
) -> str:
    if not user_input or not user_input.strip():
        logger.warning(f"Empty user input for {operation_name}")
        if use_fallback:
            return fallback_value
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User input cannot be empty"
            )
    return user_input.strip()

def log_extraction_start(
    operation_name: str,
    user_input: str,
    model: str,
    extra_info: dict = None
) -> None:
    log_data = {
        "operation": operation_name,
        "input_length": len(user_input),
        "model": model,
        "input_preview": user_input[:150]
    }
    if extra_info:
        log_data.update(extra_info)
    
    logger.info(f"Starting {operation_name}", extra=log_data)

def log_extraction_success(
    operation_name: str,
    result_data: dict
) -> None:
    logger.info(
        f"{operation_name} successful",
        extra={**{"operation": operation_name}, **result_data}
    )

def validate_confidence(
    confidence: float,
    operation_name: str,
    threshold: float = 0.5
) -> None:
    """Log warning if confidence is below threshold."""
    if confidence < threshold:
        logger.warning(
            f"Low confidence in {operation_name}: {confidence}",
            extra={"confidence": confidence, "operation": operation_name}
        )