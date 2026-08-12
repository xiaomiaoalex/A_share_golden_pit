# 黄金坑策略 · 量化初筛

## 1. 范围与隔离

量化初筛使用独立的点时数据适配器、计算模块、决策状态机、SQLite仓储和CLI。
旧 `RadarScanner → DeepScreener → CoreConfirmer` 调用链保持不变；
`screen-tier1` 不实例化旧应用，也不会触发Tier2或Tier3。

当前计算契约版本为 `tier1-v2.3.0`；本版使用最新完整会计年度税前股息率，
并保留最近2个连续可比季度均为同比正增长。历史运行仍保留各自原始版本号和规则，
旧版断点续跑不会混用新口径。

## 2. 硬筛选口径

| 条件 | 正式口径 | 边界 |
|---|---|---|
| PE(TTM) | 当前筛选采用已验证供应商字段并保留自计算值；历史筛选采用点时总市值÷最近4个连续单季度归母净利润 | `< 15`，利润必须大于0 |
| 最新完整会计年度股息率 | 按利润归属报告期分组，选择含12月31日年末方案的最新完整会计年度；同年度中期、特别及年末已实施税前每股现金分红去重合计，再除以点时收盘价 | `> 5%` |
| 收入趋势 | 最近2个连续单季度的 `OPERATE_INCOME` 同比序列 | 两个季度同比均必须 `> 0` |
| 利润趋势 | 最近2个连续单季度的 `PARENT_NETPROFIT` 同比序列 | 两个季度同比均必须 `> 0` |
| 风险警示 | 截至as-of的ST、*ST及退市风险警示状态 | 任何风险警示均失败 |

累计报表按 `Q1=Q1累计、Q2=半年累计-Q1、Q3=前三季累计-半年累计、
Q4=年报累计-前三季累计` 还原单季度。同比使用同一自然季度的上年同期，
因此窗口可以跨年。缺少中间季度时不会跳过缺口拼接出“连续正增长”序列。

利润窗口任一上年同期归母净利润小于等于0时，不计算该硬比较，业务状态为
`NOT_COMPARABLE`，输出队列为 `TURNAROUND_WATCHLIST`。收入基数非正同样不
伪造同比，但不自动进入利润转机名单。

送转处理同时保留原始税前每股分红和调整后每股分红。若上游明确标记已经复权，
本系统不再二次调整。

`report_period` 是分红硬筛选必需字段。BaoStock缺少该字段时，仅可通过
AKShare或Tushare按“除权日+税前每股现金分红”事实匹配补全；禁止根据实施年份
推断。补全失败时数据状态为`PARTIAL`，不得PASS。过去一年实施窗口若同时出现
两个不同的12月31日报告期，记录`OVERLAPPING_ANNUAL_DIVIDEND_REPORT_PERIODS`
告警，但硬筛选仍只采用最新完整会计年度。

旧版`dividend_yield_ttm`及其原始/公司行动调整值继续保留用于历史审计，不再作为
v2.3硬筛选输入。新运行通过追加的决策替代关系使同标的同as-of旧口径结果失效，
不更新或删除旧运行、旧决策和旧证据血缘。

## 3. 状态机

业务状态：`PASS / FAIL / PENDING / NOT_COMPARABLE`。

数据状态：`COMPLETE / PARTIAL / ERROR`。

验证状态独立保存为：`SINGLE_SOURCE / CROSS_VERIFIED / PRIMARY_VERIFIED /
UNVERIFIED / CONFLICT`。当前自动筛选通常为 `SINGLE_SOURCE`；只有显式多源核验才
产生跨源证据。验证等级暂不改变五项硬筛选阈值，避免因第二源短时不可用中断业务。

对外筛选状态：

- `PASS`：全部硬条件有数据且明确通过；
- `FAIL`：至少一项硬条件明确失败；
- `PENDING_DATA`：没有明确失败，但必要字段缺失；
- `DATA_ERROR`：没有明确失败，但接口或Schema错误；
- `TURNAROUND_WATCHLIST`：利润同比存在非正基数；
- `NOT_COMPARABLE`：其他不可比情形。

已知 `FAIL` 的优先级高于缺失或错误，但独立数据状态仍会标记
`PARTIAL/ERROR`。这允许安全短路后续请求，同时不会把“不再抓取”伪装成数据完整。

## 4. 点时与血缘

- 行情只选 `price_date <= as_of_date` 的最近记录；
- 正式利润表只使用 `NOTICE_DATE <= as_of_date`，且修订更新时间也不得晚于
  `as_of_date`；供应商只保留未来修订版时宁可待补数据；
- 分红只计入截至筛选日已实施且除权日已发生的方案；
- AKShare当前ST列表只允许用于 `as_of_date=今天`；任何过去日期必须使用带生效日的
  历史来源或保持待补，最近日期也不例外；
- 每次运行、数据请求、Schema哈希、抓取时间、公告日、报告期、原始值、计算值和
  公式均单独保存；
- 历史全市场CLI要求显式点时股票池；指定股票可用 `--symbols` 复算；
- 深交所历史简称变更用于历史ST判断。免费源无法可靠重建的沪市、北交所历史ST
  状态会保持 `PENDING_DATA`，不会按“非ST”放行。

备用数据源链只补数据，不改变口径或阈值；返回值保留所有尝试的状态轨迹。

### 4.1 业务数据质量闸门

机器可读指标注册表位于 `src/data/quality/registry.py`，明确营业收入、归母净利润、
PE、税前分红和风险警示的定义、粒度、单位、可得时间、允许字段与禁止替代字段。

每个取数结果在参与决策前接受质量评估。以下问题会阻止该字段形成业务通过结论：

- 最终股票池为空、代码/交易所非法或证券代码重复；
- 行情、公告、修订、除权、公司行动或风险状态来自as-of之后；
- 同一报告期存在未消歧的多个财报版本，或报告期不是标准季度末；
- 收盘价、总市值、总股本或送转因子存在不可能值；
- 来源被注册为不支持该字段，却返回了可用数据。

来源仅具有限定覆盖、当前只有单源或非正PE等情况只记录质量问题，不中断正常筛选。
原始抓取状态与质量闸门结果分别保存，因而可以区分“接口成功但数据不可用”和
“接口本身失败”。运行结果与 `show-tier1` 会输出质量摘要。

### 4.2 生产多源链

| 顺序 | 来源 | 可用于硬筛选的已验证字段 | 明确限制 |
|---|---|---|---|
| 1 | AKShare/东方财富 | 行情、PE、正式利润表、分红；深市历史简称 | 沪市/北交所历史ST覆盖不足 |
| 2 | Tushare Pro | 点时股票池、收盘价、PE、总市值、总股本、`revenue`、`n_income_attr_p`、`cash_div_tax`、每日历史ST列表 | 需要Tushare权限和`TUSHARE_TOKEN`；`stock_st`仅覆盖2016年以来 |
| 3 | BaoStock | 沪深未复权收盘价、`peTTM`、每日`isST`、`dividCashPsBeforeTax`、送转比例 | 不覆盖北交所；不提供满足本项目定义的精确财报字段组合 |

Tushare每日指标的总市值单位为万元、总股本单位为万股，入库前分别乘以10,000；
财报只接受累计合并口径的 `revenue`（营业收入）和 `n_income_attr_p`
（归母净利润），且实际公告日不得晚于as-of。分红只接受实施方案中的税前每股现金
和除权日。BaoStock行情固定使用 `adjustflag=3` 未复权收盘价；其
`MBRevenue/netProfit` 不等同于本项目要求的营业收入/归母净利润，因此适配器明确
返回不支持，不做近似替换。

字段定义依据：

- [Tushare每日指标](https://tushare.pro/document/2?doc_id=32)
- [Tushare利润表](https://tushare.pro/document/2?doc_id=33)
- [Tushare分红送股](https://tushare.pro/document/2?doc_id=103)
- [Tushare历史名称](https://tushare.pro/document/2?doc_id=100)
- [Tushare历史ST列表](https://tushare.pro/document/2?doc_id=397)
- [Tushare股票基础信息](https://tushare.pro/document/2?doc_id=25)
- [BaoStock Python API](https://baostock.com/baostock/index.php/Python_API%E6%96%87%E6%A1%A3)

配置方式：

```powershell
$env:GOLDEN_PIT_DATA_SOURCES = "akshare,tushare,baostock"
$env:TUSHARE_TOKEN = "在本机环境变量中设置，不写入仓库"
```

未配置Tushare令牌时，CLI会明确输出Tushare未启用，而不是静默假装三源可用。
以下命令让各来源独立取数并比较同交易日PE/收盘价、同报告期财务值、TTM分红
和ST状态；差异只形成 `PASS/WARN/INSUFFICIENT` 质量结论，不改变筛选阈值：

```bash
python main.py verify-tier1-sources --as-of 2026-08-10 --symbols 000651
```

核验报告默认写入 `source_verification_reports`；可用 `--run-id` 绑定某次筛选，或用
`--no-persist` 仅输出JSON。核验是独立质量证据，不会自动覆盖供应商原始值。

## 5. 数据库迁移

升级脚本按顺序执行：

- `scripts/migrations/001_tier1_v2_up.sql`
- `scripts/migrations/002_tier1_data_quality_up.sql`

新增表：

- `screening_runs`
- `source_observations`
- `tier1_raw_metrics`
- `tier1_quarterly_series`
- `dividend_events`
- `risk_warning_intervals`
- `tier1_decisions`
- `source_lineage`
- `data_quality_assessments`
- `source_verification_reports`

迁移是增量式的，不修改旧5张表。同一股票、同一as-of在不同run中可以并存。
002迁移会在 `screening_runs` 增加质量摘要。已有001数据库可以直接升级且重复执行
迁移安全。回滚脚本只删除阶段A新增表，旧表和旧数据保留。

## 6. 测试与验收

默认测试完全离线：

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check --select F main.py config/tier1.py src/data/point_in_time src/data/quality src/screening/tier1_v2 src/storage/tier1_repository.py tests
```

覆盖严格估值/分红边界、连续两季同比正增长、旧版逐季改善兼容、跨年连续窗口、
累计转单季、未来公告/修订排除、非正利润基数、
所有无效数值不放行、主源失败后备用源补充、全部源失败、送转复权防重算、
迁移/回滚不破坏旧表、Tushare/BaoStock单位和能力边界、多源差异告警、关键未来
数据泄漏和重复粒度闸门、旧001数据库升级，以及从数据契约到数据库决策的端到端
合成测试。

真实源测试与单元测试隔离，只有显式启用才访问网络：

```bash
$env:RUN_LIVE_DATA_TESTS=1
python -m pytest -q -m live tests/live
```

实时接口成功仅验证适配器兼容性，不替代合成业务逻辑验收。

## 7. 量化初筛之后

证据研究的人机协作证据包、AI Schema与人工确认，以及风险终审的行业化风险模型
和硬否决项均由各自模块实现。
