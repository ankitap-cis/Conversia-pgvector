import os
import shutil
from fastapi import UploadFile
from tempfile import NamedTemporaryFile
from langchain_openai import OpenAIEmbeddings
from langchain_community.document_loaders import TextLoader, PyPDFLoader, Docx2txtLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
import configparser
from langchain.schema import Document
import shutil
from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader, UnstructuredWordDocumentLoader, UnstructuredPowerPointLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS  # <-- Switched from Chroma to FAISS
from logger import *
 
 
config = configparser.ConfigParser()
config.read('config.ini')
OPENAI_API_KEY = config['openAI_config']['key']
embed_model = config['openAI_config']['embedding_model']
 
embedding_model = OpenAIEmbeddings(openai_api_key=OPENAI_API_KEY, model = embed_model)
 
VECTORSTORES = {
    "precall_plan": "./vectorstores/precall_plan/"
}

from utils.file_loaders import *
async def add_file_to_vectorstore(file: UploadFile, org_id: int):
    PERSIST_DIR = VECTORSTORES["precall_plan"]+f"{org_id}"

    try:
        file_ext = file.filename.split(".")[-1].lower()
        if file_ext not in ["txt", "pdf", "docx", "ppt", "doc", "pptx"]:
            raise ValueError("Unsupported file type for vector store ingestion.")
 
        # Save uploaded file to a temporary location
        with NamedTemporaryFile(delete=False, suffix=f".{file_ext}") as tmp:
            temp_file_path = tmp.name
            with open(temp_file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

        documents = await process_document(
            source=temp_file_path,
            filename=file.filename,
            enable_ocr=True,
            return_documents=True
        )
        if not documents:
            raise ValueError(f"Failed to extract content from {file.filename}")
 
        # Split into chunks
        splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        chunks = splitter.split_documents(documents)

        for chunk in chunks:
            chunk.metadata["source"] = file.filename
 
        # Clear old vector store if exists
        if os.path.exists(PERSIST_DIR):
            shutil.rmtree(PERSIST_DIR)
        os.makedirs(PERSIST_DIR, exist_ok=True)
 
        # Create FAISS vector store
        vectorstore = FAISS.from_documents(
            documents=chunks,
            embedding=embedding_model
        )
        logger.info(f"File uploaded in vectorstore successfully")
        # Save FAISS index to disk
        vectorstore.save_local(PERSIST_DIR)
        # Clean up temp file
        os.remove(temp_file_path)
        return True
 
    except Exception as e:
        logger.error(f"{str(e)}")
        pass
 


def get_vectorstore(store_type: str, org_id) -> FAISS:
    if store_type not in VECTORSTORES:
        raise ValueError(f"Unknown vector store type: {store_type}")
 
    persist_dir = VECTORSTORES[store_type] + f"/{org_id}"
    index_file = os.path.join(persist_dir, "index.faiss")  # Check for actual index file
    
    # Check if FAISS index file exists (not just directory)
    if os.path.exists(index_file):
        try:
            # Load existing vectorstore
            return FAISS.load_local(
                persist_dir,
                embeddings=embedding_model,
                allow_dangerous_deserialization=True
            )
        except Exception as e:
            logger.warning(f"Corrupted vectorstore at {persist_dir}, recreating: {e}")
            # If loading fails, fall through to recreate
    
    # Create directory if it doesn't exist
    os.makedirs(persist_dir, exist_ok=True)
    
    # Create empty FAISS from dummy documents
    logger.info(f"Creating new vectorstore at {persist_dir}")
    empty_docs = [Document(page_content="initialization", metadata={"source": "init"})]
    empty_vectorstore = FAISS.from_documents(
        documents=empty_docs,
        embedding=embedding_model
    )
    empty_vectorstore.save_local(persist_dir)
    logger.info(f" Created empty vectorstore at {persist_dir}")
    return empty_vectorstore



 
def clear_faiss_vectorstore(store_type: str, embedding_model, org_id: int):
    """
    Clears the FAISS vector store by replacing it with a dummy-initialized empty store.
    """
    if store_type not in VECTORSTORES:
        raise ValueError(f"Unknown vector store type: {store_type}")
 
    persist_dir = VECTORSTORES[store_type]+f"{org_id}"
 
    # Use a dummy document to avoid index errors
    dummy_doc = [Document(page_content="empty", metadata={})]
    faiss_index = FAISS.from_documents(dummy_doc, embedding_model)
 
    # Now overwrite index with no vectors
    faiss_index.index.reset()  # this clears all vectors from the FAISS index
    faiss_index.docstore._dict.clear()  # clear docstore
    faiss_index.index_to_docstore_id.clear()  # clear mapping
 
    # Save the now-empty index
    faiss_index.save_local(persist_dir)
    logger.info(f"File deleted from vectorstore successfully")
    return True
 
 
def list_faiss_vectorstore(store_type: str, org_id: int):
    """
    Lists all documents/chunks currently stored in the FAISS vector store.
    """
    if store_type not in VECTORSTORES:
        raise ValueError(f"Unknown vector store type: {store_type}")
 
    persist_dir = VECTORSTORES[store_type]+f"{org_id}"
 
    if not os.path.exists(persist_dir):
        raise FileNotFoundError(f"No vector store found at: {persist_dir}")
 
    # Load vector store
    vectorstore = FAISS.load_local(
        persist_dir,
        embeddings=embedding_model,
        allow_dangerous_deserialization=True
    )
 
    # Access stored documents
    documents = list(vectorstore.docstore._dict.values())
 
    results = []
    for i, doc in enumerate(documents):
        results.append({
            "index": i,
            "content": doc.page_content,
            "metadata": doc.metadata
        })
 
    return results
