"""
全局配置模块

集中管理所有路径、API参数、缓存策略等配置项。
使用 dataclass 确保类型安全和可维护性。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict


@dataclass
class Settings:
    """全局配置单例"""

    # ========== 路径配置 ==========
    PROJECT_ROOT: Path = field(default_factory=lambda: Path(__file__).parent.parent)
    DATA_DIR: Path = field(default_factory=lambda: Path(__file__).parent.parent / "data")
    CACHE_DIR: Path = field(default_factory=lambda: Path(__file__).parent.parent / "data" / "cache")
    DB_DIR: Path = field(default_factory=lambda: Path(__file__).parent.parent / "data" / "db")
    OUTPUT_DIR: Path = field(default_factory=lambda: Path(__file__).parent.parent / "output")
    LOG_DIR: Path = field(default_factory=lambda: Path(__file__).parent.parent / "logs")
    DB_PATH: Path = field(default_factory=lambda: Path(__file__).parent.parent / "data" / "db" / "golden_pit.db")

    # ========== 日志配置 ==========
    LOG_LEVEL: str = "INFO"
    LOG_MAX_BYTES: int = 10 * 1024 * 1024  # 10MB
    LOG_BACKUP_COUNT: int = 5

    # ========== API请求配置 ==========
    API_RETRY_COUNT: int = 3
    API_RETRY_DELAY: float = 1.0  # 初始延迟秒数
    API_RETRY_BACKOFF: float = 2.0  # 退避乘数
    API_TIMEOUT: int = 30  # 超时秒数
    API_MIN_INTERVAL: float = 0.5  # 最小请求间隔
    BATCH_SIZE: int = 50  # 批量请求大小

    # ========== 缓存配置 (秒) ==========
    CACHE_TTL: Dict[str, int] = field(default_factory=lambda: {
        "stock_list": 86400,  # 24小时
        "daily_quotes": 3600,  # 1小时
        "financial_data": 86400 * 7,  # 7天
        "valuation_data": 3600 * 4,  # 4小时
        "shareholder_data": 86400 * 30,  # 30天
    })

    # ========== 筛选参数 ==========
    DRAWDOWN_LOOKBACK: int = 250  # 52周(交易日)
    PE_PERCENTILE_YEARS: int = 5  # PE分位计算历史年数
    PE_MIN_DATA_POINTS: int = 20  # 最少数据点数
    MIN_MARKET_CAP: float = 50_0000_0000  # 最小市值50亿

    # ========== 排除规则 ==========
    EXCLUDE_ST: bool = True
    EXCLUDE_NEW_LISTING_DAYS: int = 365  # 上市不足1年排除
    EXCLUDED_INDUSTRIES: list = field(default_factory=list)

    # ========== 估值参数 ==========
    WACC_DEFAULT: float = 0.10  # 默认WACC
    TERMINAL_GROWTH_DEFAULT: float = 0.03  # 默认永续增长率
    FORECAST_YEARS: int = 10  # DCF预测年限
    RISK_FREE_RATE: float = 0.025  # 无风险利率（10年期国债近似）
    MARKET_RISK_PREMIUM: float = 0.06  # 市场风险溢价

    # ========== 评分权重 ==========
    SCORE_WEIGHTS: Dict[str, float] = field(default_factory=lambda: {
        "business_quality": 0.12,
        "competitive_advantage": 0.15,
        "demand_certainty": 0.12,
        "management": 0.08,
        "financial_quality": 0.10,
        "valuation_margin": 0.15,
        "odds": 0.12,
        "predictability": 0.06,
        "market_pessimism": 0.05,
        "reversal_verifiability": 0.05,
    })

    def __post_init__(self):
        """创建必要的目录"""
        for d in [
            self.DATA_DIR,
            self.CACHE_DIR,
            self.DB_DIR,
            self.OUTPUT_DIR,
            self.LOG_DIR,
        ]:
            d.mkdir(parents=True, exist_ok=True)


# 全局单例
settings = Settings()
