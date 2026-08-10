from datetime import date, datetime

from src.data.point_in_time.contracts import (
    DataEnvelope,
    DividendBundle,
    FetchStatus,
    UniverseItem,
)
from src.screening.tier1_v2.contracts import (
    DividendEvent,
    MarketSnapshot,
    RiskWarningStatus,
)
from src.screening.tier1_v2.pipeline import Tier1Pipeline
from src.storage.tier1_repository import Tier1Repository
from tests.fixtures.tier1_synthetic import improving_financial_facts


def success(data, endpoint):
    return DataEnvelope(
        status=FetchStatus.SUCCESS,
        data=data,
        provider="synthetic",
        endpoint=endpoint,
        request={},
        fetched_at=datetime(2026, 8, 10),
    )


class SyntheticProvider:
    def __init__(self, supplier_pe=12.0, today=date(2026, 8, 10)):
        self.supplier_pe = supplier_pe
        self.today = today
        self.calls = []

    @staticmethod
    def exchange_for(symbol):
        return "SZ"

    def get_market_snapshot(self, symbol, as_of_date):
        self.calls.append("market")
        return success(
            MarketSnapshot(
                symbol=symbol,
                price_date=as_of_date,
                close_price=10,
                market_cap=522,
                total_shares=52.2,
                supplier_pe_ttm=self.supplier_pe,
                source="synthetic:market",
            ),
            "market",
        )

    def get_financial_facts(self, symbol, as_of_date):
        self.calls.append("financial")
        return success(improving_financial_facts(), "financial")

    def get_dividend_bundle(self, symbol, as_of_date):
        self.calls.append("dividend")
        return success(
            DividendBundle(
                events=(
                    DividendEvent(
                        symbol=symbol,
                        ex_date=date(2026, 2, 1),
                        raw_cash_per_share_pre_tax=0.6,
                        status="实施分配",
                        source="synthetic:dividend",
                    ),
                ),
                actions=(),
            ),
            "dividend",
        )

    def get_risk_warning_status(self, symbol, stock_name, as_of_date):
        self.calls.append("risk")
        return success(
            RiskWarningStatus(
                symbol=symbol,
                as_of_date=as_of_date,
                is_risk_warning=False,
                security_name=stock_name,
                source="synthetic:risk",
            ),
            "risk",
        )


def run_one(tmp_path, provider, as_of=date(2026, 8, 10)):
    repository = Tier1Repository(tmp_path / "tier1.db")
    result = Tier1Pipeline(provider, repository).run(
        as_of,
        universe_items=[UniverseItem("000001", "测试股份", "SZ")],
    )
    row = repository.decisions(result["run_id"])[0]
    return result, row, repository


def test_pipeline_pass_persists_raw_series_lineage_and_decision(tmp_path):
    result, row, repository = run_one(tmp_path, SyntheticProvider())

    assert result["summary"] == {"PASS": 1}
    assert row["business_status"] == "PASS"
    assert row["data_status"] == "COMPLETE"
    with repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM tier1_raw_metrics").fetchone()[0] > 0
        assert connection.execute("SELECT COUNT(*) FROM tier1_quarterly_series").fetchone()[0] > 0
        assert connection.execute("SELECT COUNT(*) FROM source_lineage").fetchone()[0] >= 4


def test_known_pe_fail_short_circuits_but_keeps_partial_data_state(tmp_path):
    provider = SyntheticProvider(supplier_pe=15.0)
    result, row, _ = run_one(tmp_path, provider)

    assert result["summary"] == {"FAIL": 1}
    assert row["business_status"] == "FAIL"
    assert row["data_status"] == "PARTIAL"
    assert provider.calls == ["market"]


def test_historical_run_uses_point_in_time_self_computed_pe(tmp_path):
    provider = SyntheticProvider(supplier_pe=10.0)
    _, row, _ = run_one(tmp_path, provider, as_of=date(2026, 4, 30))

    assert row["pe_selection_method"] == "POINT_IN_TIME_SELF_COMPUTED"
    assert row["supplier_pe_ttm"] == 10.0
    assert row["self_pe_ttm"] == 12.0
    assert row["selected_pe_ttm"] == 12.0
