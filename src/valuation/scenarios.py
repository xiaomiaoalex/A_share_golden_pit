"""三情景估值模型。

基于悲观、基准、乐观三种情景对股票进行估值，
计算加权公允价值和安全边际。
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


class ScenarioValuation:
    """三情景估值模型：悲观/基准/乐观。

    基于不同PE和盈利假设构建三种估值情景，
    通过概率加权计算综合公允价值和预期收益。
    """

    def __init__(self, fetcher, settings=None):
        """初始化三情景估值模型。

        Args:
            fetcher: 数据获取器实例，需提供 get_stock_list() 方法
            settings: 可选配置对象，可包含 WACC_DEFAULT、TERMINAL_GROWTH_DEFAULT、
                     FORECAST_YEARS 等参数
        """
        self.fetcher = fetcher
        self.settings = settings
        self.wacc_default = (
            getattr(settings, 'WACC_DEFAULT', 0.10) if settings else 0.10
        )
        self.terminal_growth = (
            getattr(settings, 'TERMINAL_GROWTH_DEFAULT', 0.03) if settings else 0.03
        )
        self.forecast_years = (
            getattr(settings, 'FORECAST_YEARS', 10) if settings else 10
        )

    def build_scenarios(self, symbol: str, basic_info: dict = None) -> dict:
        """构建三情景估值模型。

        基于不同PE倍数和盈利假设，计算悲观、基准、乐观三种情景下的
        公允价值，并通过概率加权得出综合估值。

        Args:
            symbol: 股票代码
            basic_info: 股票基本信息字典，需包含 price、pe_dynamic 字段

        Returns:
            dict: 包含以下字段的估值结果：
                - pessimistic: 悲观情景（公允价值、上涨空间、概率、假设PE）
                - base: 基准情景（公允价值、上涨空间、概率、假设PE）
                - optimistic: 乐观情景（公允价值、上涨空间、概率、假设PE）
                - weighted_fair_value: 概率加权公允价值
                - current_price: 当前价格
                - expected_return: 预期收益率(%)
                - margin_of_safety: 安全边际(%)
        """
        try:
            price = float(basic_info.get('price', 0)) if basic_info else 0
            pe = float(basic_info.get('pe_dynamic', 0)) if basic_info else 0

            if price <= 0 or pe <= 0:
                stock_list = self.fetcher.get_stock_list()
                if not stock_list.empty:
                    row = stock_list[
                        stock_list['symbol'].astype(str).str[:6] == symbol[:6]
                    ]
                    if not row.empty:
                        price = float(row.iloc[0].get('price', 0) or 0)
                        pe = float(row.iloc[0].get('pe_dynamic', 0) or 0)

            if price <= 0:
                return self._empty_result()

            earnings = price / pe if pe > 0 else 0

            pessimistic_pe = max(8, pe * 0.6)
            base_pe = max(12, pe * 0.9)
            optimistic_pe = max(15, pe * 1.2)

            pessimistic_earnings = earnings * 0.85
            base_earnings = earnings
            optimistic_earnings = earnings * 1.15

            pv = pessimistic_earnings * pessimistic_pe
            bv = base_earnings * base_pe
            ov = optimistic_earnings * optimistic_pe

            p_prob, b_prob, o_prob = 0.30, 0.50, 0.20

            weighted_value = pv * p_prob + bv * b_prob + ov * o_prob

            margin_of_safety = (
                (weighted_value - price) / weighted_value if weighted_value > 0 else 0
            )

            return {
                'pessimistic': {
                    'fair_value': round(pv, 2),
                    'upside_pct': round((pv / price - 1) * 100, 1),
                    'probability': p_prob,
                    'pe_assumed': round(pessimistic_pe, 1),
                },
                'base': {
                    'fair_value': round(bv, 2),
                    'upside_pct': round((bv / price - 1) * 100, 1),
                    'probability': b_prob,
                    'pe_assumed': round(base_pe, 1),
                },
                'optimistic': {
                    'fair_value': round(ov, 2),
                    'upside_pct': round((ov / price - 1) * 100, 1),
                    'probability': o_prob,
                    'pe_assumed': round(optimistic_pe, 1),
                },
                'weighted_fair_value': round(weighted_value, 2),
                'current_price': round(price, 2),
                'expected_return': round((weighted_value / price - 1) * 100, 1),
                'margin_of_safety': round(margin_of_safety * 100, 1),
            }
        except Exception as e:
            logger.error(f"三情景估值失败 {symbol}: {e}")
            return self._empty_result()

    def _empty_result(self) -> dict:
        """返回数据不足时的空结果。

        Returns:
            dict: 包含默认零值的估值结果字典
        """
        return {
            'pessimistic': {
                'fair_value': 0,
                'upside_pct': 0,
                'probability': 0.3,
            },
            'base': {
                'fair_value': 0,
                'upside_pct': 0,
                'probability': 0.5,
            },
            'optimistic': {
                'fair_value': 0,
                'upside_pct': 0,
                'probability': 0.2,
            },
            'weighted_fair_value': 0,
            'current_price': 0,
            'expected_return': 0,
            'margin_of_safety': 0,
        }
