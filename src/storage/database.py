"""
数据库管理器 - A股黄金坑股票数据库持久化存储层。

提供数据库初始化、CRUD操作、快照管理、统计信息等核心功能。
"""

import datetime
import logging
from contextlib import contextmanager
from typing import Any, Generator, Optional

import pandas as pd
from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import Session, sessionmaker

from .models import (
    Base,
    FinancialData,
    RiskCheckResult,
    ScreeningResult,
    Stock,
    ValuationSnapshot,
)

logger = logging.getLogger(__name__)


class DatabaseManager:
    """数据库管理器。

    负责数据库初始化、连接管理、数据持久化操作。
    使用 SQLAlchemy 2.0 风格，SQLite + WAL 模式。
    """

    def __init__(self, db_path: str) -> None:
        """初始化数据库管理器。

        Args:
            db_path: SQLite 数据库文件路径
        """
        self.db_path = db_path
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

    def initialize(self) -> None:
        """初始化数据库。

        创建所有表，启用 WAL 模式，创建必要的索引。
        """
        # 启用 WAL 模式
        with self.engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL;"))
            conn.execute(text("PRAGMA synchronous=NORMAL;"))
            conn.execute(text("PRAGMA cache_size=-64000;"))
            conn.execute(text("PRAGMA foreign_keys=ON;"))
            conn.commit()

        # 创建所有表
        Base.metadata.create_all(self.engine)

        # 创建额外的复合索引
        self._create_indexes()

        logger.info("数据库初始化完成: %s (WAL模式)", self.db_path)

    def _create_indexes(self) -> None:
        """创建额外的复合索引以优化查询性能。"""
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_financial_symbol_report ON financial_data(symbol, report_date DESC);",
            "CREATE INDEX IF NOT EXISTS idx_valuation_symbol_date ON valuation_snapshots(symbol, date DESC);",
            "CREATE INDEX IF NOT EXISTS idx_screening_symbol_scan ON screening_results(symbol, scan_date DESC);",
            "CREATE INDEX IF NOT EXISTS idx_screening_tier_active ON screening_results(tier, is_active);",
            "CREATE INDEX IF NOT EXISTS idx_risk_symbol_date ON risk_check_results(symbol, check_date DESC);",
        ]
        with self.engine.connect() as conn:
            for idx_sql in indexes:
                conn.execute(text(idx_sql))
            conn.commit()

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """获取数据库会话的上下文管理器。

        自动处理事务提交和回滚，确保会话正确关闭。

        Yields:
            SQLAlchemy Session 对象

        Example:
            with db.get_session() as session:
                stocks = session.query(Stock).all()
        """
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # =========================================================================
    # 股票基础信息
    # =========================================================================

    def upsert_stocks(self, stocks: list[dict[str, Any]]) -> int:
        """批量插入或更新股票基础信息。

        以 symbol 为唯一键，存在则更新，不存在则插入。

        Args:
            stocks: 股票信息字典列表，每个字典需包含 symbol 字段

        Returns:
            处理的股票数量
        """
        with self.get_session() as session:
            count = 0
            for stock_data in stocks:
                symbol = stock_data.get("symbol")
                if not symbol:
                    continue

                existing = session.query(Stock).filter(Stock.symbol == symbol).first()
                if existing:
                    for key, value in stock_data.items():
                        if hasattr(existing, key):
                            setattr(existing, key, value)
                else:
                    stock = Stock(**stock_data)
                    session.add(stock)
                count += 1
            return count

    def get_stock_by_symbol(self, symbol: str) -> Optional[Stock]:
        """根据股票代码查询单只股票。

        Args:
            symbol: 股票代码

        Returns:
            Stock 对象，未找到返回 None
        """
        with self.get_session() as session:
            return session.query(Stock).filter(Stock.symbol == symbol).first()

    def get_active_stocks(self) -> list[Stock]:
        """获取所有活跃股票（非ST、未退市）。

        Returns:
            活跃股票列表
        """
        with self.get_session() as session:
            return (
                session.query(Stock)
                .filter(Stock.is_st == False, Stock.is_delisted == False)
                .all()
            )

    # =========================================================================
    # 财务数据
    # =========================================================================

    def upsert_financial_data(self, symbol: str, df: pd.DataFrame) -> int:
        """插入或更新财务数据。

        DataFrame 需包含 report_date 列及对应的财务指标列。
        以 (symbol, report_date) 为唯一键进行 upsert。

        Args:
            symbol: 股票代码
            df: 包含财务数据的 DataFrame

        Returns:
            处理的行数
        """
        with self.get_session() as session:
            count = 0
            for _, row in df.iterrows():
                record = row.to_dict()
                record["symbol"] = symbol

                report_date = record.get("report_date")
                if report_date is None:
                    continue

                existing = (
                    session.query(FinancialData)
                    .filter(
                        FinancialData.symbol == symbol,
                        FinancialData.report_date == report_date,
                    )
                    .first()
                )

                if existing:
                    for key, value in record.items():
                        if hasattr(existing, key):
                            setattr(existing, key, value)
                else:
                    fd = FinancialData(**record)
                    session.add(fd)
                count += 1
            return count

    def get_latest_financial(self, symbol: str) -> Optional[FinancialData]:
        """获取某股票的最新财务数据。

        Args:
            symbol: 股票代码

        Returns:
            最新 FinancialData 对象，无数据返回 None
        """
        with self.get_session() as session:
            return (
                session.query(FinancialData)
                .filter(FinancialData.symbol == symbol)
                .order_by(FinancialData.report_date.desc())
                .first()
            )

    def get_financial_history(
        self, symbol: str, quarters: int = 20
    ) -> list[FinancialData]:
        """获取某股票最近 N 个季度的财务数据历史。

        Args:
            symbol: 股票代码
            quarters: 获取的季度数，默认 20

        Returns:
            财务数据列表，按报告期降序排列
        """
        with self.get_session() as session:
            return (
                session.query(FinancialData)
                .filter(FinancialData.symbol == symbol)
                .order_by(FinancialData.report_date.desc())
                .limit(quarters)
                .all()
            )

    # =========================================================================
    # 估值数据
    # =========================================================================

    def upsert_valuation(self, symbol: str, data: dict[str, Any]) -> None:
        """插入估值快照。

        每次插入一条新记录，不做 upsert（估值快照按日期保留历史）。

        Args:
            symbol: 股票代码
            data: 估值数据字典，需包含 date 字段（可为 str 或 date 类型）
        """
        data["symbol"] = symbol

        # 将字符串日期转换为 date 对象
        if "date" in data and isinstance(data["date"], str):
            data["date"] = datetime.date.fromisoformat(data["date"])

        with self.get_session() as session:
            valuation = ValuationSnapshot(**data)
            session.add(valuation)

    def get_latest_valuation(self, symbol: str) -> Optional[ValuationSnapshot]:
        """获取某股票的最新估值快照。

        Args:
            symbol: 股票代码

        Returns:
            最新 ValuationSnapshot 对象，无数据返回 None
        """
        with self.get_session() as session:
            return (
                session.query(ValuationSnapshot)
                .filter(ValuationSnapshot.symbol == symbol)
                .order_by(ValuationSnapshot.date.desc())
                .first()
            )

    def get_valuation_history(self, symbol: str) -> list[ValuationSnapshot]:
        """获取某股票的估值历史记录。

        Args:
            symbol: 股票代码

        Returns:
            估值快照列表，按日期降序排列
        """
        with self.get_session() as session:
            return (
                session.query(ValuationSnapshot)
                .filter(ValuationSnapshot.symbol == symbol)
                .order_by(ValuationSnapshot.date.desc())
                .all()
            )

    # =========================================================================
    # 筛选结果
    # =========================================================================

    def save_screening_result(
        self, symbol: str, tier: int, result: dict[str, Any]
    ) -> None:
        """保存筛选结果。

        Args:
            symbol: 股票代码
            tier: 层级 (1/2/3)
            result: 筛选结果字典，需包含 scan_date 字段
        """
        result["symbol"] = symbol
        result["tier"] = tier
        with self.get_session() as session:
            sr = ScreeningResult(**result)
            session.add(sr)

    def get_screening_by_tier(
        self, tier: int, date: Optional[datetime.date] = None
    ) -> list[ScreeningResult]:
        """按层级获取筛选结果。

        默认返回该层级所有活跃结果，按评分降序排列。

        Args:
            tier: 层级 (1/2/3)
            date: 可选，指定扫描日期过滤

        Returns:
            筛选结果列表
        """
        with self.get_session() as session:
            query = session.query(ScreeningResult).filter(
                ScreeningResult.tier == tier,
                ScreeningResult.is_active == True,
            )
            if date is not None:
                query = query.filter(ScreeningResult.scan_date == date)
            return query.order_by(ScreeningResult.total_score.desc()).all()

    def get_screening_history(self, symbol: str) -> list[ScreeningResult]:
        """获取某股票的历史筛选结果。

        Args:
            symbol: 股票代码

        Returns:
            筛选结果列表，按扫描日期降序排列
        """
        with self.get_session() as session:
            return (
                session.query(ScreeningResult)
                .filter(ScreeningResult.symbol == symbol)
                .order_by(ScreeningResult.scan_date.desc())
                .all()
            )

    def deactivate_stale_results(self, scan_date: datetime.date) -> int:
        """将指定日期之前的活跃结果标记为非活跃。

        通常在新的批量筛选完成后调用，确保只有最新一批结果为活跃状态。

        Args:
            scan_date: 扫描日期，该日期之前的结果将被标记为非活跃

        Returns:
            被标记为非活跃的记录数
        """
        with self.get_session() as session:
            count = (
                session.query(ScreeningResult)
                .filter(
                    ScreeningResult.scan_date < scan_date,
                    ScreeningResult.is_active == True,
                )
                .update({"is_active": False})
            )
            return count

    # =========================================================================
    # 风险检查
    # =========================================================================

    def save_risk_check(self, symbol: str, result: dict[str, Any]) -> None:
        """保存风险检查结果。

        Args:
            symbol: 股票代码
            result: 风险检查结果字典，需包含 check_date 字段
        """
        result["symbol"] = symbol
        with self.get_session() as session:
            rc = RiskCheckResult(**result)
            session.add(rc)

    def get_latest_risk_check(self, symbol: str) -> Optional[RiskCheckResult]:
        """获取某股票的最新风险检查结果。

        Args:
            symbol: 股票代码

        Returns:
            最新 RiskCheckResult 对象，无数据返回 None
        """
        with self.get_session() as session:
            return (
                session.query(RiskCheckResult)
                .filter(RiskCheckResult.symbol == symbol)
                .order_by(RiskCheckResult.check_date.desc())
                .first()
            )

    # =========================================================================
    # 快照管理
    # =========================================================================

    def create_snapshot(self, scan_date: datetime.date) -> dict[str, Any]:
        """创建当前活跃筛选结果的快照统计。

        统计指定日期的各层级股票数量及评分分布。

        Args:
            scan_date: 快照日期

        Returns:
            包含快照统计信息的字典
        """
        with self.get_session() as session:
            snapshot = {"scan_date": scan_date.isoformat(), "tiers": {}}

            for tier in [1, 2, 3]:
                results = (
                    session.query(ScreeningResult)
                    .filter(
                        ScreeningResult.tier == tier,
                        ScreeningResult.scan_date == scan_date,
                        ScreeningResult.is_active == True,
                    )
                    .all()
                )

                scores = [r.total_score for r in results if r.total_score is not None]
                snapshot["tiers"][f"tier_{tier}"] = {
                    "count": len(results),
                    "avg_score": sum(scores) / len(scores) if scores else 0,
                    "max_score": max(scores) if scores else 0,
                    "min_score": min(scores) if scores else 0,
                    "symbols": [r.symbol for r in results],
                }

            return snapshot

    def get_historical_snapshots(self) -> list[datetime.date]:
        """获取所有历史快照日期列表。

        Returns:
            去重的扫描日期列表，按日期降序排列
        """
        with self.get_session() as session:
            dates = (
                session.query(ScreeningResult.scan_date)
                .distinct()
                .order_by(ScreeningResult.scan_date.desc())
                .all()
            )
            return [d[0] for d in dates]

    def compare_snapshots(
        self, date1: datetime.date, date2: datetime.date
    ) -> dict[str, Any]:
        """对比两个快照之间的变化。

        Args:
            date1: 第一个快照日期（基准）
            date2: 第二个快照日期（对比）

        Returns:
            包含变化统计的字典
        """
        with self.get_session() as session:
            comparison = {"date1": date1.isoformat(), "date2": date2.isoformat(), "changes": {}}

            for tier in [1, 2, 3]:
                symbols1 = set(
                    r[0]
                    for r in session.query(ScreeningResult.symbol)
                    .filter(
                        ScreeningResult.tier == tier,
                        ScreeningResult.scan_date == date1,
                        ScreeningResult.is_active == True,
                    )
                    .all()
                )

                symbols2 = set(
                    r[0]
                    for r in session.query(ScreeningResult.symbol)
                    .filter(
                        ScreeningResult.tier == tier,
                        ScreeningResult.scan_date == date2,
                        ScreeningResult.is_active == True,
                    )
                    .all()
                )

                comparison["changes"][f"tier_{tier}"] = {
                    "added": list(symbols2 - symbols1),
                    "removed": list(symbols1 - symbols2),
                    "unchanged": list(symbols1 & symbols2),
                    "count_before": len(symbols1),
                    "count_after": len(symbols2),
                }

            return comparison

    # =========================================================================
    # 统计信息
    # =========================================================================

    def get_statistics(self) -> dict[str, Any]:
        """获取数据库整体统计信息。

        Returns:
            包含各表记录数及概要统计的字典
        """
        with self.get_session() as session:
            stats = {
                "stocks": session.query(func.count(Stock.id)).scalar(),
                "active_stocks": session.query(func.count(Stock.id))
                .filter(Stock.is_st == False, Stock.is_delisted == False)
                .scalar(),
                "financial_records": session.query(func.count(FinancialData.id)).scalar(),
                "valuation_snapshots": session.query(func.count(ValuationSnapshot.id)).scalar(),
                "screening_results": session.query(func.count(ScreeningResult.id)).scalar(),
                "active_screening_results": session.query(func.count(ScreeningResult.id))
                .filter(ScreeningResult.is_active == True)
                .scalar(),
                "risk_checks": session.query(func.count(RiskCheckResult.id)).scalar(),
            }

            # 各层级统计
            for tier in [1, 2, 3]:
                count = (
                    session.query(func.count(ScreeningResult.id))
                    .filter(
                        ScreeningResult.tier == tier,
                        ScreeningResult.is_active == True,
                    )
                    .scalar()
                )
                stats[f"tier_{tier}_count"] = count

            # 最新扫描日期
            latest_scan = (
                session.query(func.max(ScreeningResult.scan_date)).scalar()
            )
            stats["latest_scan_date"] = (
                latest_scan.isoformat() if latest_scan else None
            )

            return stats
