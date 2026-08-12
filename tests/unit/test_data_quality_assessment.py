from datetime import date, datetime

from src.data.point_in_time.contracts import (
    DataEnvelope,
    DividendBundle,
    FetchStatus,
    UniverseItem,
)
from src.data.quality import VerificationStatus, assess_envelope, gate_envelope
from src.screening.tier1_v2.contracts import FinancialReportFact, MarketSnapshot


def envelope(data, provider="synthetic"):
    return DataEnvelope(
        FetchStatus.SUCCESS,
        data,
        provider,
        "test",
        {},
        fetched_at=datetime(2026, 8, 10),
    )


def test_future_market_data_is_blocked_without_changing_raw_fetch_status():
    raw = envelope(MarketSnapshot("000001", date(2026, 8, 11), 10, 100, 10, 10, "test"))
    assessment = assess_envelope("market", raw, date(2026, 8, 10))
    gated = gate_envelope(raw, assessment)

    assert raw.status == FetchStatus.SUCCESS
    assert assessment.blocking is True
    assert gated.status == FetchStatus.SCHEMA_ERROR
    assert gated.error_type == "DATA_QUALITY_GATE"


def test_duplicate_universe_business_key_is_blocked():
    raw = envelope(
        [
            UniverseItem("000001", "测试一", "SZ"),
            UniverseItem("000001", "测试二", "SZ"),
        ]
    )
    assessment = assess_envelope("universe", raw, date(2026, 8, 10))

    assert assessment.blocking is True
    assert any(issue.code == "DUPLICATE_UNIVERSE_KEY" for issue in assessment.issues)


def test_baostock_cannot_supply_exact_financial_contract():
    raw = envelope(
        [
            FinancialReportFact(
                "000001", date(2026, 3, 31), date(2026, 4, 20), 100, 10, "Bao"
            )
        ],
        provider="BaoStock",
    )
    assessment = assess_envelope("financial_statements", raw, date(2026, 8, 10))

    assert assessment.blocking is True
    assert any(
        issue.code == "UNSUPPORTED_SOURCE_CONTRACT" for issue in assessment.issues
    )


def test_valid_unknown_source_remains_operational_but_single_source():
    raw = envelope(MarketSnapshot("000001", date(2026, 8, 10), 10, 100, 10, 10, "test"))
    assessment = assess_envelope("market", raw, date(2026, 8, 10))

    assert assessment.blocking is False
    assert assessment.verification_status == VerificationStatus.SINGLE_SOURCE


def test_report_period_capable_akshare_dividend_source_is_exact():
    raw = envelope(DividendBundle((), ()), provider="AKShare")

    assessment = assess_envelope(
        "dividend_and_actions", raw, date(2026, 8, 10)
    )

    assert assessment.blocking is False
    assert assessment.verification_status == VerificationStatus.SINGLE_SOURCE
