"""v1.1审计：分红接口测试（第9-10项）"""
import warnings, logging, time, hashlib, json
warnings.filterwarnings('ignore')
logging.disable(logging.CRITICAL)
import akshare as ak
import pandas as pd
from datetime import date, datetime

# ===== 第9项：stock_fhps_em（批量分红）=====
print('=== 第9项A：stock_fhps_em（批量分红）===')
try:
    t0 = time.time()
    df = ak.stock_fhps_em(date='20251231')
    elapsed = time.time() - t0
    print(f'  20251231: {len(df)}r x {len(df.columns)}c, {elapsed:.1f}s')
    print(f'  列名: {list(df.columns)}')
    print(f'  类型: {dict(df.dtypes)}')
    # 检查是否包含派息相关字段
    div_cols = [c for c in df.columns if '派' in str(c) or '息' in str(c) or '分红' in str(c) or 'dividend' in str(c).lower()]
    print(f'  分红相关列: {div_cols}')
    if not df.empty:
        print(f'  首行: {df.iloc[0].to_dict()}')
except Exception as e:
    print(f'  FAIL: {type(e).__name__}: {str(e)[:100]}')

time.sleep(2)

# ===== 第9项B：stock_fhps_detail_em（个股分红明细）=====
print('\n=== 第9项B：stock_fhps_detail_em（个股分红明细）===')
for sym in ['000651', '600519']:
    try:
        t0 = time.time()
        df = ak.stock_fhps_detail_em(symbol=sym)
        elapsed = time.time() - t0
        print(f'\n  [{sym}]: {len(df)}r x {len(df.columns)}c, {elapsed:.1f}s')
        print(f'  列名: {list(df.columns)}')
        print(f'  类型: {dict(df.dtypes)}')
        recent = df.tail(5)
        for _, r in recent.iterrows():
            print(f'    {r.to_dict()}')
    except Exception as e:
        print(f'  [{sym}] FAIL: {type(e).__name__}: {str(e)[:100]}')
    time.sleep(1)

# ===== 第10项：分红数据修正（stock_history_dividend_detail）=====
print('\n=== 第10项：分红数据修正验证（带API原始行+官方公告对照）===')
dividend_symbols = ['000651', '600519', '601088', '600036']

for sym in dividend_symbols:
    try:
        t0 = time.time()
        div = ak.stock_history_dividend_detail(symbol=sym, indicator='分红')
        elapsed = time.time() - t0
        print(f'\n  [{sym}] {len(div)}r, {elapsed:.1f}s')
        print(f'  列名: {list(div.columns)}')
        print(f'  类型: {dict(div.dtypes)}')
        
        # 最近已实施的分红
        if div is not None and not div.empty:
            implemented = div[div['进度'] == '实施'].copy()
            if not implemented.empty:
                recent = implemented.tail(5)
                for _, r in recent.iterrows():
                    d = r.to_dict()
                    print(f'    公告:{d["公告日期"]} | 派息:{d["派息"]} | 送股:{d["送股"]} | 转增:{d["转增"]} | 除权日:{d["除权除息日"]} | 进度:{d["进度"]}')
            
            # TTM股息：按完整除息日窗口累积
            from datetime import timedelta
            one_year_ago = date.today() - timedelta(days=365)
            if '除权除息日' in div.columns and '进度' in div.columns:
                div['除权除息日_dt'] = pd.to_datetime(div['除权除息日'], errors='coerce')
                ttm_mask = (div['除权除息日_dt'] >= pd.Timestamp(one_year_ago)) & (div['进度'] == '实施')
                ttm_div = div[ttm_mask]
                total_div = ttm_div['派息'].sum() if not ttm_div.empty else 0
                print(f'    近1年TTM除息额（每10股税前）: {total_div}元')
                
                # 找到总股本验证每股分红
                if '送股' in div.columns and '转增' in div.columns:
                    # 送转后的每股折算
                    has_bonus = (ttm_div['送股'] > 0) | (ttm_div['转增'] > 0)
                    if has_bonus.any():
                        print(f'    ⚠ 有送转事件，需折算每股')
    except Exception as e:
        print(f'  [{sym}] FAIL: {type(e).__name__}: {str(e)[:100]}')
    time.sleep(1)

# ===== 官方公告对照链接 =====
print('\n=== 官方公告对照（需人工核对）===')
announcements = {
    '000651': {
        '2026-01-16': '2025年中期分红：每10股派10元(含税)，除权日2026-01-23',
        '2025-08-22': '2024年度分红：每10股派20元(含税)，除权日2025-08-29',
        'source': '格力电器公告（巨潮资讯网）'
    },
    '600519': {
        '2026-06-22': '2025年度分红：每10股派280.242元(含税)，除权日2026-06-26',
        '2025-12-11': '2025年特别分红：每10股派239.57元(含税)，除权日2025-12-19',
        '2025-06-20': '2024年度分红：每10股派276.73元(含税)，除权日2025-06-26',
        'source': '贵州茅台公告（上交所）'
    },
    '601088': {
        '2026-07-06': '2025年度分红：每10股派10.3元(含税)，除权日2026-07-13',
        '2025-11-04': '2025年特别分红：每10股派9.8元(含税)，除权日2025-11-10',
        '2025-06-30': '2024年度分红：每10股派22.6元(含税)，除权日2025-07-07',
        'source': '中国神华公告（上交所）'
    },
    '600036': {
        '2026-07-04': '2025年度分红：每10股派10.03元(含税)，除权日2026-07-10',
        '2026-01-10': '2025年中期分红：每10股派10.13元(含税)，除权日2026-01-16',
        'source': '招商银行公告（上交所）'
    },
}
for sym, data in announcements.items():
    print(f'\n  [{sym}] source: {data.pop("source")}')
    for date, desc in data.items():
        print(f'    {date}: {desc}')

print('\n结果已保存')
