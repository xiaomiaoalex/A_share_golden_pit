"""数据源实测：关键口径验证"""
import warnings, logging, json, hashlib, time
warnings.filterwarnings('ignore')
logging.disable(logging.CRITICAL)
import akshare as ak

def test(name, func, **kwargs):
    start = time.time()
    try:
        df = func(**kwargs)
        elapsed = time.time() - start
        if df is None:
            print(f'[{name}] None ({elapsed:.1f}s)')
            return None, elapsed, None
        h = hashlib.md5(str(df.shape).encode()).hexdigest()[:8]
        print(f'[{name}] {len(df)}r x {len(df.columns)}c ({elapsed:.1f}s) hash={h}')
        print(f'  cols={list(df.columns)}')
        return df, elapsed, h
    except Exception as e:
        elapsed = time.time() - start
        print(f'[{name}] FAIL ({elapsed:.1f}s): {type(e).__name__}: {str(e)[:80]}')
        return None, elapsed, str(e)[:80]

# ===== 关键1: yjbb 净利润 是否归母口径？抽样验证 =====
print('===== 1. yjbb 净利润 vs financial_abstract 归母净利润 交叉验证 =====')
yjbb_q1, _, _ = test('yjbb_em(20250331)', ak.stock_yjbb_em, date='20250331')
time.sleep(2)

# 抽样5只: 格力000651 茅台600519 招行600036 万科000002 平安601318
test_symbols = ['000651', '600519', '600036', '000002', '601318']
for sym in test_symbols:
    # yjbb
    if yjbb_q1 is not None:
        row = yjbb_q1[yjbb_q1['股票代码'] == sym]
        if not row.empty:
            yj_np = row.iloc[0]['净利润-净利润']
            yj_rev = row.iloc[0]['营业总收入-营业总收入']
            print(f'  {sym}: yjbb 净利润={yj_np:,.0f}  营收={yj_rev:,.0f}')
    
    # financial_abstract
    try:
        fa = ak.stock_financial_abstract(symbol=sym)
        if fa is not None and not fa.empty:
            # 找2025Q1的归母净利润
            q1_col = None
            for c in fa.columns:
                if '20250331' in c:
                    q1_col = c
                    break
            if q1_col:
                guimu_row = fa[fa['指标'] == '归母净利润']
                jingli_row = fa[fa['指标'] == '净利润']
                if not guimu_row.empty:
                    guimu_np = guimu_row[q1_col].iloc[0]
                    print(f'       financial_abstract 归母净利润={guimu_np:,.0f}', end='')
                    if yjbb_q1 is not None:
                        row = yjbb_q1[yjbb_q1['股票代码'] == sym]
                        if not row.empty:
                            diff_pct = (yj_np - guimu_np) / abs(guimu_np) * 100 if guimu_np else 0
                            print(f'  | yjbb-归母偏差={diff_pct:.2f}%')
                        else:
                            print()
                    else:
                        print()
                if not jingli_row.empty:
                    jingli_np = jingli_row[q1_col].iloc[0]
                    print(f'       financial_abstract 净利润(含少数)={jingli_np:,.0f}')
    except Exception as e:
        print(f'       financial_abstract FAIL: {type(e).__name__}')
    time.sleep(1)
time.sleep(2)

# ===== 关键2: 分红派息字段单位验证 =====
print('\n===== 2. 分红派息字段单位验证 =====')
dividend_symbols = ['000651', '600519', '601088', '600036']
for sym in dividend_symbols:
    try:
        div = ak.stock_history_dividend_detail(symbol=sym, indicator='分红')
        if div is not None and not div.empty:
            # 只看已实施、近年
            div['year'] = div['公告日期'].dt.year
            recent = div[(div['进度'].isin(['实施','实施方案']))].tail(5)
            for _, r in recent.iterrows():
                pd_date = str(r['派息'])
                yr = str(r['公告日期'])[:10] if hasattr(r['公告日期'],'strftime') else str(r['公告日期'])
                print(f'  {sym} {yr} 派息={r["派息"]} 除权日={r["除权除息日"]}')
    except Exception as e:
        print(f'  {sym} FAIL: {type(e).__name__}: {str(e)[:60]}')
    time.sleep(1)

print('\n===== 3. 批量请求压力测试（50只分层样本） =====')
# 测试连续请求financial_abstract的失败率
import random
test_sample = ['000651','600519','600036','000002','601318','000858','600887','601398',
               '601288','000333','002415','300750','600900','601857','601088','600276',
               '601012','603259','600809','000001','601899','600585','600031','002714',
               '601668','600048','601628','601601','601390','600030','603288','600104',
               '000725','600690','600000','601818','600016','600837','601211','002230']
success_count = 0
fail_count = 0
total_time = 0
for i, sym in enumerate(test_sample[:25]):  # 只测25只避免过载
    t0 = time.time()
    try:
        fa = ak.stock_financial_abstract(symbol=sym)
        elapsed = time.time() - t0
        if fa is not None and not fa.empty:
            success_count += 1
        else:
            fail_count += 1
            print(f'  {sym}: empty result ({elapsed:.1f}s)')
        total_time += elapsed
    except Exception as e:
        fail_count += 1
        elapsed = time.time() - t0
        print(f'  {sym}: FAIL {type(e).__name__} ({elapsed:.1f}s)')
        total_time += elapsed
    time.sleep(0.5)  # 控制频率
    
    if (i+1) % 10 == 0:
        print(f'  progress: {i+1}/25, success={success_count}, fail={fail_count}, avg={total_time/(i+1):.1f}s/req')
print(f'\n结果: {success_count}/25 成功 ({success_count/25*100:.0f}%), avg={total_time/25:.1f}s/request')

print('\n===== 4. financial_abstract 列结构 =====')
fa_df, _, _ = test('financial_abstract(000651)', ak.stock_financial_abstract, symbol='000651')
if fa_df is not None:
    print(f'  选项: {list(fa_df["选项"].unique())}')
    print(f'  指标示例: {list(fa_df["指标"].unique())[:30]}')
    print(f'  报告期列: {[c for c in fa_df.columns if c not in ["选项","指标"]]}')
    # 找总股本相关
    share_rows = fa_df[fa_df['指标'].str.contains('股', na=False)]['指标'].unique()
    print(f'  股本相关指标: {list(share_rows)}')
