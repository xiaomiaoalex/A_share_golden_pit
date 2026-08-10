from datetime import date, datetime

from src.data.point_in_time.contracts import DataEnvelope, DividendBundle, FetchStatus
from src.data.point_in_time.reconciliation import verify_symbol_sources
from src.screening.tier1_v2.contracts import (
    DividendEvent,
    FinancialReportFact,
    MarketSnapshot,
    RiskWarningStatus,
)


def success(data, provider, endpoint):
    return DataEnvelope(
        FetchStatus.SUCCESS,
        data,
        provider,
        endpoint,
        {},
        fetched_at=datetime(2026, 8, 10),
    )


class Provider:
    def __init__(self, name, pe, revenue):
        self.provider_name = name
        self.today = date(2026, 8, 10)
        self.pe = pe
        self.revenue = revenue

    def get_market_snapshot(self, symbol, as_of_date):
        return success(
            MarketSnapshot(
                symbol, as_of_date, 10, 100, 10, self.pe, self.provider_name
            ),
            self.provider_name,
            "market",
        )

    def get_financial_facts(self, symbol, as_of_date):
        return success(
            [
                FinancialReportFact(
                    symbol,
                    date(2026, 3, 31),
                    date(2026, 4, 20),
                    self.revenue,
                    10,
                    self.provider_name,
                )
            ],
            self.provider_name,
            "financial",
        )

    def get_dividend_bundle(self, symbol, as_of_date):
        return success(
            DividendBundle(
                (
                    DividendEvent(
                        symbol,
                        date(2026, 5, 1),
                        1,
                        "实施",
                        self.provider_name,
                    ),
                ),
                (),
            ),
            self.provider_name,
            "dividend",
        )

    def get_risk_warning_status(self, symbol, stock_name, as_of_date):
        return success(
            RiskWarningStatus(
                symbol, as_of_date, False, stock_name, self.provider_name
            ),
            self.provider_name,
            "risk",
        )


def test_reconciliation_passes_matching_contracts_and_warns_material_difference():
    report = verify_symbol_sources(
        [Provider("one", 12, 100), Provider("two", 12.1, 102)],
        "000001",
        date(2026, 8, 10),
    )
    by_field = {check["field"]: check for check in report["checks"]}
    assert by_field["supplier_pe_ttm"]["verdict"] == "PASS"
    assert by_field["operating_revenue"]["verdict"] == "WARN"
    assert by_field["risk_warning_status"]["verdict"] == "PASS"
    assert report["overall_verdict"] == "WARN"


def test_reconciliation_is_insufficient_when_only_one_source_is_available():
    report = verify_symbol_sources(
        [Provider("one", 12, 100)],
        "000001",
        date(2026, 8, 10),
    )

    assert report["overall_verdict"] == "INSUFFICIENT"
    assert all(check["verdict"] == "INSUFFICIENT" for check in report["checks"])


class HistoryProvider(Provider):
    def get_financial_facts(self, symbol, as_of_date):
        facts = []
        for year in range(2023, 2026):
            for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
                period = date(year, month, day)
                facts.append(
                    FinancialReportFact(
                        symbol,
                        period,
                        period,
                        self.revenue,
                        10,
                        self.provider_name,
                    )
                )
        return success(facts, self.provider_name, "financial")


def test_reconciliation_limits_financial_checks_to_decision_window():
    report = verify_symbol_sources(
        [HistoryProvider("one", 12, 100), HistoryProvider("two", 12, 100)],
        "000001",
        date(2026, 8, 10),
    )

    financial_checks = [
        check
        for check in report["checks"]
        if check["field"] in {"operating_revenue", "parent_net_profit"}
    ]
    assert len(financial_checks) == 16
    assert min(check["grain"] for check in financial_checks) == "2024-03-31"
