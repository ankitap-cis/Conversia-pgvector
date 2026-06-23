from typing import Dict, Any
from pathlib import Path
import urllib
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.prompts import PromptTemplate
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_chroma import Chroma
from langchain.schema import HumanMessage, SystemMessage
from datetime import datetime
from pathlib import Path
import tempfile
from langchain_community.chat_message_histories import RedisChatMessageHistory
import requests
import tempfile
import os
import configparser
from logger import *
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda
from fastapi import HTTPException
from langchain.text_splitter import RecursiveCharacterTextSplitter
from collections import OrderedDict
import re
from langchain.retrievers.multi_query import MultiQueryRetriever
import time
from urllib.parse import urlparse, unquote
import urllib
import os
from langchain_core.messages import HumanMessage, AIMessage
from models.conversation_models import ChatBotMessages
from langchain.retrievers import BM25Retriever, EnsembleRetriever, MultiQueryRetriever
from langchain.retrievers.document_compressors import (
    EmbeddingsFilter
)
from langchain.storage import InMemoryStore
from utils.token_consumption import TokenUsageCallback, embedding_token_count
from utils.file_loaders import *
from langchain.chains import create_history_aware_retriever
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder


config = configparser.ConfigParser()
config.read('config.ini')
OPENAI_API_KEY = config['openAI_config']['key']
gpt_model = config['openAI_config']['model']
embed_model = config['openAI_config']['embedding_model']
vectordb_host = config['vectordb']['vectordb_host']
vectordb_port = int(config['vectordb']['vectordb_port'])

os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGCHAIN_TRACING"] = "false"
os.environ["LANGCHAIN_TELEMETRY"] = "false"


def annotate_with_citations(answer: str, citations: list[dict]) -> str:

    file_path_and_name = None 

    used_sources = set()
    ordered_citations = OrderedDict()
    paragraphs = [p.strip() for p in re.split(r'\n{2,}', answer) if p.strip()]
    annotated_paragraphs = []
    for i, para in enumerate(paragraphs):
        citation = None
        for c in citations:
            source_id = c["source"]
            if source_id in used_sources:
                continue
            citation = c
            used_sources.add(source_id)
            ordered_citations[source_id] = c["link"]
        annotated_paragraphs.append(para)
    annotated_html = "<br><br>".join(annotated_paragraphs)

    annotated_html = re.sub(
        r'<h3>\s*Sources\s*</h3>\s*<ul>.*?</ul>',
        '',
        annotated_html,
        flags=re.IGNORECASE | re.DOTALL
    )
    if ordered_citations:
        sources_html = "<h3>Sources</h3>\n<ul>"
        for name, link in ordered_citations.items():
            file_path_and_name = unquote(urlparse(link).path)
            sources_html += f'<li><a href="{file_path_and_name}" target="_blank">{name}</a></li>'
        sources_html += "</ul>"
        annotated_html += f"<br><br>{sources_html}"
    return annotated_html, file_path_and_name

class GeneralChatBot:
    def __init__(self, model_name=gpt_model, storage_dir="./chatdata/general", redis_url: str = None, org_id: int = None):
        self.llm = ChatOpenAI(model_name=model_name, openai_api_key=OPENAI_API_KEY,temperature=0.1, top_p=0.1, presence_penalty=0,seed=420)
        self.embedding_model = OpenAIEmbeddings(openai_api_key=OPENAI_API_KEY, model= embed_model)
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.vectorstore = Chroma(
            collection_name="example_collection",
            embedding_function=self.embedding_model,
            host=vectordb_host,
            port=vectordb_port,
        )

        self.all_documents = {"documents": []}
        self.bm25_retriever = None
        self.org_id = org_id

        # Initial vector retriever
        vector_retriever = self.vectorstore.as_retriever(
            search_kwargs={"k": 10}
        )
        # Use vector retriever initially; will rebuild after first doc add
        self.ensemble_retriever = vector_retriever
        self.retriever = self._priority_based_retriever()
        
        self.memory_store = InMemoryStore()

        self._loaded_sessions = set()
    
        if redis_url is None:
            redis_url = f"redis://{config.get('redis_config', 'host', fallback='localhost')}:{config.getint('redis_config', 'port', fallback=6379)}/1"
            self.redis_url = redis_url

    def _get_redis_history(self, session_id: str) -> RedisChatMessageHistory:
        """Get Redis-backed chat history for a session."""
        return RedisChatMessageHistory(
            session_id=session_id,
            url=self.redis_url,
            key_prefix="general_chat:",
            ttl=86400  # 24 hours expiry
        )
        
    async def load_history_from_db(self, session_id: str, db: Session):
        """
        Load conversation history from database and populate Redis.
        Only loads once per session to avoid redundant DB queries.
        """
        # Skip if already loaded for this session
        if session_id in self._loaded_sessions:
            logger.info(f"Session {session_id} already loaded from DB, skipping...")
            return
        
        try:
            # Get Redis history instance
            redis_history = self._get_redis_history(session_id)
            
            # Check if Redis already has messages (to avoid overwriting)
            existing_messages = redis_history.messages
            if len(existing_messages) > 0:
                logger.info(f"Redis already has {len(existing_messages)} messages for session {session_id}")
                self._loaded_sessions.add(session_id)
                return
            
            # Query database for conversation history
            db_messages = db.query(ChatBotMessages).filter(
                ChatBotMessages.conversation_id == session_id
            ).order_by(ChatBotMessages.created_at.asc()).all()
            
            if not db_messages:
                logger.info(f"No messages found in DB for session {session_id}")
                self._loaded_sessions.add(session_id)
                return
            
            # Convert DB messages to LangChain message format and add to Redis
            langchain_messages = []
            for msg in db_messages:
                if msg.role == "user":
                    langchain_messages.append(HumanMessage(content=msg.content))
                elif msg.role == "assistant":
                    langchain_messages.append(AIMessage(content=msg.content))
            
            # Bulk add messages to Redis
            if langchain_messages:
                redis_history.add_messages(langchain_messages)
                logger.info(f" Loaded {len(langchain_messages)} messages from DB to Redis for session {session_id}")
            
            # Mark session as loaded
            self._loaded_sessions.add(session_id)
            
        except Exception as e:
            logger.error(f"Error loading history from DB for session {session_id}: {e}", exc_info=True)
            # Don't raise exception - allow chat to continue even if history loading fails
            
    
    def add_assistant_message_to_redis(self, session_id: str, message: str):
        """
        Manually add assistant message to Redis after it's saved to database.
        """
        try:
            redis_history = self._get_redis_history(session_id)
            redis_history.add_ai_message(message)
            logger.info(f" Added assistant message to Redis for session: {session_id}")
        except Exception as e:
            logger.error(f"Error adding assistant message to Redis for session {session_id}: {e}", exc_info=True)
            
    def _format_history_as_string(self, messages):
        lines = []
        for msg in messages:
            role = "User" if isinstance(msg, HumanMessage) else "Assistant"
            lines.append(f"{role}: {msg.content}")
        return "\n".join(lines)

    def chat(
        self, 
        message: str, 
        session_id: str = "default", 
        system_prompt: str = None,
        org_id: int = None
    ) -> Dict[str, Any]:
        """
        Chat with Redis-backed conversation history.
        History is automatically loaded from DB before first chat.
        """
        try:
            history = self._get_redis_history(session_id)
            
            # Build the prompt
            if system_prompt is None:
                system_prompt = "You are a helpful assistant."
            
            prompt = PromptTemplate.from_template(
                f"""{system_prompt}

            Chat History:
                {{chat_history}}

                Retrieved Context:
                {{context}}

                User Input:
                {{input}}

                    Response Instructions:
                    - Always return your answer as valid HTML (only the inner <body> content).
                    - Do not include <html>, <head>, or <body> tags.
                    - Use proper semantic HTML tags like <h1>, <h2>, <p>, <ul>, <li>, <strong>, etc.
                    - The output must be compact, without extra whitespace or line breaks.
                    - Do not wrap with ```html or markdown fences.
                    - If listing, use <ul><li>…</li></ul> or <ol><li>…</li></ol>.
                    - If formatting text, use <p>…</p>.

                Guardrails:
                - Do not disclose information about yourself (model, training, frameworks, etc.).
                - If asked about such things, reply with: "I'm here to assist you with your questions or tasks. Let's focus on that."

                Now generate the response strictly in HTML format.
            """
            )
            
            chain = create_stuff_documents_chain(self.llm, prompt)
            
            # Get chat history messages from Redis (includes DB history + current session)
            chat_history_messages = history.messages

            contextualize_q_system_prompt = (
                "Given a chat history and the latest user question "
                "which might reference context in the chat history, "
                "formulate a standalone question which can be understood "
                "without the chat history. Do NOT answer the question."
            )

            contextualize_q_prompt = ChatPromptTemplate.from_messages([
                ("system", contextualize_q_system_prompt),
                MessagesPlaceholder("chat_history"),
                ("human", "{input}"),
            ])

            history_aware_retriever = create_history_aware_retriever(
                self.llm,
                self.retriever,
                contextualize_q_prompt
            )


            chat_history_str = self._format_history_as_string(chat_history_messages)
            
            # Retrieve context documents
            # retrieved_docs = history_aware_retriever.invoke({
            #     "input": message,
            #     "chat_history": chat_history_messages,
            #     "org_id": org_id
            # })

            filename_docs = self._retrieve_by_filename(
                query=message,
                org_id=org_id,
                k=8
            )

            if filename_docs:
                retrieved_docs = filename_docs
                logger.info(
                    f"[CHAT_RETRIEVAL] Using filename-based retrieval: {len(retrieved_docs)} docs"
                )
            else:
                retrieved_docs = history_aware_retriever.invoke({
                    "input": message,
                    "chat_history": chat_history_messages,
                    "org_id": org_id
                })
                logger.info(
                    f"[CHAT_RETRIEVAL] Using semantic retrieval: {len(retrieved_docs)} docs"
                )

            # Limit chunk size
            MAX_CHUNK_CHAR = 3000
            for doc in retrieved_docs:
                if len(doc.page_content) > MAX_CHUNK_CHAR:
                    doc.page_content = doc.page_content[:MAX_CHUNK_CHAR]

            token_callback = TokenUsageCallback()
            
            # Invoke chain
            response = chain.invoke({
                "input": message,
                "context": retrieved_docs,
                "chat_history": chat_history_str
            },
            config={"callbacks": [token_callback]}
            )
            
            # Clean HTML output
            def clean_html_output(text: str) -> str:
                return re.sub(r'(\\n|\n)+', '', text)
            
            if isinstance(response, str):
                clean_response = clean_html_output(response)
            else:
                clean_response = clean_html_output(response.get("output_text", ""))
            
            answer = clean_response
            
            # Add user message to Redis (assistant message will be added after save_message)
            history.add_user_message(message)

            logger.info(f" User message saved to Redis for session: {session_id}")
            
            # Final cleanup
            # Prepare citations only when user is asking about files/documents
            source_trigger_words = [
                "file", "document", "doc", "pdf", "excel", "xlsx",
                "csv", "sheet", "uploaded", "source", "knowledge base",
                "according to", "from"
            ]

            # Prepare citations
            citations = [{
                "source": urllib.parse.unquote(
                    doc.metadata.get("source").split("?")[0].split("/")[-1]
                ),
                "source_path": doc.metadata.get("source_path"),
                "link": doc.metadata.get("source_path"),
                "snippet": doc.page_content[:300]
            } for doc in retrieved_docs if doc.metadata.get("source") and doc.metadata.get("source_path")]

            # Deduplicate sources
            unique_citations = []
            seen_sources = set()

            for c in citations:
                source = c.get("source")
                if source and source not in seen_sources:
                    unique_citations.append(c)
                    seen_sources.add(source)

            # Show max 1 source in chat
            citations = unique_citations[:1]

            casual_messages = [
                "hi", "hello", "hey", "hello there", "thanks", "thank you",
                "ok", "okay", "bye", "good morning", "good evening"
            ]

            normalized_message = message.strip().lower()

            # should_hide_sources = (
            #     normalized_message in casual_messages
            #     or len(normalized_message.split()) <= 2
            # )

            has_retrieved_docs = bool(retrieved_docs)

            should_hide_sources = (
                normalized_message in casual_messages
                and not has_retrieved_docs
            )

            file_path_and_name = None

            if citations and not should_hide_sources:
                try:
                    answer, file_path_and_name = annotate_with_citations(answer, citations)
                except Exception as e:
                    logger.warning(f"Annotation step failed: {e}")
            else:
                citations = []
                file_path_and_name = None
            answer = answer.strip().replace("``````", "").replace("```", "")    

            return {
                "answer": answer,
                "citations": citations,
                "file_path_and_name": file_path_and_name,
                "history": [{"type": msg.type, "content": msg.content} for msg in history.messages],
                "usage_metadata": {
                    "input_tokens": token_callback.prompt_tokens if token_callback.successful else None,
                    "output_tokens": token_callback.completion_tokens if token_callback.successful else None,
                    "total_tokens": token_callback.total_tokens if token_callback.successful else None
                }
            }
        
        except Exception as e:
            error_message = str(e)
            if "insufficient_quota" in error_message or "You exceeded your current quota" in error_message:
                logger.error(
                    f"[LLM_QUOTA] OpenAI API quota exceeded. Details: {error_message}",
                    exc_info=True
                )
                raise HTTPException(
                    status_code=429,
                    detail={
                        "status": "failure",
                        "message": "Error Generating Response",
                        "data": None
                    }
                )
            logger.error(f"Error in chat method: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail={
                    "status": "failure",
                    "message": "Error Generating Response",
                    "data": None
                }
            )

    @staticmethod
    def generate_chat_title(user_message: str, assistant_response: str, llm, min_words: int = 5) -> str:
        try:
            trivial_phrases = [
                "hi", "hello", "hey", "how are you", "good morning", "good evening",
                "what's up", "thank you", "thanks", "ok", "okay", "bye", "see you"
            ]

            def is_trivial(text: str) -> bool:
                stripped = text.strip().lower()
                return (
                    len(stripped.split()) < min_words or
                    any(phrase in stripped for phrase in trivial_phrases)
                )

            if is_trivial(user_message) and is_trivial(assistant_response):
                return "New Chat"

            messages = [
                SystemMessage(content="You are a helpful assistant that creates short and meaningful conversation titles. Only generate titles when the conversation contains clear, non-trivial content."),
                HumanMessage(content=f"User: {user_message}\nAssistant: {assistant_response}\n\nGive a concise 3-5 word title summarizing this conversation.")
            ]

            response = llm.invoke(messages)
            title = response.content.strip().strip('"')
            return title if len(title.split()) > 1 else "New Chat"

        except Exception as e:
            logger.error(f"Failed to generate title using llm: {e}")
            return "New Chat"

    def _priority_based_retriever(self) -> RunnableLambda:
        """Priority-based retriever with parallel ensemble → sequen tial parent doc → contextual compression."""
        logger.info(f"Building retriever for org_id: {self.org_id}")  # Add logging here
    
        try:
            # Build where clause conditionally
            where_clause = {"org_id": self.org_id} if self.org_id is not None else None
            
            if where_clause:
                self.all_documents = self.vectorstore._collection.get(
                    where=where_clause,
                    include=["metadatas", "documents"]  # IDs are returned by default
                )
            else:
                # Get all documents without filter
                self.all_documents = self.vectorstore._collection.get(
                    include=["metadatas", "documents"]  # IDs are returned by default
                )
        except Exception as e:
            logger.error(f"Error fetching documents: {e}", exc_info=True)
            self.all_documents = {"documents": [], "metadatas": [], "ids": []}
        
        # Create base vector retriever
        vector_search_kwargs = {"k": 5}
        if self.org_id is not None:
            vector_search_kwargs["filter"] = {"org_id": self.org_id}
        
        vector_retriever = self.vectorstore.as_retriever(
            search_kwargs=vector_search_kwargs
        )
        
        # Only create ensemble if documents exist
        if self.all_documents.get("documents"):
            # Convert to Document objects for BM25
            documents = [
                Document(
                    page_content=self.all_documents["documents"][i],
                    metadata=self.all_documents["metadatas"][i] if self.all_documents["metadatas"][i] else {}
                )
                for i in range(len(self.all_documents["documents"]))
            ]
            
            # BM25 retriever (keyword-based)
            bm25_retriever = BM25Retriever.from_documents(documents, k=5)
            
            # Multi-query retriever with vector search
            multi_query_retriever = MultiQueryRetriever.from_llm(
                retriever=vector_retriever,
                llm=self.llm,
                include_original=True
            )
            
            # Ensemble retriever (parallel retrieval)
            ensemble_retriever = EnsembleRetriever(
                retrievers=[bm25_retriever, vector_retriever, multi_query_retriever],
                weights=[0.2, 0.5, 0.3]
            )
            
            # Setup for contextual compression
            embeddings_filter = EmbeddingsFilter(
                embeddings=self.embedding_model,
                similarity_threshold=0.5
            )
            
            def retrieve(inputs) -> list[Document]:
                if isinstance(inputs, dict):
                    query = inputs.get("input", "")
                    org_id = (
                        str(inputs.get("org_id"))
                        if inputs.get("org_id") is not None
                        else None
                    )
                    mode = inputs.get("mode", "chat")
                else:
                    query = str(inputs)
                    org_id = (
                        str(self.org_id)
                        if self.org_id is not None
                        else None
                    )
                    mode = "chat"

                if not query.strip():
                    logger.info("Empty query received in retriever")
                    return []

                # file_match = re.search(
                #     r'([\w\s\-().]+?\.(?:pdf|docx|doc|pptx|ppt|xlsx|xls|csv|tsv|txt))',
                #     query,
                #     re.IGNORECASE
                # )

                # if file_match:
                #     requested_filename = file_match.group(1).strip().lower()

                #     all_results = self.vectorstore._collection.get(
                #         include=["documents", "metadatas"]
                #     )

                #     filename_docs = []

                #     for content, meta in zip(
                #         all_results.get("documents", []),
                #         all_results.get("metadatas", [])
                #     ):
                #         source = str(meta.get("source", "")).lower()
                #         source_path = str(meta.get("source_path", "")).lower()

                #         is_same_file = (
                #             requested_filename in source
                #             or requested_filename in source_path
                #         )

                #         is_same_org = (
                #             org_id is None
                #             or str(meta.get("org_id")) == str(org_id)
                #         )

                #         if is_same_file and is_same_org:
                #             filename_docs.append(
                #                 Document(
                #                     page_content=content,
                #                     metadata=meta
                #                 )
                #             )

                #     if filename_docs:
                #         logger.info(
                #             f"[FILENAME_ONLY_RETRIEVAL] "
                #             f"filename={requested_filename}, docs={len(filename_docs)}"
                #         )

                #         return filename_docs[:30]

                
                file_match = re.search(
                    r'([A-Za-z0-9_\-(). ]+\.(?:pdf|docx|doc|pptx|ppt|xlsx|xls|csv|tsv|txt))',
                    query,
                    re.IGNORECASE
                )

                if file_match:

                    def normalize_filename(name: str) -> str:
                        base = os.path.basename(
                            str(name).split("?")[0]
                        ).lower()

                        name_without_ext, ext = os.path.splitext(base)

                        # remove timestamps like _1781522443
                        name_without_ext = re.sub(
                            r'_\d+',
                            '',
                            name_without_ext
                        )

                        return f"{name_without_ext}{ext}"

                    requested_filename = (
                        file_match.group(1)
                        .strip()
                        .lower()
                    )

                    requested_normalized = normalize_filename(
                        requested_filename
                    )

                    all_results = self.vectorstore._collection.get(
                        include=["documents", "metadatas"]
                    )

                    filename_docs = []

                    for content, meta in zip(
                        all_results.get("documents", []),
                        all_results.get("metadatas", [])
                    ):

                        source_normalized = normalize_filename(
                            meta.get("source", "")
                        )

                        source_path_normalized = normalize_filename(
                            meta.get("source_path", "")
                        )

                        is_same_file = (
                            requested_normalized
                            == source_normalized
                            or requested_normalized
                            == source_path_normalized
                            or requested_normalized
                            in source_normalized
                            or requested_normalized
                            in source_path_normalized
                        )

                        is_same_org = (
                            org_id is None
                            or str(meta.get("org_id"))
                            == str(org_id)
                        )

                        if is_same_file and is_same_org:
                            filename_docs.append(
                                Document(
                                    page_content=content,
                                    metadata=meta
                                )
                            )

                    logger.info(f"Question: {query}")
                    logger.info(f"Compressed docs: {len(compressed_docs)}")     
                    logger.info(f"Filtered docs: {len(filtered_docs)}")
                    logger.info(f"Top source: {filtered_docs[0]['metadata'].get('source')}")


                    logger.info(
                        f"[FILENAME_RETRIEVAL] "
                        f"requested={requested_filename}, "
                        f"matched_docs={len(filename_docs)}"
                    )

                    if filename_docs:
                        return filename_docs[:30]

                    logger.warning(
                        f"No matching file found for "
                        f"{requested_filename}"
                    )

                    return []
                # Ensemble retrieval
                ensemble_docs = ensemble_retriever.invoke(query)

                logger.info(
                    f"Ensemble retrieval returned "
                    f"{len(ensemble_docs)} chunks"
                )

                # Parent document retrieval
                parent_docs = []
                seen_parent_ids = set()

                for doc in ensemble_docs:
                    doc_id = doc.metadata.get("doc_id")

                    if doc_id and doc_id not in seen_parent_ids:
                        try:
                            parent_result = self.vectorstore._collection.get(
                                ids=[doc_id],
                                include=["metadatas", "documents"]
                            )

                            if parent_result.get("documents"):
                                parent_doc = Document(
                                    page_content=parent_result["documents"][0],
                                    metadata=(
                                        parent_result["metadatas"][0]
                                        if parent_result.get("metadatas")
                                        and parent_result["metadatas"][0]
                                        else {}
                                    )
                                )

                                parent_docs.append(parent_doc)
                                seen_parent_ids.add(doc_id)

                            else:
                                parent_docs.append(doc)

                        except Exception as e:
                            logger.warning(
                                f"Could not fetch parent doc "
                                f"{doc_id}: {e}"
                            )
                            parent_docs.append(doc)

                    else:
                        parent_docs.append(doc)

                logger.info(
                    f"Retrieved {len(parent_docs)} "
                    f"parent documents"
                )

                spreadsheet_full_query = any(
                    phrase in query.lower()
                    for phrase in [
                        "all rows",
                        "all data",
                        "entire file",
                        "full file",
                        "complete file",
                        "complete data",
                        "show all",
                        "list all",
                        "how many rows",
                        "total rows",
                        "summarize excel",
                        "summarize csv",
                        "summarize spreadsheet",
                        "uploaded excel",
                        "uploaded csv",
                        "spreadsheet"
                    ]
                )

                # Compression
                compressed_docs = (
                    embeddings_filter.compress_documents(
                        parent_docs,
                        query
                    )
                )

                logger.info(
                    f"Contextual compression returned "
                    f"{len(compressed_docs)} docs"
                )

                if not compressed_docs and parent_docs:
                    spreadsheet_docs = []

                    for doc in parent_docs:
                        file_type = str(doc.metadata.get("file_type", "")).lower()
                        source = str(doc.metadata.get("source", "")).lower()
                        source_path = str(doc.metadata.get("source_path", "")).lower()

                        is_spreadsheet = (
                            file_type in ["xlsx", "xls", "csv", "tsv"]
                            or source.endswith((".xlsx", ".xls", ".csv", ".tsv"))
                            or source_path.split("?")[0].endswith((".xlsx", ".xls", ".csv", ".tsv"))
                        )

                        if is_spreadsheet:
                            spreadsheet_docs.append(doc)

                    logger.info(
                        f"[SPREADSHEET_FALLBACK_CHECK] "
                        f"parent_docs={len(parent_docs)}, "
                        f"spreadsheet_docs={len(spreadsheet_docs)}, "
                        f"sample_metadata={[doc.metadata for doc in parent_docs[:2]]}"
                    )

                    if spreadsheet_docs:
                        logger.warning(
                            f"Compression returned 0 docs, using "
                            f"{len(spreadsheet_docs)} spreadsheet docs fallback."
                        )
                        compressed_docs = spreadsheet_docs


                # Fallback ONLY for content generation
                if (
                    mode == "content_generation"
                    and not compressed_docs
                    and parent_docs
                ):
                    logger.warning(
                        f"Compression returned 0 docs. "
                        f"Falling back to "
                        f"{len(parent_docs)} parent docs."
                    )
                    compressed_docs = parent_docs

                # Org filtering
                filtered_docs = []

                for doc in compressed_docs:
                    doc_org_id = doc.metadata.get("org_id")

                    logger.info(
                        f"Doc org_id={doc_org_id} | "
                        f"Request org_id={org_id} | "
                        f"Mode={mode}"
                    )

                    if (
                        org_id is not None
                        and doc_org_id is not None
                    ):
                        if str(doc_org_id) != str(org_id):
                            continue

                    filtered_docs.append({
                        "document": doc.page_content,
                        "metadata": doc.metadata,
                        "similarity": doc.metadata.get(
                            "relevance_score",
                            0.7
                        )
                    })

                logger.info(
                    f"Final docs after org filter: "
                    f"{len(filtered_docs)}"
                )

                def sort_key(x):
                    priority = x["metadata"].get(
                        "priority",
                        999
                    )

                    try:
                        timestamp = -datetime.fromisoformat(
                            x["metadata"].get(
                                "timestamp",
                                datetime.min.isoformat()
                            )
                        ).timestamp()

                    except Exception:
                        timestamp = float("-inf")

                    similarity = -x["similarity"]

                    return (
                        priority,
                        timestamp,
                        similarity
                    )

                filtered_docs.sort(key=sort_key)

                # limit = (
                #     5
                #     if mode == "content_generation"
                #     else 1
                # )

                has_spreadsheet_docs = any(
                    str(doc["metadata"].get("file_type", "")).lower()
                    in ["xlsx", "xls", "csv", "tsv"]
                    for doc in filtered_docs
                )

                if mode == "content_generation":
                    limit = 20
                elif spreadsheet_full_query and has_spreadsheet_docs:
                    limit = 30
                else:
                    limit = 1

                final_docs = [
                    Document(
                        page_content=doc["document"],
                        metadata=doc["metadata"]
                    )
                    for doc in filtered_docs[:limit]
                ]

                logger.info(
                    f"Final docs returned: "
                    f"{len(final_docs)} | "
                    f"Mode={mode}"
                )

                return final_docs
                        
            return RunnableLambda(retrieve)
        
        else:
            # def simple_retrieve(inputs: Dict[str, Any]) -> list[Document]:
            #     query = inputs["input"]
            #     return vector_retriever.get_relevant_documents(query)
            def simple_retrieve(inputs) -> list[Document]:
                if isinstance(inputs, dict):
                    query = inputs.get("input", "")
                else:
                    query = str(inputs)

                return vector_retriever.get_relevant_documents(query)

            return RunnableLambda(simple_retrieve)


    # def normalize_filename(name: str) -> str:
    #     base = os.path.basename(str(name).split("?")[0]).lower()
    #     name_without_ext, ext = os.path.splitext(base)
    #     name_without_ext = re.sub(r'_\d+', '', name_without_ext)
    #     return f"{name_without_ext}{ext}"


    def _retrieve_by_filename(
        self,
        query: str,
        org_id: int,
        k: int = 8
    ) -> list[Document]:
        try:
            results = self.vectorstore._collection.get(
                where={"org_id": org_id},
                include=["documents", "metadatas"]
            )

            docs = results.get("documents", [])
            metas = results.get("metadatas", [])

            if not docs or not metas:
                return []

            normalized_query = self.normalize_filename(query)

            matched_docs = []

            for content, meta in zip(docs, metas):
                source = meta.get("source", "")
                source_path = meta.get("source_path", "")

                filename = os.path.basename(
                    urllib.parse.unquote(urlparse(source or source_path).path)
                )

                normalized_file = self._normalize_filename(filename)

                if filename and filename in normalized_query:
                    matched_docs.append(
                        Document(
                            page_content=content,
                            metadata=meta
                        )
                    )

            logger.info(
                f"[FILENAME_RETRIEVAL] query={query} matched_docs={len(matched_docs)}"
            )

            return matched_docs[:k]

        except Exception as e:
            logger.error(f"[FILENAME_RETRIEVAL_FAILED] {e}", exc_info=True)
            return []    


    def _rebuild_ensemble_retriever(self):
        """Rebuild BM25 and ensemble retriever after doc changes."""
        if not self.all_documents:
            return
        valid_docs = [
            doc for doc in self.all_documents["documents"] 
            if isinstance(doc, Document)
        ]
        self.bm25_retriever = BM25Retriever.from_documents(
            valid_docs, k=10
        )
        vector_retriever = self.vectorstore.as_retriever(
            search_kwargs={"k": 10}
        )
        self.ensemble_retriever = EnsembleRetriever(
            retrievers=[self.bm25_retriever, vector_retriever],
            weights=[0.6, 0.4]  # Tune for your preference
        )

    def add_document(self, file_path: str, priority: int, org_id: int):
        start_time = time.time()
        documents = []
        local_temp_path = None

        try:
            logger.info(f"Downloading file from: {file_path}")
            local_temp_path = self.download_to_temp_file(file_path)
            logger.info(f"Downloaded to temp path: {local_temp_path}")

            if not os.path.exists(local_temp_path):
                raise ValueError(f"Downloaded file not found: {local_temp_path}")
            
            file_size = os.path.getsize(local_temp_path)
            logger.info(f"Downloaded file size: {file_size} bytes")
            
            if file_size == 0:
                raise ValueError(f"Downloaded file is empty: {local_temp_path}")
            
            parsed_url = urlparse(file_path)
            filename = os.path.basename(parsed_url.path)
            logger.info(f"Processing filename: {filename}")

            logger.info("Starting document processing with OCR enabled")
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

            logger.info(
                f"Loaded {len(documents)} documents in "
                f"{time.time() - start_time:.2f}s"
            )

            # Keep metadata same as existing working retrieval logic.
            timestamp = datetime.now().isoformat()
            file_type = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

            logger.info(f"Processing filename: {filename}, file_type: {file_type}, timestamp: {timestamp}, org_id: {org_id}, priority: {priority}")
            source = unquote(urlparse(file_path).path)
            source_path_url = source
            logger.info(f"Source: {source}************************")

            for doc in documents:
                doc.metadata.update({
                    "priority": priority,
                    "source": source,
                    "source_path": file_path,
                    "timestamp": timestamp,
                    "org_id": org_id,
                    "file_type": file_type
                })

            chunked_documents = []
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=1500,
                chunk_overlap=300
            )

            # for doc in documents:
            #     chunked_documents.extend(
            #         text_splitter.create_documents(
            #             texts=[doc.page_content],
            #             metadatas=[doc.metadata]
            #         )
            #     )

            spreadsheet_types = [
                "csv",
                "tsv",
                "xlsx",
                "xls"
            ]

            for doc in documents:

                file_type = str(
                    doc.metadata.get(
                        "file_type",
                        ""
                    )
                ).lower()

                # Don't split spreadsheet rows
                if file_type in spreadsheet_types:
                    chunked_documents.append(doc)

                else:
                    chunked_documents.extend(
                        text_splitter.create_documents(
                            texts=[doc.page_content],
                            metadatas=[doc.metadata]
                        )
                    )

            texts_to_embed = [doc.page_content for doc in chunked_documents]
            usage_metadata = embedding_token_count(texts_to_embed, model=embed_model)

            logger.info(
                f"Created {len(chunked_documents)} chunks in "
                f"{time.time() - start_time:.2f}s"
            )

            BATCH_INSERT_SIZE = 25
            for i in range(0, len(chunked_documents), BATCH_INSERT_SIZE):
                batch = chunked_documents[i:i + BATCH_INSERT_SIZE]
                self.vectorstore.add_documents(batch)

            # Safe debug only. Does not change retrieval logic.
            try:

                vector_summary = self.list_documents()

                logger.info(
                    f"[VECTORSTORE_SUMMARY] "
                    f"documents={vector_summary['total_documents']} "
                    f"chunks={vector_summary['total_chunks']}"
                    f"source_path_url = {source_path_url}"
                    f"file_path = {file_path}"
                )

                results = self.vectorstore._collection.get(
                    where={"org_id": org_id},
                    include=["documents", "metadatas"]
                )

                logger.info(
                    f"[VECTOR_CHECK] org_id={org_id}, "
                    f"docs={len(results.get('documents', []))}"
                )

                logger.info(
                    f"[VECTOR_SAMPLE] "
                    f"{results.get('metadatas', [])[:2]}"
                )
            except Exception as debug_error:
                logger.warning(f"[VECTOR_CHECK_FAILED] {debug_error}")

            self.all_documents["documents"].extend(chunked_documents)
            self._rebuild_ensemble_retriever()
            self.retriever = self._priority_based_retriever()

            logger.info(
                f"Inserted into vectorstore in "
                f"{time.time() - start_time:.2f}s"
            )

            return usage_metadata

        except Exception as e:
            logger.error(f"Error in add_document: {e}", exc_info=True)
            return {
                "total_tokens": 0,
                "model": embed_model,
            }

        finally:
            if local_temp_path and os.path.exists(local_temp_path):
                try:
                    os.remove(local_temp_path)
                except Exception as cleanup_error:
                    logger.warning(f"Failed to remove temp file: {cleanup_error}")

    def delete_document(self, file_path: str):
        logger.info("Vector store cleared.")

        self.vectorstore._collection.delete(where={"source": file_path})
        logger.info("File successfully removed from vectorstore.")

        remaining = self.vectorstore._collection.get(
            where={"source": file_path},
            include=["metadatas"]
        )

        is_deleted = len(remaining["ids"]) == 0
        return is_deleted

    def list_documents(self):
        results = self.vectorstore._collection.get(include=["metadatas", "documents"])

        chunks_count = len(results.get("documents", []))
        metadatas = results.get("metadatas", [])

        documents_summary = {}
        for metadata in metadatas:
            if isinstance(metadata, dict):
                source = metadata.get("source") or metadata.get("document_id")
                if source:
                    if source not in documents_summary:
                        documents_summary[source] = {
                            "source": source,
                            "metadata": metadata
                        }

        documents_count = len(documents_summary)

        return {
            "total_documents": documents_count,
            "total_chunks": chunks_count,
            "documents": list(documents_summary.values())
        }

    def update_vectorstore_document(self, file_path: str, new_priority: int, org_id: int):
        try:
            existing_docs = self.vectorstore._collection.get(include=["metadatas", "documents"])
            file_docs_ids = [
                doc_id for doc_id, meta in zip(existing_docs["ids"], existing_docs["metadatas"])
                if meta.get("source_path") == file_path and meta.get("org_id") == org_id
            ]

            if not file_docs_ids:
                logger.warning(f"No matching documents found in vectorstore for update: {file_path}")
                return

            logger.info(f"Updating priority for {len(file_docs_ids)} chunks for {file_path}")
            updated_metadata = [{"priority": new_priority}] * len(file_docs_ids)
            self.vectorstore._collection.update(ids=file_docs_ids, metadatas=updated_metadata)
            
            logger.info(f"Updated priority to {new_priority} for {file_path}")

        except Exception as e:
            logger.error(f"Error while updating vectorstore priority for file {file_path}: {e}", exc_info=True)

    def clear_vectorstore(self):
        all_docs = self.vectorstore._collection.get()
        all_ids = all_docs.get("ids", [])

        if not all_ids:
            logger.info("Vectorstore is already empty.")
            return

        self.vectorstore._collection.delete(ids=all_ids)
        logger.info(f"Cleared {len(all_ids)} documents from the vector store.")

    def download_to_temp_file(self,file_url: str) -> str:
        parsed_url = urlparse(file_url)
        response = requests.get(file_url)
        response.raise_for_status()
        response.raise_for_status()        
        path = parsed_url.path
        ext = os.path.splitext(path)[1] or ".tmp"
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        temp_file.write(response.content)
        temp_file.close()
        return temp_file.name
