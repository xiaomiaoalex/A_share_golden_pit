"""
数据源适配器模块。

提供多数据源统一接口：
- AKShareProvider: AKShare 主数据源
- BaostockProvider: baostock 备用数据源
"""

from .akshare_provider import AKShareProvider
from .baostock_provider import BaostockProvider

__all__ = ["AKShareProvider", "BaostockProvider"]
