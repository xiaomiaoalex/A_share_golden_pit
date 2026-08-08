"""v1.1审计：financial_abstract 50只分层3轮压力测试"""
import warnings, logging, time, hashlib, json
warnings.filterwarnings('ignore')
logging.disable(logging.CRITICAL)
import akshare as ak
import pandas as pd

# 50只分层样本
STOCKS = [
    # 沪主板(10)
    '600519','600036','601318','600585','600031','600900','601088','600276','601012','603259',
    # 深主板(10)
    '000651','000002','000333','000858','000725','000001','002415','002230','000568','000538',
    # 创业板(8)
    '300750','300059','300015','300124','300274','300433','300498','300760',
    # 科创板(8)
    '688981','688012','688036','688111','688187','688008','688009','688005',
    # 北交所(4)
    '835185','838402','839729','832491',
    # 金融(5)
    '600036','601318','601398','600016','000001',  # 重复的已经在上面
    # 中小市值(5)
    '002572','002444','002705','300146','603898',
    # 周期(5)
    '002601','000630','600019','601899','002466',
]
STOCKS = list(dict.fromkeys(STOCKS))  # 去重但保序
STOCKS = STOCKS[:50]

results = {
    'total': len(STOCKS),
    'rounds': [],
}

for round_num in range(1, 4):
    print(f'\n===== 第{round_num}轮 ({len(STOCKS)}只) =====')
    success = 0
    fail = 0
    errors = {}
    latencies = []
    
    for i, sym in enumerate(STOCKS):
        t0 = time.time()
        try:
            df = ak.stock_financial_abstract(symbol=sym)
            elapsed = time.time() - t0
            latencies.append(elapsed)
            if df is not None and not df.empty:
                success += 1
            else:
                fail += 1
                errors[sym] = f'empty({elapsed:.1f}s)'
        except Exception as e:
            elapsed = time.time() - t0
            fail += 1
            err_type = type(e).__name__
            errors[sym] = f'{err_type}({elapsed:.1f}s)'
        time.sleep(0.3)
        
        if (i+1) % 10 == 0:
            print(f'  进度: {i+1}/{len(STOCKS)}, 成功={success}, 失败={fail}')
    
    latencies.sort()
    p50 = latencies[len(latencies)//2] if latencies else 0
    p95_idx = int(len(latencies) * 0.95)
    p95 = latencies[min(p95_idx, len(latencies)-1)] if latencies else 0
    
    error_summary = {}
    for v in errors.values():
        etype = v.split('(')[0]
        error_summary[etype] = error_summary.get(etype, 0) + 1
    
    round_result = {
        'round': round_num,
        'success': success,
        'fail': fail,
        'rate_first_pass': round(success/len(STOCKS)*100, 1),
        'p50_latency_s': round(p50, 2),
        'p95_latency_s': round(p95, 2),
        'error_types': error_summary,
        'failed_symbols': dict(list(errors.items())[:5]),
    }
    results['rounds'].append(round_result)
    print(f'  首轮成功率: {round_result["rate_first_pass"]}%, p50={p50:.2f}s, p95={p95:.2f}s')
    print(f'  错误分类: {error_summary}')
    time.sleep(3)  # 轮间间隔

# 计算总体指标
total_success = sum(r['success'] for r in results['rounds'])
total_attempts = len(STOCKS) * 3
results['overall_success_rate'] = round(total_success/total_attempts*100, 1)
results['test_time'] = time.strftime('%Y-%m-%d %H:%M:%S')

# 保存
with open('/tmp/fa_audit_v1.1.json', 'w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)

print(f'\n=== 汇总 ===')
for r in results['rounds']:
    print(f'  第{r["round"]}轮: 首轮成功率={r["rate_first_pass"]}%, p50={r["p50_latency_s"]}s, p95={r["p95_latency_s"]}s, 错误={r["error_types"]}')
print(f'  3轮总体: {total_success}/{total_attempts} ({results["overall_success_rate"]}%)')
print(f'\n结果已保存: /tmp/fa_audit_v1.1.json')
