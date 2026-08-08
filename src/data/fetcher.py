"""
数据获取门面模块。

提供统一的数据获取接口，协调 AKShare（主数据源）和 baostock（备用数据源），
并集成本地缓存机制以减少重复请求。
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from pathlib import Path

from .cache import CacheManager
from .providers.akshare_provider import AKShareProvider
from .providers.baostock_provider import BaostockProvider

logger = logging.getLogger(__name__)


class DataFetcher:
    """数据获取门面。

    统一调度 AKShare 和 baostock 两个数据源，提供缓存透明集成。
    所有公开方法均支持 use_cache 参数控制是否使用本地缓存。
    """

    def __init__(self, cache_manager: CacheManager = None, settings=None):
        """初始化数据获取器。

        Args:
            cache_manager: 缓存管理器实例，不传则自动创建
            settings: 可选的配置对象
        """
        self.cache = cache_manager or CacheManager()
        self.akshare = AKShareProvider()
        self.baostock = BaostockProvider()
        self.settings = settings

    def get_stock_list(self, use_cache: bool = True) -> pd.DataFrame:
        """获取全市场 A 股列表（实时行情快照）。

        Args:
            use_cache: 是否使用缓存，缓存 TTL 为 24 小时

        Returns:
            包含股票代码、名称、价格、涨跌幅、PE、PB 等字段的 DataFrame
        """
        cache_key = "stock_list_all"
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        df = self.akshare.get_stock_list()
        if not df.empty:
            self.cache.set(cache_key, df, ttl=86400)
        return df

    def get_daily_kline(self, symbol: str, start_date: str = None,
                        end_date: str = None, use_cache: bool = True) -> pd.DataFrame:
        """获取日 K 线数据。

        Args:
            symbol: 股票代码
            start_date: 起始日期，格式 "YYYYMMDD"
            end_date: 结束日期，格式 "YYYYMMDD"
            use_cache: 是否使用缓存，缓存 TTL 为 1 小时

        Returns:
            日 K 线 DataFrame
        """
        cache_key = f"kline_{symbol}"
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        df = self.akshare.get_daily_kline(symbol, start_date=start_date, end_date=end_date)
        if not df.empty:
            self.cache.set(cache_key, df, ttl=3600)
        return df

    def get_financial_indicators(self, symbol: str, use_cache: bool = True) -> pd.DataFrame:
        """获取财务指标数据。

        Args:
            symbol: 股票代码
            use_cache: 是否使用缓存，缓存 TTL 为 7 天

        Returns:
            财务指标 DataFrame（ROE、ROA、毛利率、净利率等）
        """
        cache_key = f"financial_{symbol}"
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        df = self.akshare.get_financial_indicators(symbol)
        if not df.empty:
            self.cache.set(cache_key, df, ttl=86400 * 7)
        return df

    def get_balance_sheet(self, symbol: str, use_cache: bool = True) -> pd.DataFrame:
        """获取资产负债表。

        Args:
            symbol: 股票代码
            use_cache: 是否使用缓存，缓存 TTL 为 7 天

        Returns:
            资产负债表 DataFrame
        """
        cache_key = f"balance_{symbol}"
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        df = self.akshare.get_balance_sheet(symbol)
        if not df.empty:
            self.cache.set(cache_key, df, ttl=86400 * 7)
        return df

    def get_income_statement(self, symbol: str, use_cache: bool = True) -> pd.DataFrame:
        """获取利润表。

        Args:
            symbol: 股票代码
            use_cache: 是否使用缓存，缓存 TTL 为 7 天

        Returns:
            利润表 DataFrame
        """
        cache_key = f"income_{symbol}"
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        df = self.akshare.get_income_statement(symbol)
        if not df.empty:
            self.cache.set(cache_key, df, ttl=86400 * 7)
        return df

    def get_cashflow_statement(self, symbol: str, use_cache: bool = True) -> pd.DataFrame:
        """获取现金流量表。

        Args:
            symbol: 股票代码
            use_cache: 是否使用缓存，缓存 TTL 为 7 天

        Returns:
            现金流量表 DataFrame
        """
        cache_key = f"cashflow_{symbol}"
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        df = self.akshare.get_cashflow_statement(symbol)
        if not df.empty:
            self.cache.set(cache_key, df, ttl=86400 * 7)
        return df

    def get_stock_info(self, symbol: str, use_cache: bool = True) -> dict:
        """获取股票基本信息。

        Args:
            symbol: 股票代码
            use_cache: 是否使用缓存，缓存 TTL 为 24 小时

        Returns:
            包含总股本、流通股本、所属行业等信息的字典
        """
        cache_key = f"info_{symbol}"
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        info = self.akshare.get_stock_info(symbol)
        if info:
            self.cache.set(cache_key, info, ttl=86400)
        return info

    def get_dividend_data(self, symbol: str, use_cache: bool = True) -> pd.DataFrame:
        """获取分红数据（通过 baostock 备用数据源）。

        Args:
            symbol: 股票代码
            use_cache: 是否使用缓存，缓存 TTL 为 30 天

        Returns:
            分红记录 DataFrame
        """
        cache_key = f"dividend_{symbol}"
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        df = self.baostock.get_dividend_data(symbol)
        if not df.empty:
            self.cache.set(cache_key, df, ttl=86400 * 30)
        return df

    def get_valuation_snapshot(self, stock_row: pd.Series) -> dict:
        """从股票列表行中提取估值快照。

        Args:
            stock_row: 股票列表中的单行数据（pd.Series）

        Returns:
            包含 symbol、price、pe_dynamic、pb、market_cap 等字段的字典，
            解析失败返回空字典
        """
        try:
            return {
                'symbol': str(stock_row.get('symbol', '')),
                'price': float(stock_row.get('price', 0) or 0),
                'pe_dynamic': float(stock_row.get('pe_dynamic', 0) or 0),
                'pb': float(stock_row.get('pb', 0) or 0),
                'market_cap': float(stock_row.get('market_cap', 0) or 0),
                'float_market_cap': float(stock_row.get('float_market_cap', 0) or 0),
                'turnover': float(stock_row.get('turnover', 0) or 0),
                'change_pct': float(stock_row.get('change_pct', 0) or 0),
            }
        except (ValueError, TypeError):
            return {}

    def close(self) -> None:
        """清理资源，登出 baostock 连接。"""
        self.baostock.logout()
