#!/usr/bin/env python3
"""Start the local A-share multi-strategy research platform."""

import argparse

from config.settings import settings
from src.web import run_server


def main() -> None:
    parser = argparse.ArgumentParser(description="A股多策略选股研究平台")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", default=8765, type=int, help="监听端口")
    parser.add_argument("--db", default=str(settings.DB_PATH), help="SQLite 数据库路径")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()
    run_server(args.db, args.host, args.port, not args.no_browser)


if __name__ == "__main__":
    main()
