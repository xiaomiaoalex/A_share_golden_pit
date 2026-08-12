#!/bin/bash
# A股多策略选股研究平台安装脚本

set -e

echo "=========================================="
echo "  A股多策略选股研究平台 - 安装程序"
echo "=========================================="

if command -v python3 &> /dev/null; then
    PYTHON=python3
elif command -v python &> /dev/null; then
    PYTHON=python
else
    echo "[ERROR] 未找到 Python 3.10+"
    exit 1
fi

if ! "$PYTHON" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
    echo "[ERROR] 需要 Python 3.10+"
    exit 1
fi

read -p "是否创建虚拟环境（推荐）？[Y/n] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    if [ ! -d "venv" ]; then
        "$PYTHON" -m venv venv
    fi
    if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
        source venv/Scripts/activate
    else
        source venv/bin/activate
    fi
    PYTHON=python
fi

"$PYTHON" -m pip install --upgrade pip -q
"$PYTHON" -m pip install -r requirements.txt -q
"$PYTHON" main.py strategy golden-pit tier3-migrate
"$PYTHON" deploy_check.py

cat > run.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
if [ -d "venv" ]; then
    source venv/bin/activate
fi
python main.py "$@"
EOF
chmod +x run.sh

cat > run.bat << 'EOF'
@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist venv\Scripts\activate.bat call venv\Scripts\activate.bat
python main.py %*
EOF

echo
echo "安装完成。正式入口："
echo "  ./start.sh  # 一键启动前端与后端"
echo "  ./run.sh strategy golden-pit workflow --as-of YYYY-MM-DD --symbols 000651"
echo "  ./run.sh strategy golden-pit workflow --run-id RUN_ID"
