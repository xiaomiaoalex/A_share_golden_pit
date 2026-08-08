"""逆向DCF模型。

从当前股价反推市场隐含的增长假设，
计算安全边际和内在PE。
"""

import numpy as np
import logging
from typing import Dict

logger = logging.getLogger(__name__)


class ReverseDCF:
    """逆向DCF模型：从当前股价反推市场隐含增长假设。

    使用简化的戈登增长模型从股价和PE反推市场隐含的增长率，
    并与合理增长率对比，判断估值高低。
    """

    def __init__(self, fetcher, settings=None):
        """初始化逆向DCF模型。

        Args:
            fetcher: 数据获取器实例
            settings: 可选配置对象，可包含 WACC_DEFAULT、TERMINAL_GROWTH_DEFAULT、
                     FORECAST_YEARS 等参数
        """
        self.fetcher = fetcher
        self.settings = settings
        self.wacc = (
            getattr(settings, 'WACC_DEFAULT', 0.10) if settings else 0.10
        )
        self.terminal_growth = (
            getattr(settings, 'TERMINAL_GROWTH_DEFAULT', 0.03) if settings else 0.03
        )
        self.forecast_years = (
            getattr(settings, 'FORECAST_YEARS', 10) if settings else 10
        )

    def calc_implied_growth(self, symbol: str, basic_info: dict = None) -> dict:
        """计算当前股价隐含的增长率。

        使用简化的戈登增长模型反推：
        P = E / (r - g) => g = r - E/P

        其中 E/P 为盈利收益率，r 为要求回报率（WACC）。

        Args:
            symbol: 股票代码
            basic_info: 股票基本信息字典，需包含 price、pe_dynamic 字段

        Returns:
            dict: 包含以下字段的隐含增长结果：
                - implied_growth: 市场隐含增长率(%)
                - earnings_yield: 盈利收益率(%)
                - required_return: 要求回报率(%)
                - growth_gap: 隐含增长与合理增长的差距(%)
                - valuation_status: 估值状态描述
                - reasonable_growth: 合理增长率参考(%)
        """
        try:
            price = float(basic_info.get('price', 0)) if basic_info else 0
            pe = float(basic_info.get('pe_dynamic', 0)) if basic_info else 0

            if price <= 0 or pe <= 0:
                return self._empty_result()

            earnings_yield = 1.0 / pe

            implied_growth = self.wacc - earnings_yield

            reasonable_growth = 0.03

            growth_gap = reasonable_growth - implied_growth

            if implied_growth <= 0:
                status = '极度低估（市场定价零增长甚至负增长）'
            elif implied_growth < 0.03:
                status = '低估（市场定价低于GDP增速）'
            elif implied_growth < 0.05:
                status = '合理偏低'
            elif implied_growth < 0.08:
                status = '合理偏高'
            else:
                status = '高估（市场定价过高增长）'

            return {
                'implied_growth': round(implied_growth * 100, 2),
                'earnings_yield': round(earnings_yield * 100, 2),
                'required_return': round(self.wacc * 100, 2),
                'growth_gap': round(growth_gap * 100, 2),
                'valuation_status': status,
                'reasonable_growth': round(reasonable_growth * 100, 2),
            }
        except Exception as e:
            logger.error(f"逆向DCF失败 {symbol}: {e}")
            return self._empty_result()

    def calc_margin_of_safety(self, symbol: str, basic_info: dict = None) -> dict:
        """计算安全边际。

        基于WACC和合理增长率计算内在PE，与当前PE对比得出安全边际。

        Args:
            symbol: 股票代码
            basic_info: 股票基本信息字典，需包含 price、pe_dynamic 字段

        Returns:
            dict: 包含以下字段的安全边际结果：
                - margin_of_safety: 安全边际(%)
                - intrinsic_pe: 内在PE
                - current_pe: 当前PE
        """
        try:
            price = float(basic_info.get('price', 0)) if basic_info else 0
            pe = float(basic_info.get('pe_dynamic', 0)) if basic_info else 0

            if price <= 0 or pe <= 0:
                return {'margin_of_safety': 0, 'intrinsic_pe': 0, 'current_pe': 0}

            intrinsic_value_multiple = 1.0 / max(0.01, self.wacc - 0.03)
            current_pe = pe
            intrinsic_pe = min(intrinsic_value_multiple, 25)

            margin = (intrinsic_pe / current_pe - 1) if current_pe > 0 else 0

            return {
                'margin_of_safety': round(margin * 100, 1),
                'intrinsic_pe': round(intrinsic_pe, 1),
                'current_pe': round(current_pe, 1),
            }
        except Exception as e:
            logger.error(f"安全边际计算失败 {symbol}: {e}")
            return {'margin_of_safety': 0, 'intrinsic_pe': 0, 'current_pe': 0}

    def _empty_result(self) -> dict:
        """返回数据不足时的空结果。

        Returns:
            dict: 包含默认零值的隐含增长结果字典
        """
        return {
            'implied_growth': 0,
            'earnings_yield': 0,
            'required_return': 0,
            'growth_gap': 0,
            'valuation_status': '数据不足',
            'reasonable_growth': 0,
        }
