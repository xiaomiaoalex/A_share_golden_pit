"""市场隐含利润计算器。

从当前股价和PE反推市场隐含的盈利水平，
并与正常化利润对比，识别盈利预期差。
"""

import numpy as np
import pandas as pd
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ImpliedProfitCalculator:
    """市场隐含利润计算器：从股价反推市场隐含的盈利水平。

    通过市值和PE反算市场隐含的年度利润，并基于合理假设估算
    正常化利润，计算两者之间的预期差。
    """

    def __init__(self, fetcher, settings=None):
        """初始化隐含利润计算器。

        Args:
            fetcher: 数据获取器实例
            settings: 可选配置对象
        """
        self.fetcher = fetcher
        self.settings = settings

    def calc_implied_profit(self, symbol: str, basic_info: dict = None) -> dict:
        """计算市场隐含利润。

        市场市值 = 隐含利润 x 市场给PE
        隐含利润 = 市值 / PE

        通过合理乘数上调隐含利润得到正常化利润，
        计算利润预期差。

        Args:
            symbol: 股票代码
            basic_info: 股票基本信息字典，需包含 price、pe_dynamic、
                       market_cap、pb 字段

        Returns:
            dict: 包含以下字段的隐含利润结果：
                - market_cap: 总市值（亿元）
                - implied_annual_profit: 市场隐含年度利润（亿元）
                - implied_roe: 隐含ROE（%）
                - market_pe: 当前PE
                - fair_annual_profit: 正常化利润（亿元）
                - profit_gap_pct: 利润预期差（%）
                - assessment: 评估结论
        """
        try:
            price = float(basic_info.get('price', 0)) if basic_info else 0
            pe = float(basic_info.get('pe_dynamic', 0)) if basic_info else 0
            market_cap = float(basic_info.get('market_cap', 0)) if basic_info else 0
            pb = float(basic_info.get('pb', 0)) if basic_info else 0

            if price <= 0 or pe <= 0:
                return self._empty_result()

            if market_cap > 0:
                implied_profit = market_cap / pe / 1e8
            else:
                implied_profit = 0

            implied_roe = pb / pe if pe > 0 and pb > 0 else 0

            fair_profit_multiplier = 1.2 if pe < 15 else 1.1
            fair_profit = implied_profit * fair_profit_multiplier

            profit_gap = (
                (fair_profit / implied_profit - 1) * 100 if implied_profit > 0 else 0
            )

            if profit_gap > 30:
                assessment = '市场严重低估盈利能力'
            elif profit_gap > 15:
                assessment = '市场明显低估盈利能力'
            elif profit_gap > 5:
                assessment = '市场略低估盈利能力'
            elif profit_gap > -5:
                assessment = '市场定价基本合理'
            else:
                assessment = '市场可能高估盈利能力'

            return {
                'market_cap': round(market_cap / 1e8, 2) if market_cap > 0 else 0,
                'implied_annual_profit': round(implied_profit, 2),
                'implied_roe': round(implied_roe * 100, 1),
                'market_pe': round(pe, 1),
                'fair_annual_profit': round(fair_profit, 2),
                'profit_gap_pct': round(profit_gap, 1),
                'assessment': assessment,
            }
        except Exception as e:
            logger.error(f"隐含利润计算失败 {symbol}: {e}")
            return self._empty_result()

    def _empty_result(self) -> dict:
        """返回数据不足时的空结果。

        Returns:
            dict: 包含默认零值的隐含利润结果字典
        """
        return {
            'market_cap': 0,
            'implied_annual_profit': 0,
            'implied_roe': 0,
            'market_pe': 0,
            'fair_annual_profit': 0,
            'profit_gap_pct': 0,
            'assessment': '数据不足',
        }
