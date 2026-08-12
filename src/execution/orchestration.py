"""Durable DAG state machine with retry budgets, breakers and dead letters."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.strategies.golden_pit.persistence.tier1_repository import Tier1Repository


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DurableOrchestrator:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def migrate(self) -> None:
        Tier1Repository(self.db_path).migrate_all()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def create_workflow(
        self,
        workflow_type: str,
        nodes: Iterable[Mapping[str, Any]],
        *,
        priority: int = 0,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        definitions = [dict(item) for item in nodes]
        ids = {str(item["node_id"]) for item in definitions}
        if len(ids) != len(definitions):
            raise ValueError("DAG 节点 ID 重复")
        for item in definitions:
            dependencies = set(map(str, item.get("dependencies", [])))
            if not dependencies.issubset(ids) or str(item["node_id"]) in dependencies:
                raise ValueError("DAG 依赖无效")
        dependency_map = {
            str(item["node_id"]): tuple(map(str, item.get("dependencies", [])))
            for item in definitions
        }
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ValueError("DAG 不能包含环")
            if node_id in visited:
                return
            visiting.add(node_id)
            for dependency_id in dependency_map[node_id]:
                visit(dependency_id)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in ids:
            visit(node_id)
        workflow_run_id = str(uuid.uuid4())
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO workflow_runs(
                    workflow_run_id, workflow_type, priority, status,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, 'QUEUED', ?, ?, ?)
                """,
                (workflow_run_id, workflow_type, priority, json.dumps(metadata or {}), now, now),
            )
            for item in definitions:
                dependencies = list(map(str, item.get("dependencies", [])))
                connection.execute(
                    """
                    INSERT INTO workflow_nodes(
                        node_id, workflow_run_id, node_type, dependency_ids_json,
                        status, attempt_count, retry_budget, payload_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
                    """,
                    (
                        item["node_id"], workflow_run_id, item["node_type"],
                        json.dumps(dependencies), "BLOCKED" if dependencies else "READY",
                        int(item.get("retry_budget", 0)),
                        json.dumps(item.get("payload", {}), ensure_ascii=False), now,
                    ),
                )
        return workflow_run_id

    def claim_ready(self, workflow_run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT status FROM workflow_runs WHERE workflow_run_id=?",
                (workflow_run_id,),
            ).fetchone()
            if run is None or run["status"] in {"PAUSED", "CANCELLED", "FAILED", "SUCCEEDED"}:
                return None
            row = connection.execute(
                """
                SELECT * FROM workflow_nodes
                WHERE workflow_run_id=? AND status='READY'
                ORDER BY node_id LIMIT 1
                """,
                (workflow_run_id,),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                UPDATE workflow_nodes SET status='RUNNING', attempt_count=attempt_count+1,
                    updated_at=? WHERE workflow_run_id=? AND node_id=? AND status='READY'
                """,
                (_now(), workflow_run_id, row["node_id"]),
            )
            connection.execute(
                "UPDATE workflow_runs SET status='RUNNING', updated_at=? WHERE workflow_run_id=?",
                (_now(), workflow_run_id),
            )
        return self.node(workflow_run_id, str(row["node_id"]))

    def complete(
        self, workflow_run_id: str, node_id: str, result: Mapping[str, Any]
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT workflow_run_id FROM workflow_nodes
                WHERE workflow_run_id=? AND node_id=? AND status='RUNNING'
                """,
                (workflow_run_id, node_id),
            ).fetchone()
            if row is None:
                raise ValueError("节点不存在或未运行")
            connection.execute(
                """
                UPDATE workflow_nodes SET status='SUCCEEDED', result_json=?, updated_at=?
                WHERE workflow_run_id=? AND node_id=?
                """,
                (json.dumps(result, ensure_ascii=False), _now(), workflow_run_id, node_id),
            )
            blocked = connection.execute(
                "SELECT node_id, dependency_ids_json FROM workflow_nodes WHERE workflow_run_id=? AND status='BLOCKED'",
                (workflow_run_id,),
            ).fetchall()
            succeeded = {
                str(item[0])
                for item in connection.execute(
                    "SELECT node_id FROM workflow_nodes WHERE workflow_run_id=? AND status='SUCCEEDED'",
                    (workflow_run_id,),
                ).fetchall()
            }
            for item in blocked:
                if set(json.loads(item["dependency_ids_json"])).issubset(succeeded):
                    connection.execute(
                        """
                        UPDATE workflow_nodes SET status='READY', updated_at=?
                        WHERE workflow_run_id=? AND node_id=?
                        """,
                        (_now(), workflow_run_id, item["node_id"]),
                    )
            unfinished = connection.execute(
                "SELECT COUNT(*) FROM workflow_nodes WHERE workflow_run_id=? AND status!='SUCCEEDED'",
                (workflow_run_id,),
            ).fetchone()[0]
            if unfinished == 0:
                connection.execute(
                    "UPDATE workflow_runs SET status='SUCCEEDED', updated_at=? WHERE workflow_run_id=?",
                    (_now(), workflow_run_id),
                )

    def fail(
        self, workflow_run_id: str, node_id: str, category: str, message: str
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM workflow_nodes
                WHERE workflow_run_id=? AND node_id=? AND status='RUNNING'
                """,
                (workflow_run_id, node_id),
            ).fetchone()
            if row is None:
                raise ValueError("节点不存在或未运行")
            retry = int(row["attempt_count"]) <= int(row["retry_budget"])
            status = "READY" if retry else "DEAD_LETTER"
            connection.execute(
                """
                UPDATE workflow_nodes SET status=?, error_category=?,
                    error_message=?, updated_at=? WHERE workflow_run_id=? AND node_id=?
                """,
                (status, category, message, _now(), workflow_run_id, node_id),
            )
            if not retry:
                connection.execute(
                    """
                    INSERT INTO workflow_dead_letters(
                        dead_letter_id, node_id, workflow_run_id, payload_json,
                        error_category, error_message, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()), node_id, row["workflow_run_id"], row["payload_json"],
                        category, message, _now(),
                    ),
                )
                connection.execute(
                    """
                    UPDATE workflow_runs SET status='FAILED', updated_at=?
                    WHERE workflow_run_id=?
                    """,
                    (_now(), workflow_run_id),
                )

    def pause(self, workflow_run_id: str) -> None:
        self._transition_workflow(workflow_run_id, {"QUEUED", "RUNNING"}, "PAUSED")

    def resume(self, workflow_run_id: str) -> None:
        self._transition_workflow(workflow_run_id, {"PAUSED"}, "QUEUED")

    def cancel(self, workflow_run_id: str) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                """
                UPDATE workflow_runs SET status='CANCELLED', updated_at=?
                WHERE workflow_run_id=? AND status IN ('QUEUED','RUNNING','PAUSED')
                """,
                (_now(), workflow_run_id),
            ).rowcount
            if not changed:
                raise ValueError("工作流不存在或已终止")
            connection.execute(
                """
                UPDATE workflow_nodes SET status='CANCELLED', updated_at=?
                WHERE workflow_run_id=?
                  AND status IN ('BLOCKED','READY','RUNNING')
                """,
                (_now(), workflow_run_id),
            )

    def _transition_workflow(
        self, workflow_run_id: str, allowed: set[str], target: str
    ) -> None:
        placeholders = ",".join("?" for _ in allowed)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                f"""
                UPDATE workflow_runs SET status=?, updated_at=?
                WHERE workflow_run_id=? AND status IN ({placeholders})
                """,  # noqa: S608 - placeholders are generated, values remain bound
                (target, _now(), workflow_run_id, *sorted(allowed)),
            ).rowcount
            if not changed:
                raise ValueError("工作流不存在或状态不允许此操作")

    def record_resource_failure(self, resource_id: str, *, threshold: int = 3) -> str:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO circuit_breakers(
                    resource_id, status, failure_count, threshold_value, updated_at
                ) VALUES (?, 'CLOSED', 1, ?, ?)
                ON CONFLICT(resource_id) DO UPDATE SET
                    failure_count=failure_count+1, threshold_value=excluded.threshold_value,
                    updated_at=excluded.updated_at
                """,
                (resource_id, threshold, _now()),
            )
            connection.execute(
                """
                UPDATE circuit_breakers SET status='OPEN', opened_at=?
                WHERE resource_id=? AND failure_count>=threshold_value
                """,
                (_now(), resource_id),
            )
            return str(connection.execute(
                "SELECT status FROM circuit_breakers WHERE resource_id=?", (resource_id,)
            ).fetchone()[0])

    def node(self, workflow_run_id: str, node_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM workflow_nodes
                WHERE workflow_run_id=? AND node_id=?
                """,
                (workflow_run_id, node_id),
            ).fetchone()
        if row is None:
            raise ValueError("未知工作流节点")
        result = dict(row)
        result["dependencies"] = json.loads(result.pop("dependency_ids_json"))
        result["payload"] = json.loads(result.pop("payload_json"))
        return result
