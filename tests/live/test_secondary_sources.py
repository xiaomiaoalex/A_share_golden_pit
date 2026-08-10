import os
from datetime import date

import pytest

from src.data.point_in_time.baostock_adapter import BaoStockPointInTimeProvider
from src.data.point_in_time.tushare_adapter import TusharePointInTimeProvider


pytestmark = pytest.mark.live


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_DATA_TESTS") != "1",
    reason="set RUN_LIVE_DATA_TESTS=1 to access external data sources",
)
def test_baostock_market_dividend_and_historical_st_contracts():
    provider = BaoStockPointInTimeProvider()
    try:
        market = provider.get_market_snapshot("000651", date.today())
        dividend = provider.get_dividend_bundle("000651", date.today())
        risk = provider.get_risk_warning_status("000651", "格力电器", date.today())
    finally:
        provider.close()
    assert market.usable
    assert dividend.usable or dividend.data is not None
    assert risk.usable


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_DATA_TESTS") != "1" or not os.getenv("TUSHARE_TOKEN"),
    reason="set RUN_LIVE_DATA_TESTS=1 and TUSHARE_TOKEN to test Tushare Pro",
)
def test_tushare_exact_tier1_contracts():
    provider = TusharePointInTimeProvider()
    market = provider.get_market_snapshot("000651", date.today())
    financial = provider.get_financial_facts("000651", date.today())
    dividend = provider.get_dividend_bundle("000651", date.today())
    risk = provider.get_risk_warning_status("000651", "格力电器", date.today())
    assert market.usable
    assert financial.usable
    assert dividend.usable or dividend.data is not None
    assert risk.usable
