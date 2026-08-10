"""正式 Stage A/B/C 工作流的路径与日志配置。"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    """全局配置单例"""

    # ========== 路径配置 ==========
    PROJECT_ROOT: Path = field(default_factory=lambda: Path(__file__).parent.parent)
    OUTPUT_DIR: Path = field(default_factory=lambda: Path(__file__).parent.parent / "output")
    LOG_DIR: Path = field(default_factory=lambda: Path(__file__).parent.parent / "logs")
    DB_PATH: Path = field(default_factory=lambda: Path(__file__).parent.parent / "data" / "db" / "golden_pit.db")

    # ========== 日志配置 ==========
    LOG_LEVEL: str = "INFO"

    def __post_init__(self):
        """创建必要的目录"""
        for d in [self.DB_PATH.parent, self.OUTPUT_DIR, self.LOG_DIR]:
            d.mkdir(parents=True, exist_ok=True)


# 全局单例
settings = Settings()
