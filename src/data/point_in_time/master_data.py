"""Point-in-time security master and financial report version store."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src.strategies.golden_pit.persistence.tier1_repository import Tier1Repository


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PointInTimeRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def migrate(self) -> None:
        Tier1Repository(self.db_path).migrate_all()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def add_security(
        self,
        *,
        security_id: str,
        issuer_name: str,
        symbol: str,
        exchange: str,
        valid_from: str,
        listed_at: str | None = None,
        delisted_at: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO securities(
                    security_id, issuer_name, listed_at, delisted_at, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (security_id, issuer_name, listed_at, delisted_at, _now()),
            )
            connection.execute(
                """
                INSERT INTO security_code_history(
                    security_id, symbol, exchange, valid_from, name
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (security_id, symbol, exchange, valid_from, issuer_name),
            )

    def change_code(
        self,
        security_id: str,
        *,
        symbol: str,
        exchange: str,
        name: str,
        valid_from: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE security_code_history SET valid_to=?
                WHERE security_id=? AND valid_to IS NULL AND valid_from<?
                """,
                (valid_from, security_id, valid_from),
            )
            connection.execute(
                """
                INSERT INTO security_code_history(
                    security_id, symbol, exchange, valid_from, name
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (security_id, symbol, exchange, valid_from, name),
            )

    def security_as_of(self, security_id: str, as_of_date: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT s.security_id, s.issuer_name, s.listed_at, s.delisted_at,
                       h.symbol, h.exchange, h.name, h.valid_from, h.valid_to
                FROM securities s JOIN security_code_history h USING(security_id)
                WHERE s.security_id=? AND h.valid_from<=?
                  AND (h.valid_to IS NULL OR h.valid_to>?)
                ORDER BY h.valid_from DESC LIMIT 1
                """,
                (security_id, as_of_date, as_of_date),
            ).fetchone()
        if row is None:
            raise ValueError("该时点不存在证券身份记录")
        return dict(row)

    def add_financial_report(
        self,
        *,
        security_id: str,
        report_period: str,
        announcement_date: str,
        payload: Mapping[str, Any],
        source_record_id: str,
    ) -> str:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        report_version_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            revision = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(revision), 0) + 1
                    FROM financial_report_versions
                    WHERE security_id=? AND report_period=?
                    """,
                    (security_id, report_period),
                ).fetchone()[0]
            )
            connection.execute(
                """
                INSERT INTO financial_report_versions(
                    report_version_id, security_id, report_period,
                    announcement_date, revision, payload_json, content_hash,
                    source_record_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_version_id,
                    security_id,
                    report_period,
                    announcement_date,
                    revision,
                    canonical,
                    content_hash,
                    source_record_id,
                    _now(),
                ),
            )
        return report_version_id

    def financial_reports_as_of(
        self, security_id: str, as_of_date: str
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT f.* FROM financial_report_versions f
                WHERE f.security_id=? AND f.announcement_date<=?
                  AND f.revision=(
                    SELECT MAX(v.revision) FROM financial_report_versions v
                    WHERE v.security_id=f.security_id
                      AND v.report_period=f.report_period
                      AND v.announcement_date<=?
                  )
                ORDER BY f.report_period
                """,
                (security_id, as_of_date, as_of_date),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            result.append(item)
        return result
