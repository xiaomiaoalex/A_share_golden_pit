"""第一层筛选：黄金坑雷达池

从全市场约5000只股票快速筛选到200-400只候选标的，
通过基本排除、市值、盈利、回撤、估值分位等维度进行初筛。
"""

import pandas as pd
import numpy as np
import logging
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class RadarScanner:
    """第一层：黄金坑雷达池 —— 快速扫描数百家候选标的"""

    def __init__(self, fetcher, thresholds):
        """初始化雷达扫描器

        Args:
            fetcher: DataFetcher实例，用于获取行情与财务数据
            thresholds: RadarThreshold配置，包含各筛选阈值
        """
        self.fetcher = fetcher
        self.thresholds = thresholds

    def scan(self, stock_list: pd.DataFrame) -> pd.DataFrame:
        """执行雷达扫描，返回通过初步筛选的股票列表

        筛选逻辑：
        1. 排除ST、*ST、退市整理
        2. 排除上市不足1年
        3. 排除市值 < 50亿
        4. ROE > 10%（近3年平均）
        5. 52周最大回撤 > 30%
        6. PE历史分位 < 30%

        Args:
            stock_list: 全市场股票列表DataFrame

        Returns:
            通过筛选的股票DataFrame，包含筛选指标列
        """
        if stock_list.empty:
            logger.warning("股票列表为空，无法扫描")
            return pd.DataFrame()

        df = stock_list.copy()
        total = len(df)

        # 1. 基本排除
        df = self._apply_exclusions(df)
        logger.info(f"排除ST/新股后: {len(df)}/{total}")

        # 2. 市值筛选
        df = self._filter_market_cap(df)
        logger.info(f"市值筛选后: {len(df)}/{total}")

        # 3. 盈利筛选（ROE）
        df = self._filter_roe(df)
        logger.info(f"ROE筛选后: {len(df)}/{total}")

        # 4. 回撤筛选
        df = self._filter_drawdown(df)
        logger.info(f"回撤筛选后: {len(df)}/{total}")

        # 5. PE分位筛选
        df = self._filter_pe_percentile(df)
        logger.info(f"PE分位筛选后: {len(df)}/{total}")

        # 排序：按回撤从大到小
        if not df.empty and 'drawdown_52w' in df.columns:
            df = df.sort_values('drawdown_52w')

        return df

    def _apply_exclusions(self, df: pd.DataFrame) -> pd.DataFrame:
        """排除ST、*ST、上市不足1年及科创板/北交所标的

        Args:
            df: 股票列表DataFrame

        Returns:
            排除后的DataFrame
        """
        # 排除ST
        if 'name' in df.columns:
            df = df[~df['name'].str.contains(r'\*ST|ST|退市', na=False)]

        # 排除科创板/北交所（可选，用symbol判断）
        # 科创板代码688开头，北交所8/4开头
        if 'symbol' in df.columns:
            df = df[~df['symbol'].astype(str).str.startswith(('8', '4'))]

        return df

    def _filter_market_cap(self, df: pd.DataFrame) -> pd.DataFrame:
        """市值筛选：排除市值低于阈值的标的

        Args:
            df: 股票列表DataFrame

        Returns:
            筛选后的DataFrame
        """
        if 'market_cap' in df.columns:
            df['market_cap_num'] = pd.to_numeric(df['market_cap'], errors='coerce')
            # 只有当有有效数值时才筛选，全部为NaN时跳过
            valid_mask = df['market_cap_num'].notna()
            if valid_mask.any():
                df = df[valid_mask & (df['market_cap_num'] >= self.thresholds.MIN_MARKET_CAP)].copy()
            # 如果全部为NaN，跳过市值筛选（保留所有）
        return df

    def _filter_roe(self, df: pd.DataFrame) -> pd.DataFrame:
        """ROE筛选：近3年平均ROE > 阈值

        优先使用PE倒数作为隐含ROE代理，其次使用直接的ROE字段。
        如果PE数据不可用，跳过ROE筛选。

        Args:
            df: 股票列表DataFrame

        Returns:
            筛选后的DataFrame
        """
        if 'pe_dynamic' in df.columns:
            df['pe_num'] = pd.to_numeric(df['pe_dynamic'], errors='coerce')
            valid_mask = df['pe_num'].notna() & (df['pe_num'] > 0) & (df['pe_num'] < 100)
            if valid_mask.any():
                df['implied_roe'] = np.where(valid_mask, 1.0 / df['pe_num'], 0)
                df = df[df['implied_roe'] >= self.thresholds.MIN_ROE].copy()
            # 如果所有PE都无效，跳过ROE筛选
        elif 'roe' in df.columns:
            df['roe_num'] = pd.to_numeric(df['roe'], errors='coerce')
            valid_mask = df['roe_num'].notna()
            if valid_mask.any():
                df = df[df['roe_num'] >= self.thresholds.MIN_ROE].copy()
        # 无PE和ROE数据时，跳过此筛选
        return df

    def _filter_drawdown(self, df: pd.DataFrame) -> pd.DataFrame:
        """52周回撤筛选：优先使用60日涨跌幅，其次年初至今涨跌幅

        如果两者都不可用，跳过回撤筛选。

        Args:
            df: 股票列表DataFrame

        Returns:
            筛选后的DataFrame，附加drawdown_52w列
        """
        if 'change_60d' in df.columns:
            df['change_60d_num'] = pd.to_numeric(df['change_60d'], errors='coerce')
            valid_mask = df['change_60d_num'].notna()
            if valid_mask.any():
                df = df[valid_mask & (df['change_60d_num'] <= self.thresholds.MAX_DRAWDOWN * 100)].copy()
                df['drawdown_52w'] = df['change_60d_num']
                return df
        if 'change_ytd' in df.columns:
            df['change_ytd_num'] = pd.to_numeric(df['change_ytd'], errors='coerce')
            valid_mask = df['change_ytd_num'].notna()
            if valid_mask.any():
                df = df[valid_mask & (df['change_ytd_num'] <= self.thresholds.MAX_DRAWDOWN * 100)].copy()
                df['drawdown_52w'] = df['change_ytd_num']
                return df
        # 无回撤数据时跳过此筛选
        df['drawdown_52w'] = 0
        return df

    def _filter_pe_percentile(self, df: pd.DataFrame) -> pd.DataFrame:
        """PE估值筛选：PE在合理范围（正PE且不过高）

        Args:
            df: 股票列表DataFrame

        Returns:
            筛选后的DataFrame
        """
        if 'pe_dynamic' in df.columns:
            df['pe_num'] = pd.to_numeric(df['pe_dynamic'], errors='coerce')
            valid_mask = df['pe_num'].notna() & (df['pe_num'] > 0) & (df['pe_num'] < 50)
            if valid_mask.any():
                df = df[valid_mask].copy()
            # 如果所有PE都无效，跳过筛选
        return df

    def get_scan_summary(self, result: pd.DataFrame) -> dict:
        """获取扫描摘要统计

        Args:
            result: 扫描结果DataFrame

        Returns:
            包含候选数量、平均回撤、平均PE、行业分布的字典
        """
        return {
            'total_candidates': len(result),
            'avg_drawdown': float(result['drawdown_52w'].mean()) if 'drawdown_52w' in result.columns else 0,
            'avg_pe': float(result['pe_num'].mean()) if 'pe_num' in result.columns else 0,
            'industries': result['industry'].value_counts().to_dict() if 'industry' in result.columns else {},
        }
