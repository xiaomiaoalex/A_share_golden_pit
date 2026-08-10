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
    assert result["data_quality"]["quality_gate_passed"] is True
    assert result["data_quality"]["verification_counts"] == {"SINGLE_SOURCE": 5}
    with repository.connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM tier1_raw_metrics").fetchone()[0]
            > 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM tier1_quarterly_series"
            ).fetchone()[0]
            > 0
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM source_lineage").fetchone()[0] >= 4
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM screening_run_universe"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT status FROM tier1_item_attempts"
        ).fetchone()[0] == "COMPLETED"


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


def test_quality_gate_blocks_future_market_data_and_preserves_run(tmp_path):
    class FutureMarketProvider(SyntheticProvider):
        def get_market_snapshot(self, symbol, as_of_date):
            result = super().get_market_snapshot(symbol, as_of_date)
            result.data = MarketSnapshot(
                symbol=symbol,
                price_date=date(2026, 8, 11),
                close_price=10,
                market_cap=522,
                total_shares=52.2,
                supplier_pe_ttm=12,
                source="synthetic:future",
            )
            return result

    result, row, repository = run_one(tmp_path, FutureMarketProvider())

    assert row["business_status"] != "PASS"
    assert result["data_quality"]["quality_gate_passed"] is False
    assert result["data_quality"]["blocking_assessments"] == 1
    with repository.connect() as connection:
        observation = connection.execute(
            "SELECT fetch_status FROM source_observations WHERE field_group='market'"
        ).fetchone()
        assessment = connection.execute(
            "SELECT blocking FROM data_quality_assessments WHERE field_group='market'"
        ).fetchone()
    assert observation["fetch_status"] == "SUCCESS"
    assert assessment["blocking"] == 1


def test_resume_skips_completed_and_runs_symbol_without_decision(tmp_path):
    provider = SyntheticProvider()
    repository = Tier1Repository(tmp_path / "resume.db")
    pipeline = Tier1Pipeline(provider, repository)
    result = pipeline.run(
        date(2026, 8, 10),
        universe_items=[
            UniverseItem("000001", "甲公司", "SZ"),
            UniverseItem("000002", "乙公司", "SZ"),
        ],
    )
    run_id = result["run_id"]
    with repository.connect() as connection:
        connection.execute(
            "DELETE FROM tier1_decisions WHERE run_id=? AND symbol='000002'",
            (run_id,),
        )
        connection.execute(
            """
            UPDATE screening_run_universe
            SET item_status='PENDING'
            WHERE run_id=? AND symbol='000002'
            """,
            (run_id,),
        )
        connection.execute(
            "UPDATE screening_runs SET status='INTERRUPTED' WHERE run_id=?",
            (run_id,),
        )
    provider.calls.clear()

    resumed = pipeline.resume(run_id, mode="unfinished")

    assert resumed["processed_count"] == 1
    assert len(repository.decisions(run_id)) == 2
    assert provider.calls == ["market", "financial", "dividend", "risk"]
    with repository.connect() as connection:
        trigger = connection.execute(
            """
            SELECT trigger_type FROM tier1_item_attempts
            WHERE run_id=? AND symbol='000002' ORDER BY attempt_no DESC LIMIT 1
            """,
            (run_id,),
        ).fetchone()[0]
    assert trigger == "RESUME"


def test_data_retry_reprocesses_data_error_but_not_normal_fail(tmp_path):
    class FinancialErrorProvider(SyntheticProvider):
        def get_financial_facts(self, symbol, as_of_date):
            self.calls.append("financial")
            return DataEnvelope(
                status=FetchStatus.ERROR,
                data=None,
                provider="synthetic",
                endpoint="financial",
                request={},
                error_type="TimeoutError",
                error_message="temporary",
            )

    repository = Tier1Repository(tmp_path / "retry-data.db")
    failing = FinancialErrorProvider()
    result = Tier1Pipeline(failing, repository).run(
        date(2026, 8, 10),
        universe_items=[UniverseItem("000001", "测试股份", "SZ")],
    )
    run_id = result["run_id"]
    assert repository.decisions(run_id)[0]["screen_status"] == "DATA_ERROR"

    healthy = SyntheticProvider()
    retried = Tier1Pipeline(healthy, repository).resume(run_id, mode="data_gaps")

    assert retried["processed_count"] == 1
    assert repository.decisions(run_id)[0]["screen_status"] == "PASS"
    with repository.connect() as connection:
        trigger = connection.execute(
            """
            SELECT trigger_type FROM tier1_item_attempts
            WHERE run_id=? ORDER BY attempt_no DESC LIMIT 1
            """,
            (run_id,),
        ).fetchone()[0]
    assert trigger == "DATA_RETRY"


def test_keyboard_interrupt_marks_run_and_item_recoverable(tmp_path):
    class InterruptingProvider(SyntheticProvider):
        def get_market_snapshot(self, symbol, as_of_date):
            raise KeyboardInterrupt("operator stop")

    repository = Tier1Repository(tmp_path / "interrupt.db")
    try:
        Tier1Pipeline(InterruptingProvider(), repository).run(
            date(2026, 8, 10),
            universe_items=[UniverseItem("000001", "测试股份", "SZ")],
        )
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("expected KeyboardInterrupt")

    with repository.connect() as connection:
        run = connection.execute("SELECT status FROM screening_runs").fetchone()
        item = connection.execute(
            "SELECT item_status FROM screening_run_universe"
        ).fetchone()
        lease_count = connection.execute(
            "SELECT COUNT(*) FROM screening_run_leases"
        ).fetchone()[0]
    assert run["status"] == "INTERRUPTED"
    assert item["item_status"] == "RETRYABLE_FAILED"
    assert lease_count == 0


def test_legacy_run_reconstructs_validated_universe_before_resume(tmp_path):
    class UniverseProvider(SyntheticProvider):
        def get_universe(self, as_of_date):
            return success(
                [
                    UniverseItem("000001", "甲公司", "SZ"),
                    UniverseItem("000002", "乙公司", "SZ"),
                ],
                "universe",
            )

    provider = UniverseProvider()
    repository = Tier1Repository(tmp_path / "legacy-resume.db")
    pipeline = Tier1Pipeline(provider, repository)
    result = pipeline.run(
        date(2026, 8, 10),
        universe_items=[
            UniverseItem("000001", "甲公司", "SZ"),
            UniverseItem("000002", "乙公司", "SZ"),
        ],
    )
    run_id = result["run_id"]
    with repository.connect() as connection:
        connection.execute("DELETE FROM tier1_item_attempts WHERE run_id=?", (run_id,))
        connection.execute("DELETE FROM screening_run_universe WHERE run_id=?", (run_id,))
        connection.execute(
            "DELETE FROM screening_universe_snapshots WHERE run_id=?", (run_id,)
        )
        connection.execute(
            "DELETE FROM tier1_decisions WHERE run_id=? AND symbol='000002'",
            (run_id,),
        )
        connection.execute(
            "UPDATE screening_runs SET status='INTERRUPTED' WHERE run_id=?",
            (run_id,),
        )

    resumed = pipeline.resume(run_id, mode="unfinished")

    assert resumed["processed_count"] == 1
    assert repository.has_run_universe(run_id) is True
    assert len(repository.decisions(run_id)) == 2
    with repository.connect() as connection:
        snapshot_source = connection.execute(
            "SELECT snapshot_source FROM screening_universe_snapshots WHERE run_id=?",
            (run_id,),
        ).fetchone()[0]
    assert snapshot_source == "RECONSTRUCTED_LEGACY"
