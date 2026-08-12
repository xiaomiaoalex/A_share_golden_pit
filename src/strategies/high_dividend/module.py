"""Minimal second strategy proving platform routing is strategy-neutral."""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from typing import Any

from src.strategies.contracts import StrategyDescriptor, StrategyOperation


class HighDividendStrategy:
    asset_root = Path(__file__).resolve().parent / "static"
    descriptor = StrategyDescriptor(
        strategy_id="high-dividend",
        name="低估值高股息策略（开发预览）",
        short_name="高股息",
        description="尚未接入正式数据规则与运行链路，仅用于预览插件框架。",
        version="preview-v1",
        ui_module="/strategy-assets/high-dividend/app.js",
        ui_template="/strategy-assets/high-dividend/template.html",
        status="PREVIEW",
        stages=("价值筛选", "股息质量", "统一信号"),
        capabilities=("插件框架预览",),
        accent="amber",
    )

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def catalog_entry(self) -> dict[str, Any]:
        return {
            **self.descriptor.as_dict(),
            "latest_run": None,
            "metrics": [
                {"key": "universe", "label": "覆盖股票", "value": 0},
                {"key": "signals", "label": "统一信号", "value": 0},
            ],
        }

    def overview(
        self, run_id: str | None = None, *, compact: bool = False
    ) -> dict[str, Any]:
        return {
            "strategy": self.descriptor.as_dict(),
            "run": None,
            "summary": {"universe": 0, "signals": 0},
            "run_id": run_id,
        }

    def candidates_page(self, run_id: str, **query: Any) -> dict[str, Any]:
        return {"items": [], "page": 1, "page_size": 50, "total": 0, "pages": 0}

    def quality_page(self, run_id: str, **query: Any) -> dict[str, Any]:
        return {"items": [], "page": 1, "page_size": 50, "total": 0, "pages": 0}

    def running_runs(self) -> list[dict[str, Any]]:
        return []

    def handle_action(
        self, action: str, body: dict[str, Any]
    ) -> StrategyOperation:
        if action != "describe":
            raise ValueError(f"高股息演示策略暂不支持动作: {action}")
        return StrategyOperation(
            kind="result",
            status=HTTPStatus.OK,
            payload={"strategy": self.descriptor.as_dict()},
        )
