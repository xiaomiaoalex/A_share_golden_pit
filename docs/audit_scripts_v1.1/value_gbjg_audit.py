"""v1.1审计：stock_value_em + stock_zh_a_gbjg_em（第7-8项）"""
import warnings, logging, time, hashlib, json
warnings.filterwarnings('ignore')
logging.disable(logging.CRITICAL)
import akshare as ak
import pandas as pd

# ===== 第7项：stock_value_em =====
print('=== 第7项：stock_value_em ===')

# 测试不同市场样本
test_codes = {
    '沪主板': '600519',
    '深主板': '000651',
    '创业板': '300750',
    '科创板': '688981',
    '北交所': '835185',
}

value_results = {}
for label, code in test_codes.items():
    t0 = time.time()
    try:
        df = ak.stock_value_em(symbol=code)
        elapsed = time.time() - t0
        r = {
            'rows': len(df) if df is not None and not df.empty else 0,
            'columns': list(df.columns) if df is not None and not df.empty else [],
            'dtypes': {c: str(df[c].dtype) for c in df.columns} if df is not None and not df.empty else {},
            'elapsed_s': round(elapsed, 2),
            'earliest_date': str(df['日期'].min()) if df is not None and not df.empty and '日期' in df.columns else None,
            'latest_date': str(df['日期'].max()) if df is not None and not df.empty and '日期' in df.columns else None,
            'latest_row': df.iloc[-1].to_dict() if df is not None and not df.empty else None,
        }
        r['hash'] = hashlib.md5(str(r['columns']).encode()).hexdigest()[:8]
        value_results[label] = r
        print(f'  [{label}] {code}: {r["rows"]}r, {r["earliest_date"]}~{r["latest_date"]}, {elapsed:.1f}s')
        print(f'    列名: {r["columns"]}')
        if r['latest_row']:
            print(f'    末行: {r["latest_row"]}')
    except Exception as e:
        elapsed = time.time() - t0
        value_results[label] = {'error': f'{type(e).__name__}: {str(e)[:100]}'}
        print(f'  [{label}] {code}: FAIL ({elapsed:.1f}s) - {value_results[label]["error"]}')
    time.sleep(0.5)

# ===== 稳定性和日期匹配测试 =====
print('\n--- 日期匹配与连续性检查（茅台，近2年）---')
try:
    df = ak.stock_value_em(symbol='600519')
    df['日期'] = pd.to_datetime(df['日期'])
    recent = df[df['日期'] >= '2024-01-01']
    print(f'  近2年共 {len(recent)} 个交易日')
    gaps = recent['日期'].diff().dropna()
    large_gaps = gaps[gaps > pd.Timedelta(days=7)]
    if len(large_gaps) > 0:
        print(f'  ⚠ 发现超过7天的日期缺口: {len(large_gaps)} 处')
        for _, gap_row in large_gaps.reset_index().iterrows():
            idx = gap_row['index']
            print(f'    {recent.loc[recent["日期"]==idx-df.loc[idx-1,"日期"]].iloc[0] if False else "..."} ')
    else:
        print(f'  ✅ 无超过7天的日期缺口')
    
    # 检查关键字段
    key_cols = ['日期','总市值','流通市值','总股本','流通股本','市盈率-动态','市净率','收盘价']
    available = [c for c in key_cols if c in df.columns]
    missing = [c for c in key_cols if c not in df.columns]
    print(f'  关键字段可用: {available}')
    print(f'  关键字段缺失: {missing}')
    if '市盈率-动态' in df.columns:
        pe_valid = (df['市盈率-动态'] > 0) & (df['市盈率-动态'] < 200)
        print(f'  PE(TTM)有效值: {pe_valid.sum()}/{len(df)} ({pe_valid.sum()/len(df)*100:.1f}%)')
except Exception as e:
    print(f'  日期匹配检查失败: {e}')

time.sleep(2)

# ===== 第8项：stock_zh_a_gbjg_em =====
print('\n=== 第8项：stock_zh_a_gbjg_em（股本变更）===')
gb_results = {}
for label, code in test_codes.items():
    t0 = time.time()
    try:
        df = ak.stock_zh_a_gbjg_em(symbol=code)
        elapsed = time.time() - t0
        r = {
            'rows': len(df) if df is not None and not df.empty else 0,
            'columns': list(df.columns) if df is not None and not df.empty else [],
            'elapsed_s': round(elapsed, 2),
        }
        if df is not None and not df.empty:
            r['earliest'] = str(df.iloc[0].to_dict())
            r['latest'] = str(df.iloc[-1].to_dict())
            # 检查送转/增发/回购事件
            if '变动原因' in df.columns or '变更原因' in df.columns:
                reason_col = '变动原因' if '变动原因' in df.columns else '变更原因'
                events = df[df[reason_col].str.contains('送|转|增发|回购|回购注销', na=False)]
                r['events_count'] = len(events)
                r['events'] = events.head(5).to_dict('records')
        gb_results[label] = r
        print(f'  [{label}] {code}: {r["rows"]}r, {elapsed:.1f}s')
        print(f'    列名: {r["columns"]}')
        if r.get('events_count'):
            print(f'    送转/增发/回购事件: {r["events_count"]} 次')
    except Exception as e:
        elapsed = time.time() - t0
        gb_results[label] = {'error': f'{type(e).__name__}: {str(e)[:100]}'}
        print(f'  [{label}] {code}: FAIL ({elapsed:.1f}s) - {gb_results[label]["error"]}')
    time.sleep(0.5)

# 保存
with open('/tmp/value_gbjg_audit_v1.1.json', 'w') as f:
    json.dump({
        'stock_value_em': {k: v for k, v in value_results.items() if not k.startswith('_')},
        'stock_zh_a_gbjg_em': gb_results,
    }, f, ensure_ascii=False, indent=2, default=str)

print('\n结果已保存: /tmp/value_gbjg_audit_v1.1.json')
