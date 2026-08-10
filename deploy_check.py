#!/usr/bin/env python3
"""A股黄金坑股票数据库 - 部署自检脚本

验证系统依赖、数据库初始化、核心功能是否正常。
"""

import sys
import warnings
warnings.filterwarnings('ignore')

def check_python():
    """检查Python版本"""
    v = sys.version_info
    print(f"  Python {v.major}.{v.minor}.{v.micro}")
    if v.major < 3 or (v.major == 3 and v.minor < 10):
        print("  [FAIL] 需要 Python 3.10+")
        return False
    print("  [OK]")
    return True

def check_deps():
    """检查核心依赖"""
    required = {
        'pandas': 'pandas',
        'numpy': 'numpy',
        'akshare': 'akshare',
        'baostock': 'baostock',
        'sqlalchemy': 'sqlalchemy',
        'openpyxl': 'openpyxl',
        'matplotlib': 'matplotlib',
    }
    all_ok = True
    for mod, pkg in required.items():
        try:
            __import__(mod)
            print(f"  [OK] {pkg}")
        except ImportError:
            print(f"  [MISSING] {pkg} — pip install {pkg}")
            all_ok = False
    return all_ok

def check_db():
    """检查数据库初始化"""
    try:
        from config.settings import settings
        from src.storage.database import DatabaseManager
        db = DatabaseManager(settings.DB_PATH)
        db.initialize()
        stats = db.get_statistics()
        print(f"  [OK] 数据库已初始化 ({settings.DB_PATH})")
        print(f"       表: stocks={stats['stocks']}, screening={stats['screening_results']}")
        return True
    except Exception as e:
        print(f"  [FAIL] 数据库初始化失败: {e}")
        return False

def check_akshare():
    """检查AKShare数据源"""
    try:
        import akshare as ak
        print("  [OK] akshare 已安装")
        
        # 快速测试一个接口
        import logging
        logging.disable(logging.CRITICAL)
        
        # 测试 stock_info_a_code_name（最稳定）
        try:
            df = ak.stock_info_a_code_name()
            if df is not None and not df.empty:
                print(f"  [OK] stock_info_a_code_name: {len(df)} 只")
            else:
                print("  [WARN] stock_info_a_code_name 返回空数据")
        except Exception as e:
            print(f"  [WARN] stock_info_a_code_name 不可用: {str(e)[:60]}")
        
        # 测试 stock_zh_a_spot_em
        try:
            df = ak.stock_zh_a_spot_em()
            if df is not None and not df.empty:
                print(f"  [OK] stock_zh_a_spot_em: {len(df)} 只 (东财源)")
        except Exception:
            print("  [WARN] stock_zh_a_spot_em 不可用（将使用备用源）")
        
        # 测试 yjbb
        try:
            df = ak.stock_yjbb_em(date='20250331')
            if df is not None and not df.empty:
                print(f"  [OK] stock_yjbb_em: {len(df)} 条业绩快报")
        except Exception:
            print("  [WARN] stock_yjbb_em 不可用")
        
        return True
    except ImportError:
        print("  [FAIL] akshare 未安装")
        return False

def check_baostock():
    """检查baostock"""
    try:
        import baostock as bs
        lg = bs.login()
        if lg.error_code == '0':
            print(f"  [OK] baostock 登录成功")
            bs.logout()
            return True
        else:
            print(f"  [WARN] baostock 登录失败: {lg.error_msg}")
            return False
    except Exception as e:
        print(f"  [WARN] baostock 异常: {e}")
        return False

def main():
    print("=" * 50)
    print("  A股黄金坑股票数据库 — 部署自检")
    print("=" * 50)
    
    checks = [
        ("Python 版本", check_python),
        ("核心依赖", check_deps),
        ("数据库初始化", check_db),
        ("AKShare 数据源", check_akshare),
        ("baostock 数据源", check_baostock),
    ]
    
    results = {}
    for name, func in checks:
        print(f"\n[{name}]")
        results[name] = func()
    
    print("\n" + "=" * 50)
    print("  自检结果")
    print("=" * 50)
    
    all_pass = True
    for name, passed in results.items():
        status = "[OK]" if passed else "[FAIL]"
        print(f"  {status} {name}")
        if not passed:
            all_pass = False
    
    print()
    if all_pass:
        print("  系统就绪！运行: python main.py workflow --help")
    else:
        print("  部分检查未通过，请先安装缺失的依赖:")
        print("  pip install -r requirements.txt")
    
    print("=" * 50)

if __name__ == '__main__':
    main()
