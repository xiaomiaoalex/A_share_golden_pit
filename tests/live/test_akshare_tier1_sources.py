import os
from datetime import date

import pytest

from src.data.point_in_time.akshare_adapter import AKSharePointInTimeProvider

pytestmark = pytest.mark.live


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_DATA_TESTS") != "1",
    reason="set RUN_LIVE_DATA_TESTS=1 to access external data sources",
)
def test_representative_point_in_time_sources():
    provider = AKSharePointInTimeProvider()
    market = provider.get_market_snapshot("000651", date.today())
    financial = provider.get_financial_facts("000651", date.today())
    dividend = provider.get_dividend_bundle("000651", date.today())

    assert market.usable
    assert financial.usable
    assert dividend.usable
