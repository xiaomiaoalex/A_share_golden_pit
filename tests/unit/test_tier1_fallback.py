from datetime import date, datetime

from src.data.point_in_time.contracts import DataEnvelope, FetchStatus, UniverseItem
from src.data.point_in_time.fallback import FallbackPointInTimeProvider
from src.screening.tier1_v2.contracts import MarketSnapshot


class MarketProvider:
    def __init__(self, envelope):
        self.envelope = envelope
        self.today = date(2026, 8, 10)

    def get_market_snapshot(self, symbol, as_of_date):
        return self.envelope


class UniverseProvider:
    def __init__(self, provider_name, symbols):
        self.provider_name = provider_name
        self.symbols = symbols
        self.today = date(2026, 8, 10)
        self.current_window_days = 7
        self.call_count = 0

    def get_universe(self, as_of_date):
        self.call_count += 1
        return DataEnvelope(
            FetchStatus.SUCCESS,
            [UniverseItem(symbol, symbol, "SZ") for symbol in self.symbols],
            self.provider_name,
            "universe",
            {"as_of_date": as_of_date.isoformat()},
        )


class DividendProvider:
    def __init__(self, provider_name):
        self.provider_name = provider_name
        self.today = date(2026, 8, 10)
        self.call_count = 0

    def get_dividend_bundle(self, symbol, as_of_date):
        self.call_count += 1
        return envelope(FetchStatus.EMPTY, data=(), provider=self.provider_name)


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


def test_historical_universe_skips_limited_source_and_uses_exact_source():
    limited = UniverseProvider("AKShare", ["000001"])
    exact = UniverseProvider("Tushare Pro", ["000001", "000002"])
    provider = FallbackPointInTimeProvider(limited, exact)

    result = provider.get_universe(date(2020, 12, 31))

    assert result.provider == "Tushare Pro"
    assert [item.symbol for item in result.data] == ["000001", "000002"]
    assert limited.call_count == 0
    assert exact.call_count == 1


def test_historical_universe_fails_closed_without_exact_source():
    akshare = UniverseProvider("AKShare", ["000001"])
    baostock = UniverseProvider("BaoStock", ["000001"])
    provider = FallbackPointInTimeProvider(akshare, baostock)

    result = provider.get_universe(date(2020, 12, 31))

    assert result.status == FetchStatus.ERROR
    assert result.error_type == "NO_QUALIFIED_SOURCE"
    assert akshare.call_count == 0
    assert baostock.call_count == 0


def test_recent_universe_can_use_current_limited_source():
    limited = UniverseProvider("AKShare", ["000001"])
    provider = FallbackPointInTimeProvider(limited)

    result = provider.get_universe(date(2026, 8, 9))

    assert result.provider == "AKShare"
    assert [item.symbol for item in result.data] == ["000001"]
    assert limited.call_count == 1


def test_exact_capability_is_preferred_over_configured_limited_source():
    limited = DividendProvider("AKShare")
    exact = DividendProvider("BaoStock")
    provider = FallbackPointInTimeProvider(limited, exact)

    result = provider.get_dividend_bundle("000001", date(2026, 8, 10))

    assert result.provider == "BaoStock"
    assert exact.call_count == 1
    assert limited.call_count == 0


def test_repeated_provider_failures_open_circuit_and_use_backup():
    primary = MarketProvider(envelope(FetchStatus.ERROR, provider="primary"))
    primary.provider_name = "primary"
    backup_snapshot = MarketSnapshot(
        "000001", date(2026, 8, 10), 10, 120, 12, 12, "backup"
    )
    backup = MarketProvider(
        envelope(FetchStatus.SUCCESS, backup_snapshot, provider="backup")
    )
    backup.provider_name = "backup"
    provider = FallbackPointInTimeProvider(
        primary,
        backup,
        circuit_failure_threshold=1,
        circuit_cooldown_seconds=60,
    )

    provider.get_market_snapshot("000001", date(2026, 8, 10))
    result = provider.get_market_snapshot("000002", date(2026, 8, 10))

    assert result.provider == "backup"
    assert result.raw_payload["fallback_trace"][0]["error_type"] == "CIRCUIT_OPEN"
