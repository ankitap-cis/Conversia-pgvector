import os
import subprocess
from pathlib import Path
from logger import *
from langchain.document_loaders import PyPDFLoader, TextLoader 
from langchain_community.document_loaders import TextLoader, PyPDFLoader, UnstructuredWordDocumentLoader, UnstructuredPowerPointLoader
from langchain.schema import Document
import fitz

# Remove async and rename the function
def load_document(local_temp_path: str, ext: str) -> list[Document]:
    """Synchronous document loader that returns documents directly."""
    
    if ext == "pdf":
        try:
            documents = _load_pdf_document(local_temp_path)
            return documents
        except Exception as e:
            logger.warning(f"PyPDFLoader failed, trying fallback: {e}")
            fallback_text = read_pdf_multiple_methods(local_temp_path)
            if fallback_text:
                return [Document(page_content=fallback_text)]
            return []

    elif ext == "txt":
        return _load_text_document(local_temp_path)

    elif ext in ["doc", "docx"]:
        return _load_word_document(local_temp_path, ext)

    elif ext in ["ppt", "pptx"]:
        return _load_powerpoint_document(local_temp_path)

    else:
        logger.warning(f"Unsupported file format: {ext}")
        return []

def _load_pdf_document(local_temp_path: str) -> list[Document]:
    """Synchronous PDF document loading"""
    try:
        loader = PyPDFLoader(local_temp_path)
        documents = loader.load()
        logger.info(f"Loaded {len(documents)} PDF pages using PyPDFLoader")
        return documents
    except Exception as e:
        logger.warning(f"PyPDFLoader failed: {e}")
        raise e

def _load_text_document(local_temp_path: str) -> list[Document]:
    """Synchronous text document loading"""
    try:
        loader = TextLoader(local_temp_path)
        documents = loader.load()
        logger.info(f"Loaded text document with {len(documents)} sections")
        return documents
    except Exception as e:
        logger.error(f"Failed to load text document: {e}")
        raise e

def _load_word_document(local_temp_path: str, ext: str) -> list[Document]:
    """Synchronous Word document loading"""
    try:
        if ext == "doc":
            local_temp_path = convert_doc_to_docx(local_temp_path)
        
        loader = UnstructuredWordDocumentLoader(local_temp_path)
        documents = loader.load()
        logger.info(f"Loaded Word document with {len(documents)} sections")
        return documents
    except Exception as e:
        logger.error(f"Failed to load Word document: {e}")
        raise e

def _load_powerpoint_document(local_temp_path: str) -> list[Document]:
    """Synchronous PowerPoint document loading"""
    try:
        loader = UnstructuredPowerPointLoader(local_temp_path)
        documents = loader.load()
        logger.info(f"Loaded PowerPoint document with {len(documents)} slides")
        return documents
    except Exception as e:
        logger.error(f"Failed to load PowerPoint document: {e}")
        raise e

def read_pdf_multiple_methods(file_path):
    """Fallback PDF reading method"""
    file_path = Path(file_path)
    try:
        doc = fitz.open(file_path)
        text_content = ""
        for page_num in range(doc.page_count):
            try:
                page = doc.load_page(page_num)
                page_text = page.get_text()
                text_content += f"\n--- Page {page_num + 1} ---\n{page_text}\n"
            except Exception as e:
                logger.error(f"Error reading page {page_num + 1}: {e}")
        doc.close()
        if text_content.strip():
            return text_content
    except Exception as e:
        logger.error(f"Fallback PDF parsing failed: {e}")
        return ""

def convert_doc_to_docx(doc_path):
    """Convert .doc to .docx using LibreOffice"""
    output_dir = os.path.dirname(doc_path)
    subprocess.run([
        "libreoffice", "--headless", "--convert-to", "docx", "--outdir", output_dir, doc_path
    ], check=True)
    
    return os.path.join(output_dir, os.path.splitext(os.path.basename(doc_path))[0] + ".docx")