import warnings, logging, signal
warnings.filterwarnings('ignore')
logging.disable(logging.CRITICAL)

class TO(Exception): pass
def hdl(s, f): raise TO()
signal.signal(signal.SIGALRM, hdl)

import akshare as ak

# 1. 东财个股信息（总股本）
signal.alarm(30)
try:
    df = ak.stock_individual_info_em(symbol='000651')
    print(f'[individual_info_em] OK: {dict(zip(df["item"], df["value"]))}')
except Exception as e:
    print(f'[individual_info_em] FAIL: {type(e).__name__} {str(e)[:60]}')
signal.alarm(0)

# 2. baostock
signal.alarm(60)
try:
    import baostock as bs
    lg = bs.login()
    print(f'[bs login] {lg.error_code}')
    if lg.error_code == '0':
        rs = bs.query_profit_data(code='sz.000651', year=2026, quarter=1)
        print(f'[bs profit] code={rs.error_code} fields={rs.fields}')
        data = []
        while rs.error_code == '0' and rs.next():
            data.append(rs.get_row_data())
        if data:
            print(f'  sample={dict(zip(rs.fields, data[0]))}')
        rs2 = bs.query_history_k_data_plus('sz.000651', 'date,close,peTTM,pbMRQ',
                                           start_date='2026-07-01', end_date='2026-08-07')
        d2 = []
        while rs2.error_code == '0' and rs2.next():
            d2.append(rs2.get_row_data())
        print(f'[bs kline peTTM] rows={len(d2)} tail={d2[-2:] if d2 else None}')
        bs.logout()
except Exception as e:
    print(f'[baostock] FAIL: {type(e).__name__} {str(e)[:80]}')
signal.alarm(0)
