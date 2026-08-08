import warnings, logging
warnings.filterwarnings('ignore')
logging.disable(logging.CRITICAL)
import akshare as ak
import time

def test(name, func, **kwargs):
    try:
        df = func(**kwargs)
        if df is None:
            print(f'[{name}] None')
            return None
        print(f'[{name}] OK, {len(df)}rows, cols: {list(df.columns)[:25]}')
        return df
    except Exception as e:
        print(f'[{name}] FAIL - {type(e).__name__}: {str(e)[:100]}')
        return None

test('stock_dividend_cninfo', ak.stock_dividend_cninfo, symbol='000651')
time.sleep(1)
test('stock_individual_info_em', ak.stock_individual_info_em, symbol='000651')
time.sleep(1)

import baostock as bs
lg = bs.login()
print(f'[baostock login] code={lg.error_code} msg={lg.error_msg}')
if lg.error_code == '0':
    rs = bs.query_profit_data(code='sz.000651', year=2026, quarter=1)
    print(f'[profit_data] code={rs.error_code}')
    if rs.error_code == '0':
        print(f'  fields={rs.fields}')
        data = []
        while rs.next():
            data.append(rs.get_row_data())
        if data:
            print(f'  sample: {dict(list(zip(rs.fields, data[0]))[:14])}')
    rs2 = bs.query_history_k_data_plus('sz.000651', 'date,close,peTTM,pbMRQ',
                                       start_date='2026-08-01', end_date='2026-08-07')
    data2 = []
    while rs2.error_code == '0' and rs2.next():
        data2.append(rs2.get_row_data())
    print(f'[kline peTTM] rows={len(data2)} sample={data2[:2]}')
    bs.logout()
