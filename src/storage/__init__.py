"""
存储层模块 - A股黄金坑股票数据库持久化存储层。

提供数据库管理、ORM模型定义和数据访问对象。
"""

__all__ = [
    "DatabaseManager",
    "Base",
    "Stock",
    "FinancialData",
    "ValuationSnapshot",
    "ScreeningResult",
    "RiskCheckResult",
]


def __getattr__(name):
    """延迟加载旧ORM；Tier1 v2的sqlite仓储不依赖SQLAlchemy。"""
    if name == "DatabaseManager":
        from .database import DatabaseManager

        return DatabaseManager
    model_names = {
        "Base",
        "Stock",
        "FinancialData",
        "ValuationSnapshot",
        "ScreeningResult",
        "RiskCheckResult",
    }
    if name in model_names:
        from . import models

        return getattr(models, name)
    raise AttributeError(name)
