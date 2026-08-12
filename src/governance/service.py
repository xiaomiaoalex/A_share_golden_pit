from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from src.strategies.golden_pit.persistence.tier1_repository import Tier1Repository


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReleaseStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    SHADOW = "SHADOW"
    PRODUCTION = "PRODUCTION"
    DISABLED = "DISABLED"
    ARCHIVED = "ARCHIVED"


class GovernanceService:
    TRANSITIONS = {
        ReleaseStatus.DRAFT: {ReleaseStatus.VALIDATED, ReleaseStatus.ARCHIVED},
        ReleaseStatus.VALIDATED: {ReleaseStatus.SHADOW, ReleaseStatus.ARCHIVED},
        ReleaseStatus.SHADOW: {ReleaseStatus.PRODUCTION, ReleaseStatus.DISABLED},
        ReleaseStatus.PRODUCTION: {ReleaseStatus.DISABLED},
        ReleaseStatus.DISABLED: {ReleaseStatus.ARCHIVED, ReleaseStatus.SHADOW},
        ReleaseStatus.ARCHIVED: set(),
    }
    REQUIRED_ROLES = {
        ReleaseStatus.VALIDATED: "RESEARCH_REVIEWER",
        ReleaseStatus.SHADOW: "RELEASE_MANAGER",
        ReleaseStatus.PRODUCTION: "RELEASE_MANAGER",
        ReleaseStatus.DISABLED: "RELEASE_MANAGER",
        ReleaseStatus.ARCHIVED: "RELEASE_MANAGER",
    }

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def migrate(self) -> None:
        Tier1Repository(self.db_path).migrate_all()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def grant_role(self, actor: str, role: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO role_bindings(actor, role, created_at) VALUES (?, ?, ?)",
                (actor, role, _now()),
            )

    def create_release(
        self,
        *,
        release_id: str,
        object_type: str,
        object_id: str,
        manifest: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO governance_releases(
                    release_version_id, release_id, object_type, object_id,
                    version, status, manifest_json, actor, created_at
                ) VALUES (?, ?, ?, ?, 1, 'DRAFT', ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    release_id,
                    object_type,
                    object_id,
                    json.dumps(manifest, ensure_ascii=False, sort_keys=True),
                    actor,
                    _now(),
                ),
            )
            self._audit(connection, actor, "CREATE_RELEASE", object_type, object_id, manifest)
        return self.get_release(release_id)

    def transition(
        self,
        release_id: str,
        target: ReleaseStatus,
        *,
        actor: str,
        note: str = "",
    ) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            latest = connection.execute(
                "SELECT * FROM governance_releases WHERE release_id=? ORDER BY version DESC LIMIT 1",
                (release_id,),
            ).fetchone()
            if latest is None:
                raise ValueError("未知发布对象")
            current = ReleaseStatus(str(latest["status"]))
            if target not in self.TRANSITIONS[current]:
                raise ValueError(f"发布不能从 {current.value} 变更为 {target.value}")
            required = self.REQUIRED_ROLES[target]
            authorized = connection.execute(
                "SELECT 1 FROM role_bindings WHERE actor=? AND role=?",
                (actor, required),
            ).fetchone()
            if authorized is None:
                raise PermissionError(f"缺少发布角色: {required}")
            version = int(latest["version"]) + 1
            connection.execute(
                """
                INSERT INTO governance_releases(
                    release_version_id, release_id, object_type, object_id,
                    version, status, manifest_json, actor, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    release_id,
                    latest["object_type"],
                    latest["object_id"],
                    version,
                    target.value,
                    latest["manifest_json"],
                    actor,
                    note,
                    _now(),
                ),
            )
            self._audit(
                connection,
                actor,
                f"RELEASE_{target.value}",
                latest["object_type"],
                latest["object_id"],
                {"release_id": release_id, "version": version, "note": note},
            )
        return self.get_release(release_id)

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        actor: str,
        action: str,
        object_type: str,
        object_id: str,
        payload: dict[str, Any],
    ) -> None:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        connection.execute(
            """
            INSERT INTO audit_events(
                audit_id, actor, action, object_type, object_id,
                payload_hash, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                actor,
                action,
                object_type,
                object_id,
                hashlib.sha256(canonical.encode()).hexdigest(),
                canonical,
                _now(),
            ),
        )

    def get_release(self, release_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM governance_releases WHERE release_id=? ORDER BY version DESC LIMIT 1",
                (release_id,),
            ).fetchone()
        if row is None:
            raise ValueError("未知发布对象")
        result = dict(row)
        result["manifest"] = json.loads(result.pop("manifest_json"))
        return result

    def audit_timeline(self, object_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_events WHERE object_id=? ORDER BY created_at",
                (object_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def overview(self) -> dict[str, Any]:
        with self._connect() as connection:
            releases = connection.execute(
                """
                SELECT r.release_id, r.object_type, r.object_id, r.version,
                       r.status, r.actor, r.note, r.created_at
                FROM governance_releases r
                WHERE r.version=(
                    SELECT MAX(v.version) FROM governance_releases v
                    WHERE v.release_id=r.release_id
                )
                ORDER BY r.created_at DESC LIMIT 100
                """
            ).fetchall()
            audits = connection.execute(
                """
                SELECT audit_id, actor, action, object_type, object_id,
                       payload_hash, created_at
                FROM audit_events ORDER BY created_at DESC LIMIT 100
                """
            ).fetchall()
        return {
            "releases": [dict(row) for row in releases],
            "audit_events": [dict(row) for row in audits],
        }
