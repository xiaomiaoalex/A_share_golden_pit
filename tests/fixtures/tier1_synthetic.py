from __future__ import annotations

from datetime import date

from src.screening.tier1_v2.contracts import FinancialReportFact, QuarterlyMetric


def fact(
    period: date,
    revenue: float,
    parent_np: float,
    announcement: date | None = None,
) -> FinancialReportFact:
    return FinancialReportFact(
        symbol="000001",
        report_period=period,
        announcement_date=announcement or period,
        operating_revenue=revenue,
        parent_net_profit=parent_np,
        source="synthetic",
    )


def improving_financial_facts() -> list[FinancialReportFact]:
    """Latest three YoY points are 5%, 10%, 15% across a year boundary."""

    return [
        fact(date(2024, 3, 31), 100, 10),
        fact(date(2024, 6, 30), 200, 20),
        fact(date(2024, 9, 30), 300, 30),
        fact(date(2024, 12, 31), 400, 40),
        fact(date(2025, 3, 31), 100, 10),
        fact(date(2025, 6, 30), 205, 20.5),
        fact(date(2025, 9, 30), 310, 31),
        fact(date(2025, 12, 31), 420, 42),
        fact(date(2026, 3, 31), 115, 11.5, date(2026, 4, 20)),
    ]


def improving_window() -> list[QuarterlyMetric]:
    quarters = [date(2025, 9, 30), date(2025, 12, 31), date(2026, 3, 31)]
    growth = [0.05, 0.10, 0.15]
    return [
        QuarterlyMetric(
            symbol="000001",
            quarter=quarter,
            revenue_single=100 * (1 + yoy),
            parent_np_single=10 * (1 + yoy),
            prior_year_revenue_single=100,
            prior_year_parent_np_single=10,
            revenue_yoy=yoy,
            parent_np_yoy=yoy,
            revenue_comparable=True,
            parent_np_comparable=True,
            formula="synthetic",
        )
        for quarter, yoy in zip(quarters, growth)
    ]
