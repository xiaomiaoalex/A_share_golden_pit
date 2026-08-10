from datetime import date

import pandas as pd

from src.data.point_in_time.baostock_adapter import BaoStockPointInTimeProvider
from src.data.point_in_time.contracts import FetchStatus


class Result:
    error_code = "0"
    error_msg = "success"

    def __init__(self, frame):
        self.frame = frame
        self.fields = list(frame.columns)

    def get_data(self):
        return self.frame.copy()


class LoginResult:
    error_code = "0"
    error_msg = "success"


class FakeBaoStock:
    def login(self):
        return LoginResult()

    def logout(self):
        return LoginResult()

    def query_trade_dates(self, **kwargs):
        return Result(
            pd.DataFrame(
                {
                    "calendar_date": ["2026-08-08", "2026-08-10"],
                    "is_trading_day": ["0", "1"],
                }
            )
        )

    def query_all_stock(self, day=None):
        return Result(
            pd.DataFrame(
                {
                    "code": ["sh.000001", "sh.600000", "sz.000001"],
                    "tradeStatus": ["1", "1", "1"],
                    "code_name": ["上证指数", "浦发银行", "平安银行"],
                }
            )
        )

    def query_history_k_data_plus(self, *args, **kwargs):
        return Result(
            pd.DataFrame(
                {
                    "date": ["2026-08-07", "2026-08-10"],
                    "code": ["sz.000001", "sz.000001"],
                    "close": ["10", "11"],
                    "peTTM": ["12", "13"],
                    "isST": ["1", "0"],
                    "tradestatus": ["1", "1"],
                }
            )
        )

    def query_dividend_data(self, *args, **kwargs):
        year = kwargs.get("year")
        if year != "2026":
            return Result(pd.DataFrame())
        return Result(
            pd.DataFrame(
                {
                    "dividPlanAnnounceDate": ["2026-04-01"],
                    "dividPlanDate": ["2026-04-20"],
                    "dividOperateDate": ["2026-05-01"],
                    "dividCashPsBeforeTax": ["1"],
                    "dividStocksPs": ["0.1"],
                    "dividReserveToStockPs": ["0.2"],
                }
            )
        )


def provider():
    return BaoStockPointInTimeProvider(FakeBaoStock(), today=date(2026, 8, 10))


def test_baostock_universe_excludes_indices_and_keeps_sh_sz_stocks():
    result = provider().get_universe(date(2026, 8, 10))
    assert {item.symbol for item in result.data} == {"600000", "000001"}


def test_baostock_market_uses_unadjusted_close_and_pe_but_not_fake_market_cap():
    result = provider().get_market_snapshot("000001", date(2026, 8, 10))
    assert result.data.close_price == 11
    assert result.data.supplier_pe_ttm == 13
    assert result.data.market_cap is None
    assert "adjustflag=3" in result.raw_payload["metric_contract"]


def test_baostock_daily_isst_is_point_in_time():
    result = provider().get_risk_warning_status("000001", "测试", date(2026, 8, 7))
    assert result.data.is_risk_warning is True
    assert result.data.effective_date == date(2026, 8, 7)


def test_baostock_dividend_uses_pre_tax_cash_and_combined_share_action():
    result = provider().get_dividend_bundle("000001", date(2026, 8, 10))
    assert result.data.events[0].raw_cash_per_share_pre_tax == 1
    assert result.data.actions[0].share_factor == 1.3


def test_baostock_financial_never_substitutes_approximate_profit_fields():
    result = provider().get_financial_facts("000001", date(2026, 8, 10))
    assert result.status == FetchStatus.EMPTY
    assert result.data is None
    assert "禁止近似补数" in result.quality_warnings[0]
