import json
import os
import re
from datetime import datetime
from typing import Any, Iterable, Optional
from urllib.parse import unquote, urlparse

from langchain_core.documents import Document
from sqlalchemy import text
from sqlalchemy.orm import Session

from connection import SessionLocal
from logger import logger


class PGVectorGeneralChatStore:
    """Small pgvector-backed store for general chatbot knowledge chunks."""

    def __init__(
        self,
        embedding_model,
        table_name: str = "general_chatbot_vectors",
        embedding_dimension: int = 3072,
    ):
        self.embedding_model = embedding_model
        self.table_name = table_name
        self.embedding_dimension = embedding_dimension

    @staticmethod
    def _normalize_filename(name: str) -> str:
        base = os.path.basename(unquote(str(name).split("?")[0])).lower()
        name_without_ext, ext = os.path.splitext(base)
        name_without_ext = re.sub(r"_\d+", "", name_without_ext)
        return f"{name_without_ext}{ext}"

    @staticmethod
    def _embedding_literal(embedding: Iterable[float]) -> str:
        values = [float(value) for value in embedding]
        return "[" + ",".join(str(value) for value in values) + "]"

    @staticmethod
    def _parse_timestamp(value: Any) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except Exception:
            return None

    @staticmethod
    def _row_to_document(row) -> Document:
        data = row._mapping
        metadata = dict(data.get("metadata") or {})
        for key in [
            "org_id",
            "source",
            "source_path",
            "file_type",
            "row_number",
            "sheet_name",
            "priority",
        ]:
            value = data.get(key)
            if value is not None:
                metadata[key] = value

        return Document(
            page_content=data["content"],
            metadata=metadata,
        )

    def _execute_with_session(self, db: Optional[Session], fn):
        if db is not None:
            return fn(db)

        local_db = SessionLocal()
        try:
            result = fn(local_db)
            local_db.commit()
            return result
        except Exception:
            local_db.rollback()
            raise
        finally:
            local_db.close()

    def add_documents(
        self,
        documents: list[Document],
        db: Optional[Session] = None,
        batch_size: int = 50,
    ) -> int:
        if not documents:
            return 0

        texts = [doc.page_content for doc in documents]
        embeddings = self.embedding_model.embed_documents(texts)

        if len(embeddings) != len(documents):
            raise ValueError("Embedding count does not match document count")

        def insert(session: Session) -> int:
            inserted = 0
            sql = text(
                f"""
                INSERT INTO {self.table_name}
                    (
                        org_id,
                        content,
                        embedding,
                        source,
                        source_path,
                        file_type,
                        row_number,
                        sheet_name,
                        priority,
                        timestamp,
                        metadata
                    )
                VALUES
                    (
                        :org_id,
                        :content,
                        CAST(:embedding AS vector),
                        :source,
                        :source_path,
                        :file_type,
                        :row_number,
                        :sheet_name,
                        :priority,
                        :timestamp,
                        CAST(:metadata AS jsonb)
                    )
                """
            )

            for start in range(0, len(documents), batch_size):
                batch_docs = documents[start:start + batch_size]
                batch_embeddings = embeddings[start:start + batch_size]
                params = []

                for doc, embedding in zip(batch_docs, batch_embeddings):
                    metadata = dict(doc.metadata or {})
                    params.append({
                        "org_id": metadata.get("org_id"),
                        "content": doc.page_content,
                        "embedding": self._embedding_literal(embedding),
                        "source": metadata.get("source"),
                        "source_path": metadata.get("source_path"),
                        "file_type": metadata.get("file_type"),
                        "row_number": metadata.get("row_number"),
                        "sheet_name": metadata.get("sheet_name") or metadata.get("sheet"),
                        "priority": metadata.get("priority"),
                        "timestamp": self._parse_timestamp(metadata.get("timestamp")),
                        "metadata": json.dumps(metadata),
                    })

                session.execute(sql, params)
                inserted += len(params)

            logger.info(f"Inserted {inserted} pgvector general chatbot chunks")
            return inserted

        return self._execute_with_session(db, insert)

    def similarity_search(
        self,
        query: str,
        org_id: Optional[int] = None,
        k: int = 5,
        db: Optional[Session] = None,
    ) -> list[Document]:
        query_embedding = self.embedding_model.embed_query(query)
        return self.similarity_search_by_vector(
            embedding=query_embedding,
            org_id=org_id,
            k=k,
            db=db,
        )

    def similarity_search_by_vector(
        self,
        embedding: Iterable[float],
        org_id: Optional[int] = None,
        k: int = 5,
        db: Optional[Session] = None,
    ) -> list[Document]:
        def search(session: Session) -> list[Document]:
            sql = text(
                f"""
                SELECT
                    id,
                    org_id,
                    content,
                    source,
                    source_path,
                    file_type,
                    row_number,
                    sheet_name,
                    priority,
                    metadata,
                    embedding <=> CAST(:embedding AS vector) AS distance
                FROM {self.table_name}
                WHERE (:org_id IS NULL OR org_id = :org_id)
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT :limit
                """
            )
            rows = session.execute(
                sql,
                {
                    "embedding": self._embedding_literal(embedding),
                    "org_id": org_id,
                    "limit": k,
                },
            ).all()

            docs = []
            for row in rows:
                data = row._mapping
                doc = self._row_to_document(row)
                doc.metadata["distance"] = float(data["distance"])
                doc.metadata["relevance_score"] = 1.0 - float(data["distance"])
                docs.append(doc)
            return docs

        return self._execute_with_session(db, search)

    def retrieve_by_filename(
        self,
        query: str,
        org_id: Optional[int] = None,
        limit: int = 200,
        db: Optional[Session] = None,
    ) -> list[Document]:
        requested_normalized = self._normalize_filename(query)

        def retrieve(session: Session) -> list[Document]:
            sql = text(
                f"""
                SELECT
                    id,
                    org_id,
                    content,
                    source,
                    source_path,
                    file_type,
                    row_number,
                    sheet_name,
                    priority,
                    metadata
                FROM {self.table_name}
                WHERE (:org_id IS NULL OR org_id = :org_id)
                ORDER BY COALESCE(sheet_name, ''), COALESCE(row_number, 0), id
                """
            )
            rows = session.execute(sql, {"org_id": org_id}).all()

            docs = []
            for row in rows:
                data = row._mapping
                source_name = os.path.basename(
                    unquote(urlparse(data.get("source") or data.get("source_path") or "").path)
                )
                source_path_name = os.path.basename(
                    unquote(urlparse(data.get("source_path") or data.get("source") or "").path)
                )

                source_normalized = self._normalize_filename(source_name)
                source_path_normalized = self._normalize_filename(source_path_name)

                if (
                    (source_normalized and source_normalized in requested_normalized)
                    or (
                        source_path_normalized
                        and source_path_normalized in requested_normalized
                    )
                ):
                    docs.append(self._row_to_document(row))

                if len(docs) >= limit:
                    break

            logger.info(
                f"[PGVECTOR_FILENAME_RETRIEVAL] query={query} matched_docs={len(docs)}"
            )
            return docs

        return self._execute_with_session(db, retrieve)

    def delete_by_source(
        self,
        file_path: str,
        org_id: Optional[int] = None,
        db: Optional[Session] = None,
    ) -> int:
        def delete(session: Session) -> int:
            sql = text(
                f"""
                DELETE FROM {self.table_name}
                WHERE (source = :file_path OR source_path = :file_path)
                  AND (:org_id IS NULL OR org_id = :org_id)
                """
            )
            result = session.execute(
                sql,
                {
                    "file_path": file_path,
                    "org_id": org_id,
                },
            )
            return result.rowcount or 0

        return self._execute_with_session(db, delete)

    def update_priority(
        self,
        file_path: str,
        new_priority: int,
        org_id: Optional[int] = None,
        db: Optional[Session] = None,
    ) -> int:
        def update(session: Session) -> int:
            sql = text(
                f"""
                UPDATE {self.table_name}
                SET
                    priority = :priority,
                    metadata = jsonb_set(
                        metadata,
                        '{{priority}}',
                        to_jsonb(CAST(:priority AS integer)),
                        true
                    )
                WHERE (source = :file_path OR source_path = :file_path)
                  AND (:org_id IS NULL OR org_id = :org_id)
                """
            )
            result = session.execute(
                sql,
                {
                    "priority": new_priority,
                    "file_path": file_path,
                    "org_id": org_id,
                },
            )
            return result.rowcount or 0

        return self._execute_with_session(db, update)

    def list_documents(
        self,
        org_id: Optional[int] = None,
        db: Optional[Session] = None,
    ) -> dict[str, Any]:
        def list_docs(session: Session) -> dict[str, Any]:
            sql = text(
                f"""
                SELECT
                    COALESCE(source_path, source) AS source_key,
                    COUNT(*) AS chunk_count,
                    MIN(created_at) AS first_seen,
                    MAX(created_at) AS last_seen
                FROM {self.table_name}
                WHERE (:org_id IS NULL OR org_id = :org_id)
                GROUP BY COALESCE(source_path, source)
                ORDER BY last_seen DESC
                """
            )
            rows = session.execute(sql, {"org_id": org_id}).all()
            return {
                "total_documents": len(rows),
                "total_chunks": sum(row._mapping["chunk_count"] for row in rows),
                "documents": [
                    {
                        "source": row._mapping["source_key"],
                        "chunks": row._mapping["chunk_count"],
                        "first_seen": row._mapping["first_seen"],
                        "last_seen": row._mapping["last_seen"],
                    }
                    for row in rows
                ],
            }

        return self._execute_with_session(db, list_docs)

    def clear(
        self,
        org_id: Optional[int] = None,
        db: Optional[Session] = None,
    ) -> int:
        def clear_rows(session: Session) -> int:
            sql = text(
                f"""
                DELETE FROM {self.table_name}
                WHERE (:org_id IS NULL OR org_id = :org_id)
                """
            )
            result = session.execute(sql, {"org_id": org_id})
            return result.rowcount or 0

        return self._execute_with_session(db, clear_rows)
