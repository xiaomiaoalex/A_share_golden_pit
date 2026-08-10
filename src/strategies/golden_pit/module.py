"""Golden-pit strategy facade: metadata, read model and executable actions."""

from __future__ import annotations

import sys
from datetime import date
from http import HTTPStatus
from pathlib import Path
from typing import Any

from src.storage.tier2_repository import Tier2Repository
from src.storage.tier3_repository import Tier3Repository
from src.strategies.contracts import StrategyDescriptor, StrategyOperation

from .presentation import GoldenPitReadModel

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class GoldenPitStrategy:
    """Composition boundary for the adjustable Stage A/B/C strategy."""

    descriptor = StrategyDescriptor(
        strategy_id="golden-pit",
        name="黄金坑 Stage A/B/C",
        short_name="黄金坑",
        description="低估值、高分红与趋势改善初筛，叠加证据研究和行业化风险终审。",
        version="tier1-v2.1.0",
        ui_module="/strategies/golden-pit.js",
        stages=("客观初筛", "证据研究", "风险终审"),
        capabilities=("全市场筛选", "断点续跑", "数据缺口补跑", "人工复核"),
        accent="emerald",
    )

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self.read_model = GoldenPitReadModel(db_path)

    def catalog_entry(self) -> dict[str, Any]:
        overview = self.overview()
        run = overview.get("run")
        summary = overview["summary"]
        return {
            **self.descriptor.as_dict(),
            "latest_run": (
                {
                    "run_id": run["run_id"],
                    "as_of_date": run["as_of_date"],
                    "status": run["status"],
                    "started_at": run.get("started_at"),
                    "finished_at": run.get("finished_at"),
                }
                if run
                else None
            ),
            "metrics": [
                {"key": "universe", "label": "覆盖股票", "value": summary["universe"]},
                {"key": "stage_a", "label": "初筛通过", "value": summary["stage_a_pass"]},
                {"key": "stage_b", "label": "研究通过", "value": summary["stage_b_pass"]},
                {"key": "stage_c", "label": "最终候选", "value": summary["stage_c_pass"]},
            ],
        }

    def overview(self, run_id: str | None = None) -> dict[str, Any]:
        value = self.read_model.overview(run_id)
        value["strategy"] = self.descriptor.as_dict()
        return value

    def running_runs(self) -> list[dict[str, Any]]:
        runs = self.read_model.running_runs()
        for run in runs:
            run["strategy_id"] = self.descriptor.strategy_id
            run["strategy_name"] = self.descriptor.short_name
        return runs

    def handle_action(
        self, action: str, body: dict[str, Any]
    ) -> StrategyOperation:
        handlers = {
            "run": self._run,
            "export-evidence": self._export_evidence,
            "resume": lambda value: self._resume(value, data_retry=False),
            "retry-data": lambda value: self._resume(value, data_retry=True),
            "review-stage-b": self._review_stage_b,
            "review-stage-c": self._review_stage_c,
        }
        try:
            handler = handlers[action]
        except KeyError as exc:
            raise ValueError(f"黄金坑策略不支持动作: {action}") from exc
        return handler(body)

    def _run(self, body: dict[str, Any]) -> StrategyOperation:
        as_of = str(body.get("as_of", "")).strip()
        try:
            date.fromisoformat(as_of)
        except ValueError as exc:
            raise ValueError("筛选日期必须是 YYYY-MM-DD") from exc
        scope = str(body.get("scope", "symbols")).strip().lower()
        if scope not in {"market", "symbols"}:
            raise ValueError("scope 必须为 market 或 symbols")
        symbols = self._symbols(body.get("symbols", []))
        if scope == "symbols" and not symbols:
            raise ValueError("请至少输入一个股票代码")
        command = [
            sys.executable,
            str(PROJECT_ROOT / "main.py"),
            "workflow",
            "--as-of",
            as_of,
            "--db",
            self.db_path,
        ]
        if scope == "symbols":
            command.extend(["--symbols", *symbols])
        label = (
            f"{as_of} 黄金坑全市场筛选"
            if scope == "market"
            else f"{as_of} 黄金坑筛选（{len(symbols)} 只）"
        )
        return StrategyOperation(
            kind="job",
            status=HTTPStatus.ACCEPTED,
            label=label,
            command=tuple(command),
        )

    def _export_evidence(self, body: dict[str, Any]) -> StrategyOperation:
        run_id = self._required(body, "run_id")
        command = [
            sys.executable,
            str(PROJECT_ROOT / "main.py"),
            "export-tier2",
            "--run-id",
            run_id,
            "--db",
            self.db_path,
        ]
        symbols = self._symbols(body.get("symbols", []))
        if symbols:
            command.extend(["--symbols", *symbols])
        return StrategyOperation(
            kind="job",
            status=HTTPStatus.ACCEPTED,
            label="黄金坑 Stage B 证据包",
            command=tuple(command),
        )

    def _resume(
        self, body: dict[str, Any], *, data_retry: bool
    ) -> StrategyOperation:
        run_id = self._required(body, "run_id")
        command = [
            sys.executable,
            str(PROJECT_ROOT / "main.py"),
            "retry-tier1-data" if data_retry else "resume-tier1",
            "--run-id",
            run_id,
            "--db",
            self.db_path,
        ]
        symbols = self._symbols(body.get("symbols", []))
        if symbols:
            command.extend(["--symbols", *symbols])
        return StrategyOperation(
            kind="job",
            status=HTTPStatus.ACCEPTED,
            label="黄金坑数据缺口补跑" if data_retry else "黄金坑断点续跑",
            command=tuple(command),
        )

    def _review_stage_b(self, body: dict[str, Any]) -> StrategyOperation:
        review_id = Tier2Repository(self.db_path).save_human_review(
            assessment_id=self._required(body, "assessment_id"),
            decision=self._decision(body),
            reviewer=self._required(body, "reviewer"),
            rationale=self._required(body, "rationale"),
            expected_run_id=self._required(body, "run_id"),
            expected_symbol=self._required(body, "symbol"),
        )
        return StrategyOperation(
            kind="result",
            status=HTTPStatus.CREATED,
            payload={"review_id": review_id},
        )

    def _review_stage_c(self, body: dict[str, Any]) -> StrategyOperation:
        review_id = Tier3Repository(self.db_path).save_human_review(
            risk_assessment_id=self._required(body, "risk_assessment_id"),
            decision=self._decision(body),
            reviewer=self._required(body, "reviewer"),
            rationale=self._required(body, "rationale"),
            expected_run_id=self._required(body, "run_id"),
            expected_symbol=self._required(body, "symbol"),
        )
        return StrategyOperation(
            kind="result",
            status=HTTPStatus.CREATED,
            payload={"review_id": review_id},
        )

    @staticmethod
    def _symbols(raw: Any) -> list[str]:
        values = raw
        if isinstance(values, str):
            values = [item for item in values.replace(",", " ").split() if item]
        clean: list[str] = []
        for value in values or []:
            symbol = str(value).strip().upper()
            if symbol.endswith((".SH", ".SZ", ".BJ")):
                symbol = symbol[:-3]
            if not symbol.isdigit() or len(symbol) > 6:
                raise ValueError(f"无效股票代码: {value}")
            normalized = symbol.zfill(6)
            if normalized not in clean:
                clean.append(normalized)
        return clean

    @staticmethod
    def _required(body: dict[str, Any], key: str) -> str:
        value = str(body.get(key, "")).strip()
        if not value:
            raise ValueError(f"缺少字段: {key}")
        return value

    @staticmethod
    def _decision(body: dict[str, Any]) -> str:
        decision = str(body.get("decision", "")).upper()
        if decision not in {"PASS", "REVIEW", "REJECT"}:
            raise ValueError("decision 必须为 PASS、REVIEW 或 REJECT")
        return decision
