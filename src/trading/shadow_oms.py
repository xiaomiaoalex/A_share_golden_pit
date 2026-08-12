"""Append-only simulated OMS; it contains no broker gateway."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from src.artifacts import ArtifactRepository
from src.strategies.golden_pit.persistence.tier1_repository import Tier1Repository


class ShadowOMS:
    TRANSITIONS = {
        "CREATED": {"APPROVED", "REJECTED", "CANCELLED"},
        "APPROVED": {"SUBMITTED", "CANCELLED"},
        "SUBMITTED": {"FILLED", "REJECTED", "CANCELLED"},
        "FILLED": set(),
        "REJECTED": set(),
        "CANCELLED": set(),
    }

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def migrate(self) -> None:
        Tier1Repository(self.db_path).migrate_all()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _human(actor: str) -> None:
        if not actor or actor.lower().startswith("ai:"):
            raise PermissionError("AI 不得创建或推进交易订单")

    def emergency_stop(self, *, actor: str, reason: str) -> None:
        self._human(actor)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO trading_controls(control_id, enabled, reason, actor, created_at)
                VALUES (?, 0, ?, ?, ?)
                """,
                (str(uuid.uuid4()), reason, actor, datetime.now(timezone.utc).isoformat()),
            )

    def enable(self, *, actor: str, reason: str) -> None:
        self._human(actor)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO trading_controls(control_id, enabled, reason, actor, created_at)
                VALUES (?, 1, ?, ?, ?)
                """,
                (str(uuid.uuid4()), reason, actor, datetime.now(timezone.utc).isoformat()),
            )

    def _enabled(self, connection: sqlite3.Connection) -> bool:
        row = connection.execute(
            "SELECT enabled FROM trading_controls ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return bool(row and row["enabled"])

    def create_orders(
        self,
        portfolio_artifact_id: str,
        orders: Iterable[Mapping],
        *,
        actor: str,
    ) -> list[str]:
        self._human(actor)
        artifact = ArtifactRepository(self.db_path).get(portfolio_artifact_id)
        if artifact["artifact_type"] != "PORTFOLIO" or artifact["status"] not in {
            "FEASIBLE",
            "VALIDATED",
            "PUBLISHED",
        }:
            raise PermissionError("只有约束通过的组合产物可生成 Shadow 订单")
        created = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not self._enabled(connection):
                raise PermissionError("Shadow Trading 已紧急停止或尚未启用")
            for order in orders:
                quantity = int(order["quantity"])
                if quantity <= 0 or quantity % 100 != 0:
                    raise ValueError("Shadow 订单必须为正整手数量")
                order_id = str(uuid.uuid4())
                connection.execute(
                    """
                    INSERT INTO shadow_orders(
                        order_version_id, order_id, version, portfolio_artifact_id,
                        security_id, side, quantity, status, actor, created_at
                    ) VALUES (?, ?, 1, ?, ?, ?, ?, 'CREATED', ?, ?)
                    """,
                    (
                        str(uuid.uuid4()), order_id, portfolio_artifact_id,
                        order["security_id"], order["side"], quantity, actor,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                created.append(order_id)
        return created

    def transition(self, order_id: str, target: str, *, actor: str, note: str = "") -> dict:
        self._human(actor)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            latest = connection.execute(
                "SELECT * FROM shadow_orders WHERE order_id=? ORDER BY version DESC LIMIT 1",
                (order_id,),
            ).fetchone()
            if latest is None:
                raise ValueError("未知 Shadow 订单")
            if target not in self.TRANSITIONS[str(latest["status"])]:
                raise ValueError("Shadow 订单状态转换无效")
            if target == "SUBMITTED" and not self._enabled(connection):
                raise PermissionError("紧急停止状态禁止提交订单")
            connection.execute(
                """
                INSERT INTO shadow_orders(
                    order_version_id, order_id, version, portfolio_artifact_id,
                    security_id, side, quantity, status, actor, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()), order_id, int(latest["version"]) + 1,
                    latest["portfolio_artifact_id"], latest["security_id"],
                    latest["side"], latest["quantity"], target, actor, note,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return self.get(order_id)

    def get(self, order_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM shadow_orders WHERE order_id=? ORDER BY version DESC LIMIT 1",
                (order_id,),
            ).fetchone()
        if row is None:
            raise ValueError("未知 Shadow 订单")
        return dict(row)
