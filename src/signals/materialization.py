"""Materialize strategy-owned results into the cross-strategy SignalRecord contract."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, timedelta
from typing import Iterable, Mapping

from .contracts import SignalDirection, SignalRecord


def materialize_golden_pit_signals(
    decisions: Iterable[Mapping],
    *,
    run_id: str,
    release_id: str,
    data_snapshot_id: str,
    as_of_date: date,
) -> list[SignalRecord]:
    candidates = [item for item in decisions if item.get("screen_status") == "PASS"]
    candidates.sort(
        key=lambda item: (
            -(float(item.get("latest_fiscal_year_dividend_yield") or 0.0)),
            float(item.get("selected_pe_ttm") or float("inf")),
            str(item["symbol"]),
        )
    )
    result = []
    for rank, item in enumerate(candidates, 1):
        dividend = float(item.get("latest_fiscal_year_dividend_yield") or 0.0)
        pe = float(item.get("selected_pe_ttm") or 0.0)
        confidence = min(1.0, max(0.0, 0.5 + min(dividend, 0.1) * 3 - max(pe - 10, 0) / 100))
        result.append(
            SignalRecord(
                signal_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{run_id}:{item['symbol']}")),
                run_id=run_id,
                strategy_id="golden-pit",
                release_id=release_id,
                security_id=str(item.get("security_id") or f"CN:{item['symbol']}"),
                symbol=str(item["symbol"]),
                as_of_date=as_of_date,
                direction=SignalDirection.LONG,
                score=confidence * 100,
                rank=rank,
                confidence=confidence,
                valid_until=as_of_date + timedelta(days=30),
                attribution={
                    "screen_status": "PASS",
                    "pe_ttm": pe,
                    "latest_fiscal_year_dividend_yield": dividend,
                    "decision_id": item.get("decision_id"),
                },
                data_snapshot_id=data_snapshot_id,
            )
        )
    return result


def materialize_high_dividend_signals(
    rows: Iterable[Mapping],
    *,
    run_id: str,
    release_id: str,
    data_snapshot_id: str,
    as_of_date: date,
    max_pe: float = 12.0,
    min_dividend_yield: float = 0.04,
) -> list[SignalRecord]:
    candidates = [
        dict(item)
        for item in rows
        if float(item.get("pe_ttm") or float("inf")) > 0
        and float(item.get("pe_ttm") or float("inf")) <= max_pe
        and float(item.get("dividend_yield") or 0.0) >= min_dividend_yield
    ]
    candidates.sort(
        key=lambda item: (-float(item["dividend_yield"]), float(item["pe_ttm"]), str(item["symbol"]))
    )
    result = []
    for rank, item in enumerate(candidates, 1):
        dividend = float(item["dividend_yield"])
        pe = float(item["pe_ttm"])
        score = min(100.0, dividend * 1000 + (max_pe - pe) * 3)
        result.append(
            SignalRecord(
                signal_id=hashlib.sha256(f"{run_id}:{item['symbol']}".encode()).hexdigest(),
                run_id=run_id,
                strategy_id="high-dividend",
                release_id=release_id,
                security_id=str(item.get("security_id") or f"CN:{item['symbol']}"),
                symbol=str(item["symbol"]),
                as_of_date=as_of_date,
                direction=SignalDirection.LONG,
                score=score,
                rank=rank,
                confidence=min(0.95, 0.55 + dividend * 3),
                valid_until=as_of_date + timedelta(days=30),
                attribution={
                    "pe_ttm": pe,
                    "dividend_yield": dividend,
                    "thresholds": {"max_pe": max_pe, "min_dividend_yield": min_dividend_yield},
                },
                data_snapshot_id=data_snapshot_id,
            )
        )
    return result
