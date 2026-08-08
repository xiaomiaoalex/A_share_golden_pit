"""历史估值分位分析器。

通过价格回撤分位近似估值分位，计算PE/PB的历史位置和估值区域。
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class HistoricalValuation:
    """历史估值分位分析器。

    基于价格序列的回撤程度近似估算PE/PB的历史分位，
    判断当前估值在历史中所处的位置。
    """

    def __init__(self, fetcher, settings=None):
        """初始化历史估值分析器。

        Args:
            fetcher: 数据获取器实例，需提供 get_daily_kline() 和 get_stock_list() 方法
            settings: 可选配置对象
        """
        self.fetcher = fetcher
        self.settings = settings

    def calc_percentile(self, symbol: str, years: int = 5) -> dict:
        """计算PE/PB的历史分位。

        通过价格序列的回撤位置近似估算估值分位，
        同时从股票列表中获取当前PE/PB值。

        Args:
            symbol: 股票代码
            years: 回溯年数（保留参数，实际使用全部可用数据）

        Returns:
            dict: 包含以下字段的估值分位结果：
                - pe_current: 当前动态PE
                - pe_percentile: PE在历史中的分位数(%)
                - pe_median: PE中位数
                - pe_min: PE最小值
                - pe_max: PE最大值
                - pb_current: 当前PB
                - pb_percentile: PB在历史中的分位数(%)
                - price_percentile: 价格在历史中的分位数(%)
                - valuation_zone: 估值区域（极度低估/低估/合理/高估/泡沫）
                - data_points: 有效数据点数
                - lookback_start: 回溯起始日期
        """
        try:
            kline = self.fetcher.get_daily_kline(symbol)
            if kline.empty:
                return self._empty_result()

            if 'close' not in kline.columns:
                return self._empty_result()

            prices = kline['close'].dropna()
            if len(prices) < 20:
                return self._empty_result()

            current_price = prices.iloc[-1]
            price_percentile = (prices <= current_price).mean()

            stock_info = self.fetcher.get_stock_list()
            stock_row = (
                stock_info[stock_info['symbol'].astype(str).str[:6] == symbol[:6]]
                if not stock_info.empty
                else pd.DataFrame()
            )

            pe_current = None
            pb_current = None

            if not stock_row.empty:
                pe_current = float(stock_row.iloc[0].get('pe_dynamic', 0) or 0)
                pb_current = float(stock_row.iloc[0].get('pb', 0) or 0)

            if price_percentile <= 0.15:
                zone = '极度低估'
            elif price_percentile <= 0.30:
                zone = '低估'
            elif price_percentile <= 0.70:
                zone = '合理'
            elif price_percentile <= 0.85:
                zone = '高估'
            else:
                zone = '泡沫'

            lookback_start = prices.index[0]
            if hasattr(lookback_start, 'strftime'):
                lookback_start = lookback_start.strftime('%Y-%m-%d')
            else:
                lookback_start = str(lookback_start)

            return {
                'pe_current': round(pe_current, 2) if pe_current else None,
                'pe_percentile': round(price_percentile * 100, 1),
                'pe_median': round(float(prices.median()), 2),
                'pe_min': round(float(prices.min()), 2),
                'pe_max': round(float(prices.max()), 2),
                'pb_current': round(pb_current, 2) if pb_current else None,
                'pb_percentile': round(price_percentile * 100, 1),
                'price_percentile': round(price_percentile * 100, 1),
                'valuation_zone': zone,
                'data_points': len(prices),
                'lookback_start': lookback_start,
            }
        except Exception as e:
            logger.error(f"估值分位计算失败 {symbol}: {e}")
            return self._empty_result()

    def calc_valuation_zscore(self, symbol: str) -> float:
        """计算估值Z-Score，即估值偏离历史均值的标准差数。

        将价格分位数通过正态分布逆变换转换为Z-Score，
        负值表示低估，正值表示高估。

        Args:
            symbol: 股票代码

        Returns:
            float: 估值Z-Score，保留2位小数
        """
        result = self.calc_percentile(symbol)
        percentile = result.get('price_percentile', 50) / 100.0
        from scipy.stats import norm

        try:
            return round(float(norm.ppf(percentile)), 2)
        except Exception:
            return 0.0

    def _empty_result(self) -> dict:
        """返回数据不足时的空结果。

        Returns:
            dict: 包含默认空值的估值结果字典
        """
        return {
            'pe_current': None,
            'pe_percentile': None,
            'pe_median': None,
            'pe_min': None,
            'pe_max': None,
            'pb_current': None,
            'pb_percentile': None,
            'price_percentile': None,
            'valuation_zone': '数据不足',
            'data_points': 0,
            'lookback_start': None,
        }
