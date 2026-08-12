"""Machine-readable Tier1 metric contracts and source capability boundaries."""

from __future__ import annotations

from dataclasses import dataclass

from .types import CapabilityLevel


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    field_group: str
    business_definition: str
    grain: str
    unit: str
    available_at: str
    allowed_source_fields: dict[str, tuple[str, ...]]
    forbidden_substitutes: tuple[str, ...] = ()


METRIC_REGISTRY = {
    "close_price": MetricDefinition(
        name="close_price",
        field_group="market",
        business_definition="as-of日或之前最近交易日的未复权收盘价",
        grain="security + trade_date",
        unit="CNY/share",
        available_at="trade_date",
        allowed_source_fields={
            "AKShare": ("收盘",),
            "Tushare Pro": ("daily_basic.close",),
            "BaoStock": ("close(adjustflag=3)",),
        },
    ),
    "supplier_pe_ttm": MetricDefinition(
        name="supplier_pe_ttm",
        field_group="market",
        business_definition="供应商滚动PE；与点时自计算PE并列保留",
        grain="security + trade_date",
        unit="multiple",
        available_at="trade_date",
        allowed_source_fields={
            "AKShare": ("市盈率(TTM)",),
            "Tushare Pro": ("daily_basic.pe_ttm",),
            "BaoStock": ("peTTM",),
        },
        forbidden_substitutes=("static_pe", "dynamic_pe"),
    ),
    "operating_revenue": MetricDefinition(
        name="operating_revenue",
        field_group="financial_statements",
        business_definition="正式累计合并利润表营业收入",
        grain="security + report_period + disclosure_version",
        unit="CNY",
        available_at="actual_announcement_date",
        allowed_source_fields={
            "AKShare": ("营业收入",),
            "Tushare Pro": ("income.revenue",),
        },
        forbidden_substitutes=("total_revenue", "MBRevenue"),
    ),
    "parent_net_profit": MetricDefinition(
        name="parent_net_profit",
        field_group="financial_statements",
        business_definition="正式累计合并利润表归属于母公司股东的净利润",
        grain="security + report_period + disclosure_version",
        unit="CNY",
        available_at="actual_announcement_date",
        allowed_source_fields={
            "AKShare": ("归属于母公司股东的净利润",),
            "Tushare Pro": ("income.n_income_attr_p",),
        },
        forbidden_substitutes=("net_profit", "n_income", "BaoStock.netProfit"),
    ),
    "dividend_cash_pre_tax": MetricDefinition(
        name="dividend_cash_pre_tax",
        field_group="dividend_and_actions",
        business_definition="已实施方案的税前每股现金分红，按除权日进入TTM",
        grain="security + ex_date + plan",
        unit="CNY/share",
        available_at="implementation_announcement_date",
        allowed_source_fields={
            "AKShare": ("税前派息",),
            "Tushare Pro": ("dividend.cash_div_tax",),
            "BaoStock": ("dividCashPsBeforeTax",),
        },
        forbidden_substitutes=("cash_div_after_tax",),
    ),
    "risk_warning_status": MetricDefinition(
        name="risk_warning_status",
        field_group="risk_warning_status",
        business_definition="最近交易日有效的ST/*ST/退市风险警示状态",
        grain="security + effective_trade_date",
        unit="boolean",
        available_at="effective_trade_date",
        allowed_source_fields={
            "AKShare": ("风险警示板/历史简称",),
            "Tushare Pro": ("stock_st",),
            "BaoStock": ("isST",),
        },
    ),
}


SOURCE_CAPABILITIES: dict[str, dict[str, CapabilityLevel]] = {
    "PIPELINE_INPUT": {
        "universe": CapabilityLevel.EXACT,
    },
    "AKShare": {
        "universe": CapabilityLevel.LIMITED,
        "market": CapabilityLevel.EXACT,
        "financial_statements": CapabilityLevel.EXACT,
        "dividend_and_actions": CapabilityLevel.EXACT,
        "risk_warning_status": CapabilityLevel.LIMITED,
    },
    "Tushare Pro": {
        "universe": CapabilityLevel.EXACT,
        "market": CapabilityLevel.EXACT,
        "financial_statements": CapabilityLevel.EXACT,
        "dividend_and_actions": CapabilityLevel.EXACT,
        "risk_warning_status": CapabilityLevel.EXACT,
    },
    "BaoStock": {
        "universe": CapabilityLevel.LIMITED,
        "market": CapabilityLevel.LIMITED,
        "financial_statements": CapabilityLevel.UNSUPPORTED,
        # The endpoint has implemented cash/share and ex-date, but no profit
        # attribution report period.  It cannot independently satisfy the
        # latest-complete-fiscal-year screening contract.
        "dividend_and_actions": CapabilityLevel.LIMITED,
        "risk_warning_status": CapabilityLevel.EXACT,
    },
}


def capability_for(provider: str, field_group: str) -> CapabilityLevel:
    return SOURCE_CAPABILITIES.get(provider, {}).get(
        field_group, CapabilityLevel.UNKNOWN
    )
