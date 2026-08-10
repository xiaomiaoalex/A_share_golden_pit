"""
A股黄金坑股票数据库 - 数据获取层。

提供统一的数据获取接口，包括：
- DataFetcher: 数据获取门面，统一调度多个数据源
- CacheManager: 本地缓存管理
"""

__all__ = ["DataFetcher", "CacheManager"]


def __getattr__(name):
    """延迟加载旧数据门面，避免独立点时模块被可选数据源阻塞。"""
    if name == "DataFetcher":
        from .fetcher import DataFetcher

        return DataFetcher
    if name == "CacheManager":
        from .cache import CacheManager

        return CacheManager
    raise AttributeError(name)
