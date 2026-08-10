"""
SQLAlchemy ORM 模型定义 - A股黄金坑股票数据库持久化存储层。

定义股票基础信息、财务数据、估值快照、筛选结果、风险检查结果
等核心数据表的 ORM 模型。
"""

import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """ORM 模型基类"""
    pass


class Stock(Base):
    """股票基础信息表。

    存储A股股票的基本信息，包括交易所、行业分类、市值等。
    """
    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), unique=True, index=True, comment="股票代码")
    name: Mapped[str] = mapped_column(String(64), comment="股票名称")
    exchange: Mapped[Optional[str]] = mapped_column(String(8), comment="交易所(sh/sz)")
    industry: Mapped[Optional[str]] = mapped_column(String(64), comment="行业分类")
    sub_industry: Mapped[Optional[str]] = mapped_column(String(64), comment="子行业分类")
    market_cap: Mapped[Optional[float]] = mapped_column(Float, comment="总市值")
    float_market_cap: Mapped[Optional[float]] = mapped_column(Float, comment="流通市值")
    list_date: Mapped[Optional[datetime.date]] = mapped_column(Date, comment="上市日期")
    is_st: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否ST")
    is_delisted: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否已退市")
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    # 关联关系
    financial_data: Mapped[list["FinancialData"]] = relationship(
        "FinancialData", back_populates="stock", cascade="all, delete-orphan"
    )
    valuations: Mapped[list["ValuationSnapshot"]] = relationship(
        "ValuationSnapshot", back_populates="stock", cascade="all, delete-orphan"
    )
    screening_results: Mapped[list["ScreeningResult"]] = relationship(
        "ScreeningResult", back_populates="stock", cascade="all, delete-orphan"
    )
    risk_checks: Mapped[list["RiskCheckResult"]] = relationship(
        "RiskCheckResult", back_populates="stock", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Stock(symbol='{self.symbol}', name='{self.name}')>"


class FinancialData(Base):
    """财务数据快照表。

    存储每只股票在每个报告期的关键财务指标快照。
    """
    __tablename__ = "financial_data"
    __table_args__ = (
        UniqueConstraint("symbol", "report_date", name="uq_financial_symbol_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        String(16), ForeignKey("stocks.symbol"), index=True, comment="股票代码"
    )
    report_date: Mapped[datetime.date] = mapped_column(Date, comment="报告期日期")

    # 盈利能力
    roe: Mapped[Optional[float]] = mapped_column(Float, comment="净资产收益率(%)")
    roa: Mapped[Optional[float]] = mapped_column(Float, comment="总资产收益率(%)")
    roic: Mapped[Optional[float]] = mapped_column(Float, comment="投入资本回报率(%)")
    gross_margin: Mapped[Optional[float]] = mapped_column(Float, comment="毛利率(%)")
    net_margin: Mapped[Optional[float]] = mapped_column(Float, comment="净利率(%)")
    operating_margin: Mapped[Optional[float]] = mapped_column(Float, comment="营业利润率(%)")

    # 核心财务数据
    revenue: Mapped[Optional[float]] = mapped_column(Float, comment="营业收入")
    net_profit: Mapped[Optional[float]] = mapped_column(Float, comment="净利润")
    operating_cashflow: Mapped[Optional[float]] = mapped_column(Float, comment="经营活动现金流")
    free_cashflow: Mapped[Optional[float]] = mapped_column(Float, comment="自由现金流")

    # 资产负债
    total_assets: Mapped[Optional[float]] = mapped_column(Float, comment="总资产")
    total_equity: Mapped[Optional[float]] = mapped_column(Float, comment="股东权益")
    total_debt: Mapped[Optional[float]] = mapped_column(Float, comment="总负债")
    goodwill: Mapped[Optional[float]] = mapped_column(Float, comment="商誉")

    # 运营指标
    acct_receivable: Mapped[Optional[float]] = mapped_column(Float, comment="应收账款")
    inventory: Mapped[Optional[float]] = mapped_column(Float, comment="存货")
    dividend_per_share: Mapped[Optional[float]] = mapped_column(Float, comment="每股分红")

    # 成长性
    revenue_growth: Mapped[Optional[float]] = mapped_column(Float, comment="营收增长率(%)")
    net_profit_growth: Mapped[Optional[float]] = mapped_column(Float, comment="净利润增长率(%)")

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )

    # 关联关系
    stock: Mapped["Stock"] = relationship("Stock", back_populates="financial_data")

    def __repr__(self) -> str:
        return f"<FinancialData(symbol='{self.symbol}', report_date='{self.report_date}')>"


class ValuationSnapshot(Base):
    """估值快照表。

    存储每只股票在特定日期的估值指标快照。
    """
    __tablename__ = "valuation_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        String(16), ForeignKey("stocks.symbol"), index=True, comment="股票代码"
    )
    date: Mapped[datetime.date] = mapped_column(Date, index=True, comment="估值日期")

    # 估值指标
    pe_ttm: Mapped[Optional[float]] = mapped_column(Float, comment="市盈率TTM")
    pb: Mapped[Optional[float]] = mapped_column(Float, comment="市净率")
    ps_ttm: Mapped[Optional[float]] = mapped_column(Float, comment="市销率TTM")
    ev_ebitda: Mapped[Optional[float]] = mapped_column(Float, comment="企业价值/EBITDA")
    dividend_yield: Mapped[Optional[float]] = mapped_column(Float, comment="股息率(%)")

    # 历史分位数
    pe_percentile_5y: Mapped[Optional[float]] = mapped_column(Float, comment="PE 5年分位数")
    pb_percentile_5y: Mapped[Optional[float]] = mapped_column(Float, comment="PB 5年分位数")

    # 市值与价格
    market_cap: Mapped[Optional[float]] = mapped_column(Float, comment="总市值")
    price: Mapped[Optional[float]] = mapped_column(Float, comment="股价")
    fcf_yield: Mapped[Optional[float]] = mapped_column(Float, comment="自由现金流收益率(%)")

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )

    # 关联关系
    stock: Mapped["Stock"] = relationship("Stock", back_populates="valuations")

    def __repr__(self) -> str:
        return f"<ValuationSnapshot(symbol='{self.symbol}', date='{self.date}')>"


class ScreeningResult(Base):
    """筛选结果表。

    存储黄金坑筛选的核心结果，包含评分、概率、估值分析等完整信息。
    """
    __tablename__ = "screening_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        String(16), ForeignKey("stocks.symbol"), index=True, comment="股票代码"
    )
    scan_date: Mapped[datetime.date] = mapped_column(Date, index=True, comment="扫描日期")

    # 分层与评分
    tier: Mapped[int] = mapped_column(Integer, comment="层级(1/2/3)")
    total_score: Mapped[Optional[float]] = mapped_column(Float, comment="总评分")
    odds_ratio: Mapped[Optional[float]] = mapped_column(Float, comment="赔率")
    confidence: Mapped[Optional[float]] = mapped_column(Float, comment="置信度(0-1)")

    # 结构化数据
    score_breakdown: Mapped[Optional[dict]] = mapped_column(JSON, comment="评分明细(JSON)")
    position_advice: Mapped[Optional[dict]] = mapped_column(JSON, comment="仓位建议(JSON)")

    # 分析结论
    implied_profit: Mapped[Optional[float]] = mapped_column(Float, comment="隐含利润")
    market_pessimism_hypothesis: Mapped[Optional[str]] = mapped_column(
        Text, comment="市场悲观假说"
    )
    base_assumption: Mapped[Optional[str]] = mapped_column(Text, comment="基本假设")
    expectation_gap: Mapped[Optional[float]] = mapped_column(Float, comment="预期差")

    # 估值分析
    valuation_pessimistic: Mapped[Optional[float]] = mapped_column(Float, comment="悲观估值")
    valuation_base: Mapped[Optional[float]] = mapped_column(Float, comment="基准估值")
    valuation_optimistic: Mapped[Optional[float]] = mapped_column(Float, comment="乐观估值")

    # 验证与指标
    falsification_conditions: Mapped[Optional[dict]] = mapped_column(JSON, comment="证伪条件(JSON)")
    key_metrics: Mapped[Optional[dict]] = mapped_column(JSON, comment="关键指标(JSON)")

    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否当前活跃结果")
    remarks: Mapped[Optional[str]] = mapped_column(Text, comment="备注")

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )

    # 关联关系
    stock: Mapped["Stock"] = relationship("Stock", back_populates="screening_results")

    def __repr__(self) -> str:
        return f"<ScreeningResult(symbol='{self.symbol}', tier={self.tier}, scan_date='{self.scan_date}')>"


class RiskCheckResult(Base):
    """风险检查结果表。

    存储每只股票的风险检查结果，包括质押比例、商誉风险、财务操纵评分等。
    """
    __tablename__ = "risk_check_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        String(16), ForeignKey("stocks.symbol"), index=True, comment="股票代码"
    )
    check_date: Mapped[datetime.date] = mapped_column(Date, index=True, comment="检查日期")

    # 风险指标
    pledge_ratio: Mapped[Optional[float]] = mapped_column(Float, comment="股权质押比例")
    goodwill_ratio: Mapped[Optional[float]] = mapped_column(Float, comment="商誉占净资产比例")
    beneish_mscore: Mapped[Optional[float]] = mapped_column(Float, comment="Beneish M-Score")

    # 关联交易与应收
    related_party_revenue_ratio: Mapped[Optional[float]] = mapped_column(
        Float, comment="关联交易收入占比"
    )
    ar_to_revenue_ratio: Mapped[Optional[float]] = mapped_column(
        Float, comment="应收账款占营收比例"
    )

    # 现金流与审计
    cfo_to_ni_ratio: Mapped[Optional[float]] = mapped_column(Float, comment="经营现金流/净利润")
    audit_opinion: Mapped[Optional[str]] = mapped_column(String(64), comment="审计意见")

    # 风险汇总
    risk_flags: Mapped[Optional[dict]] = mapped_column(JSON, comment="风险标志(JSON)")
    overall_risk_level: Mapped[Optional[str]] = mapped_column(
        String(32), comment="整体风险等级(低/中/高)"
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )

    # 关联关系
    stock: Mapped["Stock"] = relationship("Stock", back_populates="risk_checks")

    def __repr__(self) -> str:
        return (
            f"<RiskCheckResult(symbol='{self.symbol}', "
            f"check_date='{self.check_date}', risk_level='{self.overall_risk_level}')>"
        )
