from datetime import date

from src.data.point_in_time.provider_factory import build_point_in_time_provider
from tests.unit.test_akshare_point_in_time import FakeAK
from tests.unit.test_baostock_point_in_time import FakeBaoStock
from tests.unit.test_tushare_point_in_time import FakeTushare


def test_factory_enables_three_sources_when_tushare_is_configured():
    provider = build_point_in_time_provider(
        environment={"GOLDEN_PIT_DATA_SOURCES": "akshare,tushare,baostock"},
        today=date(2026, 8, 10),
        ak_module=FakeAK(),
        tushare_client=FakeTushare(),
        baostock_client=FakeBaoStock(),
    )
    assert provider.provider_names == ["AKShare", "Tushare Pro", "BaoStock"]
    assert provider.configuration_warnings == []


def test_factory_skips_tushare_without_token_but_keeps_baostock():
    provider = build_point_in_time_provider(
        environment={"TIER1_DATA_SOURCES": "akshare,tushare,baostock"},
        today=date(2026, 8, 10),
        ak_module=FakeAK(),
        baostock_client=FakeBaoStock(),
    )
    assert provider.provider_names == ["AKShare", "BaoStock"]
    assert "TUSHARE_TOKEN未配置" in provider.configuration_warnings[0]
