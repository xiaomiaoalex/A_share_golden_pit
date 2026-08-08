"""赔率计算器。

计算风险回报比（赔率）、凯利仓位建议和回归均值赔率，
帮助判断投资的风险收益特征。
"""

import numpy as np
import logging
from typing import Dict

logger = logging.getLogger(__name__)


class OddsCalculator:
    """赔率计算器：计算风险回报比和仓位建议。

    基于三情景估值结果计算综合赔率（加权上涨空间/加权下跌空间），
    通过凯利公式给出仓位建议。
    """

    def __init__(self, scenario_valuation=None):
        """初始化赔率计算器。

        Args:
            scenario_valuation: ScenarioValuation 实例，用于获取情景估值结果
        """
        self.scenario_valuation = scenario_valuation

    def calc_odds_ratio(self, scenarios: dict) -> dict:
        """计算综合赔率。

        赔率 = 加权上涨空间 / 加权下跌空间。
        基于悲观、基准、乐观三种情景的概率加权计算。

        Args:
            scenarios: ScenarioValuation.build_scenarios() 的输出字典，
                      需包含 pessimistic、base、optimistic 三个情景

        Returns:
            dict: 包含以下字段的赔率结果：
                - odds_ratio: 赔率（加权上涨空间/下跌空间）
                - expected_return: 期望收益(%)
                - max_upside: 最大上涨空间(%)
                - max_downside: 最大下跌空间(%)
                - risk_reward_grade: 风险回报等级
                - kelly_position: 凯利公式建议仓位(%)
                - win_probability: 胜率(%)
        """
        try:
            pessimistic = scenarios.get('pessimistic', {})
            base = scenarios.get('base', {})
            optimistic = scenarios.get('optimistic', {})

            p_upside = pessimistic.get('upside_pct', 0)
            b_upside = base.get('upside_pct', 0)
            o_upside = optimistic.get('upside_pct', 0)

            p_prob = pessimistic.get('probability', 0.3)
            b_prob = base.get('probability', 0.5)
            o_prob = optimistic.get('probability', 0.2)

            # 下跌空间：取悲观情景下跌幅度，至少5%
            downside = abs(min(0, p_upside)) if p_upside < 0 else 5.0

            # 加权上涨空间（仅计正收益部分）
            weighted_upside = (
                max(0, p_upside) * p_prob + 
                max(0, b_upside) * b_prob + 
                max(0, o_upside) * o_prob
            )
            # 如果为零，使用基准和乐观情景
            if weighted_upside <= 0:
                weighted_upside = max(0, b_upside) * 0.6 + max(0, o_upside) * 0.4

            odds = weighted_upside / downside if downside > 0 else 3.0

            if odds >= 3:
                grade = '极高赔率'
            elif odds >= 2:
                grade = '高赔率'
            elif odds >= 1.5:
                grade = '中等赔率'
            elif odds >= 1:
                grade = '低赔率'
            else:
                grade = '不划算'

            win_prob = 1 - p_prob
            kelly = (
                (win_prob * odds - (1 - win_prob)) / odds if odds > 0 else 0
            )
            kelly = max(0, min(0.20, kelly))

            return {
                'odds_ratio': round(odds, 2),
                'expected_return': round(weighted_upside, 1),
                'max_upside': round(o_upside, 1),
                'max_downside': round(-downside, 1),
                'risk_reward_grade': grade,
                'kelly_position': round(kelly * 100, 1),
                'win_probability': round(win_prob * 100, 1),
            }
        except Exception as e:
            logger.error(f"赔率计算失败: {e}")
            return {
                'odds_ratio': 0,
                'expected_return': 0,
                'max_upside': 0,
                'max_downside': 0,
                'risk_reward_grade': '无法计算',
                'kelly_position': 0,
                'win_probability': 50,
            }

    def calc_recovery_odds(self, current_pe: float, historical_median_pe: float) -> float:
        """计算回归均值赔率。

        基于当前PE回归到历史中位数的潜在上涨空间。

        Args:
            current_pe: 当前PE
            historical_median_pe: 历史PE中位数

        Returns:
            float: 回归均值赔率（上涨空间百分比），无效输入返回0
        """
        if current_pe <= 0 or historical_median_pe <= 0:
            return 0
        return (historical_median_pe / current_pe - 1) * 100
