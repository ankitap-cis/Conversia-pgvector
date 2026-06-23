import os
import io
import asyncio
import subprocess
import configparser
from pathlib import Path
from typing import Optional, List, Union
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from functools import partial
from models.users import Organization
import fitz  # PyMuPDF
import docx2txt
import textract
from langchain.schema import Document
from langchain_community.document_loaders import (
    PyPDFLoader, 
    TextLoader, 
    UnstructuredWordDocumentLoader, 
    UnstructuredPowerPointLoader
)

from logger import logger
from openai import OpenAI
import base64
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError


config = configparser.ConfigParser()
config.read("config.ini")
OPENAI_API_KEY = config["openAI_config"]["key"]


_easyocr_reader = None
_paddleocr_reader = None

_io_executor = ThreadPoolExecutor(max_workers=2)
_cpu_executor = ProcessPoolExecutor(max_workers=2)


# OCR Configuration

class OCRConfig:
    """OCR fallback configuration"""
    ENABLE_TESSERACT = False 
    ENABLE_EASYOCR = False    
    ENABLE_PADDLEOCR = False 
    ENABLE_OPENAI = True 

    # Timeout configuration
    OPENAI_TIMEOUT = 15  # seconds
    TESSERACT_TIMEOUT = 5  # seconds
    
    MIN_TEXT_THRESHOLD = 50
    
    MIN_CONFIDENCE = 0.5
    
    OPENAI_MODEL = "gpt-4o-mini" 
    OPENAI_MAX_TOKENS = 4096


def _get_easyocr_reader(languages=['en']):
    global _easyocr_reader
    if _easyocr_reader is None:
        try:
            import easyocr
            _easyocr_reader = easyocr.Reader(languages, gpu=False)
            logger.info("EasyOCR reader initialized")
        except ImportError:
            logger.warning("EasyOCR not installed. Install with: pip install easyocr")
            return None
        except Exception as e:
            logger.error(f"Failed to initialize EasyOCR: {e}")
            return None
    return _easyocr_reader


def _get_paddleocr_reader(language='en'):
    global _paddleocr_reader
    if _paddleocr_reader is None:
        try:
            from paddleocr import PaddleOCR
            _paddleocr_reader = PaddleOCR(
                use_angle_cls=True,
                lang=language,
            )
            logger.info("PaddleOCR reader initialized")
        except ImportError:
            logger.warning("PaddleOCR not installed. Install with: pip install paddleocr")
            return None
        except Exception as e:
            logger.error(f"Failed to initialize PaddleOCR: {e}")
            return None
    return _paddleocr_reader


# Unified Public Interface

async def process_document(
    source: Union[str, bytes],
    filename: str,
    enable_ocr: bool = True,
    enable_openai: bool = True,
    ocr_language: str = "eng",
    ocr_dpi: int = 200,
    return_documents: bool = True
) -> Union[List[Document], str, None]:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if not ext:
        logger.warning(f"No file extension detected for: {filename}")
        return [] if return_documents else None
    
    if isinstance(source, str):
        if not os.path.exists(source):
            logger.error(f"File not found: {source}")
            return [] if return_documents else None
        
        if return_documents:
            return await load_document_async(
                local_temp_path=source,
                ext=ext,
                enable_ocr=enable_ocr,
                ocr_language=ocr_language,
                ocr_dpi=ocr_dpi
            )
        else:
            loop = asyncio.get_event_loop()
            file_bytes = await loop.run_in_executor(
                _io_executor,
                _read_file_sync,
                source
            )
            return await extract_text_from_bytes_async(
                filename=filename,
                file_bytes=file_bytes,
                enable_ocr=enable_ocr,
                ocr_language=ocr_language,
                ocr_dpi=ocr_dpi
            )
    
    elif isinstance(source, bytes):
        if return_documents:
            return await _bytes_to_documents(
                file_bytes=source,
                filename=filename,
                ext=ext,
                enable_ocr=enable_ocr,
                ocr_language=ocr_language,
                ocr_dpi=ocr_dpi
            )
        else:
            return await extract_text_from_bytes_async(
                filename=filename,
                file_bytes=source,
                enable_ocr=enable_ocr,
                ocr_language=ocr_language,
                ocr_dpi=ocr_dpi
            )
    
    else:
        logger.error(f"Invalid source type: {type(source)}")
        return [] if return_documents else None


async def _bytes_to_documents(
    file_bytes: bytes,
    filename: str,
    ext: str,
    enable_ocr: bool,
    ocr_language: str,
    ocr_dpi: int
) -> List[Document]:
    """Convert bytes to Documents by saving to temp file and loading."""
    import tempfile
    
    try:
        with tempfile.NamedTemporaryFile(
            mode='wb',
            suffix=f'.{ext}',
            delete=False
        ) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        
        documents = await load_document_async(
            local_temp_path=tmp_path,
            ext=ext,
            enable_ocr=enable_ocr,
            ocr_language=ocr_language,
            ocr_dpi=ocr_dpi
        )
        
        for doc in documents:
            doc.metadata['source'] = filename
        
        return documents
    
    except Exception as e:
        logger.error(f"Failed to convert bytes to documents: {e}", exc_info=True)
        return []
    
    finally:
        try:
            if 'tmp_path' in locals():
                os.unlink(tmp_path)
        except Exception:
            pass


def _read_file_sync(file_path: str) -> bytes:
    """Synchronous file reading (runs in thread pool)."""
    with open(file_path, 'rb') as f:
        return f.read()


# Document Loading (File Path -> Documents)

async def load_document_async(
    local_temp_path: str, 
    ext: str,
    enable_ocr: bool = True,
    ocr_language: str = "eng",
    ocr_dpi: int = 300
) -> List[Document]:
    """Load document from file path, returns LangChain Documents."""
    ext = ext.lower().strip(".")
    
    try:
        if ext == "pdf":
            return await _load_pdf_async(
                local_temp_path, 
                enable_ocr=enable_ocr,
                language=ocr_language,
                dpi=ocr_dpi
            )
        
        elif ext == "txt":
            return await _load_text_async(local_temp_path)
        
        elif ext in ["doc", "docx"]:
            return await _load_word_async(local_temp_path, ext)
        
        elif ext in ["ppt", "pptx"]:
            return await _load_powerpoint_async(local_temp_path)

        elif ext in ["csv", "tsv"]:
            return await _load_csv_async(local_temp_path)

        elif ext in ["xlsx", "xls"]:
            return await _load_excel_async(local_temp_path)
        
        elif ext in ["jpg", "jpeg", "png", "heic", "heif", "bmp", "tiff", "tif", "webp"]:
            return await _load_image_async(
                local_temp_path,
                enable_ocr=enable_ocr,
                language=ocr_language
            )
        
        else:
            logger.warning(f"Unsupported file format: {ext}")
            return []
    
    except Exception as e:
        logger.error(f"Failed to load document {local_temp_path}: {e}", exc_info=True)
        return []
    
async def _load_image_async(
    file_path: str,
    enable_ocr: bool = True,
    language: str = "eng"
) -> List[Document]:
    if not enable_ocr:
        logger.warning(f"OCR disabled, cannot extract text from image: {file_path}")
        return []
    
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _cpu_executor,
        _extract_image_with_openai_ocr,
        file_path,
        language
    )

# Text Extraction (Bytes -> String)

async def extract_text_from_bytes_async(
    filename: str, 
    file_bytes: bytes,
    enable_ocr: bool = True,
    ocr_language: str = "eng",
    ocr_dpi: int = 300
) -> Optional[str]:
    """Extract plain text from file bytes."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    
    try:
        if ext == "pdf":
            return await _extract_pdf_bytes_async(
                file_bytes,
                enable_ocr=enable_ocr,
                language=ocr_language,
                dpi=ocr_dpi
            )
        
        elif ext == "txt":
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                _io_executor,
                partial(file_bytes.decode, "utf-8", errors="ignore")
            )
        
        elif ext == "docx":
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                _cpu_executor,
                _extract_docx_bytes,
                file_bytes
            )
        
        elif ext in ["doc", "ppt", "pptx"]:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                _cpu_executor,
                _extract_with_textract,
                file_bytes
            )
        
        elif ext in ["jpg", "jpeg", "png", "heic", "heif", "bmp", "tiff", "tif", "webp"]:
            return await _extract_image_bytes_async(
                file_bytes,
                language=ocr_language
            )
        
        else:
            logger.warning(f"Unsupported file format for byte extraction: {ext}")
            return None
    
    except Exception as e:
        logger.error(f"Failed to extract text from {filename}: {e}", exc_info=True)
        return None


# PDF Processing with Advanced OCR

async def _load_pdf_async(
    file_path: str,
    enable_ocr: bool = True,
    language: str = "eng",
    dpi: int = 200
) -> List[Document]:
    """Load PDF with multi-level OCR fallback."""
    try:
        loop = asyncio.get_event_loop()
        documents = await loop.run_in_executor(
            _io_executor,
            _load_with_pypdf,
            file_path
        )
        
        total_text = sum(len(doc.page_content.strip()) for doc in documents)
        
        if total_text > 100:
            logger.info(f"Loaded {len(documents)} PDF pages with PyPDFLoader")
            return documents
        
        logger.warning("PyPDFLoader extracted minimal text, falling back to advanced OCR")
    
    except Exception as e:
        logger.warning(f"PyPDFLoader failed: {e}")
    
    # Fallback: PyMuPDF with multi-level OCR
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _cpu_executor,
        _extract_pdf_with_advanced_ocr,
        file_path,
        enable_ocr,
        language,
        dpi
    )

def _load_with_pypdf(file_path: str) -> List[Document]:
    """Synchronous PyPDFLoader (runs in thread pool)."""
    loader = PyPDFLoader(file_path)
    return loader.load()

def _extract_pdf_with_advanced_ocr(
    file_path: str,
    enable_ocr: bool,
    language: str,
    dpi: int
) -> List[Document]:
    """
    Extract PDF with PyMuPDF, using multi-level OCR fallback.
    Runs in process pool (CPU-bound).
    """
    documents = []
    try:
        with fitz.open(file_path) as doc:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            def process_page(page_data):
                page, page_num = page_data
                try:
                    text = page.get_text()
                    
                    if enable_ocr and len(text.strip()) < OCRConfig.MIN_TEXT_THRESHOLD:
                        text = _apply_multi_level_ocr(page, page_num, language, dpi)
                    
                    return page_num, text, None
                except Exception as page_error:
                    logger.error(f"Error processing page {page_num + 1}: {page_error}")
            
            page_data_list = [(doc[i], i) for i in range(len(doc))]
            results = {}
            with ThreadPoolExecutor(max_workers=min(2, len(doc))) as executor:
                futures = {executor.submit(process_page, data): data[1] 
                           for data in page_data_list}
                
                for future in as_completed(futures):
                    page_num, text, error = future.result()
                    results[page_num] = (text, error)
            
            for page_num in sorted(results.keys()):
                text, error = results[page_num]
                documents.append(Document(
                    page_content=text,
                    metadata={"page": page_num + 1, "source": file_path}
                ))
        
        logger.info(f"Extracted {len(documents)} pages from PDF")
        return documents
    
    except Exception as e:
        logger.error(f"PyMuPDF extraction failed: {e}")
        return []

def _extract_image_with_openai_ocr(
    file_path: str,
    language: str
) -> List[Document]:
    try:
        with open(file_path, 'rb') as f:
            img_bytes = f.read()
        
        text, confidence = _extract_text_with_openai(img_bytes, language)
        
        if len(text.strip()) < OCRConfig.MIN_TEXT_THRESHOLD:
            logger.warning(f"OpenAI OCR extracted minimal text from {file_path}")
        
        logger.info(f"Extracted {len(text)} characters from image with confidence {confidence}")
        
        return [Document(
            page_content=text,
            metadata={
                "source": file_path,
                "ocr_confidence": confidence,
                "ocr_method": "openai_vision"
            }
        )]
    except Exception as e:
        logger.error(f"Failed to extract text from image {file_path}: {e}", exc_info=True)
        return []

def ocr_timeout_handler(func):
    from functools import wraps
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
    
    @wraps(func)
    def wrapper(page, page_num: int, language: str, dpi: int) -> str:
        if OCRConfig.ENABLE_TESSERACT and not OCRConfig.ENABLE_OPENAI:
            return func(page, page_num, language, dpi)
        
        if OCRConfig.ENABLE_OPENAI:
            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(func, page, page_num, language, dpi)
                    result = future.result(timeout=OCRConfig.OPENAI_TIMEOUT)
                    
                    if result and len(result.strip()) >= OCRConfig.MIN_TEXT_THRESHOLD:
                        return result
            except FuturesTimeoutError:
                logger.warning(f"OpenAI OCR timeout after {OCRConfig.OPENAI_TIMEOUT}s on page {page_num + 1}, trying Tesseract")
            except Exception as e:
                logger.warning(f"OCR failed on page {page_num + 1}: {e}")
            
            original_openai = OCRConfig.ENABLE_OPENAI
            original_tesseract = OCRConfig.ENABLE_TESSERACT
            
            try:
                OCRConfig.ENABLE_OPENAI = False
                OCRConfig.ENABLE_TESSERACT = True
                
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(func, page, page_num, language, dpi)
                    result = future.result(timeout=OCRConfig.TESSERACT_TIMEOUT)
                    
                    if result and len(result.strip()) >= OCRConfig.MIN_TEXT_THRESHOLD:
                        return result
            except FuturesTimeoutError:
                logger.warning(f"Tesseract fallback timeout after {OCRConfig.TESSERACT_TIMEOUT}s on page {page_num + 1}")
            except Exception as e:
                logger.warning(f"Tesseract fallback failed on page {page_num + 1}: {e}")
            finally:
                OCRConfig.ENABLE_OPENAI = original_openai
                OCRConfig.ENABLE_TESSERACT = original_tesseract
            
            return "[OCR failed: Document could not be processed. Please try uploading again or use a different file format.]"
        
        else:
            return func(page, page_num, language, dpi)
    
    return wrapper

@ocr_timeout_handler
def _apply_multi_level_ocr(page, page_num: int, language: str, dpi: int) -> str:
    text = ""
    
    # Tesseract via PyMuPDF
    if OCRConfig.ENABLE_TESSERACT:
        try:
            tp = page.get_textpage_ocr(dpi=dpi, language=language)
            text = page.get_text(textpage=tp)
            if len(text.strip()) >= OCRConfig.MIN_TEXT_THRESHOLD:
                logger.info(f"Tesseract OCR succeeded on page {page_num + 1}")
                return text
            logger.debug(f"Tesseract extracted minimal text on page {page_num + 1}")
        except Exception as e:
            logger.warning(f"Tesseract OCR failed on page {page_num + 1}: {e}")
    
    # EasyOCR
    if OCRConfig.ENABLE_EASYOCR:
        try:
            pix = page.get_pixmap(dpi=dpi)
            img_bytes = pix.tobytes("png")
            
            reader = _get_easyocr_reader([_map_language_code(language)])
            if reader:
                import numpy as np
                from PIL import Image
                
                img = Image.open(io.BytesIO(img_bytes))
                img_array = np.array(img)
                
                results = reader.readtext(img_array)
                text = "\n".join([res[1] for res in results if res[2] >= OCRConfig.MIN_CONFIDENCE])
                
                if len(text.strip()) >= OCRConfig.MIN_TEXT_THRESHOLD:
                    logger.info(f"EasyOCR succeeded on page {page_num + 1}")
                    return text
                logger.debug(f"EasyOCR extracted minimal text on page {page_num + 1}")
        except Exception as e:
            logger.warning(f"EasyOCR failed on page {page_num + 1}: {e}")
    
    if OCRConfig.ENABLE_OPENAI:
        try:
            pix = page.get_pixmap(dpi=dpi)
            img_bytes = pix.tobytes("png")
            
            text, confidence = _extract_text_with_openai(img_bytes, language)
            
            if len(text.strip()) >= OCRConfig.MIN_TEXT_THRESHOLD and confidence >= OCRConfig.MIN_CONFIDENCE:
                logger.info(f"OpenAI Vision OCR succeeded on page {page_num + 1}")
                return text
            logger.debug(f"OpenAI Vision extracted minimal text on page {page_num + 1}")
        except Exception as e:
            logger.warning(f"OpenAI Vision OCR failed on page {page_num + 1}: {e}")
    
    # PaddleOCR
    if OCRConfig.ENABLE_PADDLEOCR:
        try:
            pix = page.get_pixmap(dpi=dpi)
            img_bytes = pix.tobytes("png")
            
            reader = _get_paddleocr_reader(_map_language_code(language))
            if reader:
                import numpy as np
                from PIL import Image
                
                img = Image.open(io.BytesIO(img_bytes))
                img_array = np.array(img)
                
                results = reader.ocr(img_array, cls=True)
                
                if results and results[0]:
                    text_lines = []
                    for line in results[0]:
                        if line[1][1] >= OCRConfig.MIN_CONFIDENCE:  # Check confidence
                            text_lines.append(line[1][0])
                    text = "\n".join(text_lines)
                    
                    if len(text.strip()) >= OCRConfig.MIN_TEXT_THRESHOLD:
                        logger.info(f"PaddleOCR succeeded on page {page_num + 1}")
                        return text
                logger.debug(f"PaddleOCR extracted minimal text on page {page_num + 1}")
        except Exception as e:
            logger.warning(f"PaddleOCR failed on page {page_num + 1}: {e}")
    
    # If all OCR methods failed, return whatever we have
    logger.warning(f"All OCR methods produced minimal text on page {page_num + 1}")
    return text

def _map_language_code(tesseract_lang: str) -> str:
    lang_map = {
        'eng': 'en',
        'fra': 'fr',
        'deu': 'de',
        'spa': 'es',
        'ita': 'it',
        'por': 'pt',
        'rus': 'ru',
        'chi_sim': 'ch',
        'chi_tra': 'chinese_cht',
        'jpn': 'japan',
        'kor': 'korean',
        'ara': 'arabic',
        'hin': 'hi',
    }
    return lang_map.get(tesseract_lang, 'en')

async def _extract_pdf_bytes_async(
    file_bytes: bytes,
    enable_ocr: bool,
    language: str,
    dpi: int
) -> Optional[str]:
    """Extract text from PDF bytes with advanced OCR support."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _cpu_executor,
        _extract_pdf_bytes_with_advanced_ocr,
        file_bytes,
        enable_ocr,
        language,
        dpi
    )

async def _extract_image_bytes_async(
    file_bytes: bytes,
    language: str
) -> Optional[str]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _cpu_executor,
        _extract_image_bytes_with_openai,
        file_bytes,
        language
    )

def _extract_pdf_bytes_with_advanced_ocr(
    file_bytes: bytes,
    enable_ocr: bool,
    language: str,
    dpi: int
) -> str:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            def process_page(page_data):
                page, page_num = page_data
                try:
                    text = page.get_text()
                    
                    if enable_ocr and len(text.strip()) < OCRConfig.MIN_TEXT_THRESHOLD:
                        text = _apply_multi_level_ocr(page, page_num, language, dpi)
                    return page_num, text
                except Exception as page_error:
                    logger.error(f"Error processing page {page_num + 1}: {page_error}")
            page_data_list = [(doc[i], i) for i in range(len(doc))]
            
            results = {}
            with ThreadPoolExecutor(max_workers=min(2, len(doc))) as executor:
                futures = {executor.submit(process_page, data): data[1] 
                           for data in page_data_list}
                
                for future in as_completed(futures):
                    page_num, text = future.result()
                    results[page_num] = text
            
            text_parts = [results[i] for i in sorted(results.keys())]
        
        return "\n".join(text_parts)
    
    except Exception as e:
        logger.error(f"PDF bytes extraction failed: {e}")
        return ""

def _extract_image_bytes_with_openai(
    file_bytes: bytes,
    language: str
) -> str:
    """Synchronous image bytes extraction with OpenAI OCR."""
    try:
        text, confidence = _extract_text_with_openai(file_bytes, language)
        
        if len(text.strip()) < OCRConfig.MIN_TEXT_THRESHOLD:
            logger.warning("OpenAI OCR extracted minimal text from image bytes")
        
        logger.info(f"Extracted {len(text)} characters from image bytes with confidence {confidence}")
        
        return text
    except Exception as e:
        logger.error(f"Image bytes extraction failed: {e}", exc_info=True)
        return ""
# Text Processing

async def _load_text_async(file_path: str) -> List[Document]:
    """Load text file asynchronously."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _io_executor,
        _load_text_file,
        file_path
    )


def _load_text_file(file_path: str) -> List[Document]:
    """Synchronous text loader (runs in thread pool)."""
    loader = TextLoader(file_path)
    documents = loader.load()
    logger.info(f"Loaded text document with {len(documents)} sections")
    return documents


# Word Document Processing

async def _load_word_async(file_path: str, ext: str) -> List[Document]:
    """Load Word document asynchronously with .doc conversion."""
    if ext == "doc":
        loop = asyncio.get_event_loop()
        file_path = await loop.run_in_executor(
            _io_executor,
            _convert_doc_to_docx,
            file_path
        )
    
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _cpu_executor,
        _load_word_file,
        file_path
    )


def _convert_doc_to_docx(doc_path: str) -> str:
    """Convert .doc to .docx using LibreOffice (runs in thread pool)."""
    output_dir = os.path.dirname(doc_path)
    
    try:
        subprocess.run(
            [
                "libreoffice", "--headless", "--convert-to", "docx",
                "--outdir", output_dir, doc_path
            ],
            check=True,
            timeout=30,
            capture_output=True
        )
        
        docx_path = os.path.join(
            output_dir,
            os.path.splitext(os.path.basename(doc_path))[0] + ".docx"
        )
        
        if not os.path.exists(docx_path):
            raise FileNotFoundError(f"Conversion produced no output: {docx_path}")
        
        logger.info(f"Converted {doc_path} to {docx_path}")
        return docx_path
    
    except subprocess.TimeoutExpired:
        logger.error(f"LibreOffice conversion timed out for {doc_path}")
        raise
    except Exception as e:
        logger.error(f"Doc to docx conversion failed: {e}")
        raise


def _load_word_file(file_path: str) -> List[Document]:
    """Synchronous Word document loader (runs in process pool)."""
    loader = UnstructuredWordDocumentLoader(file_path)
    documents = loader.load()
    logger.info(f"Loaded Word document with {len(documents)} sections")
    return documents


def _extract_docx_bytes(file_bytes: bytes) -> str:
    """Extract text from DOCX bytes (runs in process pool)."""
    file_stream = io.BytesIO(file_bytes)
    return docx2txt.process(file_stream)


def _extract_text_with_openai(img_bytes: bytes, language: str = "eng") -> tuple[str, float]:
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        base64_image = base64.b64encode(img_bytes).decode('utf-8')
        
        # Create prompt for text extraction
        prompt = """Extract ALL text from this file. 
        Return ONLY the extracted text, preserving formatting and line breaks.
        Do not add any commentary, explanations, or markdown formatting.
        If there's no text, return an empty string."""
        
        # Call OpenAI Vision API
        response = client.chat.completions.create(
            model=OCRConfig.OPENAI_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}",
                                "detail": "high" 
                            }
                        }
                    ]
                }
            ],
            max_tokens=OCRConfig.OPENAI_MAX_TOKENS,
            temperature=0
        )
        
        extracted_text = response.choices[0].message.content.strip()
        
        confidence = 0.95 if extracted_text else 0.0
        
        logger.info(f"OpenAI Vision extracted {len(extracted_text)} characters")
        return extracted_text, confidence
        
    except ImportError:
        logger.error("OpenAI library not installed. Install with: pip install openai")
        return "", 0.0
    except Exception as e:
        logger.error(f"OpenAI Vision OCR failed: {e}")
        return "", 0.0


# PowerPoint Processing

async def _load_powerpoint_async(file_path: str) -> List[Document]:
    """Load PowerPoint asynchronously."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _cpu_executor,
        _load_powerpoint_file,
        file_path
    )


def _load_powerpoint_file(file_path: str) -> List[Document]:
    """Synchronous PowerPoint loader (runs in process pool)."""
    loader = UnstructuredPowerPointLoader(file_path)
    documents = loader.load()
    logger.info(f"Loaded PowerPoint with {len(documents)} slides")
    return documents


async def _load_csv_async(file_path: str) -> List[Document]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_io_executor, _load_csv_file, file_path)


def _load_csv_file(file_path: str) -> List[Document]:
    try:
        import pandas as pd
    except Exception:
        logger.error("pandas not installed. Install with: pip install pandas")
        return []

    try:
        # Try to infer delimiter; default to comma
        df = pd.read_csv(file_path, dtype=str, keep_default_na=False)
        # Convert rows to simple textual representation
        lines = []
        header = list(df.columns)
        lines.append(", ".join(header))
        for _, row in df.iterrows():
            vals = [str(row.get(col, "")) for col in header]
            lines.append(", ".join(vals))

        text = "\n".join(lines)
        return [Document(page_content=text, metadata={"source": file_path})]
    except Exception as e:
        logger.error(f"CSV loading failed for {file_path}: {e}")
        return []

# def _load_csv_file(file_path: str) -> List[Document]:
#     try:
#         import pandas as pd
#     except Exception:
#         logger.error("pandas not installed. Install with: pip install pandas")
#         return []

#     try:
#         df = pd.read_csv(
#             file_path,
#             dtype=str,
#             keep_default_na=False
#         )

#         df = df.fillna("")

#         documents = []

#         for row_index, row in df.iterrows():

#             row_content = []

#             for column in df.columns:
#                 value = str(row[column]).strip()

#                 if value:
#                     row_content.append(
#                         f"{column}: {value}"
#                     )

#             if not row_content:
#                 continue

#             text = (
#                 f"Row: {row_index + 1}\n"
#                 + "\n".join(row_content)
#             )

#             documents.append(
#                 Document(
#                     page_content=text,
#                     metadata={
#                         "source": file_path,
#                         "row_number": row_index + 1,
#                         "file_type": "csv"
#                     }
#                 )
#             )

#         logger.info(
#             f"Loaded CSV with "
#             f"{len(documents)} rows"
#         )

#         return documents

#     except Exception as e:
#         logger.error(
#             f"CSV loading failed for "
#             f"{file_path}: {e}"
#         )
#         return []

async def _load_excel_async(file_path: str) -> List[Document]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_io_executor, _load_excel_file, file_path)


# def _load_excel_file(file_path: str) -> List[Document]:
#     try:
#         import pandas as pd
#     except Exception:
#         logger.error("pandas not installed. Install with: pip install pandas")
#         return []

#     try:
#         sheets = pd.read_excel(file_path, sheet_name=None, dtype=str)
#         documents = []
#         for sheet_name, df in sheets.items():
#             header = list(df.columns)
#             lines = [f"Sheet: {sheet_name}", ", ".join(header)]
#             for _, row in df.iterrows():
#                 vals = [str(row.get(col, "")) for col in header]
#                 lines.append(", ".join(vals))

#             text = "\n".join(lines)
#             documents.append(Document(page_content=text, metadata={"source": file_path, "sheet": sheet_name}))

#         return documents
#     except Exception as e:
#         logger.error(f"Excel loading failed for {file_path}: {e}")
#         return []

def _load_excel_file(file_path: str) -> List[Document]:
    try:
        import pandas as pd
    except Exception:
        logger.error("pandas not installed. Install with: pip install pandas")
        return []

    try:
        sheets = pd.read_excel(
            file_path,
            sheet_name=None,
            dtype=str,
            keep_default_na=False
        )

        documents = []

        for sheet_name, df in sheets.items():

            df = df.fillna("")

            for row_index, row in df.iterrows():

                row_content = []

                for column in df.columns:
                    value = str(row[column]).strip()

                    if value:
                        row_content.append(
                            f"{column}: {value}"
                        )

                if not row_content:
                    continue

                text = (
                    f"Sheet: {sheet_name}\n"
                    f"Row: {row_index + 1}\n"
                    + "\n".join(row_content)
                )

                documents.append(
                    Document(
                        page_content=text,
                        metadata={
                            "source": file_path,
                            "sheet_name": sheet_name,
                            "row_number": row_index + 1,
                            "file_type": "xlsx"
                        }
                    )
                )

        logger.info(
            f"Loaded Excel with "
            f"{len(documents)} rows"
        )

        return documents

    except Exception as e:
        logger.error(
            f"Excel loading failed for "
            f"{file_path}: {e}"
        )
        return []

def _extract_with_textract(file_bytes: bytes) -> str:
    """Extract text using textract (runs in process pool)."""
    return textract.process(io.BytesIO(file_bytes)).decode("utf-8", errors="ignore")

# Cleanup

def shutdown_executors():
    """Shutdown executor pools gracefully. Call on application shutdown."""
    _io_executor.shutdown(wait=True)
    _cpu_executor.shutdown(wait=True)
    logger.info("Document processing executors shut down")

def get_system_prompt(db, org_id, field, default):
    org = db.query(Organization).filter(Organization.id == org_id).first()
    return getattr(org, field, None) or default
