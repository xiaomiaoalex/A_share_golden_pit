#!/bin/bash
# A股黄金坑股票数据库 - 一键安装脚本
# 支持 Linux / macOS / Windows(WSL)

set -e

echo "=========================================="
echo "  A股黄金坑股票数据库 - 安装程序"
echo "=========================================="
echo ""

# 检测Python版本
check_python() {
    if command -v python3 &> /dev/null; then
        PYTHON=python3
    elif command -v python &> /dev/null; then
        PYTHON=python
    else
        echo "[ERROR] 未找到 Python，请先安装 Python 3.10+"
        exit 1
    fi
    
    VERSION=$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    MAJOR=$($PYTHON -c 'import sys; print(sys.version_info.major)')
    MINOR=$($PYTHON -c 'import sys; print(sys.version_info.minor)')
    
    echo "[INFO] 检测到 Python $VERSION"
    
    if [ "$MAJOR" -lt 3 ] || ([ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 10 ]); then
        echo "[ERROR] 需要 Python 3.10 或更高版本，当前为 $VERSION"
        exit 1
    fi
}

# 创建虚拟环境（推荐）
setup_venv() {
    echo ""
    echo "[INFO] 创建虚拟环境..."
    if [ ! -d "venv" ]; then
        $PYTHON -m venv venv
        echo "[INFO] 虚拟环境创建完成: venv/"
    else
        echo "[INFO] 虚拟环境已存在"
    fi
    
    # 激活虚拟环境
    if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
        source venv/Scripts/activate
    else
        source venv/bin/activate
    fi
    
    PYTHON=python
    echo "[INFO] 已激活虚拟环境"
}

# 安装依赖
install_deps() {
    echo ""
    echo "[INFO] 安装依赖包..."
    pip install --upgrade pip -q
    pip install -r requirements.txt -q
    
    echo ""
    echo "[INFO] 验证关键依赖..."
    python -c "
import sys
required = {
    'pandas': 'pandas',
    'numpy': 'numpy',
    'akshare': 'akshare',
    'baostock': 'baostock',
    'sqlalchemy': 'sqlalchemy',
    'openpyxl': 'openpyxl',
}
missing = []
for mod, pkg in required.items():
    try:
        __import__(mod)
        print(f'  [OK] {pkg}')
    except ImportError:
        missing.append(pkg)
        print(f'  [MISSING] {pkg}')
if missing:
    print(f'\\n[ERROR] 以下依赖安装失败: {missing}')
    sys.exit(1)
"
    
    if [ $? -ne 0 ]; then
        echo "[ERROR] 依赖安装不完整，请检查网络或手动安装"
        exit 1
    fi
}

# 初始化数据库
init_db() {
    echo ""
    echo "[INFO] 初始化数据库..."
    python -c "
import sys
sys.path.insert(0, '.')
from config.settings import settings
from src.storage.database import DatabaseManager
db = DatabaseManager(settings.DB_PATH)
db.initialize()
print(f'  [OK] 数据库已初始化: {settings.DB_PATH}')
"
}

# 创建快捷启动脚本
create_scripts() {
    echo ""
    echo "[INFO] 创建快捷启动脚本..."
    
    # Linux/macOS 启动脚本
    cat > run.sh << 'EOF'
#!/bin/bash
# 黄金坑数据库快捷启动脚本

cd "$(dirname "$0")"

if [ -d "venv" ]; then
    source venv/bin/activate
fi

case "${1:-help}" in
    workflow)
        shift
        python main.py workflow "$@"
        ;;
    legacy-scan)
        shift
        python main.py legacy-scan --i-understand-this-uses-legacy-rules "$@"
        ;;
    stock)
        if [ -z "$2" ]; then
            echo "用法: ./run.sh stock <股票代码>"
            echo "示例: ./run.sh stock 000651"
            exit 1
        fi
        python main.py stock "$2"
        ;;
    show)
        TIER=${2:-3}
        echo "查看 Tier$TIER 结果..."
        python main.py show --tier "$TIER"
        ;;
    report)
        echo "生成报告..."
        python main.py report
        ;;
    stats)
        echo "数据库统计..."
        python main.py stats
        ;;
    help|*)
        echo "A股黄金坑股票数据库 - 使用帮助"
        echo ""
        echo "命令:"
        echo "  ./run.sh workflow --as-of YYYY-MM-DD [--symbols ...]  启动正式工作流"
        echo "  ./run.sh workflow --run-id RUN_ID                    检查正式工作流"
        echo "  ./run.sh legacy-scan                                 兼容旧算法"
        echo "  ./run.sh stock 000651  单股票深度分析"
        echo "  ./run.sh show [1|2|3]  查看筛选结果（默认Tier3）"
        echo "  ./run.sh report    生成Excel报告和HTML仪表盘"
        echo "  ./run.sh stats     数据库统计信息"
        echo ""
        echo "示例:"
        echo "  ./run.sh workflow --as-of 2026-08-10 --symbols 000651"
        echo "  ./run.sh stock 000651      # 分析格力电器"
        echo "  ./run.sh show 2            # 查看观察池"
        ;;
esac
EOF
    chmod +x run.sh
    
    # Windows 批处理
    cat > run.bat << 'EOF'
@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

if "%1"=="" goto help
if "%1"=="workflow" goto workflow
if "%1"=="legacy-scan" goto legacy_scan
if "%1"=="stock" goto stock
if "%1"=="show" goto show
if "%1"=="report" goto report
if "%1"=="stats" goto stats
goto help

:workflow
python main.py workflow %2 %3 %4 %5 %6 %7 %8 %9
goto end

:legacy_scan
python main.py legacy-scan --i-understand-this-uses-legacy-rules %2 %3 %4 %5 %6 %7 %8 %9
goto end

:stock
if "%2"=="" (
    echo 用法: run.bat stock ^<股票代码^>
    echo 示例: run.bat stock 000651
    goto end
)
python main.py stock %2
goto end

:show
if "%2"=="" (set TIER=3) else (set TIER=%2)
echo 查看 Tier%TIER% 结果...
python main.py show --tier %TIER%
goto end

:report
echo 生成报告...
python main.py report
goto end

:stats
echo 数据库统计...
python main.py stats
goto end

:help
echo A股黄金坑股票数据库 - 使用帮助
echo.
echo 命令:
echo   run.bat workflow --as-of YYYY-MM-DD --symbols 000651
echo   run.bat workflow --run-id RUN_ID
echo   run.bat legacy-scan  兼容旧算法
echo   run.bat stock 000651  单股票深度分析
echo   run.bat show [1^|2^|3]  查看筛选结果
echo   run.bat report    生成报告
echo   run.bat stats     数据库统计
echo.

:end
pause
EOF
    
    echo "  [OK] run.sh (Linux/macOS)"
    echo "  [OK] run.bat (Windows)"
}

# 主流程
main() {
    check_python
    
    # 询问是否使用虚拟环境
    echo ""
    read -p "是否创建虚拟环境（推荐）？[Y/n] " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        setup_venv
    fi
    
    install_deps
    init_db
    create_scripts
    
    echo ""
    echo "=========================================="
    echo "  安装完成！"
    echo "=========================================="
    echo ""
    echo "使用方法:"
    echo "  ./run.sh workflow --as-of 2026-08-10 --symbols 000651"
    echo "  ./run.sh stock 000651  # 分析单只股票"
    echo "  ./run.sh show 3      # 查看核心黄金坑"
    echo "  ./run.sh help        # 查看所有命令"
    echo ""
    echo "或使用 Python 直接运行:"
    echo "  python main.py workflow --as-of 2026-08-10 --symbols 000651"
    echo "  python main.py stock 000651"
    echo ""
}

main "$@"
