# A股黄金坑股票数据库

以“重仓长周期确定性的高赔率”为第一原则，持续识别长期价值仍在、但价格因阶段性
悲观而明显错位的A股公司。本仓库只保留重构后的正式 Stage A/B/C 工作流。

## 正式研究链路

```text
Stage A：点时、硬条件、失败关闭的客观初筛
  → Stage B：可复核证据包 + 人机协作研究 + 人工确认
  → Stage C：行业化风险与价值陷阱过滤 + 人工终审
```

系统不使用机械综合分抵消致命缺陷。业务状态与数据状态分开保存；数据不足进入
`PENDING_DATA / DATA_ERROR / REVIEW`，不会被解释为通过。

## Stage A：Tier1严格筛选

五项硬条件必须全部明确成立：

1. 点时 `PE(TTM) < 15`；
2. 税前、已实施、按公司行动调整后的 `股息率(TTM) > 5%`；
3. 最近3个连续可比单季度的营业收入同比严格逐季改善；
4. 同一窗口的归母净利润同比严格逐季改善；
5. 截至筛选日不属于ST、*ST或其他风险警示股票。

利润同比窗口任一上年同期归母净利润小于等于0时进入
`TURNAROUND_WATCHLIST`，不会混入正式雷达池。历史全市场筛选只接受具备精确点时
能力的股票池；无合格来源时失败关闭，防止幸存者偏差。

```bash
python main.py screen-tier1 --as-of 2026-08-10 --symbols 000651 600519
python main.py screen-tier1 --as-of 2020-12-31 \
  --universe-file universe_20201231.csv
python main.py verify-tier1-sources --as-of 2026-08-10 --symbols 000651
python main.py show-tier1 --run-id RUN_ID
```

完整口径见 [Stage A说明](docs/stage_a_tier1_v2.md)。

## Stage B：SOR3.0人机协作研究

Stage B只接收同一运行中的 Stage A `PASS`。每条外部事实必须绑定：

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

完整契约见 [Stage B说明](docs/stage_b_tier2_human_ai.md) 和
[研究提示词](docs/tier2_ai_prompt_template.md)。

## Stage C：行业化风险与价值陷阱过滤

Stage C只接收最新 Stage B人工 `PASS`，按一般企业、银行、保险、地产四类模型检查
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

完整规则见 [Stage C说明](docs/stage_c_tier3_risk_filter.md)。

## 快速开始

```bash
python -m venv venv
# Linux/macOS: source venv/bin/activate
# Windows: venv\Scripts\activate
python -m pip install -r requirements.txt
python main.py tier3-migrate
python deploy_check.py
```

启动新的正式工作流，或检查已有运行：

```bash
python main.py workflow --as-of 2026-08-10 --symbols 000651 600519
python main.py workflow --run-id RUN_ID
```

`workflow` 会汇总A/B/C状态并给出下一条受控操作，不会自动越过AI研究或人工复核。

## 数据源

| 来源 | 正式用途 | 点时边界 |
|---|---|---|
| AKShare/东方财富 | 当前行情、正式利润表、分红、部分历史简称 | 历史股票池能力有限 |
| Tushare Pro | 点时股票池、PE/市值、营业收入、归母净利润、分红、历史ST | 需 `TUSHARE_TOKEN` |
| BaoStock | 沪深历史行情、PE、每日ST、分红和送转 | 不用于近似季度财务趋势 |
| SQLite | 运行、原始观察、血缘、质量、评估和人工复核 | 追加式版本迁移 |

默认顺序由 `TIER1_DATA_SOURCES=akshare,tushare,baostock` 控制。当前筛选可采用通过
字段契约验证的供应商PE；历史回扫采用点时自计算并同时保存供应商值和自计算值。

## 正式CLI

| 命令 | 作用 |
|---|---|
| `workflow` | 启动或检查正式A→B→C工作流 |
| `screen-tier1` | 执行Stage A严格筛选 |
| `verify-tier1-sources` | 多源口径与数值交叉验证 |
| `show-tier1` | 查看某次Stage A结果 |
| `export/import/review-tier2` | Stage B证据包、研究导入和人工确认 |
| `export/import/review-tier3` | Stage C模板、风险导入和人工终审 |
| `tier1/2/3-migrate` | 应用或回滚对应阶段迁移 |

## 项目结构

```text
config/                         正式阈值、Schema和行业风险规则
src/data/point_in_time/         AKShare、Tushare、BaoStock点时适配
src/data/quality/               来源能力、质量评估和闸门
src/evidence/                   快照、哈希、摘录和事实映射验证
src/screening/tier1_v2/         Stage A硬筛选
src/screening/tier2_human_ai/   Stage B证据包和结论状态机
src/risk/tier3/                 Stage C行业化风险模型
src/storage/                    Stage A/B/C SQLite仓储
scripts/migrations/             版本化、原子数据库迁移
tests/                          离线业务测试和实时数据canary
```

## 验证

```bash
python -m pytest -q
python -m ruff check --select F,I main.py deploy_check.py src tests
python deploy_check.py
```

默认测试不访问网络。GitHub Actions定时运行AKShare、BaoStock以及配置Token后的
Tushare实时契约canary，结果用于发现供应商接口或字段口径变化。

## 免责声明

本系统仅为研究和事实核查工具，不构成投资建议。公开数据可能存在错误、修订或延迟；
任何投资判断都需要独立复核并自行承担风险。

## License

MIT License
