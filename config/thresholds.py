"""
三层筛选阈值定义

为三个筛选层级分别定义阈值参数。
支持行业差异化调整（金融行业使用PB/ROA替代PE/ROE）。
"""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class RadarThreshold:
    """第一层：黄金坑雷达池阈值"""

    # 盈利质量
    MIN_ROE: float = 0.10  # 近3年平均ROE > 10%
    MIN_ROA: float = 0.04  # 近3年平均ROA > 4%

    # 回撤
    MAX_DRAWDOWN: float = -0.30  # 从52周高点最大回撤 > 30%

    # 估值分位
    MAX_PE_PERCENTILE: float = 0.30  # PE历史分位 < 30%
    MAX_PB_PERCENTILE: float = 0.40  # PB历史分位 < 40%

    # 规模
    MIN_MARKET_CAP: float = 50_0000_0000  # 最小市值50亿

    # 排除
    EXCLUDE_ST: bool = True
    EXCLUDE_NEW_LISTING_DAYS: int = 365


@dataclass
class DeepScreenThreshold:
    """第二层：深度观察池阈值"""

    # 自由现金流质量
    MIN_FCF_YIELD: float = 0.03  # FCF/市值 > 3%
    MIN_FCF_NI_RATIO: float = 0.50  # 经营现金流/净利润 > 50%

    # 资本回报
    MIN_ROIC: float = 0.12  # ROIC > 12%

    # 商誉风险
    MAX_GOODWILL_EQUITY: float = 0.30  # 商誉/净资产 < 30%

    # 质押风险
    MAX_PLEDGE_RATIO: float = 0.50  # 大股东质押率 < 50%

    # 应收账款异常
    MAX_AR_GROWTH_DEV: float = 0.20  # 应收增速偏离营收增速 < 20pp

    # 负债
    MAX_DEBT_EQUITY: float = 2.0  # 有息负债/权益 < 2.0

    # 毛利率稳定性
    MIN_GROSS_MARGIN_STABILITY: float = 0.60  # 毛利率稳定性 > 60%（3年变异系数倒数归一化）

    # 分红
    MIN_DIVIDEND_STABILITY: float = 0.50  # 近3年至少2年有分红


@dataclass
class CoreConfirmThreshold:
    """第三层：核心黄金坑阈值"""

    # 护城河评分
    MIN_MOAT_SCORE: int = 4  # 竞争优势评分 >= 4/5

    # 赔率
    MIN_ODDS_RATIO: float = 2.0  # 赔率 >= 2:1（上涨空间:下跌空间）

    # 置信度
    MIN_CONFIDENCE: float = 0.70  # 综合置信度 >= 70%

    # 安全边际
    MIN_MARGIN_OF_SAFETY: float = 0.30  # 安全边际 >= 30%

    # 最大仓位
    MAX_POSITION_PCT: float = 0.20  # 单只股票最大仓位20%


# ========== 行业差异化调整 ==========

# 金融行业：使用PB/ROA替代PE/ROE
FINANCIAL_INDUSTRIES: List[str] = [
    "银行",
    "非银金融",
]

# 周期行业：使用周期调整PE（席勒PE）
CYCLICAL_INDUSTRIES: List[str] = [
    "钢铁",
    "煤炭",
    "有色金属",
    "石油石化",
    "基础化工",
]

# 行业特殊调整参数
INDUSTRY_ADJUSTMENTS: Dict[str, Dict] = {
    "银行": {
        "use_pb_instead_pe": True,
        "min_roe_override": 0.12,
        "min_roa_override": 0.008,
        "exclude_high_leverage_check": True,
    },
    "非银金融": {
        "use_pb_instead_pe": True,
        "min_roe_override": 0.10,
        "exclude_high_leverage_check": True,
    },
    "医药生物": {
        "min_roic_override": 0.10,
        "max_goodwill_equity_override": 0.25,
    },
    "电子": {
        "min_roic_override": 0.10,
        "max_capex_revenue_override": 0.15,
    },
    "计算机": {
        "max_goodwill_equity_override": 0.25,
        "max_capex_revenue_override": 0.10,
    },
}


def get_industry_threshold(industry: str, threshold_type: str = "deep") -> dict:
    """根据行业获取差异化阈值

    Args:
        industry: 申万一级行业名称
        threshold_type: 阈值类型 ('deep' 或 'core')

    Returns:
        调整后的阈值参数字典
    """
    base = INDUSTRY_ADJUSTMENTS.get(industry, {})
    return base
