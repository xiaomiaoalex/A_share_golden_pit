"""v1.1b审计 Part2: 股本接口 + stock_value_em + 分红多期交叉验证"""
import warnings, logging, hashlib, json, time, sys, requests
from datetime import date, datetime, timedelta
warnings.filterwarnings('ignore')
logging.disable(logging.CRITICAL)
import akshare as ak
import pandas as pd

OUT = '/workspace/docs/audit_v1.1b'
LOG = f'{OUT}/logs'

# ===== 1. 股本历史接口（1.18.83）=====
print('=== 股本历史接口测试（akshare 1.18.83）===')

# stock_zh_a_gbjg_em
try:
    df = ak.stock_zh_a_gbjg_em(symbol='000651')
    print(f'stock_zh_a_gbjg_em(格力): {len(df)}r, cols={list(df.columns)}')
    if not df.empty:
        print(f'  首行: {df.iloc[0].to_dict()}')
        print(f'  末行: {df.iloc[-1].to_dict()}')
except Exception as e:
    print(f'stock_zh_a_gbjg_em FAIL: {type(e).__name__}: {str(e)[:100]}')

time.sleep(1)

# stock_share_change_cninfo
try:
    df = ak.stock_share_change_cninfo(symbol='000651')
    print(f'\nstock_share_change_cninfo(格力): {len(df)}r, cols={list(df.columns)}')
    if not df.empty:
        print(f'  首行: {df.iloc[0].to_dict()}')
        print(f'  末行: {df.iloc[-1].to_dict()}')
except Exception as e:
    print(f'stock_share_change_cninfo FAIL: {type(e).__name__}: {str(e)[:100]}')

time.sleep(1)

# stock_hold_change_cninfo
try:
    df = ak.stock_hold_change_cninfo(symbol='000651')
    print(f'\nstock_hold_change_cninfo(格力): {len(df)}r, cols={list(df.columns)}')
    if not df.empty:
        print(f'  首行: {df.iloc[0].to_dict()}')
except Exception as e:
    print(f'stock_hold_change_cninfo FAIL: {type(e).__name__}: {str(e)[:100]}')

time.sleep(2)

# ===== 2. stock_value_em 50只分层样本 =====
print('\n=== stock_value_em 50只分层验证 ===')
STOCKS_VAL = [
    '600519','600036','601318','600585','600031','600900','601088','600276','601012','603259',
    '000651','000002','000333','000858','000725','000001','002415','002230','000568','000538',
    '300750','300059','300015','300124','300274','300433','300498','300760','300896','300014',
    '688981','688012','688036','688111','688187','688008','688009','688005','688126','688008',
    '920185','920402','920002','920099','920111','920060',
    '600518','002502','000620','600185',
]
STOCKS_VAL = list(dict.fromkeys(STOCKS_VAL))[:50]

val_results = []
for sym in STOCKS_VAL:
    t0 = time.time()
    try:
        df = ak.stock_value_em(symbol=sym)
        elapsed = time.time()-t0
        if df is not None and not df.empty:
            last = df.iloc[-1]
            price = float(last['当日收盘价'])
            gb = float(last['总股本'])
            mc = float(last['总市值'])
            pe = float(last.get('PE(TTM)',0)) if pd.notna(last.get('PE(TTM)')) else 0
            implied_mc = round(price * gb / 1e8, 2)  # 收盘价×总股本推算市值(亿)
            actual_mc = round(mc / 1e8, 2)  # 实际总市值(亿)
            mc_error = abs(implied_mc - actual_mc) / actual_mc * 100 if actual_mc > 0 else 0
            val_results.append({
                'symbol': sym, 'elapsed': round(elapsed,2), 'rows': len(df),
                'price': price, 'gb_yi': round(gb/1e8, 2),
                'implied_mc_yi': implied_mc, 'actual_mc_yi': actual_mc,
                'mc_error_pct': round(mc_error, 2), 'pe': round(pe, 2),
            })
        else:
            val_results.append({'symbol': sym, 'elapsed': round(elapsed,2), 'rows': 0, 'error': 'empty'})
    except Exception as e:
        elapsed = time.time()-t0
        val_results.append({'symbol': sym, 'elapsed': round(elapsed,2), 'error': str(e)[:60]})
    time.sleep(0.2)

df_v = pd.DataFrame(val_results)
success = (df_v['rows'] > 0).sum() if 'rows' in df_v.columns else 0
print(f'成功: {success}/{len(STOCKS_VAL)}')
mc_ok = df_v[df_v['mc_error_pct'].notna() & (df_v['mc_error_pct'] < 1)]
print(f'总市值≈收盘价×总股本误差<1%: {len(mc_ok)}/{success}')
err_samples = df_v[df_v['mc_error_pct'].notna() & (df_v['mc_error_pct'] >= 1)]
if not err_samples.empty:
    print(f'误差≥1%样本:')
    for _, r in err_samples.head(5).iterrows():
        print(f'  {r["symbol"]}: implied={r["implied_mc_yi"]} vs actual={r["actual_mc_yi"]} (diff={r["mc_error_pct"]}%)')
failed = df_v[df_v['error'].notna()]
if not failed.empty:
    print(f'失败样本: {failed[["symbol","error"]].to_dict("records")}')

# ===== 3. yjbb 多期交叉验证（非2025Q1单期）=====
print('\n=== yjbb 2025H1/2026Q1 归母净利润交叉验证 ===')
# 用financial_abstract做交叉验证（虽然不稳定，但选已成功的股票）
cross_stocks = ['600519','600036','000651','600585','002230']
# 先用stock_financial_abstract获取2025H1和2026Q1数据
for period, date_str, period_label in [
    ('20250630', '20250630', '2025H1'),
    ('20260331', '20260331', '2026Q1'),
]:
    try:
        df_yj = ak.stock_yjbb_em(date=date_str)
        print(f'\n{period_label} yjbb: {len(df_yj)}r')
        
        for sym in cross_stocks:
            rj = df_yj[df_yj['股票代码'] == sym]
            if rj.empty:
                print(f'  {sym}: yjbb未找到')
                continue
            yj_np = rj.iloc[0]['净利润-净利润']
            
            # financial_abstract交叉验证
            try:
                fa = ak.stock_financial_abstract(symbol=sym)
                if fa is not None and not fa.empty:
                    col = None
                    for c in fa.columns:
                        if date_str[:6] in str(c):
                            col = c
                            break
                    if col:
                        guimu = fa[fa['指标']=='归母净利润']
                        if not guimu.empty:
                            gm_np = guimu[col].iloc[0]
                            gm_np = float(gm_np) if gm_np and gm_np != '--' else None
                            if gm_np:
                                diff = abs(yj_np/gm_np - 1) * 100
                                print(f'  {sym}: yjbb={yj_np:,.0f} fa归母={gm_np:,.0f} diff={diff:.2f}%')
                            else:
                                print(f'  {sym}: fa归母数据不可解析')
            except Exception as e:
                print(f'  {sym}: fa交叉验证失败 {type(e).__name__}')
        time.sleep(2)
    except Exception as e:
        print(f'{period_label} yjbb失败: {e}')

# ===== 4. 保存结果 =====
json.dump(val_results, open(f'{OUT}/value_em_50.json', 'w'), indent=2, default=str)
print(f'\n结果已保存: {OUT}')
