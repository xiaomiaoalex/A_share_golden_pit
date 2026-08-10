"""Golden Pit cross-source verification for point-in-time providers."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from typing import Any

from src.data.point_in_time.contracts import FetchStatus
from src.strategies.golden_pit.quantitative_screening.metrics import (
    calculate_dividend_ttm,
)

TOLERANCES = {
    "close_price": 0.001,
    "supplier_pe_ttm": 0.05,
    "operating_revenue": 0.001,
    "parent_net_profit": 0.001,
    "dividend_ttm_adjusted_per_share": 0.001,
}

REQUIRED_FIELDS = tuple(TOLERANCES) + ("risk_warning_status",)
FINANCIAL_FIELDS = ("operating_revenue", "parent_net_profit")
FINANCIAL_REPORT_WINDOW = 8


def _relative_spread(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    scale = max(max(abs(value) for value in values), 1e-12)
    return (max(values) - min(values)) / scale


def _numeric_check(field: str, grain: str, observations: list[dict]) -> dict:
    values = [float(item["value"]) for item in observations]
    tolerance = TOLERANCES[field]
    spread = _relative_spread(values)
    return {
        "field": field,
        "grain": grain,
        "verdict": "INSUFFICIENT"
        if len(values) < 2
        else ("PASS" if spread <= tolerance else "WARN"),
        "tolerance": tolerance,
        "relative_spread": spread,
        "observations": observations,
    }


def verify_symbol_sources(
    providers: Iterable[Any], symbol: str, as_of_date: date
) -> dict:
    providers = list(providers)
    responses = []
    numeric: dict[tuple[str, str], list[dict]] = defaultdict(list)
    risk_observations = []

    for provider in providers:
        provider_name = provider.provider_name
        market = provider.get_market_snapshot(symbol, as_of_date)
        financial = provider.get_financial_facts(symbol, as_of_date)
        dividend = provider.get_dividend_bundle(symbol, as_of_date)
        risk = provider.get_risk_warning_status(symbol, symbol, as_of_date)
        envelopes = {
            "market": market,
            "financial": financial,
            "dividend": dividend,
            "risk": risk,
        }
        responses.append(
            {
                "provider": provider_name,
                "groups": {
                    group: {
                        "status": envelope.status.value,
                        "endpoint": envelope.endpoint,
                        "error_type": envelope.error_type,
                        "error_message": envelope.error_message,
                        "quality_warnings": envelope.quality_warnings,
                    }
                    for group, envelope in envelopes.items()
                },
            }
        )

        if market.usable:
            grain = market.data.price_date.isoformat()
            for field in ("close_price", "supplier_pe_ttm"):
                value = getattr(market.data, field)
                if value is not None:
                    numeric[(field, grain)].append(
                        {"provider": provider_name, "value": value}
                    )

        if financial.usable:
            for fact in financial.data:
                grain = fact.report_period.isoformat()
                for field, value in (
                    ("operating_revenue", fact.operating_revenue),
                    ("parent_net_profit", fact.parent_net_profit),
                ):
                    if value is not None:
                        numeric[(field, grain)].append(
                            {"provider": provider_name, "value": value}
                        )

        bundle_available = dividend.usable or (
            dividend.status == FetchStatus.EMPTY and dividend.data is not None
        )
        if bundle_available:
            calculated = calculate_dividend_ttm(
                events=dividend.data.events,
                actions=dividend.data.actions,
                as_of_date=as_of_date,
                close_price=1.0,
            )
            if calculated.adjusted_per_share is not None:
                numeric[
                    ("dividend_ttm_adjusted_per_share", as_of_date.isoformat())
                ].append(
                    {"provider": provider_name, "value": calculated.adjusted_per_share}
                )

        if risk.usable and risk.data.is_risk_warning is not None:
            risk_observations.append(
                {"provider": provider_name, "value": risk.data.is_risk_warning}
            )

    # Three improving single-quarter YoY observations can require up to eight
    # cumulative statements (current periods, prior-year comparables and the
    # predecessors used to de-cumulate Q2-Q4).  Older reports add noise without
    # verifying any input used by the Tier1 decision.
    for field in FINANCIAL_FIELDS:
        grains = sorted(grain for candidate, grain in numeric if candidate == field)
        keep = set(grains[-FINANCIAL_REPORT_WINDOW:])
        for key in [key for key in numeric if key[0] == field and key[1] not in keep]:
            del numeric[key]

    checks = [
        _numeric_check(field, grain, observations)
        for (field, grain), observations in sorted(numeric.items())
    ]
    if risk_observations:
        distinct = {item["value"] for item in risk_observations}
        checks.append(
            {
                "field": "risk_warning_status",
                "grain": as_of_date.isoformat(),
                "verdict": "INSUFFICIENT"
                if len(risk_observations) < 2
                else ("PASS" if len(distinct) == 1 else "WARN"),
                "tolerance": "exact",
                "observations": risk_observations,
            }
        )

    checked_fields = {check["field"] for check in checks}
    for field in REQUIRED_FIELDS:
        if field in checked_fields:
            continue
        checks.append(
            {
                "field": field,
                "grain": as_of_date.isoformat(),
                "verdict": "INSUFFICIENT",
                "tolerance": "exact"
                if field == "risk_warning_status"
                else TOLERANCES[field],
                "observations": [],
            }
        )

    verdicts = {check["verdict"] for check in checks}
    if "WARN" in verdicts:
        overall = "WARN"
    elif "INSUFFICIENT" in verdicts:
        overall = "INSUFFICIENT"
    else:
        overall = "PASS"
    return {
        "symbol": str(symbol).zfill(6),
        "as_of_date": as_of_date.isoformat(),
        "overall_verdict": overall,
        "providers": [provider.provider_name for provider in providers],
        "responses": responses,
        "checks": checks,
        "note": "交叉验证只产生质量结论，不改变Tier1硬筛选口径或阈值",
    }
