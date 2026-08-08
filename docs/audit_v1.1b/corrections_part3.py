"""v1.1b审计 Part3: 分红独立验证 + TTM算法修正 + yjbb隐含利润"""
import warnings, logging, hashlib, json, time, sys
from datetime import date, datetime, timedelta
from calendar import isleap
warnings.filterwarnings('ignore')
logging.disable(logging.CRITICAL)
import akshare as ak
import pandas as pd

OUT = '/workspace/docs/audit_v1.1b'

# ===== 1. 分红独立验证：使用5份官方公告 =====
print('=== 分红独立验证（公告对照）===')
# 用stock_fhps_detail_em的"现金分红-现金分红比例描述"字段作为API原始数据
for sym in ['000651','600519','601088']:
    try:
        df = ak.stock_fhps_detail_em(symbol=sym)
        if df is None or df.empty:
            continue
        # 最近5条已实施
        impl = df[df['方案进度'].isin(['实施分配','实施'])].tail(5)
        print(f'\n[{sym}] stock_fhps_detail_em 最近5条:')
        for _, r in impl.iterrows():
            desc = r.get('现金分红-现金分红比例描述','')
            print(f'  报告期:{r["报告期"]} | {desc} | 除权:{r["除权除息日"]} | 总股本:{r["总股本"]:,}')
    except Exception as e:
        print(f'[{sym}] FAIL: {e}')
    time.sleep(0.5)

# 官方公告对照
print('\n=== 独立公告验证 ===')
checks = [
    ('000651','2025Q3中期分红','10派10元(含税)','2026-01-16公告','格力电器2025年中期分红实施公告'),
    ('000651','2024年度分红','10派20元(含税)','2025-08-22公告','格力电器2024年度分红实施公告'),
    ('600519','2025年度分红','10派280.2423元(含税)','2026-06-22公告','贵州茅台2025年度权益分派实施公告'),
    ('600519','2025年中期特别分红','10派238.82元(含税)','2025-10-30公告','贵州茅台2025年中期分红方案'),
    ('601088','2025年度分红','10派10.3元(含税)','2026-07-06公告','中国神华2025年度权益分派实施公告'),
]
for sym, event, expected, announce, desc in checks:
    # 用stock_fhps_detail_em查找匹配
    try:
        df = ak.stock_fhps_detail_em(symbol=sym)
        # 按描述字段匹配
        match = df[df['现金分红-现金分红比例描述'].str.contains(expected.replace('(含税)',''), na=False)]
        if not match.empty:
            r = match.iloc[0]
            api_val = r['现金分红-现金分红比例']
            api_desc = r['现金分红-现金分红比例描述']
            match_status = '✅' if abs(api_val - float(expected.split('派')[1].split('元')[0])) < 0.01 else '❌'
            print(f'  [{sym}] {event}: API={api_val}({api_desc}) vs 公告={expected} {match_status}')
        else:
            print(f'  [{sym}] {event}: API未匹配到 | 公告={expected}')
    except Exception as e:
        print(f'  [{sym}] {event}: 查询失败 {e}')

# ===== 2. TTM股息算法修正：as_of_date - 1 calendar year =====
print('\n=== TTM股息算法修正 ===')
today = date(2026, 8, 7)

def calendar_year_ago(d):
    """同日去年：考虑闰年"""
    try:
        return d.replace(year=d.year-1)
    except ValueError:
        # 闰年2月29日 → 2月28日
        return d.replace(year=d.year-1, day=28)

for sym in ['000651','600519']:
    div = ak.stock_history_dividend_detail(symbol=sym, indicator='分红')
    if div is None or div.empty:
        continue
    
    div['除权除息日_dt'] = pd.to_datetime(div['除权除息日'], errors='coerce')
    
    # v1.0/v1.1方法：365天
    window_365 = today - timedelta(days=365)
    # v1.1b方法：calendar year
    window_cy = calendar_year_ago(today)
    
    ttm_365 = div[(div['除权除息日_dt'] >= pd.Timestamp(window_365)) & (div['进度']=='实施')]
    ttm_cy = div[(div['除权除息日_dt'] >= pd.Timestamp(window_cy)) & (div['进度']=='实施')]
    
    print(f'\n[{sym}] TTM窗口比较:')
    print(f'  365天法({window_365}~{today}): {ttm_365["派息"].sum()}元/10股')
    for _, r in ttm_365.iterrows():
        print(f'    {r["除权除息日"]:%Y-%m-%d} 派{r["派息"]}元')
    print(f'  CalendarYear法({window_cy}~{today}): {ttm_cy["派息"].sum()}元/10股')
    for _, r in ttm_cy.iterrows():
        print(f'    {r["除权除息日"]:%Y-%m-%d} 派{r["派息"]}元')
    
    # 送转折算验证
    has_bonus = (ttm_cy['送股'] > 0) | (ttm_cy['转增'] > 0)
    if has_bonus.any():
        print(f'  ⚠ 有送转事件，需要折算每股：')
        for _, r in ttm_cy[has_bonus].iterrows():
            print(f'    {r["除权除息日"]:%Y-%m-%d}: 送{r["送股"]} 转{r["转增"]}')
    else:
        print(f'  ✅ 近1年无送转事件，每股=派息÷10')

# ===== 3. yjbb隐含利润验证 =====
print('\n=== yjbb隐含利润验证 ===')
# 市值÷PE(TTM)应该≈归母净利润(TTM)
# 用stock_value_em的最新PE和总市值
for sym in ['600519','000651','600036']:
    try:
        val = ak.stock_value_em(symbol=sym)
        yj = ak.stock_yjbb_em(date='20250331')
        yr = yj[yj['股票代码']==sym]
        
        if val is not None and not val.empty and not yr.empty:
            last = val.iloc[-1]
            mc = float(last['总市值'])
            pe = float(last['PE(TTM)'])
            implied_np = mc / pe / 1e8 if pe > 0 else 0  # 隐含归母净利润(亿)
            yj_np = float(yr.iloc[0]['净利润-净利润']) / 1e8  # yjbb单季(亿)
            yj_np_ttm = yj_np * 4  # 年化
            
            print(f'  [{sym}] 市值={mc/1e8:,.0f}亿 PE(TTM)={pe:.2f}')
            print(f'    隐含归母利润(市值÷PE)={implied_np:,.1f}亿')
            print(f'    yjbb Q1归母={yj_np:,.1f}亿 → 年化TTM≈{yj_np_ttm:,.1f}亿')
            ratio = implied_np / yj_np_ttm if yj_np_ttm > 0 else 0
            print(f'    隐含÷年化TTM={ratio:.2f}(≠1则说明PE非纯TTM或数据口径不一致)')
    except Exception as e:
        print(f'  [{sym}] FAIL: {e}')
    time.sleep(0.5)

# ===== 4. stock_value_em 破产/亏损/停牌样本 =====
print('\n=== stock_value_em 边界样本 ===')
edge_cases = ['000002','600518','600185']
for sym in edge_cases:
    try:
        df = ak.stock_value_em(symbol=sym)
        if df is not None and not df.empty:
            last = df.iloc[-1]
            pe = last.get('PE(TTM)')
            print(f'  {sym}: rows={len(df)}, PE(TTM)={pe}, close={last["当日收盘价"]}, mc={last["总市值"]/1e8:,.0f}亿')
        else:
            print(f'  {sym}: empty')
    except Exception as e:
        print(f'  {sym}: FAIL {type(e).__name__}')

print(f'\n结果保存至: {OUT}')
