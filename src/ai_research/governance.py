"""Deterministic AI permissions, budget and change-proposal controls."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.strategies.golden_pit.persistence.tier1_repository import Tier1Repository

INJECTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore (all|any|the) previous instructions",
        r"reveal (the )?(system|developer) prompt",
        r"绕过.*(权限|规则|审批)",
        r"忽略.*(系统|开发者|之前).*(指令|提示)",
        r"直接(下单|修改策略|发布)",
    )
)


def detect_prompt_injection(content: str) -> tuple[str, ...]:
    return tuple(pattern.pattern for pattern in INJECTION_PATTERNS if pattern.search(content))


class AIGovernanceService:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def migrate(self) -> None:
        Tier1Repository(self.db_path).migrate_all()

    def validate_tools(self, requested: Iterable[str], allowed: Iterable[str]) -> None:
        denied = set(requested) - set(allowed)
        if denied:
            raise PermissionError(f"AI 工具越权: {sorted(denied)}")

    def set_budget(self, provider_id: str, period: str, budget: float) -> None:
        if budget < 0:
            raise ValueError("Provider 预算不能为负")
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            connection.execute(
                """
                INSERT INTO provider_budgets(provider_id, period, budget, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(provider_id, period) DO UPDATE SET
                    budget=excluded.budget, updated_at=excluded.updated_at
                """,
                (provider_id, period, budget, datetime.now(timezone.utc).isoformat()),
            )

    def consume_budget(self, provider_id: str, period: str, amount: float) -> None:
        if amount < 0:
            raise ValueError("成本不能为负")
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE provider_budgets SET spent=spent+?, updated_at=?
                WHERE provider_id=? AND period=? AND spent+?<=budget
                """,
                (
                    amount,
                    datetime.now(timezone.utc).isoformat(),
                    provider_id,
                    period,
                    amount,
                ),
            )
            if cursor.rowcount != 1:
                raise PermissionError("Provider 预算不足或尚未配置")

    def create_strategy_change_proposal(
        self,
        *,
        strategy_id: str,
        base_release_id: str,
        changes: dict[str, Any],
        evidence_ids: list[str],
        created_by: str,
    ) -> str:
        forbidden = {"status", "orders", "positions", "production_release"} & set(changes)
        if forbidden:
            raise PermissionError(f"AI 策略提案包含禁止字段: {sorted(forbidden)}")
        if not evidence_ids:
            raise ValueError("策略变更提案必须引用证据")
        proposal_id = str(uuid.uuid4())
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            connection.execute(
                """
                INSERT INTO strategy_change_proposals(
                    proposal_id, strategy_id, base_release_id, status,
                    change_json, evidence_json, created_by, created_at
                ) VALUES (?, ?, ?, 'DRAFT', ?, ?, ?, ?)
                """,
                (
                    proposal_id,
                    strategy_id,
                    base_release_id,
                    json.dumps(changes, ensure_ascii=False, sort_keys=True),
                    json.dumps(evidence_ids, ensure_ascii=False),
                    created_by,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return proposal_id
