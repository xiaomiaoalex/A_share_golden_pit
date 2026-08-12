# 黄金坑策略 · 风险终审

## 1. 正式业务链路

Stage C只接收同一 `run_id` 下、绑定最新证据包和最新AI评估、且最新人工复核为
`PASS` 的Stage B股票。旧 `AShareRiskChecker`、`FinancialRedFlagDetector` 和旧
Tier3评分不会进入正式链路。

```text
Stage B最新人工PASS
  → 显式行业分类及来源
  → 行业化风险研究模板
  → 结构化风险证据导入
  → 硬否决/警告/缺口状态机
  → 人工最终确认
```

Stage C不再评价“估值是否便宜”，只寻找足以推翻投资逻辑的风险证据。

## 2. 六类风险与输出

所有规则归入以下类别：

- `ACCOUNTING_QUALITY`：财务真实性与会计质量；
- `LIQUIDITY`：偿债、资本或流动性风险；
- `DIVIDEND_SUSTAINABILITY`：分红资金来源；
- `GOVERNANCE`：治理、大股东和关联方风险；
- `CYCLE_PEAK`：周期顶部利润误判；
- `STRUCTURAL_VALUE_TRAP`：结构性价值陷阱。

每项检查输入状态为：

- `TRIGGERED`：风险证据成立；
- `CLEAR`：有证据支持风险未成立；
- `UNKNOWN`：暂无可靠证据；
- `NOT_APPLICABLE`：仅规则配置明确允许时可用，当前必要规则均不允许自行跳过。

系统输出：

- 任一 `HARD_VETO + TRIGGERED`：`REJECT`；
- 无硬否决，但存在 `WARNING + TRIGGERED`：`REVIEW`；
- 任一必要检查为 `UNKNOWN`：`REVIEW`；
- 全部必要检查有证据且为 `CLEAR`：系统 `PASS`，仍需人工确认。

人工只能维持或下调系统结论，不能用总分、估值或主观判断覆盖硬否决、警告和数据
缺口。Stage B后续产生新证据包、AI评估或人工决定时，旧Stage C评估不得继续终审。

## 3. 行业适配模型

行业模型必须显式选择并给出出处，系统不会因行业字段缺失而默认套用工业模型。

| 模型 | 重点口径 | 明确不使用的替代口径 |
|---|---|---|
| `IndustrialRiskModel` | CFO/利润、营运资本、非经常损益、CAPEX、短债、正常化利润 | 缺数据默认低风险 |
| `BankRiskModel` | 监管资本、资产质量、拨备、流动性、信用集中、正常化信用成本 | 工业企业FCF/CAPEX模型 |
| `InsuranceRiskModel` | 偿付能力、准备金、资产负债匹配、投资资产、新业务价值 | 工业企业资产负债率阈值 |
| `RealEstateRiskModel` | 受限现金、短债、保交付、表外义务、项目存货、回款 | 账面现金全额可用、统一存货比例 |

规则与依据位于 `src/strategies/golden_pit/resources/tier3_risk_rules.json`。当前设计使用可证据化的风险命题，不设
跨行业统一的负债率、商誉率或现金流比率。原因是统一的“精确阈值”会把银行负债、
保险准备金、地产预收款和工业企业有息债务错误混为一谈。研究者可以在每项
`metrics` 中保存原始数值、单位、期间和定义，但触发判断必须在来源和推理中解释
行业口径。未来如增加数值阈值，应在规则配置中同时记录适用行业、统计口径和依据。

## 4. 数据质量约束

风险终审输入 Schema 为 `src/strategies/golden_pit/resources/tier3_risk_input_schema.json`，并执行以下防线：

1. 股票、run、as-of和Stage B review必须绑定最新人工PASS；
2. 行业分类必须有来源，不能自动猜测；
3. 检查集合必须与所选行业模型完全一致，不能混入其他行业规则；
4. `TRIGGERED/CLEAR` 必须同时包含事实、反方证据和来源；
5. 来源发布日期和带时区的 `available_at` 不得晚于as-of；本地快照哈希、可定位摘录
   和事实映射必须通过校验；PDF等二进制原件必须另附可检索文本及其哈希；
6. `UNKNOWN` 置信度不得高于0.5；
7. NaN、无穷值和Schema异常拒绝导入；
8. 批量输入先全部验证，任一失败时整批不写库；
9. 原始风险输入、规范化检查结果和系统评估分表保存；
10. 数据缺失不会形成“低风险”或自动PASS。

## 5. 使用方法

先准备显式行业分类文件：

```json
[
  {
    "symbol": "000001",
    "industry_model": "BANK",
    "industry": "商业银行",
    "rationale": "主营业务和监管口径均属于商业银行",
    "sources": [
      {
        "title": "年度报告",
        "publisher": "公司名称",
        "date": "2026-03-20",
        "available_at": "2026-03-20T18:30:00+08:00",
        "url_or_document": "请替换为公告链接或本地文档",
        "page_or_section": "公司业务概要",
        "snapshot_path": "evidence/annual-report.txt",
        "content_sha256": "请替换为64位SHA-256",
        "evidence_excerpt": "请复制快照中能够支持行业分类的原文片段",
        "supported_claims": ["主营业务和监管口径均属于商业银行"]
      }
    ]
  }
]
```

日期、可得时间、来源、快照和哈希必须替换为截至本次as-of真实可得的信息。URL只作
定位线索，不能替代本地证据快照。行业分类文件中的相对路径以该分类文件所在目录为
基准，导出时立即验证并规范化为绝对路径；风险检查结果新增来源的相对路径则以待导入
JSON文件所在目录为基准。

```bash
python main.py export-tier3 --run-id RUN_ID \
  --classification-file industries.json

# 逐项研究并填写导出的JSON后导入
python main.py import-tier3 --file filled_tier3_results.json

python main.py review-tier3 --run-id RUN_ID
python main.py review-tier3 --run-id RUN_ID --symbol 000001 \
  --decision REVIEW --reviewer "风险研究员" \
  --rationale "资产质量穿透证据仍需补齐"

python main.py review-tier3 --run-id RUN_ID \
  --output output/tier3/RUN_ID/risk_report.md

python main.py tier3-migrate
python main.py tier3-migrate --rollback
```

默认输出目录为 `output/tier3/RUN_ID`。每家公司生成一个可填写JSON和一个规则说明
Markdown，同时复制当次Schema和规则配置，确保研究时能复现规则版本。

## 6. 数据库迁移

`004_tier3_risk_filter_up.sql` 增量新增：

- `tier3_risk_inputs`：原始结构化风险研究及内容哈希；
- `tier3_risk_checks`：逐规则、逐来源的规范化结果；
- `tier3_risk_assessments`：硬否决、警告、价值陷阱、证伪条件和系统状态；
- `tier3_human_reviews`：追加式人工终审。

迁移不修改旧5张表及Stage A/B表。Stage C回滚只删除上述四张表；Stage A/B完整
回滚会先删除下游Stage C表，避免留下外键依赖。

## 7. 验收与当前边界

```bash
python -m pytest -q
python -m ruff check src/risk/tier3 src/storage/tier3_repository.py \
  tests/unit/test_tier3_risk_filter.py
```

离线测试覆盖Stage B准入、四种行业模型隔离、全部CLEAR、必要数据UNKNOWN、警告、
硬否决、价值陷阱、未来来源、来源快照篡改、摘录和事实映射、NaN、跨行业规则混用、
批次原子性、人工不可上调和增量回滚。实时接口不作为业务逻辑验收依据。

当前MVP不会自动抓取所有审计、诉讼、质押、项目现金和监管资本数据，也不会自动
调用外部AI。系统先把研究结构、证据标准、行业口径和否决逻辑做成可运行闭环；没有
可靠数据的检查保持 `UNKNOWN/REVIEW`，后续再按数据源可得性逐项自动化。
