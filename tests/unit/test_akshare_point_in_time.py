from datetime import date

import pandas as pd

from src.data.point_in_time.akshare_adapter import AKSharePointInTimeProvider
from src.data.point_in_time.contracts import FetchStatus


class FakeAK:
    def __init__(self):
        self.last_financial_symbol = None

    def stock_info_a_code_name(self):
        return pd.DataFrame({"code": ["688001", "920001"], "name": ["科创测试", "北交测试"]})

    def stock_value_em(self, symbol):
        return pd.DataFrame(
            {
                "数据日期": ["2025-12-31", "2026-01-05"],
                "当日收盘价": [10, 11],
                "总市值": [100, 110],
                "总股本": [10, 10],
                "PE(TTM)": [12, 13],
            }
        )

    def stock_profit_sheet_by_report_em(self, symbol):
        self.last_financial_symbol = symbol
        return pd.DataFrame(
            {
                "REPORT_DATE": ["2025-12-31", "2026-03-31"],
                "NOTICE_DATE": ["2026-03-01", "2026-05-01"],
                "UPDATE_DATE": ["2026-03-01", "2026-05-01"],
                "OPERATE_INCOME": [100, 30],
                "PARENT_NETPROFIT": [10, 3],
            }
        )

    def stock_fhps_detail_em(self, symbol):
        return pd.DataFrame(
            {
                "报告期": ["2025-12-31"],
                "现金分红-现金分红比例": [6.0],
                "送转股份-送转总比例": [10.0],
                "除权除息日": ["2026-06-01"],
                "方案进度": ["实施分配"],
                "最新公告日期": ["2026-05-20"],
            }
        )

    def stock_zh_a_st_em(self):
        return pd.DataFrame({"代码": ["000002"], "名称": ["*ST测试"]})

    def stock_info_sz_change_name(self, symbol):
        return pd.DataFrame(
            {
                "变更日期": ["2020-01-01", "2021-01-01"],
                "证券代码": ["000001", "000001"],
                "变更前简称": ["正常公司", "ST公司"],
                "变更后简称": ["ST公司", "正常公司"],
            }
        )


def test_market_snapshot_uses_latest_date_not_after_as_of():
    provider = AKSharePointInTimeProvider(FakeAK(), today=date(2026, 1, 10))
    result = provider.get_market_snapshot("000001", date(2025, 12, 31))
    assert result.status == FetchStatus.SUCCESS
    assert result.data.price_date == date(2025, 12, 31)
    assert result.data.supplier_pe_ttm == 12


def test_financial_adapter_uses_market_prefix_and_filters_future_announcements():
    fake = FakeAK()
    provider = AKSharePointInTimeProvider(fake, today=date(2026, 4, 1))
    result = provider.get_financial_facts("000001", date(2026, 4, 1))
    assert fake.last_financial_symbol == "SZ000001"
    assert len(result.data) == 1
    assert result.data[0].report_period == date(2025, 12, 31)


def test_financial_adapter_excludes_revision_not_available_at_as_of():
    fake = FakeAK()
    original = fake.stock_profit_sheet_by_report_em

    def with_future_revision(symbol):
        frame = original(symbol)
        frame.loc[0, "UPDATE_DATE"] = "2026-04-02"
        return frame

    fake.stock_profit_sheet_by_report_em = with_future_revision
    provider = AKSharePointInTimeProvider(fake, today=date(2026, 4, 1))
    result = provider.get_financial_facts("000001", date(2026, 4, 1))

    assert result.status == FetchStatus.EMPTY
    assert result.data is None


def test_dividend_adapter_preserves_raw_per_share_and_action_factor():
    provider = AKSharePointInTimeProvider(FakeAK(), today=date(2026, 8, 10))
    result = provider.get_dividend_bundle("000001", date(2026, 8, 10))
    assert result.data.events[0].raw_cash_per_share_pre_tax == 0.6
    assert result.data.events[0].provider_adjusted is False
    assert result.data.actions[0].share_factor == 2.0


def test_historical_sz_risk_status_uses_effective_name_change_date():
    provider = AKSharePointInTimeProvider(FakeAK(), today=date(2026, 8, 10))
    during_st = provider.get_risk_warning_status(
        "000001", "正常公司", date(2020, 6, 1)
    )
    after_st = provider.get_risk_warning_status(
        "000001", "正常公司", date(2021, 6, 1)
    )
    assert during_st.data.is_risk_warning is True
    assert after_st.data.is_risk_warning is False


def test_historical_sh_risk_status_is_pending_not_false():
    provider = AKSharePointInTimeProvider(FakeAK(), today=date(2026, 8, 10))
    result = provider.get_risk_warning_status("600001", "测试", date(2020, 6, 1))
    assert result.status == FetchStatus.EMPTY
    assert result.data is None
