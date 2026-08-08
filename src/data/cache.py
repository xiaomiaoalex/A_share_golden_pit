"""
本地缓存管理模块。

使用 pickle 序列化实现本地文件缓存，支持 TTL 过期管理和模式匹配失效。
"""

import pickle
import hashlib
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta

import pandas as pd

logger = logging.getLogger(__name__)


class CacheManager:
    """本地缓存管理器。

    使用 pickle 序列化数据到本地文件，支持 TTL 过期机制。
    缓存文件以 key 的 MD5 hash 命名，存储在 cache_dir 目录下。
    """

    def __init__(self, cache_dir: str = None, default_ttl: int = 3600):
        """初始化缓存管理器。

        Args:
            cache_dir: 缓存文件存储目录，默认为 ~/.golden_pit_cache
            default_ttl: 默认过期时间（秒），默认 3600 秒（1小时）
        """
        self.cache_dir = Path(cache_dir or Path.home() / ".golden_pit_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl = default_ttl

    def _key_to_path(self, key: str) -> Path:
        """将缓存 key 转换为文件路径（使用 MD5 hash）。"""
        key_hash = hashlib.md5(key.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{key_hash}.pkl"

    def get(self, key: str) -> Optional[pd.DataFrame]:
        """从缓存中获取数据。

        Args:
            key: 缓存键

        Returns:
            缓存的数据，如果不存在或已过期则返回 None
        """
        file_path = self._key_to_path(key)
        if not file_path.exists():
            return None

        try:
            with open(file_path, "rb") as f:
                cache_entry = pickle.load(f)

            expire_at = cache_entry.get("expire_at")
            if expire_at is not None and datetime.now() > expire_at:
                file_path.unlink(missing_ok=True)
                return None

            return cache_entry.get("data")
        except (pickle.PickleError, EOFError, KeyError) as e:
            logger.warning(f"读取缓存失败 {key}: {e}")
            file_path.unlink(missing_ok=True)
            return None

    def set(self, key: str, data, ttl: int = None) -> None:
        """将数据写入缓存。

        Args:
            key: 缓存键
            data: 要缓存的数据（支持 DataFrame、dict 等可 pickle 对象）
            ttl: 过期时间（秒），None 则使用默认 TTL
        """
        file_path = self._key_to_path(key)
        expire_seconds = ttl if ttl is not None else self.default_ttl
        expire_at = datetime.now() + timedelta(seconds=expire_seconds)

        cache_entry = {
            "key": key,
            "data": data,
            "expire_at": expire_at,
            "created_at": datetime.now(),
            "ttl": expire_seconds,
        }

        try:
            with open(file_path, "wb") as f:
                pickle.dump(cache_entry, f)
        except (pickle.PickleError, OSError) as e:
            logger.error(f"写入缓存失败 {key}: {e}")

    def invalidate(self, key: str) -> bool:
        """使指定 key 的缓存失效。

        Args:
            key: 缓存键

        Returns:
            是否成功删除
        """
        file_path = self._key_to_path(key)
        if file_path.exists():
            try:
                file_path.unlink()
                return True
            except OSError as e:
                logger.error(f"删除缓存文件失败 {key}: {e}")
        return False

    def invalidate_pattern(self, pattern: str) -> int:
        """使匹配模式的所有缓存失效。

        仅支持简单字符串包含匹配（pattern in filename）。

        Args:
            pattern: 匹配模式（用于文件名匹配）

        Returns:
            删除的缓存文件数量
        """
        count = 0
        for cache_file in self.cache_dir.glob("*.pkl"):
            try:
                with open(cache_file, "rb") as f:
                    entry = pickle.load(f)
                if pattern in entry.get("key", ""):
                    cache_file.unlink()
                    count += 1
            except (pickle.PickleError, EOFError, OSError):
                cache_file.unlink(missing_ok=True)
                count += 1
        return count

    def clear_all(self) -> int:
        """清除所有缓存。

        Returns:
            删除的缓存文件数量
        """
        count = 0
        for cache_file in self.cache_dir.glob("*.pkl"):
            try:
                cache_file.unlink()
                count += 1
            except OSError:
                pass
        return count

    def get_cache_stats(self) -> dict:
        """获取缓存统计信息。

        Returns:
            包含缓存文件数量、总大小、过期/有效文件数的字典
        """
        total_files = 0
        total_size = 0
        expired_count = 0
        valid_count = 0

        for cache_file in self.cache_dir.glob("*.pkl"):
            total_files += 1
            try:
                total_size += cache_file.stat().st_size
                with open(cache_file, "rb") as f:
                    entry = pickle.load(f)
                expire_at = entry.get("expire_at")
                if expire_at and datetime.now() > expire_at:
                    expired_count += 1
                else:
                    valid_count += 1
            except (pickle.PickleError, EOFError, OSError):
                expired_count += 1

        return {
            "total_files": total_files,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "valid_count": valid_count,
            "expired_count": expired_count,
            "cache_dir": str(self.cache_dir),
        }
