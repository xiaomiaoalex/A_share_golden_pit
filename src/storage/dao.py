"""
数据访问对象 (DAO) - A股黄金坑股票数据库持久化存储层。

提供面向业务场景的高级查询接口，包括行业排名、评分趋势、
Top股票筛选、搜索、层级汇总和数据导出等功能。
"""

import datetime
import logging
from typing import Any, Optional

import pandas as pd
from sqlalchemy import desc, func

from .database import DatabaseManager
from .models import ScreeningResult, Stock

logger = logging.getLogger(__name__)


class StockDAO:
    """股票数据访问对象。

    封装面向业务场景的复杂查询逻辑，提供高层数据访问接口。
    """

    def __init__(self, db: DatabaseManager) -> None:
        """初始化数据访问对象。

        Args:
            db: DatabaseManager 实例
        """
        self.db = db

    def get_industry_rankings(self, tier: int) -> list[dict[str, Any]]:
        """按行业分组统计指定层级的股票排名。

        统计每个行业的股票数量及平均评分。

        Args:
            tier: 层级 (1/2/3)

        Returns:
            行业排名列表，按平均评分降序排列
        """
        with self.db.get_session() as session:
            results = (
                session.query(
                    Stock.industry,
                    func.count(Stock.symbol).label("count"),
                    func.round(func.avg(ScreeningResult.total_score), 2).label("avg_score"),
                )
                .join(ScreeningResult, Stock.symbol == ScreeningResult.symbol)
                .filter(
                    ScreeningResult.tier == tier,
                    ScreeningResult.is_active == True,
                    Stock.industry.isnot(None),
                )
                .group_by(Stock.industry)
                .order_by(desc("avg_score"))
                .all()
            )

            return [
                {
                    "industry": row.industry,
                    "count": row.count,
                    "avg_score": float(row.avg_score) if row.avg_score else 0,
                }
                for row in results
            ]

    def get_score_changes(
        self, symbol: str, days: int = 90
    ) -> list[dict[str, Any]]:
        """获取某股票在指定天数内的评分变化趋势。

        Args:
            symbol: 股票代码
            days: 回溯天数，默认 90 天

        Returns:
            评分变化记录列表，按日期升序排列
        """
        cutoff_date = datetime.date.today() - datetime.timedelta(days=days)

        with self.db.get_session() as session:
            results = (
                session.query(ScreeningResult)
                .filter(
                    ScreeningResult.symbol == symbol,
                    ScreeningResult.scan_date >= cutoff_date,
                )
                .order_by(ScreeningResult.scan_date.asc())
                .all()
            )

            return [
                {
                    "scan_date": r.scan_date.isoformat() if r.scan_date else None,
                    "tier": r.tier,
                    "total_score": r.total_score,
                    "odds_ratio": r.odds_ratio,
                    "confidence": r.confidence,
                }
                for r in results
            ]

    def get_top_stocks(
        self, tier: int, limit: int = 20
    ) -> list[dict[str, Any]]:
        """获取指定层级评分最高的 Top 股票。

        Args:
            tier: 层级 (1/2/3)
            limit: 返回数量上限，默认 20

        Returns:
            Top 股票信息列表，按评分降序排列
        """
        with self.db.get_session() as session:
            results = (
                session.query(ScreeningResult, Stock)
                .join(Stock, ScreeningResult.symbol == Stock.symbol)
                .filter(
                    ScreeningResult.tier == tier,
                    ScreeningResult.is_active == True,
                )
                .order_by(desc(ScreeningResult.total_score))
                .limit(limit)
                .all()
            )

            return [
                {
                    "symbol": sr.symbol,
                    "name": st.name if st else None,
                    "industry": st.industry if st else None,
                    "tier": sr.tier,
                    "total_score": sr.total_score,
                    "odds_ratio": sr.odds_ratio,
                    "confidence": sr.confidence,
                    "pe_ttm": sr.key_metrics.get("pe_ttm") if sr.key_metrics else None,
                    "pb": sr.key_metrics.get("pb") if sr.key_metrics else None,
                }
                for sr, st in results
            ]

    def search_stocks(self, keyword: str) -> list[dict[str, Any]]:
        """根据关键词搜索股票（按代码或名称模糊匹配）。

        Args:
            keyword: 搜索关键词

        Returns:
            匹配的股票信息列表
        """
        with self.db.get_session() as session:
            stocks = (
                session.query(Stock)
                .filter(
                    (Stock.symbol.contains(keyword))
                    | (Stock.name.contains(keyword))
                )
                .filter(Stock.is_delisted == False)
                .limit(50)
                .all()
            )

            return [
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "exchange": s.exchange,
                    "industry": s.industry,
                    "market_cap": s.market_cap,
                    "is_st": s.is_st,
                }
                for s in stocks
            ]

    def get_tier_summary(self) -> dict[str, Any]:
        """获取三层筛选结果的汇总统计。

        Returns:
            包含各层级统计信息的字典
        """
        summary = {"total_active": 0, "tiers": {}}

        with self.db.get_session() as session:
            for tier in [1, 2, 3]:
                results = (
                    session.query(ScreeningResult)
                    .filter(
                        ScreeningResult.tier == tier,
                        ScreeningResult.is_active == True,
                    )
                    .all()
                )

                scores = [
                    r.total_score for r in results if r.total_score is not None
                ]
                symbols = [r.symbol for r in results]

                # 行业分布
                industries = (
                    session.query(Stock.industry, func.count(Stock.symbol))
                    .filter(Stock.symbol.in_(symbols))
                    .group_by(Stock.industry)
                    .all()
                )

                summary["tiers"][f"tier_{tier}"] = {
                    "count": len(results),
                    "avg_score": sum(scores) / len(scores) if scores else 0,
                    "max_score": max(scores) if scores else 0,
                    "min_score": min(scores) if scores else 0,
                    "industry_distribution": {
                        ind: cnt for ind, cnt in industries if ind
                    },
                }
                summary["total_active"] += len(results)

        return summary

    def export_to_dataframe(
        self, tier: Optional[int] = None, date: Optional[datetime.date] = None
    ) -> pd.DataFrame:
        """将筛选结果导出为 Pandas DataFrame。

        Args:
            tier: 可选，按层级过滤
            date: 可选，按扫描日期过滤

        Returns:
            包含筛选结果和股票基础信息的 DataFrame
        """
        with self.db.get_session() as session:
            query = (
                session.query(
                    ScreeningResult.symbol,
                    Stock.name,
                    Stock.industry,
                    Stock.sub_industry,
                    Stock.market_cap,
                    ScreeningResult.tier,
                    ScreeningResult.total_score,
                    ScreeningResult.odds_ratio,
                    ScreeningResult.confidence,
                    ScreeningResult.implied_profit,
                    ScreeningResult.expectation_gap,
                    ScreeningResult.valuation_pessimistic,
                    ScreeningResult.valuation_base,
                    ScreeningResult.valuation_optimistic,
                    ScreeningResult.scan_date,
                    ScreeningResult.is_active,
                )
                .join(Stock, ScreeningResult.symbol == Stock.symbol)
            )

            if tier is not None:
                query = query.filter(ScreeningResult.tier == tier)
            if date is not None:
                query = query.filter(ScreeningResult.scan_date == date)

            results = query.all()

            df = pd.DataFrame(
                results,
                columns=[
                    "symbol", "name", "industry", "sub_industry", "market_cap",
                    "tier", "total_score", "odds_ratio", "confidence",
                    "implied_profit", "expectation_gap",
                    "valuation_pessimistic", "valuation_base", "valuation_optimistic",
                    "scan_date", "is_active",
                ],
            )

            return df
