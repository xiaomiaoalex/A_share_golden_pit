"""Append-only SQLite repository for research governance records."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.strategies.golden_pit.persistence.tier1_repository import Tier1Repository

from .contracts import DataEgressClass, ResearchReport, ResearchReportStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class ResearchRepository:
    """All versioned content and state transitions are immutable rows."""

    TRANSITIONS = {
        ResearchReportStatus.DRAFT: {ResearchReportStatus.VALIDATED},
        ResearchReportStatus.VALIDATED: {
            ResearchReportStatus.IN_REVIEW,
            ResearchReportStatus.REJECTED,
        },
        ResearchReportStatus.IN_REVIEW: {
            ResearchReportStatus.PUBLISHED,
            ResearchReportStatus.REJECTED,
        },
        ResearchReportStatus.PUBLISHED: set(),
        ResearchReportStatus.REJECTED: set(),
    }

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

    def create_dataset(
        self,
        *,
        dataset_id: str,
        strategy_id: str,
        release_id: str,
        as_of_date: str,
        content_hash: str,
        egress_class: DataEgressClass,
        manifest: dict[str, Any],
        status: str = "READY",
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO research_datasets(
                    dataset_id, strategy_id, release_id, as_of_date, content_hash,
                    egress_class, manifest_json, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset_id,
                    strategy_id,
                    release_id,
                    as_of_date,
                    content_hash,
                    egress_class.value,
                    _json(manifest),
                    status,
                    _now(),
                ),
            )

    def add_template_version(
        self,
        *,
        template_id: str,
        version: int,
        prompt: str,
        output_schema: dict[str, Any],
        model_policy: dict[str, Any],
        status: str = "DRAFT",
    ) -> str:
        version_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO research_templates(
                    template_version_id, template_id, version, prompt,
                    output_schema_json, model_policy_json, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    template_id,
                    version,
                    prompt,
                    _json(output_schema),
                    _json(model_policy),
                    status,
                    _now(),
                ),
            )
        return version_id

    def start_run(
        self, dataset_id: str, template_version_id: str, subject: str
    ) -> str:
        run_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO research_runs(
                    run_id, dataset_id, template_version_id, subject, status,
                    usage_json, created_at
                ) VALUES (?, ?, ?, ?, 'RUNNING', '{}', ?)
                """,
                (run_id, dataset_id, template_version_id, subject, _now()),
            )
        return run_id

    def complete_run(
        self,
        run_id: str,
        report: ResearchReport,
        *,
        provider_id: str,
        model_id: str,
        usage: dict[str, Any],
        actor: str = "provider",
    ) -> str:
        report.validate()
        report_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE research_runs SET provider_id=?, model_id=?, status='SUCCEEDED',
                    usage_json=? WHERE run_id=? AND status='RUNNING'
                """,
                (provider_id, model_id, _json(usage), run_id),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise ValueError("研究运行不存在或已结束")
            connection.execute(
                """
                INSERT INTO research_report_versions(
                    report_version_id, report_id, run_id, version, status,
                    report_json, actor, created_at
                ) VALUES (?, ?, ?, 1, 'DRAFT', ?, ?, ?)
                """,
                (str(uuid.uuid4()), report_id, run_id, _json(asdict(report)), actor, _now()),
            )
        return report_id

    def transition(
        self,
        report_id: str,
        target: ResearchReportStatus,
        *,
        actor: str,
        note: str = "",
    ) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            latest = connection.execute(
                """
                SELECT * FROM research_report_versions
                WHERE report_id=? ORDER BY version DESC LIMIT 1
                """,
                (report_id,),
            ).fetchone()
            if latest is None:
                raise ValueError("未知研究报告")
            current = ResearchReportStatus(str(latest["status"]))
            if target not in self.TRANSITIONS[current]:
                raise ValueError(f"研究报告不能从 {current.value} 变更为 {target.value}")
            version = int(latest["version"]) + 1
            connection.execute(
                """
                INSERT INTO research_report_versions(
                    report_version_id, report_id, run_id, version, status,
                    report_json, actor, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    report_id,
                    latest["run_id"],
                    version,
                    target.value,
                    latest["report_json"],
                    actor,
                    note,
                    _now(),
                ),
            )
        return self.get_report(report_id)

    def get_report(self, report_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM research_report_versions
                WHERE report_id=? ORDER BY version DESC LIMIT 1
                """,
                (report_id,),
            ).fetchone()
        if row is None:
            raise ValueError("未知研究报告")
        result = dict(row)
        result["report"] = json.loads(result.pop("report_json"))
        return result

    def history(self, report_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT version, status, actor, note, created_at
                FROM research_report_versions WHERE report_id=? ORDER BY version
                """,
                (report_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def overview(self) -> dict[str, Any]:
        with self._connect() as connection:
            datasets = connection.execute(
                """
                SELECT dataset_id, strategy_id, release_id, as_of_date,
                       egress_class, status, created_at
                FROM research_datasets ORDER BY created_at DESC LIMIT 50
                """
            ).fetchall()
            templates = connection.execute(
                """
                SELECT template_version_id, template_id, version, status, created_at
                FROM research_templates ORDER BY created_at DESC LIMIT 50
                """
            ).fetchall()
            reports = connection.execute(
                """
                SELECT v.report_id, v.version, v.status, v.actor, v.created_at,
                       r.subject, r.provider_id, r.model_id
                FROM research_report_versions v
                JOIN research_runs r ON r.run_id=v.run_id
                WHERE v.version=(
                    SELECT MAX(v2.version) FROM research_report_versions v2
                    WHERE v2.report_id=v.report_id
                )
                ORDER BY v.created_at DESC LIMIT 50
                """
            ).fetchall()
        return {
            "datasets": [dict(row) for row in datasets],
            "templates": [dict(row) for row in templates],
            "reports": [dict(row) for row in reports],
            "providers": [
                {
                    "provider_id": provider_id,
                    "region": region,
                    "status": (
                        "AVAILABLE"
                        if key_name is None or bool(os.environ.get(key_name))
                        else "NOT_CONFIGURED"
                    ),
                    "mode": "SIMULATION" if key_name is None else "REAL",
                    "api_key_configured": (
                        False if key_name is None else bool(os.environ.get(key_name))
                    ),
                }
                for provider_id, region, key_name in (
                    ("mock-cn", "CN", None),
                    ("deepseek", "CN", "DEEPSEEK_API_KEY"),
                    ("qwen", "CN", "DASHSCOPE_API_KEY"),
                    ("glm", "CN", "GLM_API_KEY"),
                    ("kimi", "CN", "KIMI_API_KEY"),
                    ("openai", "US", "OPENAI_API_KEY"),
                )
            ],
        }
