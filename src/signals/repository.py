"""Persistence for cross-strategy signal aggregation."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from src.strategies.golden_pit.persistence.tier1_repository import Tier1Repository

from .contracts import SignalRecord


class SignalRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def migrate(self) -> None:
        Tier1Repository(self.db_path).migrate_all()

    def save(self, signals: Iterable[SignalRecord]) -> None:
        rows = list(signals)
        if not rows:
            return
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            connection.execute("PRAGMA busy_timeout=10000")
            connection.executemany(
                """
                INSERT OR IGNORE INTO strategy_signals(
                    signal_id, run_id, strategy_id, release_id, security_id,
                    symbol, as_of_date, direction, score, rank_value, confidence,
                    valid_until, attribution_json, data_snapshot_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.signal_id,
                        item.run_id,
                        item.strategy_id,
                        item.release_id,
                        item.security_id,
                        item.symbol,
                        item.as_of_date.isoformat(),
                        item.direction.value,
                        item.score,
                        item.rank,
                        item.confidence,
                        item.valid_until.isoformat(),
                        json.dumps(item.attribution, ensure_ascii=False, sort_keys=True),
                        item.data_snapshot_id,
                        item.created_at.isoformat(),
                    )
                    for item in rows
                ],
            )

    def aggregate(self, *, as_of_date: str | None = None) -> list[dict]:
        where = "WHERE as_of_date=?" if as_of_date else ""
        params = (as_of_date,) if as_of_date else ()
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                f"""
                SELECT * FROM strategy_signals {where}
                ORDER BY as_of_date DESC, strategy_id, rank_value
                """,  # noqa: S608 - where is a fixed internal fragment
                params,
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["rank"] = item.pop("rank_value")
            item["attribution"] = json.loads(item.pop("attribution_json"))
            result.append(item)
        return result
