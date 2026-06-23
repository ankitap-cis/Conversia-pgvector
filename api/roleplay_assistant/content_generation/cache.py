"""
cache.py - Centralized caching for content generation module
"""

import logging
from typing import Optional, Dict
from langchain_openai import ChatOpenAI
from functools import lru_cache
import asyncio

logger = logging.getLogger(__name__)

# Global Cache Storage

_llm_cache: Dict[str, ChatOpenAI] = {}
_llm_cache_lock = asyncio.Lock()

@lru_cache(maxsize=10)
def get_cached_llm(model: str, temperature: float, api_key: str) -> ChatOpenAI:
    cache_key = f"{model}_{temperature}_{api_key[:10]}"
    
    if cache_key not in _llm_cache:
        logger.info(f"Creating new LLM instance: model={model}, temp={temperature}")
        _llm_cache[cache_key] = ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=api_key
        )
    else:
        logger.debug(f"Using cached LLM instance: {cache_key}")
    
    return _llm_cache[cache_key]


def warm_llm_cache(model: str, temperatures: list[float], api_key: str):
    logger.info(f"Warming LLM cache for model={model} with {len(temperatures)} temperature configs")
    for temp in temperatures:
        get_cached_llm(model, temp, api_key)
    
    logger.info(f"LLM cache warmed: {len(temperatures)} instances ready")


def clear_llm_cache():
    global _llm_cache
    _llm_cache.clear()
    get_cached_llm.cache_clear()
    logger.info("LLM cache cleared")
