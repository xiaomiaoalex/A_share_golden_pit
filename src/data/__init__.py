"""
A股黄金坑股票数据库 - 数据获取层。

提供统一的数据获取接口，包括：
- DataFetcher: 数据获取门面，统一调度多个数据源
- CacheManager: 本地缓存管理
"""

from .fetcher import DataFetcher
from .cache import CacheManager

__all__ = ["DataFetcher", "CacheManager"]
