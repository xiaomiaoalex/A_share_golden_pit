# A股多策略选股研究平台

面向持续扩展的选股策略平台：数据采集、证据校验、任务执行和 Web 外壳由平台共享，
每个策略独立维护规则、持久化适配、结果投影与展示模块。当前首个正式策略“黄金坑”
用于识别长期价值仍在、但价格因阶段性悲观而明显错位的 A 股公司。

后续平台建设、AI 研究层和第三方框架集成以
[专业量化策略平台开发路线图](docs/development_roadmap.md)为准；AI 数据集、模型路由、
受控读取、结构化报告和人工审批规范见
[AI 研究与知识治理层架构](docs/ai_research_architecture.md)。AI 模型默认采用中国模型
优先策略，首选适配 DeepSeek，并以通义千问作为首个自动降级供应商。

## 正式研究链路

```text
量化初筛：点时、硬条件、失败关闭的量化筛选
  → 证据研究：可复核证据包 + 人机协作研究 + 人工确认
  → 风险终审：行业化风险与价值陷阱过滤 + 人工终审
```

系统不使用机械综合分抵消致命缺陷。业务状态与数据状态分开保存；数据不足进入
`PENDING_DATA / DATA_ERROR / REVIEW`，不会被解释为通过。

## 量化初筛（Tier1）

五项硬条件必须全部明确成立：

1. 点时 `PE(TTM) < 15`；
2. 税前、已实施、按公司行动调整后的 `股息率(TTM) > 5%`；
3. 最近2个连续可比单季度的营业收入同比均为正增长；
4. 同一窗口的归母净利润同比均为正增长；
5. 截至筛选日不属于ST、*ST或其他风险警示股票。

利润同比窗口任一上年同期归母净利润小于等于0时进入
`TURNAROUND_WATCHLIST`，不会混入正式雷达池。近期窗口（默认 7 日）允许按最近
交易日使用当前股票池；超出窗口的历史全市场筛选只接受具备精确点时能力的股票池，
无合格来源时失败关闭，防止幸存者偏差。

```bash
python main.py screen-tier1 --as-of 2026-08-10 --symbols 000651 600519
python main.py screen-tier1 --as-of 2020-12-31 \
  --universe-file universe_20201231.csv
python main.py verify-tier1-sources --as-of 2026-08-10 --symbols 000651
python main.py show-tier1 --run-id RUN_ID
python main.py resume-tier1 --run-id RUN_ID
python main.py retry-tier1-data --run-id RUN_ID
```

完整口径见 [量化初筛说明](docs/strategies/golden_pit/quantitative_screening.md)。

## 证据研究（Tier2）

证据研究只接收同一运行中量化初筛为 `PASS` 的标的。每条外部事实必须绑定：

- 带时区的点时可得时间；
- 本地证据快照及SHA-256；
- 可在快照中检索到的原文摘录；
- 事实与来源的逐项映射；
- 二进制原件对应的可检索文本及哈希。

任一关键维度 `FAIL` 即 `REJECT`；关键证据不足为 `REVIEW`。人工可以维持或下调
系统结论，不能上调。

```bash
python main.py export-tier2 --run-id RUN_ID
python main.py import-tier2 --file ai_results.json
python main.py review-tier2 --run-id RUN_ID
```

完整契约见 [证据研究说明](docs/strategies/golden_pit/evidence_research.md)。

## 风险终审（Tier3）

风险终审只接收最新证据研究人工 `PASS`，按一般企业、银行、保险、地产四类模型检查
财务真实性、流动性、分红、治理、周期顶部和结构性价值陷阱。行业分类自身也必须
经过同样的证据快照验证。

- 硬否决成立：`REJECT`；
- 风险警告或必要证据缺失：`REVIEW`；
- 全部必要检查有证据且为 `CLEAR`：系统 `PASS`，仍需人工终审。

```bash
python main.py export-tier3 --run-id RUN_ID \
  --classification-file industries.json
python main.py import-tier3 --file filled_tier3_results.json
python main.py review-tier3 --run-id RUN_ID
```

完整规则见 [风险终审说明](docs/strategies/golden_pit/risk_review.md)。

## 快速开始

```bash
python -m venv venv
# Linux/macOS: source venv/bin/activate
# Windows: venv\Scripts\activate
python -m pip install -r requirements-lock.txt
python main.py strategy list
python main.py migrate
python deploy_check.py
```

启动新的正式工作流，或检查已有运行：

```bash
python main.py strategy golden-pit workflow --as-of 2026-08-10 --symbols 000651 600519
python main.py strategy golden-pit workflow --run-id RUN_ID
```

`workflow` 会汇总A/B/C状态并给出下一条受控操作，不会自动越过AI研究或人工复核。

## Web 研究控制台

项目内置零新增依赖的多策略 Web 研究平台。首页集中展示已注册策略；每个策略拥有
独立的结果投影和前端展示模块。当前接入的首个策略是黄金坑三阶段流程，可
查看研究漏斗、候选股详情、数据质量和运行记录，并可一键启动全市场筛选（或指定
股票）、生成证据研究包以及提交证据研究/风险终审人工复核：

Windows 可直接双击项目根目录的 `start.bat`；Linux/macOS 使用：

```bash
bash start.sh
```

启动器会在同一进程中提供前端静态页面和后端 API，自动应用数据库迁移并完成 SQLite
读写预检，健康检查通过后再打开浏览器。重复点击时会复用已运行的平台；默认端口被其他
程序占用时会自动尝试后续端口。

浏览器默认打开 `http://127.0.0.1:8765`。如需指定数据库、端口或禁止自动打开浏览器：

```bash
python web_app.py --db data/db/strategy_platform.db --port 9000 --no-browser
```

后端状态可由 `http://127.0.0.1:8765/api/health` 检查。控制台默认仅监听本机回环
地址；一键启动入口会执行版本化迁移，CLI 和其他部署流程仍可显式运行
`python main.py migrate`。策略模块构造和只读 API 不会隐式修改数据库。筛选和证据包导出由持久化、单并发的
本地任务队列执行，可在“运行记录”查看排队、运行和中断状态；AI研究 JSON 和行业
分类等正式材料仍通过对应 CLI 导入，以保留既有的严格校验和证据契约。

Docker 环境可一条命令启动同一套前后端：

```bash
docker compose up --build
```

平台通过策略注册表隔离数据、策略、执行和展示层。新增策略可内置注册，也可发布
`a_share_strategy_platform.strategies` Python entry point，由平台启动时自动发现；只需
实现稳定策略契约并提供独立前端模块，不需要修改通用 HTTP 路由或后台任务执行器。
架构和接入说明见 [多策略选股架构](docs/strategy_architecture.md)。

### 断点续跑与数据缺口补跑

量化初筛在开始逐股处理前会固化有序股票池及 SHA-256，随后为每只股票保存
`PENDING / PROCESSING / COMPLETED / RETRYABLE_FAILED` 状态和追加式尝试记录。
工作进程通过短期租约和独立心跳线程防止同一运行被并发处理；即使单只股票的数据源
调用超过租约周期，也会持续续租：

```bash
# 仅处理没有完整结束或尚未产生决策的标的
python main.py resume-tier1 --run-id RUN_ID

# 仅补跑无决策、DATA_ERROR、PENDING_DATA 或异常中断的标的
python main.py retry-tier1-data --run-id RUN_ID
```

Web 控制台会在运行停止且租约过期后显示“从断点继续”；完成运行存在数据缺口时
显示“补跑数据缺口”。续跑沿用原 `run_id`、原配置和原股票池，不重新处理正常完成
标的。旧版本运行没有股票池快照时，系统只会在重新获取的股票池通过原时点和数量
校验后建立兼容快照，否则失败关闭。

## 数据源

| 来源 | 正式用途 | 点时边界 |
|---|---|---|
| AKShare/东方财富 | 当前行情、正式利润表、分红、部分历史简称 | 历史股票池能力有限 |
| Tushare Pro | 点时股票池、PE/市值、营业收入、归母净利润、分红、历史ST | 需 `TUSHARE_TOKEN` |
| BaoStock | 沪深历史行情、PE、每日ST、分红和送转 | 不用于近似季度财务趋势 |
| SQLite | 运行、原始观察、血缘、质量、评估和人工复核 | 追加式版本迁移 |

配置顺序由 `GOLDEN_PIT_DATA_SOURCES=akshare,tushare,baostock` 控制，同一字段会先
尝试能力登记为 `EXACT` 的来源，再按配置顺序回退；分红和风险警示只有 `LIMITED`
覆盖时不能形成硬条件通过。连续失败的数据源会短时熔断，避免全市场任务持续冲击
异常接口。旧变量 `TIER1_DATA_SOURCES` 仍作为兼容别名。当前筛选可采用通过
字段契约验证的供应商PE；历史回扫采用点时自计算并同时保存供应商值和自计算值。

## 正式CLI

| 命令 | 作用 |
|---|---|
| `workflow` | 启动或检查正式A→B→C工作流 |
| `screen-tier1` | 执行量化初筛 |
| `verify-tier1-sources` | 多源口径与数值交叉验证 |
| `show-tier1` | 查看某次量化初筛结果 |
| `resume-tier1` | 使用固化股票池跳过已完成标的并断点续跑 |
| `retry-tier1-data` | 补跑未产生决策或数据状态异常的标的 |
| `export/import/review-tier2` | 证据研究包、研究导入和人工确认 |
| `export/import/review-tier3` | 风险终审模板、风险导入和人工终审 |
| `tier1/2/3-migrate` | 应用或回滚对应阶段迁移 |

## 项目结构

```text
config/                         正式阈值、Schema和行业风险规则
src/data/point_in_time/         AKShare、Tushare、BaoStock点时适配
src/data/quality/               来源能力、质量评估和闸门
src/evidence/                   快照、哈希、摘录和事实映射验证
src/screening/tier1_v2/         量化初筛规则
src/screening/tier2_human_ai/   证据研究包和结论状态机
src/risk/tier3/                 风险终审行业化模型
src/storage/                    三阶段 SQLite 仓储
src/strategies/                 可注册选股策略、读模型与策略动作
src/execution/                  策略无关的后台任务执行能力
src/web/                        多策略Web平台、通用API与独立策略展示模块
scripts/migrations/             版本化、原子数据库迁移
tests/                          离线业务测试和实时数据canary
```

## 验证

```bash
python -m pytest -q
python -m ruff check --select F,I main.py web_app.py deploy_check.py src tests
python deploy_check.py
```

默认测试不访问网络。GitHub Actions定时运行AKShare、BaoStock以及配置Token后的
Tushare实时契约canary，结果用于发现供应商接口或字段口径变化。

## 免责声明

本系统仅为研究和事实核查工具，不构成投资建议。公开数据可能存在错误、修订或延迟；
任何投资判断都需要独立复核并自行承担风险。

## License

MIT License
