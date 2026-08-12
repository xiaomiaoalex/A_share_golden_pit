#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ -x ".venv/bin/python" ]]; then
  platform_python=".venv/bin/python"
elif [[ -x "venv/bin/python" ]]; then
  platform_python="venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  platform_python="python3"
elif command -v python >/dev/null 2>&1; then
  platform_python="python"
else
  echo "[错误] 未找到 Python 3.10+。请先按 README 的‘快速开始’完成安装。" >&2
  exit 1
fi

echo "正在启动 A股多策略选股研究平台（前端 + 后端）..."
exec "$platform_python" web_app.py "$@"
