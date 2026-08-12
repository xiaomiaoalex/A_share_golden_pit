from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.strategies.golden_pit.persistence.tier1_repository import Tier1Repository


class ArtifactRepository:
    TYPES = {"FACTOR_RESEARCH", "BACKTEST", "PORTFOLIO", "RISK", "EVALUATION"}

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def migrate(self) -> None:
        Tier1Repository(self.db_path).migrate_all()

    def append(
        self,
        *,
        artifact_id: str,
        artifact_type: str,
        status: str,
        payload: dict[str, Any],
        created_by: str,
        strategy_id: str | None = None,
        release_id: str | None = None,
        data_snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        if artifact_type not in self.TYPES:
            raise ValueError("未知平台产物类型")
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE")
            version = int(
                connection.execute(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM platform_artifacts WHERE artifact_id=?",
                    (artifact_id,),
                ).fetchone()[0]
            )
            connection.execute(
                """
                INSERT INTO platform_artifacts(
                    artifact_version_id, artifact_id, artifact_type, version,
                    status, strategy_id, release_id, data_snapshot_id,
                    payload_json, payload_hash, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()), artifact_id, artifact_type, version, status,
                    strategy_id, release_id, data_snapshot_id, canonical,
                    hashlib.sha256(canonical.encode()).hexdigest(), created_by,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return self.get(artifact_id)

    def get(self, artifact_id: str) -> dict[str, Any]:
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM platform_artifacts WHERE artifact_id=? ORDER BY version DESC LIMIT 1",
                (artifact_id,),
            ).fetchone()
        if row is None:
            raise ValueError("未知平台产物")
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result

    def list_latest(self, artifact_type: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE a.artifact_type=?" if artifact_type else ""
        params = (artifact_type,) if artifact_type else ()
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                f"""
                SELECT a.artifact_id, a.artifact_type, a.version, a.status,
                       a.strategy_id, a.release_id, a.data_snapshot_id,
                       a.payload_hash, a.created_by, a.created_at
                FROM platform_artifacts a {where}
                AND a.version=(SELECT MAX(b.version) FROM platform_artifacts b
                               WHERE b.artifact_id=a.artifact_id)
                ORDER BY a.created_at DESC LIMIT 100
                """ if where else """
                SELECT a.artifact_id, a.artifact_type, a.version, a.status,
                       a.strategy_id, a.release_id, a.data_snapshot_id,
                       a.payload_hash, a.created_by, a.created_at
                FROM platform_artifacts a
                WHERE a.version=(SELECT MAX(b.version) FROM platform_artifacts b
                                 WHERE b.artifact_id=a.artifact_id)
                ORDER BY a.created_at DESC LIMIT 100
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]
