from datetime import date

import pandas as pd
import pytest

from src.data.point_in_time.contracts import FetchStatus
from src.data.point_in_time.tushare_adapter import TusharePointInTimeProvider


class FakeTushare:
    def stock_basic(self, list_status, **kwargs):
        if list_status == "L":
            return pd.DataFrame(
                {
                    "ts_code": ["920001.BJ"],
                    "symbol": ["920001"],
                    "name": ["北交测试"],
                    "exchange": ["BSE"],
                    "list_status": ["L"],
                    "list_date": ["20200101"],
                    "delist_date": [None],
                }
            )
        if list_status == "D":
            return pd.DataFrame(
                {
                    "ts_code": ["000001.SZ"],
                    "symbol": ["000001"],
                    "name": ["退市测试"],
                    "exchange": ["SZSE"],
                    "list_status": ["D"],
                    "list_date": ["19910101"],
                    "delist_date": ["20250101"],
                }
            )
        return pd.DataFrame()

    def daily_basic(self, **kwargs):
        return pd.DataFrame(
            {
                "ts_code": ["000001.SZ", "000001.SZ"],
                "trade_date": ["20260807", "20260811"],
                "close": [10, 11],
                "pe_ttm": [12, 13],
                "total_share": [100, 100],
                "total_mv": [1200, 1300],
            }
        )

    def income(self, **kwargs):
        return pd.DataFrame(
            {
                "ts_code": ["000001.SZ"] * 3,
                "ann_date": ["20260301", "20260420", "20260831"],
                "f_ann_date": ["20260301", "20260420", "20260831"],
                "end_date": ["20251231", "20260331", "20260630"],
                "report_type": ["1", "1", "1"],
                "comp_type": ["1", "1", "1"],
                "revenue": [400, 115, 240],
                "n_income_attr_p": [40, 11.5, 24],
                "update_flag": ["0", "0", "0"],
            }
        )

    def dividend(self, **kwargs):
        return pd.DataFrame(
            {
                "ts_code": ["000001.SZ", "000001.SZ"],
                "end_date": ["20251231", "20260630"],
                "ann_date": ["20260401", "20260701"],
                "div_proc": ["实施", "预案"],
                "stk_div": [0.1, 0.0],
                "stk_bo_rate": [0.0, 0.0],
                "stk_co_rate": [0.1, 0.0],
                "cash_div_tax": [1.0, 2.0],
                "ex_date": ["20260501", None],
                "imp_ann_date": ["20260420", None],
            }
        )

    def namechange(self, **kwargs):
        return pd.DataFrame(
            {
                "ts_code": ["000001.SZ", "000001.SZ"],
                "name": ["ST测试", "测试股份"],
                "start_date": ["20200101", "20210101"],
                "end_date": ["20201231", None],
                "ann_date": ["20191231", "20201231"],
                "change_reason": ["ST", "撤销ST"],
            }
        )

    def trade_cal(self, end_date, **kwargs):
        return pd.DataFrame({"cal_date": [end_date], "is_open": ["1"]})

    def stock_st(self, trade_date, **kwargs):
        if trade_date < "20210101":
            return pd.DataFrame(
                {
                    "ts_code": ["000001.SZ"],
                    "name": ["ST测试"],
                    "trade_date": [trade_date],
                    "type": ["ST"],
                    "type_name": ["风险警示板"],
                }
            )
        return pd.DataFrame()


def provider():
    return TusharePointInTimeProvider(FakeTushare(), today=date(2026, 8, 10))


def test_tushare_universe_reconstructs_delisted_and_bse_as_of():
    result = provider().get_universe(date(2024, 12, 31))
    assert result.status == FetchStatus.SUCCESS
    assert {item.symbol for item in result.data} == {"000001", "920001"}
    assert (
        next(item for item in result.data if item.symbol == "920001").exchange == "BJ"
    )


def test_tushare_market_converts_10k_units_and_excludes_future_trade_date():
    result = provider().get_market_snapshot("000001", date(2026, 8, 10))
    assert result.data.price_date == date(2026, 8, 7)
    assert result.data.market_cap == 12_000_000
    assert result.data.total_shares == 1_000_000
    assert result.data.supplier_pe_ttm == 12


def test_tushare_income_uses_exact_fields_and_actual_announcement_cutoff():
    result = provider().get_financial_facts("000001", date(2026, 8, 10))
    assert [fact.report_period for fact in result.data] == [
        date(2025, 12, 31),
        date(2026, 3, 31),
    ]
    assert result.data[-1].operating_revenue == 115
    assert result.data[-1].parent_net_profit == 11.5


def test_tushare_dividend_uses_pre_tax_per_share_and_share_action():
    result = provider().get_dividend_bundle("000001", date(2026, 8, 10))
    assert len(result.data.events) == 1
    assert result.data.events[0].raw_cash_per_share_pre_tax == 1
    assert result.data.actions[0].share_factor == pytest.approx(1.1)


def test_tushare_official_daily_list_drives_historical_st_status():
    during = provider().get_risk_warning_status("000001", None, date(2020, 6, 1))
    after = provider().get_risk_warning_status("000001", None, date(2021, 6, 1))
    assert during.data.is_risk_warning is True
    assert after.data.is_risk_warning is False
    assert during.endpoint == "stock_st"


def test_tushare_name_fallback_requires_real_announcement_date():
    fake = FakeTushare()
    fake.trade_cal = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("no access"))
    fake.namechange = lambda **kwargs: pd.DataFrame(
        {
            "name": ["ST测试"],
            "start_date": ["20100101"],
            "end_date": [None],
            "ann_date": [None],
        }
    )
    result = TusharePointInTimeProvider(fake).get_risk_warning_status(
        "000001", None, date(2020, 6, 1)
    )

    assert result.status == FetchStatus.EMPTY
    assert any("stock_st不可用" in warning for warning in result.quality_warnings)
