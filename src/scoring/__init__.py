"""A股黄金坑股票数据库 - 评分体系模块"""

from .dimensions import DimensionScorer
from .aggregator import ScoreAggregator

__all__ = ["DimensionScorer", "ScoreAggregator"]
