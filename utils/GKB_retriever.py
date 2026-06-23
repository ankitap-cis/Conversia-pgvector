from typing import Optional, Tuple, List
from langchain_core.documents import Document
import logging
import asyncio

logger = logging.getLogger(__name__)


async def _retrieve_similar_documents(
    query: str,
    general_bot,
    org_id: Optional[int] = None,
    max_docs: int = 5,
    mode: str = "content_generation",
) -> Tuple[List[Document], dict]:
    try:
        if general_bot is None:
            logger.warning("GeneralChatBot not provided, skipping retrieval")
            return [], {"status": "skipped", "reason": "no_general_bot"}

        retriever_input = {
            "input": query,
            "org_id": org_id,
            "mode": mode,
        }

        loop = asyncio.get_event_loop()
        retrieved_docs = await loop.run_in_executor(
            None,
            general_bot.retriever.invoke,
            retriever_input
        )

        if not retrieved_docs:
            logger.info("No similar documents found")
            return [], {"status": "success", "docs_found": 0}

        retrieved_docs = retrieved_docs[:max_docs]

        MAX_CHUNK_CHAR = 3000
        for doc in retrieved_docs:
            if len(doc.page_content) > MAX_CHUNK_CHAR:
                doc.page_content = doc.page_content[:MAX_CHUNK_CHAR]

        retrieval_metadata = {
            "status": "success",
            "docs_found": len(retrieved_docs),
            "mode": mode,
            "sources": [
                {
                    "source": doc.metadata.get("source", "Unknown"),
                    "priority": doc.metadata.get("priority", "N/A"),
                    "timestamp": doc.metadata.get("timestamp", "N/A"),
                }
                for doc in retrieved_docs
            ],
        }

        logger.info(f"Retrieved {len(retrieved_docs)} similar documents")

        return retrieved_docs, retrieval_metadata

    except Exception as e:
        logger.warning(f"Document retrieval failed: {e}", exc_info=True)
        return [], {
            "status": "failed",
            "error": str(e),
            "docs_found": 0,
        }