#!/usr/bin/env python3
"""Create and verify a recoverable SQLite backup without stopping readers."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def backup_database(source: str | Path, destination: str | Path) -> dict[str, object]:
    source_path = Path(source).resolve()
    destination_path = Path(destination).resolve()
    if not source_path.is_file():
        raise ValueError(f"源数据库不存在: {source_path}")
    if source_path == destination_path:
        raise ValueError("备份目标不能覆盖源数据库")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source_path, timeout=30) as source_db:
        with sqlite3.connect(destination_path, timeout=30) as destination_db:
            source_db.backup(destination_db)
    with sqlite3.connect(destination_path, timeout=30) as backup_db:
        integrity = str(backup_db.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise RuntimeError(f"备份完整性校验失败: {integrity}")
        tables = int(
            backup_db.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
        )
    digest = hashlib.sha256(destination_path.read_bytes()).hexdigest()
    return {
        "source": str(source_path),
        "destination": str(destination_path),
        "size_bytes": destination_path.stat().st_size,
        "sha256": digest,
        "integrity": integrity,
        "table_count": tables,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="备份并校验策略平台 SQLite 数据库")
    parser.add_argument("source")
    parser.add_argument("destination")
    args = parser.parse_args()
    print(json.dumps(backup_database(args.source, args.destination), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
