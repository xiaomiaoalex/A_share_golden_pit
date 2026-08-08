"""v1.1b审计：北交所920代码重测 + financial_abstract来源和HTTP证据"""
import warnings, logging, hashlib, json, time, sys
from datetime import date, datetime, timedelta
warnings.filterwarnings('ignore')
logging.disable(logging.CRITICAL)
import akshare as ak
import pandas as pd
import requests

OUT = '/workspace/docs/audit_v1.1b'
LOG = f'{OUT}/logs'
ENV = {
    'ak_version': ak.__version__,
    'python': sys.version.split()[0],
    'test_time': datetime.now().isoformat(),
    'platform': sys.platform,
}
print(f"akshare: {ENV['ak_version']} | python: {ENV['python']}")

# ===== 1. 北交所920代码重测 (yjbb, 2025Q1) =====
print('\n=== 北交所920代码重测 ===')
BJ_NEW = [
    '920185','920402','920116','920002','920099','920111','920060','920011',
    '920066','920079','920058','920096','920076','920047','920017','920030',
    '920088','920026','920122','920033','920010','920128'
]
BJ_OLD_MAP = {'835185':'920185','838402':'920402'}

df2025q1 = ak.stock_yjbb_em(date='20250331')
print(f'2025Q1总行数: {len(df2025q1)}')
print(f'唯一代码数: {df2025q1["股票代码"].nunique()}')
dup = df2025q1[df2025q1.duplicated('股票代码', keep=False)]
print(f'重复代码数: {len(dup)}')
if len(dup) > 0:
    print(f'重复样本: {dup["股票代码"].tolist()[:5]}')
prefix_dist = df2025q1['股票代码'].str[:2].value_counts().to_dict()
print(f'代码前缀分布: {prefix_dist}')

bj_found = []
bj_missing = []
for code in BJ_NEW:
    r = df2025q1[df2025q1['股票代码'] == code]
    if not r.empty:
        bj_found.append(code)
    else:
        bj_missing.append(code)
print(f'北交所920命中: {len(bj_found)}/{len(BJ_NEW)} ({bj_found[:5]}...)')
print(f'北交所920缺失: {len(bj_missing)} ({bj_missing[:5]}...)')

# 旧代码验证
for old, new in BJ_OLD_MAP.items():
    r_old = df2025q1[df2025q1['股票代码'] == old]
    r_new = df2025q1[df2025q1['股票代码'] == new]
    print(f'  {old}→{new}: old={len(r_old)}, new={len(r_new)}')

# ===== 2. financial_abstract HTTP证据（来源确认）=====
print('\n=== financial_abstract HTTP证据 ===')
# 直接用requests抓取新浪财经URL，看返回状态
# stock_financial_abstract内部调用新浪
import requests
url_sina = 'https://vip.stock.finance.sina.com.cn/corp/go.php/vFD_FinanceSummary/stockid/000651/displaytype/4.phtml'
try:
    r = requests.get(url_sina, timeout=10)
    print(f'新浪财经 HTTP status: {r.status_code}')
    print(f'Content-Type: {r.headers.get("Content-Type","")}')
    print(f'响应体前200字符: {r.text[:200]}')
    with open(f'{LOG}/fa_sina_http.txt','w') as f:
        f.write(f'status={r.status_code}\ncontent_type={r.headers.get("Content-Type")}\nbody_200={r.text[:200]}')
except Exception as e:
    print(f'新浪财经请求错误: {e}')

# 实际测试financial_abstract并捕获完整异常
print('\n=== financial_abstract 5只样本逐请求日志 ===')
for sym in ['000651','600519','600036','300750','688981']:
    t0 = time.time()
    try:
        df = ak.stock_financial_abstract(symbol=sym)
        elapsed = time.time()-t0
        ok = df is not None and not df.empty
        print(f'  {sym}: OK({len(df) if ok else 0}r) {elapsed:.1f}s')
    except Exception as e:
        elapsed = time.time()-t0
        import traceback
        tb = traceback.format_exc()[:500]
        print(f'  {sym}: {type(e).__name__}({elapsed:.1f}s)')
        print(f'    traceback: {tb[:200]}')
        with open(f'{LOG}/fa_error_{sym}.txt','w') as f:
            f.write(f'error={type(e).__name__}\nmsg={str(e)[:200]}\ntb={tb}')

# ===== 3. yjbb 2025H1 解释为何11404行 =====
print('\n=== yjbb 2025H1 行数分析 ===')
df2025h1 = ak.stock_yjbb_em(date='20250630')
print(f'2025H1总行数: {len(df2025h1)}')
print(f'唯一代码: {df2025h1["股票代码"].nunique()}')
print(f'重复: {df2025h1.duplicated("股票代码").sum()}')
print(f'2025Q1行数: {len(df2025q1)}')
print(f'差值: {len(df2025h1)-len(df2025q1)}')
# 原因：2025H1包含已披露半年报的全部公司（含2025Q1已披露+新增中报），
# 以及同一公司可能有Q1和H1两条记录（这解释了11404>6018）

# 检查多记录公司
code_counts = df2025h1['股票代码'].value_counts()
multi = code_counts[code_counts > 1]
print(f'多记录代码数: {len(multi)}')
if len(multi) > 0:
    sample_code = multi.index[0]
    sample_rows = df2025h1[df2025h1['股票代码']==sample_code]
    print(f'  示例 {sample_code}: {len(sample_rows)}条')
    for _, r in sample_rows.iterrows():
        print(f'    公告:{r["最新公告日期"]} 营收:{r["营业总收入-营业总收入"]:,.0f} 净利:{r["净利润-净利润"]:,.0f}')

# ===== 4. stock_fhps_em 列数确认 =====
print('\n=== stock_fhps_em 列数确认 ===')
try:
    df_fh = ak.stock_fhps_em(date='20251231')
    print(f'列数: {len(df_fh.columns)}')
    print(f'列名: {list(df_fh.columns)}')
    # 保存完整列名
    json.dump({'columns': list(df_fh.columns), 'count': len(df_fh.columns)},
              open(f'{OUT}/fhps_em_columns.json','w'), ensure_ascii=False)
except Exception as e:
    print(f'FAIL: {e}')

# 环境信息保存
json.dump(ENV, open(f'{OUT}/env.json','w'), indent=2)
print(f'\n所有结果已保存至: {OUT}')
