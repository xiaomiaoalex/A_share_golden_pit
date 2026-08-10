# 阶段B：Tier2 SOR3.0人机协作MVP

## 1. 业务边界

阶段B只消费指定 `screening_runs.run_id` 下 `tier1_decisions.screen_status=PASS`
的股票。它不调用旧 `DeepScreener`，不使用机械综合分替代关键维度，也不自动调用
外部AI。

正式流程为：

```text
Tier1 PASS
  → 逐股、点时证据包
  → 人工交给研究型AI并取得固定JSON
  → Schema/时点/证券/证据哈希校验
  → 系统关键维度否决
  → 人工最终确认
```

系统结论只有 `PASS / REVIEW / REJECT`。任何维度 `FAIL` 均为 `REJECT`；任何
关键维度为 `WARN` 或 `INSUFFICIENT_EVIDENCE` 均为 `REVIEW`。三情景缺数或悲观
情景永久损失风险未知时也只能 `REVIEW`。AI顶层建议只能使结论更保守，不能抵消
维度否决。人工可以维持或下调系统结论，不能上调，并且只能复核该股票最新AI评估。

## 2. 数据质量与证据包

证据包的粒度为“一次Tier1运行 × 一只股票 × 一个as-of日期”。导出器只读取绑定
同一次运行的Tier1决策、季度序列、原始财务值、已实施税前分红、字段血缘、抓取
元数据、多源验证和质量评估。

证据区块采用 `AVAILABLE / PARTIAL / MISSING`，不会用空数组伪装成零值，也不会把
旧 `financial_data` 表中缺少公告日/可得时间的数据当作历史点时证据。导出时再次
检查公告日、可得时间、修订时间和除权日；发现as-of之后的记录会拒绝生成证据包。

当前Tier1数据层通常只能完整支持客观筛选指标，以下研究证据常为显式缺口：五年
完整财报、毛利率/ROIC、现金流与CAPEX、非经常损益、分部信息、行业需求、市场
份额、历史估值和逆向估值。业务可以继续运行，但AI与人工必须把未补齐的关键证据
保留为 `REVIEW`，不得强行形成通过结论。

每个包保存SHA-256内容哈希。AI结果必须原样返回 `package_id`、哈希、run、股票和
as-of；任一不一致都按陈旧证据或串股结果拒绝。AI可以补充截至as-of已经公开的公司
公告、官方数据和行业资料，但非证据不足结论必须同时包含事实和可定位来源，来源
日期不得晚于as-of。

## 3. JSON契约和人工复核

固定Schema为 `config/tier2_ai_schema.json`，提示词为
`docs/tier2_ai_prompt_template.md`。七个维度必须各出现一次：

1. `demand_durability`
2. `competitive_position`
3. `dividend_sustainability`
4. `earnings_quality`
5. `market_mispricing`
6. `risk_reward_asymmetry`
7. `long_cycle_fit`

每个维度分别保存事实、推断、反方证据、来源、推理摘要和证伪条件。三情景必须为
`PESSIMISTIC / BASE / OPTIMISTIC`，同时记录3年和5年年化回报及永久损失风险。

导入支持单个JSON对象、对象数组或 `{"results": [...]}`。批次先全部验证再开启写入；
其中任一结果失败时整批不落库。

## 4. 命令

```bash
python main.py export-tier2 --run-id RUN_ID
python main.py import-tier2 --file ai_results.json
python main.py review-tier2 --run-id RUN_ID

# 记录人工决定；不提供assessment-id时取该股票最新评估
python main.py review-tier2 --run-id RUN_ID --symbol 000651 \
  --decision REVIEW --reviewer "研究员" --rationale "行业需求证据仍需补齐"

# 可选生成Markdown状态报告
python main.py review-tier2 --run-id RUN_ID --output output/tier2/review.md

python main.py tier2-migrate
python main.py tier2-migrate --rollback
```

默认输出目录为 `output/tier2/RUN_ID`，每只股票各有一个JSON和Markdown，同时生成
总索引、Schema副本和提示词副本。

## 5. 数据库迁移

`003_tier2_human_ai_up.sql` 增量新增：

- `tier2_evidence_packages`：不可变证据内容、覆盖率、哈希和文件位置；
- `ai_assessments`：AI原始建议与系统否决后建议分开保存；
- `human_reviews`：追加式人工复核及被替代关系。

迁移不修改旧5张表和Stage A表。`tier2-migrate --rollback` 只删除Stage B三张表；
完整Stage A回滚会先删除有外键依赖的Stage B表。

## 6. 离线验收

```bash
python -m pytest -q
python -m ruff check --select F main.py config/tier1.py \
  src/data/point_in_time src/data/quality src/screening/tier1_v2 \
  src/screening/tier2_human_ai src/storage tests
```

测试覆盖：只导出Tier1 PASS、证据缺口不隐藏、未来数据拒绝、Schema非法拒绝、批量
原子性、证据哈希绑定、关键证据不足只能REVIEW、维度FAIL硬否决、人工不可上调、
人工确认必需、Stage B回滚保留Stage A和旧表。默认测试不访问网络。
