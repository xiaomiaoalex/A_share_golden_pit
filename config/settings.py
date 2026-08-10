"""Multi-strategy platform paths and logging configuration."""

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_db_path() -> Path:
    root = Path(__file__).parent.parent
    configured = os.environ.get("STRATEGY_PLATFORM_DB", "").strip()
    if configured:
        return Path(configured).expanduser()
    platform_db = root / "data" / "db" / "strategy_platform.db"
    legacy_db = root / "data" / "db" / "golden_pit.db"
    # Existing installations keep using their historical database automatically.
    return legacy_db if legacy_db.exists() and not platform_db.exists() else platform_db


@dataclass
class Settings:
    """全局配置单例"""

    # ========== 路径配置 ==========
    PROJECT_ROOT: Path = field(default_factory=lambda: Path(__file__).parent.parent)
    OUTPUT_DIR: Path = field(
        default_factory=lambda: Path(__file__).parent.parent / "output"
    )
    LOG_DIR: Path = field(default_factory=lambda: Path(__file__).parent.parent / "logs")
    DB_PATH: Path = field(default_factory=_default_db_path)

    # ========== 日志配置 ==========
    LOG_LEVEL: str = "INFO"

    def __post_init__(self):
        """创建必要的目录"""
        for d in [self.DB_PATH.parent, self.OUTPUT_DIR, self.LOG_DIR]:
            d.mkdir(parents=True, exist_ok=True)


# 全局单例
settings = Settings()
