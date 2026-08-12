"""Dataset-scoped hybrid evidence retrieval with deterministic audit hashes."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from src.ai_research.contracts import DataEgressClass
from src.strategies.golden_pit.persistence.tier1_repository import Tier1Repository

EmbeddingFunction = Callable[[str], Sequence[float]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvidenceIndex:
    def __init__(self, db_path: str | Path, embedding: EmbeddingFunction | None = None) -> None:
        self.db_path = Path(db_path)
        self.embedding = embedding

    def migrate(self) -> None:
        Tier1Repository(self.db_path).migrate_all()

    def add_document(
        self,
        *,
        dataset_id: str,
        title: str,
        publisher: str,
        published_at: str,
        source_uri: str,
        content: str,
        egress_class: DataEgressClass,
        chunk_size: int = 800,
    ) -> str:
        if not content.strip() or chunk_size < 100:
            raise ValueError("证据文档为空或切块大小无效")
        document_id = str(uuid.uuid4())
        chunks = [content[index : index + chunk_size] for index in range(0, len(content), chunk_size)]
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO evidence_documents(
                    document_id, dataset_id, title, publisher, published_at,
                    source_uri, content_hash, egress_class, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id, dataset_id, title, publisher, published_at, source_uri,
                    hashlib.sha256(content.encode()).hexdigest(), egress_class.value, _now(),
                ),
            )
            for ordinal, chunk in enumerate(chunks):
                chunk_id = str(uuid.uuid4())
                vector = list(map(float, self.embedding(chunk))) if self.embedding else None
                connection.execute(
                    """
                    INSERT INTO evidence_chunks(
                        chunk_id, document_id, dataset_id, ordinal, content,
                        content_hash, embedding_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk_id, document_id, dataset_id, ordinal, chunk,
                        hashlib.sha256(chunk.encode()).hexdigest(),
                        json.dumps(vector) if vector is not None else None, _now(),
                    ),
                )
                connection.execute(
                    "INSERT INTO evidence_chunks_fts(chunk_id, dataset_id, title, content) VALUES (?, ?, ?, ?)",
                    (chunk_id, dataset_id, title, chunk),
                )
        return document_id

    def search(
        self,
        dataset_id: str,
        query: str,
        *,
        limit: int = 10,
        target_region: str = "CN",
    ) -> list[dict]:
        if not query.strip() or limit < 1 or limit > 50:
            raise ValueError("检索词不能为空且 limit 必须在 1 到 50 之间")
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT c.chunk_id, c.document_id, c.ordinal, c.content,
                       c.content_hash, c.embedding_json, d.title, d.publisher,
                       d.published_at, d.source_uri, d.egress_class,
                       bm25(evidence_chunks_fts) AS keyword_score
                FROM evidence_chunks_fts
                JOIN evidence_chunks c ON c.chunk_id=evidence_chunks_fts.chunk_id
                JOIN evidence_documents d ON d.document_id=c.document_id
                WHERE evidence_chunks_fts MATCH ? AND c.dataset_id=?
                ORDER BY keyword_score LIMIT 100
                """,
                (query, dataset_id),
            ).fetchall()
            if not rows:
                rows = connection.execute(
                    """
                    SELECT c.chunk_id, c.document_id, c.ordinal, c.content,
                           c.content_hash, c.embedding_json, d.title, d.publisher,
                           d.published_at, d.source_uri, d.egress_class,
                           0.0 AS keyword_score
                    FROM evidence_chunks c
                    JOIN evidence_documents d ON d.document_id=c.document_id
                    WHERE c.dataset_id=? AND (c.content LIKE ? OR d.title LIKE ?)
                    ORDER BY c.document_id, c.ordinal LIMIT 100
                    """,
                    (dataset_id, f"%{query}%", f"%{query}%"),
                ).fetchall()
        query_vector = list(map(float, self.embedding(query))) if self.embedding else None
        result = []
        for row in rows:
            item = dict(row)
            policy = DataEgressClass(item["egress_class"])
            if policy in {
                DataEgressClass.DENY_AI,
                DataEgressClass.LOCAL_ONLY,
                DataEgressClass.MASK_BEFORE_SEND,
            }:
                continue
            if target_region != "CN" and policy != DataEgressClass.APPROVED_EXTERNAL:
                continue
            vector = json.loads(item.pop("embedding_json")) if item["embedding_json"] else None
            item["vector_score"] = self._cosine(query_vector, vector) if query_vector and vector else None
            result.append(item)
        result.sort(
            key=lambda item: (
                -(item["vector_score"] if item["vector_score"] is not None else -1.0),
                float(item["keyword_score"]),
            )
        )
        return result[:limit]

    @staticmethod
    def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
        if len(left) != len(right) or not left:
            raise ValueError("向量维度不一致")
        denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(
            sum(value * value for value in right)
        )
        return sum(a * b for a, b in zip(left, right)) / denominator if denominator else 0.0
