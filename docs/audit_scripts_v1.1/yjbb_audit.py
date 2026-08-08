"""v1.1审计：yjbb（业绩报表）多期 + 全覆盖测试"""
import warnings, logging, hashlib, json, time
from datetime import datetime
warnings.filterwarnings('ignore')
logging.disable(logging.CRITICAL)
import akshare as ak
import pandas as pd

ENV = {
    'ak_version': ak.__version__,
    'python': '3.11.1',
    'platform': 'Linux-6.6.117-45.11.3.tl4.x86_64',
    'test_time': datetime.now().isoformat(),
}
print(f"=== 环境 ===")
for k, v in ENV.items():
    print(f"  {k}: {v}")

# ===== 第2项：多报告期测试 =====
dates = {
    '2025Q1': '20250331',
    '2025H1': '20250630',
    '2026Q1': '20260331',
    '2026H1': '20260630',
}
results = {}

for label, dt in dates.items():
    t0 = time.time()
    try:
        df = ak.stock_yjbb_em(date=dt)
        elapsed = time.time() - t0
        h = hashlib.md5(str(df.shape).encode() + str(list(df.columns)).encode()).hexdigest()[:12]
        results[label] = {
            'rows': len(df),
            'cols': len(df.columns),
            'elapsed_s': round(elapsed, 1),
            'hash': h,
            'columns': list(df.columns),
            'sample_codes': df['股票代码'].head(5).tolist(),
        }
        print(f'\n[{label}] date={dt}: {len(df)}r x {len(df.columns)}c, {elapsed:.1f}s, hash={h}')
        print(f'  原始列名: {list(df.columns)}')
        print(f'  前5行代码: {df["股票代码"].head(5).tolist()}')
        print(f'  首行样本: {df.iloc[0].to_dict()}')
    except Exception as e:
        elapsed = time.time() - t0
        results[label] = {'error': f'{type(e).__name__}: {str(e)[:100]}', 'elapsed_s': round(elapsed, 1)}
        print(f'\n[{label}] FAIL ({elapsed:.1f}s): {results[label]["error"]}')
    time.sleep(2)

# ===== 第4项：全覆盖测试（沪深北、主板、创业板、科创板、ST、亏损、金融、非金融）=====
print('\n' + '='*60)
print('=== 第4项：yjbb 全覆盖验证（date=20250331）===')
print('='*60)

coverage_stocks = {
    '沪主板': ['600519','600036','601318','600585','600031','600900','601088','600276'],
    '深主板': ['000651','000002','000333','000858','000725','000001','002415','002230'],
    '创业板': ['300750','300059','300015','300124','300274','300433'],
    '科创板': ['688981','688012','688036','688111','688187'],
    '北交所': ['835185','838402'],
    '金融': ['600036','601318','601398','600016','000001'],
    '非金融': ['000651','600519','000333','002415','300750'],
    'ST': ['600518','002502','002052'],
    '亏损': ['000002','600023'],
}

df = ak.stock_yjbb_em(date='20250331')
if df is not None and not df.empty:
    # 原始schema指纹
    schema_fingerprint = {
        'columns': list(df.columns),
        'dtypes': {c: str(df[c].dtype) for c in df.columns},
        'row_count': len(df),
        'date': '20250331',
    }
    print(f'\nSchema指纹 (JSON): {json.dumps(schema_fingerprint, ensure_ascii=False, indent=2)}')
    
    for category, codes in coverage_stocks.items():
        found = []
        not_found = []
        for code in codes:
            row = df[df['股票代码'] == code]
            if not row.empty:
                r = row.iloc[0]
                np_val = r['净利润-净利润']
                rev_val = r['营业总收入-营业总收入']
                eps_val = r.get('每股收益', 'N/A')
                found.append(f'{code}(净利={np_val:,.0f},EPS={eps_val})')
            else:
                not_found.append(code)
        status = '✅' if not_found == [] else f'⚠ 缺失{len(not_found)}'
        print(f'  [{category}] {status}: {", ".join(found[:6])}')
        if not_found:
            print(f'    缺失: {not_found}')

# 保存结果
with open('/tmp/yjbb_audit_v1.1.json', 'w') as f:
    json.dump({
        'env': ENV,
        'multi_date_results': results,
        'schema_fingerprint': schema_fingerprint,
    }, f, ensure_ascii=False, indent=2, default=str)
print('\n结果已保存: /tmp/yjbb_audit_v1.1.json')
