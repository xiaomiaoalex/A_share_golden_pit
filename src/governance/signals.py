"""Cross-strategy overlap, conflict and marginal contribution read model."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping


def signal_governance(signals: Iterable[Mapping]) -> dict:
    rows = [dict(item) for item in signals]
    by_strategy: dict[str, set[str]] = defaultdict(set)
    by_security: dict[str, list[dict]] = defaultdict(list)
    for item in rows:
        strategy = str(item["strategy_id"])
        security = str(item["security_id"])
        by_strategy[strategy].add(security)
        by_security[security].append(item)
    strategies = sorted(by_strategy)
    overlaps = []
    for left_index, left in enumerate(strategies):
        for right in strategies[left_index + 1 :]:
            intersection = by_strategy[left] & by_strategy[right]
            union = by_strategy[left] | by_strategy[right]
            overlaps.append(
                {
                    "left": left,
                    "right": right,
                    "shared": len(intersection),
                    "jaccard": len(intersection) / len(union) if union else 0.0,
                }
            )
    conflicts = []
    for security, items in by_security.items():
        directions = {str(item["direction"]) for item in items}
        directional = directions - {"NEUTRAL"}
        if len(directional) > 1:
            conflicts.append(
                {
                    "security_id": security,
                    "symbol": items[0]["symbol"],
                    "opinions": [
                        {
                            "strategy_id": item["strategy_id"],
                            "direction": item["direction"],
                            "score": item["score"],
                            "confidence": item["confidence"],
                        }
                        for item in items
                    ],
                }
            )
    return {
        "strategies": strategies,
        "overlaps": overlaps,
        "conflicts": conflicts,
        "signal_count": len(rows),
    }
