from datetime import date, datetime

from src.data.point_in_time.contracts import DataEnvelope, FetchStatus
from src.data.point_in_time.fallback import FallbackPointInTimeProvider
from src.screening.tier1_v2.contracts import MarketSnapshot


class MarketProvider:
    def __init__(self, envelope):
        self.envelope = envelope
        self.today = date(2026, 8, 10)

    def get_market_snapshot(self, symbol, as_of_date):
        return self.envelope


def envelope(status, data=None, provider="source"):
    return DataEnvelope(
        status=status,
        data=data,
        provider=provider,
        endpoint="market",
        request={},
        fetched_at=datetime(2026, 8, 10),
        error_message="failed" if status == FetchStatus.ERROR else None,
    )


def test_primary_failure_uses_fallback_without_changing_metric_value():
    snapshot = MarketSnapshot(
        symbol="000001",
        price_date=date(2026, 8, 10),
        close_price=10,
        market_cap=120,
        total_shares=12,
        supplier_pe_ttm=12,
        source="backup:market",
    )
    provider = FallbackPointInTimeProvider(
        MarketProvider(envelope(FetchStatus.ERROR, provider="primary")),
        MarketProvider(envelope(FetchStatus.SUCCESS, snapshot, "backup")),
    )

    result = provider.get_market_snapshot("000001", date(2026, 8, 10))

    assert result.status == FetchStatus.SUCCESS
    assert result.data.supplier_pe_ttm == 12
    assert len(result.raw_payload["fallback_trace"]) == 2
    assert "筛选口径未放宽" in result.quality_warnings[-1]


def test_all_sources_failed_remains_error():
    provider = FallbackPointInTimeProvider(
        MarketProvider(envelope(FetchStatus.ERROR, provider="primary")),
        MarketProvider(envelope(FetchStatus.SCHEMA_ERROR, provider="backup")),
    )
    result = provider.get_market_snapshot("000001", date(2026, 8, 10))
    assert result.status == FetchStatus.ERROR
    assert result.data is None
