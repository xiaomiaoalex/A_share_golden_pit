"""Explain deterministic differences between two execution engines."""

from __future__ import annotations

from typing import Iterable, Mapping


def compare_execution_results(
    left: Iterable[Mapping], right: Iterable[Mapping]
) -> dict:
    left_by_order = {str(item["order_id"]): dict(item) for item in left}
    right_by_order = {str(item["order_id"]): dict(item) for item in right}
    differences = []
    for order_id in sorted(set(left_by_order) | set(right_by_order)):
        first, second = left_by_order.get(order_id), right_by_order.get(order_id)
        if first is None or second is None:
            differences.append({"order_id": order_id, "reason": "MISSING_ORDER_IN_ENGINE"})
            continue
        fields = {}
        for field in ("status", "filled_quantity", "price", "commission", "stamp_tax", "reason"):
            if first.get(field) != second.get(field):
                fields[field] = {"left": first.get(field), "right": second.get(field)}
        if fields:
            reason = "EXECUTION_RULE_DIFFERENCE"
            if any(field in fields for field in ("commission", "stamp_tax")):
                reason = "FEE_DIFFERENCE"
            if "filled_quantity" in fields or "status" in fields:
                reason = "FILL_DIFFERENCE"
            differences.append({"order_id": order_id, "reason": reason, "fields": fields})
    return {"matched": len(set(left_by_order) & set(right_by_order)), "differences": differences}
