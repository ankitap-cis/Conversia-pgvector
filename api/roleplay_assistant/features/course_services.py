from operator import or_
import shutil
from types import SimpleNamespace
from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain.memory import ConversationBufferMemory
from langchain.schema import HumanMessage, Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.prompts import PromptTemplate
from langchain.chains.combine_documents import create_stuff_documents_chain
from pathlib import Path
import configparser
import os
import tempfile
import requests
from typing import Dict, Any, List, Optional, Tuple
from langchain.prompts import ChatPromptTemplate
import re
from api.chatbot_conversation.chatbot_conversation import save_message
from logger import logger
from datetime import datetime
from models.courses_models import Course, CourseConversation
from models.users import User
from urllib.parse import urlparse
from api.roleplay_assistant.general_chatbot import GeneralChatBot
from utils.file_loaders import get_system_prompt
import os, stat
import json
from dataclasses import dataclass
from enum import Enum
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
import hashlib
import time
from collections import OrderedDict
from typing import Any, Dict, List
from utils.token_consumption import TokenUsageCallback, embedding_token_count
from utils.file_loaders import *
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from api.ai_consumption.ai_token_credit import deduct_ai_credits
from utils.prompt_loader import inject_company_context

config = configparser.ConfigParser()
config.read('config.ini')

model_name = config['openAI_config']['model']
openai_api_key = config['openAI_config']['key']
embedding_model_name = config['openAI_config']['embedding_model']
vectordb_host = config['vectordb']['vectordb_host']
vectordb_port = config['vectordb']['vectordb_port']

general_bot = GeneralChatBot()


class PerformanceMonitor:
    """Monitor and log performance metrics"""
    
    @staticmethod
    def timer(func_name: str):
        def decorator(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                start = time.time()
                result = await func(*args, **kwargs)
                elapsed = time.time() - start
                logger.info(f"⚡ {func_name} completed in {elapsed:.2f}s")
                return result
            
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                start = time.time()
                result = func(*args, **kwargs)
                elapsed = time.time() - start
                logger.info(f"⚡ {func_name} completed in {elapsed:.2f}s")
                return result
            
            return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
        return decorator


class LRUCache:
    """Thread-safe LRU cache with TTL support"""
    
    def __init__(self, max_size: int = 1000, ttl: int = 3600):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.ttl = ttl
        self.timestamps = {}
        self._lock = asyncio.Lock()
    
    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            if key not in self.cache:
                return None
            
            if time.time() - self.timestamps.get(key, 0) > self.ttl:
                del self.cache[key]
                del self.timestamps[key]
                return None
            
            self.cache.move_to_end(key)
            return self.cache[key]
    
    async def set(self, key: str, value: Any):
        async with self._lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            else:
                if len(self.cache) >= self.max_size:
                    oldest_key = next(iter(self.cache))
                    del self.cache[oldest_key]
                    if oldest_key in self.timestamps:
                        del self.timestamps[oldest_key]
            
            self.cache[key] = value
            self.timestamps[key] = time.time()


def create_cache_key(*args, **kwargs) -> str:
    """Create a cache key from arguments"""
    key_data = str(args) + str(sorted(kwargs.items()))
    return hashlib.md5(key_data.encode()).hexdigest()


class GuardrailDecision(Enum):
    """Guardrail decision outcomes"""
    SAFE = "safe"
    BLOCKED = "blocked"
    SANITIZED = "sanitized"
    FLAGGED = "flagged"


@dataclass
class GuardrailResult:
    """Result from guardrail check"""
    decision: GuardrailDecision
    content: str
    reasons: List[str]
    risk_level: str
    suggestions: List[str]


class GuardrailAgentTools:
    """
    OPTIMIZED LLM-based guardrail tools with:
    - Aggressive caching
    - Parallel execution
    - Reduced LLM calls
    - Faster regex matching
    """
    
    def __init__(self, llm: ChatOpenAI):
        self.llm = llm
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.cache = LRUCache(max_size=2000, ttl=1800)
        
        self.pii_patterns = {
            'email': re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
            'phone': re.compile(r'\b(?:\+\d{1,3}[-.]?)?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}\b'),
            'ssn': re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
            'credit_card': re.compile(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b'),
            'api_key': re.compile(r'\b(sk-|pk-)[A-Za-z0-9]{20,}\b'),
        }
        
        self.forbidden_pattern = re.compile(
            r'\b(ignore\s+previous|override\s+safety|system\s+prompt|'
            r'developer\s+message|print\s+secrets|disable\s+guard|'
            r'jailbreak|bypass|admin\s+mode)\b',
            re.IGNORECASE
        )
        
        logger.info("GuardrailAgentTools initialized with optimizations")
    
    async def prompt_injection_detector_async(self, text: str, context: Dict[str, Any]) -> GuardrailResult:
        """ULTRA-FAST prompt injection detection"""
        cache_key = f"injection_{create_cache_key(text[:200])}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        
        if self.forbidden_pattern.search(text):
            result = GuardrailResult(
                decision=GuardrailDecision.BLOCKED,
                content=text,
                reasons=["Injection pattern detected"],
                risk_level="high",
                suggestions=["Rephrase your question without system commands"]
            )
            await self.cache.set(cache_key, result)
            return result
        
        if len(text) <= 100:
            result = GuardrailResult(
                decision=GuardrailDecision.SAFE,
                content=text,
                reasons=["No injection detected"],
                risk_level="low",
                suggestions=[]
            )
            await self.cache.set(cache_key, result)
            return result
        
        prompt = f"""Analyze for prompt injection (respond JSON only):
Input: {text[:500]}

{{"is_injection": true/false, "confidence": 0.0-1.0, "risk_level": "low/medium/high"}}"""
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.llm.invoke(prompt)
            )
            result_data = json.loads(response.content.strip())
            
            if result_data.get("is_injection") and result_data.get("confidence", 0) > 0.7:
                result = GuardrailResult(
                    decision=GuardrailDecision.BLOCKED,
                    content=text,
                    reasons=["LLM detected prompt injection"],
                    risk_level=result_data.get("risk_level", "high"),
                    suggestions=["Please ask your question directly"]
                )
                await self.cache.set(cache_key, result)
                return result
        
        except Exception as e:
            logger.warning(f"LLM injection detection failed: {e}")
        
        result = GuardrailResult(
            decision=GuardrailDecision.SAFE,
            content=text,
            reasons=["No injection detected"],
            risk_level="low",
            suggestions=[]
        )
        await self.cache.set(cache_key, result)
        return result
    
    async def pii_detector_and_redactor_async(self, text: str, context: Dict[str, Any]) -> GuardrailResult:
        """FAST PII detection - regex only, no LLM calls"""
        cache_key = f"pii_{create_cache_key(text[:200])}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        
        redacted_text = text
        detected_pii = []
        
        for pii_type, pattern in self.pii_patterns.items():
            if pattern.search(text):
                detected_pii.append(pii_type)
                redacted_text = pattern.sub(f'[REDACTED_{pii_type.upper()}]', redacted_text)
        
        if detected_pii:
            result = GuardrailResult(
                decision=GuardrailDecision.SANITIZED,
                content=redacted_text,
                reasons=[f"PII detected and redacted: {', '.join(detected_pii)}"],
                risk_level="medium",
                suggestions=["PII has been automatically redacted"]
            )
        else:
            result = GuardrailResult(
                decision=GuardrailDecision.SAFE,
                content=text,
                reasons=["No PII detected"],
                risk_level="low",
                suggestions=[]
            )
        
        await self.cache.set(cache_key, result)
        return result
    
    async def content_safety_analyzer_async(self, text: str, context: Dict[str, Any]) -> GuardrailResult:
        """OPTIMIZED content safety with keyword pre-filtering"""
        cache_key = f"safety_{create_cache_key(text[:200])}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        
        unsafe_keywords = ['violence', 'hate', 'illegal', 'harmful', 'weapon', 'drug']
        text_lower = text.lower()
        
        found_unsafe = [kw for kw in unsafe_keywords if kw in text_lower]
        
        if not found_unsafe:
            result = GuardrailResult(
                decision=GuardrailDecision.SAFE,
                content=text,
                reasons=["Content is safe"],
                risk_level="low",
                suggestions=[]
            )
            await self.cache.set(cache_key, result)
            return result
        
        prompt = f"""Safety check (JSON only):
Content: {text[:300]}...

{{"is_safe": true/false, "risk_level": "low/medium/high", "issues": []}}"""
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.llm.invoke(prompt)
            )
            result_data = json.loads(response.content.strip())
            
            if not result_data.get("is_safe") or result_data.get("risk_level") in ["medium", "high"]:
                result = GuardrailResult(
                    decision=GuardrailDecision.BLOCKED,
                    content=text,
                    reasons=result_data.get("issues", ["Content safety concern"]),
                    risk_level=result_data.get("risk_level", "medium"),
                    suggestions=["Please rephrase appropriately"]
                )
                await self.cache.set(cache_key, result)
                return result
        
        except Exception as e:
            logger.error(f"Content safety analysis failed: {e}")
        
        result = GuardrailResult(
            decision=GuardrailDecision.SAFE,
            content=text,
            reasons=["Content is safe"],
            risk_level="low",
            suggestions=[]
        )
        await self.cache.set(cache_key, result)
        return result
    
    async def topic_relevance_checker_async(self, text: str, context: Dict[str, Any]) -> GuardrailResult:
        """LIGHTWEIGHT relevance check - reduced LLM calls"""
        cache_key = f"relevance_{create_cache_key(text[:200], context.get('course_title'))}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        
        if len(text) < 50:
            result = GuardrailResult(
                decision=GuardrailDecision.SAFE,
                content=text,
                reasons=["Query is relevant"],
                risk_level="low",
                suggestions=[]
            )
            await self.cache.set(cache_key, result)
            return result
        
        course_title = context.get("course_title", "Unknown Course")
        
        prompt = f"""Is this query related to "{course_title}"? (JSON only):
Query: {text[:200]}...

{{"is_relevant": true/false, "confidence": 0.0-1.0}}"""
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.llm.invoke(prompt)
            )
            result_data = json.loads(response.content.strip())
            
            if not result_data.get("is_relevant") and result_data.get("confidence", 0) > 0.8:
                result = GuardrailResult(
                    decision=GuardrailDecision.FLAGGED,
                    content=text,
                    reasons=["Off-topic query"],
                    risk_level="low",
                    suggestions=["Please ask about course material"]
                )
                await self.cache.set(cache_key, result)
                return result
        
        except Exception as e:
            logger.warning(f"Topic relevance check failed: {e}")
        
        result = GuardrailResult(
            decision=GuardrailDecision.SAFE,
            content=text,
            reasons=["Query is relevant"],
            risk_level="low",
            suggestions=[]
        )
        await self.cache.set(cache_key, result)
        return result
    
    async def output_quality_validator_async(self, text: str, context: Dict[str, Any]) -> GuardrailResult:
        """MINIMAL output validation - basic checks only"""
        cache_key = f"quality_{create_cache_key(text[:300])}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        
        if len(text) < 20:
            result = GuardrailResult(
                decision=GuardrailDecision.BLOCKED,
                content=text,
                reasons=["Output too short"],
                risk_level="medium",
                suggestions=["Regenerate response"]
            )
        else:
            result = GuardrailResult(
                decision=GuardrailDecision.SAFE,
                content=text,
                reasons=["Output meets standards"],
                risk_level="low",
                suggestions=[]
            )
        
        await self.cache.set(cache_key, result)
        return result


class GuardrailOrchestrator:
    """
    OPTIMIZED guardrail orchestrator with:
    - Selective guardrail execution
    - Reduced LLM calls
    - Faster parallel execution
    """
    
    def __init__(self, llm: ChatOpenAI):
        self.tools = GuardrailAgentTools(llm)
        self.llm = llm
        logger.info("GuardrailOrchestrator initialized with optimizations")
    
    @PerformanceMonitor.timer("Input Validation")
    async def validate_input_async(self, user_input: str, context: Dict[str, Any]) -> Tuple[bool, str, List[str]]:
        """OPTIMIZED input validation with selective checks"""
        reasons = []
        current_content = user_input
        
        if len(current_content) > 5000:
            return False, current_content, ["Input exceeds maximum length"]
        
        logger.info("Starting optimized guardrail checks...")
        
        results = await asyncio.gather(
            self.tools.prompt_injection_detector_async(current_content, context),
            self.tools.pii_detector_and_redactor_async(current_content, context),
            self.tools.content_safety_analyzer_async(current_content, context),
            return_exceptions=True
        )
        
        injection_result, pii_result, safety_result = results
        
        if isinstance(injection_result, GuardrailResult) and injection_result.decision == GuardrailDecision.BLOCKED:
            logger.warning(f"Input blocked: {injection_result.reasons}")
            return False, current_content, injection_result.reasons
        
        if isinstance(pii_result, GuardrailResult) and pii_result.decision == GuardrailDecision.SANITIZED:
            current_content = pii_result.content
            reasons.extend(pii_result.reasons)
        
        if isinstance(safety_result, GuardrailResult) and safety_result.decision == GuardrailDecision.BLOCKED:
            logger.warning(f"Unsafe content: {safety_result.reasons}")
            return False, current_content, safety_result.reasons
        
        if not reasons:
            reasons = ["Input validation passed"]
        
        return True, current_content, reasons
    
    @PerformanceMonitor.timer("Output Validation")
    async def validate_output_async(self, generated_output: str, context: Dict[str, Any]) -> Tuple[bool, str, List[str]]:
        """MINIMAL output validation for speed"""
        reasons = []
        current_content = generated_output
        
        if len(current_content) > 10000:
            current_content = current_content[:10000] + "..."
            reasons.append("Output truncated")
        
        pii_result = await self.tools.pii_detector_and_redactor_async(current_content, context)
        
        if isinstance(pii_result, GuardrailResult) and pii_result.decision == GuardrailDecision.SANITIZED:
            current_content = pii_result.content
            reasons.extend(pii_result.reasons)
        
        if not reasons:
            reasons = ["Output validation passed"]
        
        return True, current_content, reasons
    
    @PerformanceMonitor.timer("Document Validation")
    async def validate_retrieved_docs_async(self, docs: List[Document], context: Dict[str, Any]) -> List[Document]:
        """FAST document validation - security only, no content checks"""
        validated_docs = []
        
        for doc in docs:
            if (doc.metadata.get("org_id") == str(context.get("org_id")) and
                doc.metadata.get("course_id") == str(context.get("course_id")) and
                doc.metadata.get("is_published", True)):
                validated_docs.append(doc)
        
        logger.info(f"Document validation: {len(docs)} -> {len(validated_docs)}")
        return validated_docs


class CourseChatBot:
    """
    OPTIMIZED course chatbot with:
    - Reduced guardrail overhead
    - Cached vectorstores
    - Parallel operations
    - Faster LLM calls
    - 20-turn rhythm synchronized with course summary
    """
    
    def __init__(self, storage_dir: str = "./course_data"):
        self.llm = ChatOpenAI(
            model_name=model_name,
            openai_api_key=openai_api_key,
            temperature=0,
            request_timeout=30,
            max_retries=2
        )
        self.embedding_model = OpenAIEmbeddings(
            model=embedding_model_name,
            openai_api_key=openai_api_key
        )
        
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        self.sessions: Dict[str, ConversationBufferMemory] = {}
        self.session_metadata: Dict[str, Dict] = {}  # NEW: Track turn count and progress
        self.vectorstores: Dict[str, Chroma] = {}
        
        self.guardrails = GuardrailOrchestrator(self.llm)
        self.io_executor = ThreadPoolExecutor(max_workers=5)
        
        logger.info("CourseChatBot initialized with performance optimizations")
    
    def _get_vectorstore_path(self, org_id: int, course_id: int) -> str:
        return str(self.storage_dir / f"org_{org_id}_course_{course_id}")
    
    def _get_or_create_vectorstore(self, org_id: int, course_id: int) -> Chroma:
        vectorstore_key = f"{org_id}_{course_id}"
        
        if vectorstore_key in self.vectorstores:
            return self.vectorstores[vectorstore_key]
        
        persistent_directory = self._get_vectorstore_path(org_id, course_id)
        
        os.makedirs(persistent_directory, exist_ok=True)
        os.chmod(persistent_directory, stat.S_IRWXU | stat.S_IRWXG)
        
        db_file = os.path.join(persistent_directory, "chroma.sqlite3")
        
        if os.path.exists(db_file):
            try:
                os.chmod(db_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP)
            except Exception as e:
                logger.warning(f"Failed to chmod db file {db_file}: {e}")
        
        try:
            self.vectorstores[vectorstore_key] = Chroma(
                persist_directory=persistent_directory,
                embedding_function=self.embedding_model,
                collection_name=f"org_{org_id}_course_{course_id}"
            )
        except Exception as e:
            if "readonly database" in str(e).lower():
                logger.warning(f"Readonly DB detected, fixing permissions for {persistent_directory}")
                if os.path.exists(db_file):
                    os.chmod(db_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP)
                self.vectorstores[vectorstore_key] = Chroma(
                    persist_directory=persistent_directory,
                    embedding_function=self.embedding_model,
                    collection_name=f"org_{org_id}_course_{course_id}"
                )
        
        return self.vectorstores[vectorstore_key]
    
    def _get_or_create_session(self, session_id: str, course_context: str = None) -> ConversationBufferMemory:
        """Create or retrieve session with turn tracking"""
        if session_id not in self.sessions:
            memory = ConversationBufferMemory(return_messages=True, memory_key="chat_history")
            self.sessions[session_id] = memory
            
            # Initialize session metadata for turn tracking
            self.session_metadata[session_id] = {
                "turn_count": 0,
                "parking_lot": []  # For off-scope questions
            }
            
            if course_context:
                memory.chat_memory.add_user_message(f"Course context: {course_context}")
        
        return self.sessions[session_id]
    
    def _extract_objectives_from_summary(self, summary_html: str) -> List[str]:
        """Extract 5 learning objectives from course summary (aligned with 'You'll learn to' bullets)"""
        if not summary_html:
            return []
        
        soup = BeautifulSoup(summary_html, 'html.parser')
        objectives = []
        
        # Strategy 1: Find "You'll learn to" section
        for text_node in soup.find_all(text=True):
            if "you'll learn to" in text_node.lower() or "you will learn to" in text_node.lower():
                # Get parent element's next <ul>
                parent = text_node.parent
                ul = parent.find_next('ul')
                if ul:
                    for li in ul.find_all('li', limit=5):
                        text = li.get_text(strip=True)
                        if text:
                            objectives.append(text)
                    break
        
        # Strategy 2: If no "You'll learn to" header found, look for first <ul> with 5 items
        if not objectives:
            for ul in soup.find_all('ul'):
                items = ul.find_all('li')
                if 4 <= len(items) <= 6:  # Flexible range for 5 objectives
                    objectives = [li.get_text(strip=True) for li in items[:5]]
                    break
        
        logger.info(f"Extracted {len(objectives)} objectives from course summary")
        return objectives[:5]  # Always return exactly 5 for consistent turn planning

    
    @PerformanceMonitor.timer("Add Course Document")
    async def add_course_document_async(self, course_id: int, org_id: int, file_path: str,
                                       course_title: str) -> Dict[str, Any]:
        """OPTIMIZED document addition with reduced validation"""
        start_time = datetime.now()
        local_temp_path = None
        
        try:
            loop = asyncio.get_event_loop()
            local_temp_path = await loop.run_in_executor(
                self.io_executor,
                self.download_file,
                file_path
            )
            
            ext = os.path.splitext(urlparse(file_path).path)[1].lower().lstrip(".")
            
            documents = await loop.run_in_executor(
                self.io_executor,
                self._load_documents,
                local_temp_path,
                ext,
                file_path
            )
            
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"Loaded {len(documents)} documents in {elapsed:.2f}s")
            
            sanitized_documents = documents
            
            timestamp = datetime.now().isoformat()
            file_name = os.path.basename(file_path)
            
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=1500,
                chunk_overlap=200
            )
            
            chunked_documents = [
                Document(
                    page_content=chunk.page_content,
                    metadata={**chunk.metadata, "chunk_index": idx}
                )
                for idx, chunk in enumerate(
                    text_splitter.create_documents(
                        texts=[doc.page_content for doc in sanitized_documents],
                        metadatas=[{
                            "file_path": file_path,
                            "updated_at": timestamp,
                            "course_id": str(course_id),
                            "course_title": course_title,
                            "org_id": str(org_id),
                            "file_type": ext,
                            "file_name": file_name,
                            "source": file_name,
                            "source_path": file_path,
                            "is_published": True,
                        } for _ in sanitized_documents]
                    )
                )
            ]
            
            texts_to_embed = [doc.page_content for doc in chunked_documents]
            usage_metadata = embedding_token_count(texts_to_embed, embedding_model_name)
            
            vectorstore = self._get_or_create_vectorstore(org_id, course_id)
            
            await loop.run_in_executor(
                self.io_executor,
                self._set_permissions,
                org_id,
                course_id
            )
            
            vectorstore.add_documents(chunked_documents)
            
            if local_temp_path and os.path.exists(local_temp_path):
                os.remove(local_temp_path)
            
            logger.info(f"Successfully added {len(chunked_documents)} chunks for course {course_id}")
            return {
                "success": True,
                "chunks_added": len(chunked_documents),
                "course_id": course_id,
                "org_id": org_id,
                "file_name": file_name,
                "usage_metadata": usage_metadata
            }
        
        except Exception as e:
            logger.error(f"Error adding course document: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
        
        finally:
            if local_temp_path and os.path.exists(local_temp_path):
                try:
                    os.unlink(local_temp_path)
                except Exception as cleanup_err:
                    logger.warning(f"Failed to cleanup temp file {local_temp_path}: {cleanup_err}")
    
    def _load_documents(self, local_temp_path: str, ext: str, file_path: str) -> List[Document]:
        parsed_url = urlparse(file_path)
        filename = os.path.basename(parsed_url.path)
        documents = asyncio.run(process_document(
            source=local_temp_path,
            filename=filename,
            enable_ocr=True,
            ocr_language="eng",
            ocr_dpi=300,
            return_documents=True
        ))
        
        if not documents:
            raise ValueError(f"Failed to extract content from {filename}")
        
        return documents
    
    def _set_permissions(self, org_id: int, course_id: int):
        """Helper to set file permissions"""
        path = str(self.storage_dir / f"org_{org_id}_course_{course_id}")
        for root, dirs, files in os.walk(path):
            os.chmod(root, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
            for f in files:
                os.chmod(os.path.join(root, f), stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
    
    @PerformanceMonitor.timer("Chat with Course")
    async def chat_with_course_async(self, message: str, course_id: int, course_title: str,
                                     org_id: int, session_id: str, system_prompt: str,
                                     course_summary: str = None,  # NEW PARAMETER
                                     course_context: str = None) -> str:
        """
        ULTRA-OPTIMIZED chat with 20-turn rhythm synchronized to course summary
        """
        try:
            logger.info(f"Starting optimized input validation")
            
            context = {
                "course_id": course_id,
                "org_id": org_id,
                "session_id": session_id,
                "course_title": course_title
            }
            
            affirmative_keywords = ["yes", "great", "good", "perfect", "got it", "understood", "clear", "ok", "okay"]
            is_short_affirmative = (len(message) <= 20 and 
                                any(word in message.lower() for word in affirmative_keywords))

            if is_short_affirmative:
                # Skip validation for affirmatives
                validated_message = message.strip()
                logger.info(f"SKIPPED validation for affirmative: '{message}'")
                reasons = ["Bypassed validation for learner confirmation"]
            else:
                # Full validation for real inputs
                is_valid, validated_message, reasons = await self.guardrails.validate_input_async(message, context)
                if not is_valid:
                    logger.warning(f"Input validation failed: {reasons}")
                    return self._generate_safe_response(reasons)

            logger.info(f"Input validated: '{validated_message}' | Reasons: {reasons}")
            
            logger.info(f"Input validation passed: {reasons}")
            memory = self._get_or_create_session(session_id, course_context)
            
            # Extract objectives from existing course summary
            objectives = self._extract_objectives_from_summary(course_summary) if course_summary else []
            total_objectives = len(objectives)

            # Update turn counter
            session_meta = self.session_metadata.get(session_id, {})
            session_meta["turn_count"] = session_meta.get("turn_count", 0) + 1
            turn_count = session_meta["turn_count"]

            # Initialize ALL variables FIRST with defaults
            current_phase = "Extended Support"
            current_objective = "Additional clarifications"
            current_objective_idx = 0
            check_understanding = False

            # NOW calculate based on turn - variables are always defined
            if turn_count <= 15:
                current_phase = "Core Micro-Cycles"
                current_objective_idx = min((turn_count - 1) // 3, total_objectives - 1) if objectives else 0
                current_objective = objectives[current_objective_idx] if current_objective_idx < total_objectives else "Continue learning"
                check_understanding = (turn_count % 2 == 0)  # Every OTHER turn per your spec
                
            elif turn_count <= 18:
                current_phase = "Integration Phase"
                current_objective_idx = 5  # Beyond core objectives
                current_objective = "Synthesize and apply all 5 learning objectives"
                check_understanding = False
                
            elif turn_count <= 20:
                current_phase = "Final Assessment"
                current_objective_idx = 5
                current_objective = "Complete understanding check + confidence rating (1-5)"
                check_understanding = True
                
            else:
                current_phase = "Extended Support"
                current_objective_idx = 5
                current_objective = "Address parking lot questions or additional clarifications"
                check_understanding = False

            # Now ALL variables are ALWAYS defined - no more errors!
            logger.info(f"TURN {turn_count} | Phase: {current_phase} | Obj {current_objective_idx+1}: {current_objective}")


            # Build turn-specific guidance
            turn_guidance = ""
            if turn_count <= 15:
                turn_guidance = f"""**Current Turn Instruction (Turn {turn_count}):**
            - Teach 2-4 key points related to: "{current_objective}"
            - Include 1 "In the field" practical application
            - End with {'an understanding check (ask learner to explain concept back)' if check_understanding else 'a guiding question to next concept'}
            - Keep each teaching point under 20 words"""

            elif turn_count == 16:
                turn_guidance = """**Current Turn Instruction (Turn 16):**
            - Provide 3-bullet recap of Objectives 1-3
            - Connect concepts with a real-life scenario
            - Ask: "How would you apply these in your next customer call?" """

            elif turn_count == 17:
                turn_guidance = """**Current Turn Instruction (Turn 17):**
            - Provide 3-bullet recap of Objectives 4-5
            - Scenario: competitive positioning or objection handling
            - Bridge to final assessment """

            elif turn_count == 18:
                turn_guidance = """**Current Turn Instruction (Turn 18):**
            - Synthesize all 5 objectives into field-ready application
            - Real-life scenario that requires multiple skills
            - Set up final check: "Let's test your mastery..." """

            elif turn_count == 19:
                turn_guidance = """**Current Turn Instruction (Turn 19):**
            - Comprehensive understanding check covering all 5 objectives
            - Ask learner to role-play or explain application
            - Provide constructive feedback """

            elif turn_count == 20:
                turn_guidance = """**Current Turn Instruction (Turn 20):**
            - Ask confidence rating: "On a scale of 1-5, how confident are you applying these skills?"
            - Based on rating, provide next steps
            - Offer to address parking lot questions or conclude """

            # Updated turn-aware prompt
            turn_aware_prompt = f"""**Role**: You are a structured 20-turn AI coach for B2B sales training in {course_title}.

            **Session Progress:**
            - Turn: {turn_count}/20
            - Phase: {current_phase}
            - Current Objective ({current_objective_idx + 1}/5): {current_objective}
            - Check Understanding This Turn: {check_understanding}

            **COURSE LEARNING OBJECTIVES** (from course summary):
            {chr(10).join(f'{i+1}. {obj}' for i, obj in enumerate(objectives)) if objectives else "Learning objectives not yet defined"}

            **20-TURN RHYTHM STRUCTURE:**

            **TURNS 1-15: Core Micro-Cycles** (3 turns per objective)
            - Objective 1: Turns 1-3
            - Objective 2: Turns 4-6
            - Objective 3: Turns 7-9
            - Objective 4: Turns 10-12
            - Objective 5: Turns 13-15

            Each turn structure:
            • Teach 2-4 key points (sentences ≤20 words each)
            • Include 1 "In the field" practical application tied to {course_title} context
            • **Understanding Check Cadence**: Every 3rd turn (turns 3, 6, 9, 12, 15)
            - If learner correct + confident: can skip to every 4th turn
            - If incorrect/unsure: return to every 2nd turn until stable

            **TURNS 16-18: Integration Phase**
            - Turn 16: Recap objectives 1-3 + real-life application
            - Turn 17: Recap objectives 4-5 + competitive scenario
            - Turn 18: Synthesize all 5 + complex application

            **TURNS 19-20: Final Assessment**
            - Turn 19: Comprehensive understanding check (role-play or explain-back)
            - Turn 20: Confidence rating (1-5) + next steps + parking lot review

            **OFF-SCOPE RULE:**
            - **Tangential** (related but not core): Answer in 1-2 sentences, return to planned content
            - **Off-scope** (unrelated): "Great question—I've added it to our parking lot. Let's address it after Turn 20. For now, let's focus on [current objective]."

            **SOURCE PRIORITY** (resolve conflicts in this order):
            1. Course Form & Summary Objectives — situational anchor
            2. Source Course Upload — authoritative facts
            3. Company Vector KB — supplemental context
            4. LLM General Knowledge — gap fill only (mark clearly: "General industry practice...")

            **TEACHING PRINCIPLES:**
            1. **Conversational Flow**: Short teaching + interactive questions
            2. **Sales Context**: Every concept ties to customer conversations
            3. **Active Recall**: Socratic method, learner explains in own words
            4. **Immediate Feedback**: Constructive, tied to customer impact
            5. **Adaptive Difficulty**: Match learner's demonstrated level

            **VOICE & FORMATTING:**
            - HTML tags ONLY: <h2>, <h3>, <p>, <ul>, <li>, <strong>
            - Short sentences (most ≤20 words)
            - No newlines, no extra spacing between <li> items
            - End every turn with ONE clear question guiding next step
            - Avoid using generic or unnecessary section headings (e.g., “Key Points”). Integrate points naturally without labeling them.

            {turn_guidance}
            """
            
            loop = asyncio.get_event_loop()
            
            # Retrieve fewer documents (k=3)
            retrieval_task = loop.run_in_executor(
                self.io_executor,
                self._retrieve_course_documents,
                validated_message,
                course_id,
                org_id,
                3
            )
            
            memory_task = loop.run_in_executor(
                self.io_executor,
                self._format_history_as_string,
                memory.chat_memory.messages[-5:]
            )
            
            retrieved_docs, chat_history_str = await asyncio.gather(retrieval_task, memory_task)
            
            # Fast document validation (security only)
            validated_docs = await self.guardrails.validate_retrieved_docs_async(retrieved_docs, context)
            
            if not system_prompt:
                system_prompt = "You are an intelligent teaching assistant."
            
            # Turn-aware prompt synchronized with course summary objectives
            turn_aware_prompt = f"""Role: Structured 20-turn training agent for {course_title}

**Session Progress:**
- Turn: {turn_count}/20
- Phase: {current_phase}
- Current Objective: {current_objective}
- Total Objectives: {total_objectives}
- Check Understanding This Turn: {check_understanding}

**20-TURN RHYTHM:**

**TURNS 1-15: Core Micro-Cycles**
- Cover {total_objectives} learning objectives from course summary (approximately 3 turns per objective)
- Each turn structure:
  * Teach 2-4 key points (sentences ≤20 words each)
  * Include 1 "In the field" practical application with {course_title} context
  * End with understanding check every 3rd turn (ask learner to explain back)
  
**TURNS 16-18: Integration Phase**
- Synthesize concepts with 3-bullet recap
- Real-life application scenarios involving customer conversations
- Connect to competitive positioning and objection handling

**TURNS 19-20: Final Assessment**
- Comprehensive understanding check
- Confidence rating (1-5 scale)
- Next steps and resources

**Source Priority (resolve conflicts in this order):**
1. Course Form & Summary Objectives — situational anchor
2. Source Course Upload — authoritative
3. Company Vector KB — supplemental facts
4. LLM General Knowledge — gap fill only

**Off-Scope Handling:**
- Tangential questions: Answer in 1-2 sentences, return to planned content
- Off-scope questions: Add to "Parking lot" list, address after Turn 20

**Teaching Principles:**
1. **Conversational Flow**: Short teaching points + interactive questions
2. **Sales Context**: Tie every concept to customer conversations
3. **Active Recall**: Socratic questioning, learner explains back in own words
4. **Immediate Feedback**: Constructive, tied to customer impact
5. **Adaptive Difficulty**: Match learner's demonstrated capability

**Voice & Formatting:**
- HTML tags only: <h2>, <h3>, <p>, <ul>, <li>, <strong>
- Short sentences (most ≤20 words)
- No newlines, no extra spacing between list items
- End every turn with ONE clear question guiding next step

**Current Turn Focus:**
Turn {turn_count} should {"include an understanding check where the learner explains the concept back" if check_understanding else "teach core concepts and end with a guiding question"}.
"""
            
            chat_prompt = ChatPromptTemplate.from_messages([
                ("system", turn_aware_prompt),
                ("system", system_prompt),
                ("human", "Course: {course_title}\nHistory: {chat_history}\nContent: {context}"),
                ("human", "{message}")
            ])
            
            memory.chat_memory.add_user_message(validated_message)
            
            chain = create_stuff_documents_chain(self.llm, chat_prompt)
            token_callback = TokenUsageCallback()

            response = await loop.run_in_executor(
                self.io_executor,
                lambda: chain.invoke({
                    "message": validated_message,
                    "context": validated_docs,
                    "chat_history": chat_history_str,
                    "course_title": course_title,
                    "system_prompt": system_prompt
                },
                config={"callbacks": [token_callback]}
                )
            )
            
            if isinstance(response, str):
                clean_response = self._clean_html_output(response)
            else:
                clean_response = self._clean_html_output(response.get("output_text", ""))
            
            logger.info("Starting minimal output validation")
            
            is_valid, final_response, reasons = await self.guardrails.validate_output_async(
                clean_response, context
            )
            
            if not is_valid:
                logger.warning(f"Output validation failed: {reasons}")
                return self._generate_safe_response(
                    ["Generated response did not meet safety standards"]
                )
            
            logger.info(f"Output validation passed: {reasons}")
            
            memory.chat_memory.add_ai_message(final_response)
            
            return final_response, token_callback
        
        except Exception as e:
            logger.error(f"Error in course chat: {e}", exc_info=True)
            raise
    
    @PerformanceMonitor.timer("Generate Course Summary")
    async def generate_course_summary_async(self, course_id: int, org_id: int) -> Tuple[str, Dict[str, int]]:
        """ASYNC course summary generation"""   
        try:
            loop = asyncio.get_event_loop()
            
            retrieved_docs = await loop.run_in_executor(
                self.io_executor,
                self._retrieve_course_documents,
                "Provide a structured summary",
                course_id,
                org_id,
                5
            )
            
            context = {"course_id": course_id, "org_id": org_id}
            validated_docs = await self.guardrails.validate_retrieved_docs_async(retrieved_docs, context)
            
            prompt = PromptTemplate(
                input_variables=["context"],
                template=self._get_summary_template()
            )
            
            chain = create_stuff_documents_chain(self.llm, prompt)
            
            token_callback = TokenUsageCallback()
            response = await loop.run_in_executor(
                self.io_executor,
                lambda: chain.invoke({"context": validated_docs}, config={"callbacks": [token_callback]})
            )
            
            usage_metadata = {
                "input_tokens": token_callback.prompt_tokens,
                "output_tokens": token_callback.completion_tokens,
                "total_tokens": token_callback.total_tokens
            }
            
            is_valid, final_response, _ = await self.guardrails.validate_output_async(response, context)
            if is_valid:
                return final_response, usage_metadata
            else:
                return "<p>Unable to generate course summary.</p>", None
        
        except Exception as e:
            logger.error(f"Error generating course summary: {e}", exc_info=True)
            return "<p>Error generating course summary</p>", None
    
    def _retrieve_course_documents(self, query: str, course_id: int, org_id: int, k: int = 3) -> List[Document]:
        """Retrieve documents with security filtering"""
        try:
            vectorstore = self._get_or_create_vectorstore(org_id, course_id)
            docs_and_scores = vectorstore.similarity_search_with_score(query, k=k*2)
            
            filtered_docs = []
            for doc, score in docs_and_scores:
                if (doc.metadata.get("org_id") == str(org_id) and
                    doc.metadata.get("course_id") == str(course_id) and
                    doc.metadata.get("is_published", True)):
                    filtered_docs.append(doc)
                if len(filtered_docs) >= k:
                    break
            
            logger.info(f"Retrieved {len(filtered_docs)} course documents")
            return filtered_docs
        except Exception as e:
            logger.error(f"Error in document retrieval: {e}")
            return []
    
    def delete_course_content(self, course_id: int, org_id: int) -> Dict[str, Any]:
        """Delete all embeddings for a specific course from ChromaDB vectorstore."""
        try:
            vectorstore = self._get_or_create_vectorstore(org_id, course_id)
            collection = vectorstore._collection
            
            count_before = collection.count()
            
            collection.delete(
                where={"course_id": {"$eq": str(course_id)}}
            )
            
            count_after = collection.count()
            deleted_count = count_before - count_after
            
            logger.info(
                f"Deleted {deleted_count} embeddings for course {course_id}, org {org_id}. "
                f"Count before: {count_before}, Count after: {count_after}"
            )
            
            return {
                "success": True,
                "course_id": course_id,
                "org_id": org_id,
                "deleted_count": deleted_count,
                "count_before": count_before,
                "count_after": count_after
            }
        except Exception as e:
            logger.error(f"Error deleting course content for course {course_id}: {e}", exc_info=True)
            return {"success": False, "error": str(e), "course_id": course_id, "org_id": org_id}
    
    def download_file(self, url: str) -> str:
        """Download file from URL to temporary location"""
        parsed = urlparse(url)
        ext = os.path.splitext(parsed.path)[1] or ".tmp"
        
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    temp_file.write(chunk)
        
        temp_file.close()
        return temp_file.name
    
    def _format_history_as_string(self, messages) -> str:
        """Format chat history as string"""
        lines = []
        for msg in messages:
            role = "Student" if isinstance(msg, HumanMessage) else "Assistant"
            lines.append(f"{role}: {msg.content}")
        return "\n".join(lines)
    
    def _clean_html_output(self, text: str) -> str:
        """Remove newline characters from output"""
        return re.sub(r'\n', '', text)
    
    def _generate_safe_response(self, reasons: List[str]) -> str:
        """Generate safe rejection response"""
        reason_text = str(reasons) if reasons else "safety concern"
        
        safe_responses = {
            "Injection": "<p>I detected an unusual pattern in your message. Let's focus on your learning goals. What specific topic would you like to explore?</p>",
            "PII": "<p>For your privacy, I've removed some sensitive information from your message. How can I help you with the course content?</p>",
            "safety": "<p>I'm here to help you learn in a positive environment. Please rephrase your question, and I'll be happy to assist.</p>",
            "off-topic": "<p>That question seems outside the scope of this course. Let's stay focused on the course material. What would you like to learn about?</p>",
        }
        
        for key, response in safe_responses.items():
            if key.lower() in reason_text.lower():
                return response
        
        return "<p>I couldn't process your request appropriately. Please rephrase your question about the course material, and I'll be happy to help.</p>"
    
    def _get_summary_template(self) -> str:
        """Get summary template aligned with B2B sales training format"""
        return """You are a curriculum design expert in B2B sales training for field reps.

    Write a course overview summary (150–200 words) with this EXACT structure:

    1) **Hook (1–2 sentences in BOLD)**: Outcome first + why it matters now. This is the headline And should be of only a sentence.

    2) **"You'll learn to" bullets**: Exactly 5 bullets, action verbs, field language.
    - Each bullet should be a distinct skill/concept
    - Use action verbs (e.g., "Identify", "Handle", "Position", "Navigate", "Build")
    - Write for sales reps, not corporate trainers

    3) **"In the field" line**: Single sentence that anchors the course to a real moment.
    - Answers: "When exactly will I use this?"
    - Example: "Use this when a prospect asks about pricing before you've established value."

    4) **"How it works + time" line**: "In 10–15 minutes, you'll have a 1:1 conversation with an AI coach that teaches the key concepts, runs quick checks for understanding, and answers questions anytime."

    <p>Type or say start to begin.</p>

    CONSTRAINTS:
    - 150–200 words total (strict).
    - Clear, direct, practical language. No buzzwords.
    - Do not invent facts, metrics, or features not in the source content.
    - If key details are missing, use neutral placeholders like "[specific skill]" rather than guessing.
    - Use short sentences. Most under 20 words.
    - HTML formatting: Use <h2>, <h3>, <p>, <ul>, <li>, <strong> tags only
    - No newlines - HTML only

    Source Content:
    {context}"""

    
    def list_documents(self):
        """List all documents in vectorstore"""
        try:
            results = self.vectorstore._collection.get(include=["metadatas", "documents"])
            
            chunks_count = len(results.get("documents", []))
            metadatas = results.get("metadatas", [])
            
            documents_summary = {}
            for metadata in metadatas:
                if isinstance(metadata, dict):
                    source = metadata.get("source") or metadata.get("file_name")
                    if source and source not in documents_summary:
                        documents_summary[source] = {
                            "source": source,
                            "metadata": metadata
                        }
            
            return {
                "total_documents": len(documents_summary),
                "total_chunks": chunks_count,
                "documents": list(documents_summary.values())
            }
        
        except Exception as e:
            return {"success": False, "error": str(e)}


# Initialize the chatbot
course_chatbot = CourseChatBot()

async def course_chat(conversation_id, request, body, db, current_user):
    """
    OPTIMIZED course chat endpoint
    """
    try:
        message = body.get("message")
        course_id = int(body.get("course_id"))
        
        assistant_message = SimpleNamespace(role="user", content=message)
        await save_message(str(conversation_id), assistant_message, request, db, current_user)
        
        if not message or not course_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"status": "failure", "message": "Missing message or course_id"}
            )
        
        conversation = db.query(CourseConversation).filter(
            CourseConversation.id == conversation_id
        ).first()
        
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"status": "failure", "message": "Conversation not found"}
            )
        
        course = db.query(Course).filter(Course.id == course_id).first()
        if not course:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"status": "failure", "message": "Course not found"}
            )
        
        course_context = f"""
        Title: {course.title}
        Audience: {course.audience or "N/A"}
        Description: {course.description or "N/A"}
        """
        
        if current_user.user_type not in [
            "org_admin",
            "content_creator",
            "exec_viewer",
            "field_manager",
            "sales_reps"
        ]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"status": "failure", "message": "Permission denied"}
            )
                
        org_id = current_user.organization_id
        if not org_id and current_user.user_type == "sales_reps":
            user_record = db.query(User).filter(User.id == current_user.id).first()
            if user_record and user_record.created_by:
                creator_user = db.query(User).filter(
                    User.email == user_record.created_by
                ).first()
                if creator_user:
                    org_id = creator_user.organization_id
        
        if not org_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"status": "failure", "message": "Organization not found"}
            )
        
        # OPTIMIZED CHAT

        from api.user_management.user_management import get_company_context

        company_context = await get_company_context(db, current_user, return_raw=True)
        system_prompt = get_system_prompt(
            db, org_id, "courses_prompt", "You are an expert teaching assistant."
        )
        system_prompt = inject_company_context(system_prompt, company_context, current_user.org_name)

        response_data, token_callback = await course_chatbot.chat_with_course_async(
            message=message,
            course_id=course_id,
            course_title=course.title,
            org_id=org_id,
            session_id=f"course_{current_user.id}_{course_id}_{conversation_id}",
            system_prompt=system_prompt,
            course_summary=course.course_summary,
            course_context=course_context
        )
        
        assistant_message = SimpleNamespace(role="assistant", content=response_data)
        await save_message(conversation_id, assistant_message, request, db, current_user)
        
        conversation = db.query(CourseConversation).filter(
            CourseConversation.id == conversation_id
        ).first()
        if conversation and conversation.title == "New Chat":
            generated_title = general_bot.generate_chat_title(
                message, response_data, general_bot.llm
            )
            conversation.title = generated_title
            db.commit()

        usage_metadata = {
            "input_tokens": token_callback.prompt_tokens,
            "output_tokens": token_callback.completion_tokens,
            "total_tokens": token_callback.total_tokens,
        }
        await deduct_ai_credits(
            db=db,
            user_id=current_user.id,
            input_tokens=usage_metadata['input_tokens'] if usage_metadata else 0,
            output_tokens=usage_metadata['output_tokens'] if usage_metadata else 0,
            stt_minutes=0.0,
            tts_minutes=0.0
        )

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Course chat response generated",
                "data": response_data,
                "usage_metadata": usage_metadata
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in course chat: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failure", "message": "Error in course chat"}
        )

async def admin_coursefile_to_vectordb(
    course_id,
    course_title,    
    db,
    current_user,
    file_path: str,
):
    """
    Adds a single course document to the vector store and
    generates summaries for all superadmin-created courses,
    updating only the course_summary field.
    """

    result = await course_chatbot.add_course_document_async(
        course_title=course_title,
        course_id=course_id,
        org_id=current_user.organization_id,
        file_path=file_path,
    )

    if result.get("success"):
        logger.info(f"Course content added to vectorstore: {result}")
    else:
        logger.warning(f"Failed to add course content to vectorstore: {result}")
        return

    # Generate summaries and update DB
    summary, token_usage = await course_chatbot.generate_course_summary_async(
        course_id=course_id,
        org_id=current_user.organization_id,
    )

    await deduct_ai_credits(
        db=db,
        user_id=current_user.id,
        input_tokens=token_usage['input_tokens'] if token_usage else 0,
        output_tokens=token_usage['output_tokens'] if token_usage else 0,
        stt_minutes=0.0,
        tts_minutes=0.0
    )

    db.query(Course).filter(Course.id == course_id).update(
        {Course.course_summary: summary}
    )

    # Commit once
    db.commit()
