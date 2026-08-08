"""综合评分聚合器"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)


class ScoreAggregator:
    """综合评分聚合器：聚合10维度评分，给出仓位和概率建议"""

    def __init__(self, settings=None):
        """初始化聚合器

        Args:
            settings: 配置对象，可包含 SCORE_WEIGHTS 字典自定义权重
        """
        self.settings = settings
        self.weights = getattr(settings, 'SCORE_WEIGHTS', {
            'business_quality': 0.12,
            'competitive_advantage': 0.15,
            'demand_certainty': 0.12,
            'management': 0.08,
            'financial_quality': 0.10,
            'valuation_margin': 0.15,
            'odds': 0.12,
            'predictability': 0.06,
            'market_pessimism': 0.05,
            'reversal_verifiability': 0.05,
        }) if settings else {
            'business_quality': 0.12,
            'competitive_advantage': 0.15,
            'demand_certainty': 0.12,
            'management': 0.08,
            'financial_quality': 0.10,
            'valuation_margin': 0.15,
            'odds': 0.12,
            'predictability': 0.06,
            'market_pessimism': 0.05,
            'reversal_verifiability': 0.05,
        }

    def aggregate(self, scores: Dict[str, float], odds_ratio: float = 1.0,
                  confidence: float = 0.5) -> dict:
        """聚合10维度评分，输出综合投资建议

        根据加权总分、赔率和置信度，给出概率判断、周期判断、
        仓位适配度和综合评级。

        Args:
            scores: 10维度评分字典，键为维度名，值为0-10的分数
            odds_ratio: 赔率（预期收益/预期损失）
            confidence: 置信度（0-1之间）

        Returns:
            {
                'total_score': float,           # 加权总分
                'probability': str,             # 概率：高/中/低
                'odds_level': str,              # 赔率：极高/高/中/低
                'cycle': str,                   # 周期：短/中/长
                'position_type': str,           # 仓位适配度：核心仓/中仓/小仓/观察
                'position_pct': float,          # 建议仓位占比
                'rating': str,                  # 综合评级：S/A/B/C
            }
        """
        try:
            # 加权总分
            total = 0.0
            weight_sum = 0.0
            for dim, score in scores.items():
                w = self.weights.get(dim, 0.1)
                total += score * w
                weight_sum += w

            total_score = total / weight_sum if weight_sum > 0 else 5.0

            # 概率判断
            if total_score >= 7.5:
                probability = '高'
            elif total_score >= 5.5:
                probability = '中'
            else:
                probability = '低'

            # 赔率等级
            if odds_ratio >= 3.0:
                odds_level = '极高'
            elif odds_ratio >= 2.0:
                odds_level = '高'
            elif odds_ratio >= 1.5:
                odds_level = '中'
            else:
                odds_level = '低'

            # 周期判断
            valuation_score = scores.get('valuation_margin', 5)
            pessimism_score = scores.get('market_pessimism', 5)
            if valuation_score >= 8 and pessimism_score >= 7:
                cycle = '长周期底部'
            elif valuation_score >= 6:
                cycle = '中周期'
            else:
                cycle = '短周期'

            # 仓位适配度
            if total_score >= 8 and odds_ratio >= 2.5 and confidence >= 0.8:
                position_type = '核心仓'
                position_pct = 0.20
            elif total_score >= 7 and odds_ratio >= 2.0 and confidence >= 0.7:
                position_type = '中仓'
                position_pct = 0.12
            elif total_score >= 6 and odds_ratio >= 1.5 and confidence >= 0.6:
                position_type = '小仓'
                position_pct = 0.06
            else:
                position_type = '观察'
                position_pct = 0.03

            # 综合评级 S/A/B/C
            if total_score >= 8.5 and odds_ratio >= 3.0 and confidence >= 0.85:
                rating = 'S'
            elif total_score >= 7.0 and odds_ratio >= 2.0 and confidence >= 0.7:
                rating = 'A'
            elif total_score >= 5.5 and odds_ratio >= 1.5:
                rating = 'B'
            else:
                rating = 'C'

            return {
                'total_score': round(total_score, 1),
                'probability': probability,
                'odds_level': odds_level,
                'cycle': cycle,
                'position_type': position_type,
                'position_pct': round(position_pct, 2),
                'rating': rating,
                'confidence': round(confidence, 2),
            }
        except Exception as e:
            logger.error(f"评分聚合失败: {e}")
            return {
                'total_score': 5.0, 'probability': '中', 'odds_level': '中',
                'cycle': '中周期', 'position_type': '观察', 'position_pct': 0.03,
                'rating': 'C', 'confidence': 0.5,
            }
