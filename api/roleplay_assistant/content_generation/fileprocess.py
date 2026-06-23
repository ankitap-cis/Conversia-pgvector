"""
fileprocess.py - Document processing and summarization with retrieval
"""

import logging
from typing import Optional, List, Tuple
from pathlib import Path
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.chains.summarize import load_summarize_chain
from langchain.prompts import PromptTemplate
from langchain_core.documents import Document
from fastapi import HTTPException, status, UploadFile
from utils.file_loaders import process_document
from .utility import handle_openai_error, initialize_llm, log_extraction_start
import asyncio
import configparser
from utils.GKB_retriever import _retrieve_similar_documents

config = configparser.ConfigParser()
config.read('config.ini')

content_generation_maxtokens = config['openAI_config'].getint('content_generation_maxtokens', 4000)
opeanai_api_key = config['openAI_config'].get('key', None)
model = config['openAI_config'].get('model', 'gpt-4o-mini')

logger = logging.getLogger(__name__)


class DocumentSummaryResult(BaseModel):
    summary: str = Field(description="Summarized document text")
    method_used: str = Field(description="Summarization method used")
    retrieved_docs: List[Document] = Field(default_factory=list, description="Retrieved similar documents")
    retrieval_metadata: dict = Field(default_factory=dict, description="Retrieval statistics")

DEFAULT_SUMMARY_FALLBACK = "Document content processed. Key information extracted for context."

async def summarize_document(
    file: Optional[UploadFile] = None,
    file_path: Optional[str] = None,
    file_bytes: Optional[bytes] = None,
    filename: Optional[str] = None,
    max_context_tokens: int = content_generation_maxtokens,
    chunk_size: int = 4000,
    chunk_overlap: int = 200,
    openai_api_key: Optional[str] = opeanai_api_key,
    model: str = model,
    temperature: float = 0.0,
    enable_ocr: bool = True,
    use_fallback: bool = True,
    return_detailed: bool = False,
    enable_retrieval: bool = True,
    general_bot = None,
    org_id: Optional[int] = None,
    max_retrieved_docs: int = 5
) -> str | DocumentSummaryResult:
    try:
        log_extraction_start(
            filename or "unknown",
            model,
            {
                "max_context_tokens": max_context_tokens,
                "chunk_size": chunk_size,
                "enable_retrieval": enable_retrieval
            }
        )
        
        logger.info("Step 1: Processing document to extract text")
        extracted_text = None
        
        if file is not None:
            file_bytes = await file.read()
            filename = file.filename
            logger.info(
                f"Processing UploadFile: {filename}",
                extra={"filename": filename, "size_bytes": len(file_bytes)}
            )
            extracted_text = await process_document(
                source=file_bytes,
                filename=filename,
                return_documents=False,
                enable_ocr=enable_ocr
            )
            
        elif file_path is not None:
            logger.info(
                f"Processing file from path: {file_path}",
                extra={"file_path": file_path}
            )
            documents = await process_document(
                source=file_path,
                filename=filename or Path(file_path).name,
                enable_ocr=enable_ocr,
                ocr_language="eng",
                ocr_dpi=300,
                return_documents=True
            )
            if isinstance(documents, list):
                extracted_text = "\n\n".join([doc.page_content for doc in documents])
            else:
                extracted_text = documents
                
        elif file_bytes is not None:
            logger.info(
                f"Processing raw bytes",
                extra={"size_bytes": len(file_bytes), "filename": filename}
            )
            extracted_text = await process_document(
                source=file_bytes,
                filename=filename or "document",
                return_documents=False,
                enable_ocr=enable_ocr
            )
        
        else:
            logger.error("No file source provided")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Must provide file, file_path, or file_bytes"
            )
        
        if not extracted_text or not extracted_text.strip():
            logger.error("Document processing returned empty text")
            if use_fallback:
                logger.warning("Empty extraction - using fallback summary")
                if return_detailed:
                    return DocumentSummaryResult(
                        summary=DEFAULT_SUMMARY_FALLBACK,
                        method_used="fallback",
                        retrieved_docs=[],
                        retrieval_metadata={"status": "skipped", "reason": "empty_extraction"}
                    )
                else:
                    return DEFAULT_SUMMARY_FALLBACK
            else:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Document processing returned empty text"
                )
        original_length = len(extracted_text)
        logger.info(
            f"Document text extracted successfully",
            extra={"original_length": original_length, "filename": filename}
        )
        
        llm = initialize_llm(model, temperature, openai_api_key)
        current_tokens = llm.get_num_tokens(extracted_text)
        logger.info(
            f"Document token count: {current_tokens}",
            extra={"current_tokens": current_tokens, "max_tokens": max_context_tokens}
        )
        
        summary = None
        method_used = "none"
        
        if current_tokens <= max_context_tokens * 2:
            logger.info("Skipping summarization for speed")
            return DocumentSummaryResult(
            summary=extracted_text[:max_context_tokens * 4],  # Truncate only
            method_used="truncate_only",
            retrieved_docs=[],
            retrieval_metadata={"status": "disabled"}
            )

        else:
            logger.info("Step 2: Splitting document into chunks")
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                length_function=len,
                separators=["\n\n", "\n", ". ", " ", ""]
            )
            
            chunks = text_splitter.create_documents([extracted_text])
            logger.info(
                f"Document split into {len(chunks)} chunks",
                extra={"chunk_count": len(chunks)}
            )
            
            if len(chunks) == 0:
                logger.error("Text splitting returned no chunks")
                if use_fallback:
                    if return_detailed:
                        return DocumentSummaryResult(
                            summary=DEFAULT_SUMMARY_FALLBACK,
                            method_used="fallback",
                            retrieved_docs=[],
                            retrieval_metadata={"status": "skipped", "reason": "no_chunks"}
                        )
                    else:
                        return DEFAULT_SUMMARY_FALLBACK
                else:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Text splitting failed"
                    )
            
            logger.info(f"Step 3: Summarizing with method: map_reduce")
            
            map_prompt_template = """
            Write a comprehensive summary of the following text that preserves all key information, important details, facts, and main points:
            Text:
            {text}
            COMPREHENSIVE SUMMARY:
            """
            combine_prompt_template = """
            Write a cohesive summary that combines and synthesizes the following summaries. Preserve all important information, key facts, and main points while maintaining logical flow:

            Summaries:
            {text}

            FINAL COMPREHENSIVE SUMMARY:
            """
            map_prompt = PromptTemplate(template=map_prompt_template, input_variables=["text"])
            combine_prompt = PromptTemplate(template=combine_prompt_template, input_variables=["text"])
            try:
                stuff_prompt_template = """
                Write a comprehensive summary of the following documents that preserves all key information, important details, facts, and main points while maintaining logical flow:

                Documents:
                {text}

                COMPREHENSIVE SUMMARY:
                """

                custom_prompt = PromptTemplate(
                    template=stuff_prompt_template, 
                    input_variables=["text"]
                )
                chain = load_summarize_chain(
                    llm,
                    chain_type="stuff",
                    prompt=custom_prompt,
                    verbose=False
                )
                result = await chain.ainvoke({"input_documents": chunks})
                summary = result["output_text"]
                method_used = "map_reduce"
                
                logger.info(
                    f"Summarization complete",
                    extra={"method": "map_reduce", "summary_length": len(summary)}
                )
                
            except Exception as e:
                return await handle_openai_error(
                    e,
                    "document_summarization",
                    DocumentSummaryResult(
                        summary=DEFAULT_SUMMARY_FALLBACK,
                        method_used="fallback",
                        retrieved_docs=[],
                        retrieval_metadata={"status": "skipped", "reason": "summarization_error"}
                    ) if return_detailed else DEFAULT_SUMMARY_FALLBACK,
                    use_fallback
                )
            summary_tokens = llm.get_num_tokens(summary)
            logger.info(
                f"Summary token count: {summary_tokens}",
                extra={"summary_tokens": summary_tokens, "max_tokens": max_context_tokens}
            )
            if summary_tokens > max_context_tokens:
                logger.warning(
                    f"Summary still exceeds token limit ({summary_tokens} > {max_context_tokens}), applying recursive compression"
                )
                compression_result = await summarize_document(
                    file_bytes=summary.encode('utf-8'),
                    filename=f"compressed_{filename}",
                    max_context_tokens=max_context_tokens,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    openai_api_key=openai_api_key,
                    model=model,
                    temperature=temperature,
                    enable_ocr=False,
                    use_fallback=use_fallback,
                    return_detailed=False,
                    enable_retrieval=True 
                )
                summary = compression_result if isinstance(compression_result, str) else compression_result.summary
        retrieved_docs = []
        retrieval_metadata = {"status": "skipped", "reason": "not_enabled"}
        if enable_retrieval and general_bot is not None:
            logger.info("Step 4: Retrieving similar documents using summary as query")
            try:
                retrieved_docs, retrieval_metadata = await _retrieve_similar_documents(
                    query=summary,
                    general_bot=general_bot,
                    org_id=org_id,
                    max_docs=max_retrieved_docs
                )
            except Exception as retrieval_error:
                logger.warning(
                    f"Retrieval failed, continuing without similar docs: {retrieval_error}"
                )
                retrieval_metadata = {
                    "status": "failed",
                    "error": str(retrieval_error),
                    "docs_found": 0
                }
        
        logger.info(
            f"Document summarization complete",
            extra={
                "original_length": original_length,
                "summary_length": len(summary),
                "method_used": method_used,
                "docs_retrieved": len(retrieved_docs)
            }
        )
        
        if enable_retrieval:
            return DocumentSummaryResult(
                summary=summary,
                method_used=method_used,
                retrieved_docs=retrieved_docs,
                retrieval_metadata=retrieval_metadata
            )
        else:
            return summary
            
    except HTTPException:
        raise
        
    except Exception as e:
        return await handle_openai_error(
            e,
            "document_summarization",
            DocumentSummaryResult(
                summary=DEFAULT_SUMMARY_FALLBACK,
                method_used="fallback",
                retrieved_docs=[],
                retrieval_metadata={"status": "error", "error": str(e)}
            ) if return_detailed else DEFAULT_SUMMARY_FALLBACK,
            use_fallback
        )
    