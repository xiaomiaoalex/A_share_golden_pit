# AI 研究与知识治理层架构

## 1. 定位

AI 研究层负责把策略定义、策略产出、标准化数据和原始证据发布为可追溯研究数据集，
允许大模型通过受控工具读取数据，按版本化提示词完成研究，并把结构化报告写入草稿库。
AI 不能直接连接生产数据库、修改原始数据、升级量化结论、修改正式策略或发送交易指令。

第一版产品闭环：

```text
选择黄金坑候选
  → 一键发布 AI 研究数据集
  → 预览将发送给模型的数据
  → 选择研究模板和模型策略
  → 查看工具调用、证据、进度和成本
  → 获得结构化研究报告
  → 人工审核
  → 发布到候选详情
```

## 2. 模块边界

建议代码结构：

```text
src/platform/ai_research/
  contracts/          数据集、模板、运行、报告和证据契约
  ingestion/          快照发布、文档解析、切分和索引
  retrieval/          SQL/DuckDB 查询与文档检索端口
  tools/              面向模型的只读白名单工具
  orchestration/      工具循环、预算、超时、重试和取消
  validation/         Schema、引用、数值和权限校验
  evaluation/         供应商无关的模型与提示词评测
  governance/         审批、发布、回滚、数据策略和审计
  providers/          模型供应商适配器
    deepseek/
    qwen/
    glm/
    kimi/
    openai/
  persistence/        追加式仓储
  presentation/       AI 研究中心后端读模型和前端模块
```

策略资源中的特定研究模板继续归策略所有，例如黄金坑候选研究模板位于
`src/strategies/golden_pit/resources/`；平台层只负责模板生命周期、执行和治理。

## 3. 核心契约

### 3.1 ResearchDataset

研究数据集不是整个业务库的副本，而是一次研究可读取范围的不可变清单：

- 数据集 ID、策略、策略发布和点时日期；
- 数据快照 ID、证券范围和数据类型；
- 结构化表/视图、文档和对象引用；
- 内容哈希、记录数、覆盖率和数据质量；
- 数据血缘、访问权限和外发策略；
- 索引状态、失败项和创建者。

状态：`DRAFT → VALIDATING → INDEXING → READY/PARTIAL/FAILED → ARCHIVED`。

### 3.2 ResearchTemplate

- 模板 ID、版本、研究类型和适用对象；
- developer/system prompt 和 user prompt 模板；
- 输入变量、允许工具和最大调用次数；
- 输出 Schema 版本；
- 模型策略、超时、Token 和成本预算；
- 引用要求、自动质量门槛和人工审核策略；
- 草稿、测试、正式、停用和回滚状态。

### 3.3 ResearchRun

- 数据集、模板、模型策略和发起人；
- 实际供应商、模型、适配器和参数；
- 输入摘要、工具调用、事件、重试和降级路径；
- Token、成本、延迟、限频和错误；
- 输出校验、人工审核和发布状态。

### 3.4 ResearchReport

最小字段：

```text
subject / strategy / release / as_of_date
thesis / verdict / confidence
findings / positive_evidence / counter_evidence
risks / assumptions / data_gaps
falsification_conditions / recommended_actions
dataset_snapshot / prompt_version / schema_version
provider / model / adapter_version / created_at
```

`verdict` 第一版使用：

- `SUPPORTIVE`
- `NEUTRAL`
- `CONTRADICTORY`
- `INSUFFICIENT_EVIDENCE`

每个重大结论必须关联 `EvidenceReference`。置信度由证据完整度、数据质量、多源一致性、
反证强度、时间有效性和模型自评共同计算，不能只采用模型随口给出的数字。

## 4. 模型供应商和默认路由

### 4.1 供应商优先级

默认采用中国模型优先：

| 优先级 | Provider | 第一阶段用途 | 说明 |
| --- | --- | --- | --- |
| 1 | DeepSeek | 单候选证据研究、复杂分析 | 默认首选 |
| 2 | 通义千问 | 自动降级、工具调用、多模态扩展 | 默认 fallback |
| 3 | 智谱 GLM | 评测通过后的备选研究模型 | 后续接入 |
| 4 | Kimi | 长文档研究和备选推理 | 后续接入 |
| 5 | OpenAI | 显式启用的质量对照或特殊能力 | 默认不自动外发 |

具体模型 ID 由配置管理，不写死在领域代码中。模型升级必须创建新的配置版本并通过回归
评测，不得静默替换历史研究使用的模型身份。

### 4.2 AIProviderPort

```python
class AIProviderPort(Protocol):
    def capabilities(self) -> ModelCapabilities: ...
    def health_check(self) -> ProviderHealth: ...
    def run_research(
        self,
        request: ProviderResearchRequest,
        tools: list[ResearchToolDefinition],
        output_schema: dict,
    ) -> ProviderResearchResult: ...
```

适配器负责处理供应商差异：

- Chat Completions、Responses 或供应商原生协议；
- 工具调用消息和思考模式历史回传；
- JSON mode、严格工具 Schema 和流式事件；
- Token/费用字段、限频和错误映射；
- 模型快照、请求 ID 和供应商元数据。

平台编排器负责统一：

- 权限、预算、超时、取消和重试；
- 工具执行、调用上限和审计；
- 本地 JSON Schema 校验；
- 引用、数值和数据外发校验；
- 自动降级和报告状态机。

### 4.3 DeepSeek 首选策略

DeepSeek 官方 API 提供 OpenAI 兼容调用、Tool Calls 和 JSON Output。其严格工具 Schema
目前可能处于 Beta 或能力存在版本差异，因此：

- 首版可以复用 OpenAI Python SDK，但使用独立 DeepSeek 适配器；
- 不把“OpenAI 兼容”理解为行为完全一致；
- 无论供应商是否支持 strict，返回结果都必须经过本地 Pydantic/JSON Schema 校验；
- JSON 空结果、截断和不合规输出按有限次数修复，随后失败关闭；
- 思考模式工具调用所需的供应商状态由适配器维护，不向前端展示私有推理内容；
- 只向前端展示工具调用、证据、事件和最终报告。

### 4.4 自动降级

自动降级仅在以下条件允许：

- 当前数据的外发策略允许目标供应商；
- 目标模型满足模板要求的工具、上下文和结构化输出能力；
- Provider 健康、预算和限频状态满足要求；
- 模型版本已经通过该模板对应的离线评测门槛。

建议的失败分类：

- `RATE_LIMITED`：按退避时间等待或切换；
- `TRANSIENT_PROVIDER_ERROR`：有限重试后切换；
- `CAPABILITY_MISMATCH`：不调用，直接选择兼容模型；
- `POLICY_BLOCKED`：禁止切换并提示人工处理；
- `INVALID_STRUCTURED_OUTPUT`：修复一次，仍失败则换模型或失败关闭；
- `INSUFFICIENT_EVIDENCE`：这是有效研究结论，不应自动换模型粉饰结果。

## 5. 受控数据读取

### 5.1 不开放任意 SQL

模型只获得白名单工具，例如：

- `get_strategy_release`
- `get_strategy_rules`
- `query_signals`
- `get_candidate_detail`
- `get_financial_series`
- `get_valuation_snapshot`
- `get_data_quality`
- `search_evidence_documents`
- `get_data_lineage`
- `compare_strategy_runs`
- `get_backtest_metrics`

每个工具必须定义严格参数、最大行数、最大时间范围、超时、字段白名单、权限和返回哈希。

### 5.2 按数据类型选择存储

| 数据 | 存储/访问 |
| --- | --- |
| 运行、模板、报告、审批 | 关系数据库 |
| 大规模结构化历史快照 | Parquet + DuckDB/Polars |
| 公告、文档和策略说明 | 对象存储/文件存储 |
| 文档块语义检索 | pgvector 或可替换向量检索端口 |
| 策略代码 | Git 版本、AST/摘要和必要片段检索 |

数值型数据使用确定性查询工具，不把全量财务序列转换成文本后仅依赖向量检索。

## 6. 数据出境和安全策略

每个数据域、字段和文档必须标记：

- `DOMESTIC_ALLOWED`：允许发送给已批准的中国模型服务；
- `APPROVED_EXTERNAL`：允许发送给经批准的境外服务；
- `MASK_BEFORE_SEND`：脱敏后才能发送；
- `LOCAL_ONLY`：只允许本地模型或本地工具读取；
- `DENY_AI`：禁止任何模型读取。

运行前由 `DataEgressPolicy` 对实际上下文逐项校验，前端展示即将发送的数据摘要、供应商、
地区、字段和预计大小。API Key 只保存在后端密钥系统中，日志不得记录密钥或完整敏感
正文。

外部文档一律视为不可信数据：文档内容不能修改系统规则、工具权限、预算和审批边界，
并需要提示词注入检测和来源隔离。

## 7. 输出校验和人工审批

研究结果按以下顺序进入平台：

```text
供应商输出
  → JSON/Pydantic Schema 校验
  → 引用存在性和访问范围校验
  → 数值与确定性数据对账
  → 数据时间点和质量校验
  → 业务规则校验
  → 研究草稿
  → 人工审核
  → 正式发布
```

自动拒绝条件至少包括：

- 重大结论没有证据引用；
- 引用不属于当前研究数据集；
- 财务数字与工具返回值不一致；
- 使用筛选日以后信息；
- 证据不足却输出明确支持或反对；
- 试图修改量化结论、正式策略或交易状态。

人工审核可以通过、驳回、要求重跑和补充备注，但不能无痕覆盖模型原始输出。

## 8. 前端 AI 研究中心

### AI 数据集

- 数据范围、策略发布、点时日期、质量、覆盖率和血缘；
- 索引进度、失败项、重建、停用和归档；
- 每个供应商可读取的数据范围。

### 提示词模板

- 模板编辑、变量、允许工具、Schema 和预算；
- 草稿、测试、发布、版本差异、回滚和评测结果。

### 发起研究

- 对象、数据集、模板、模型策略、预算和外部搜索策略；
- 发起前的数据外发预览和权限校验。

### 研究运行

- 当前步骤、工具调用、证据、进度、错误、重试和降级；
- Token、预计/实际成本、模型和请求 ID；
- 不展示供应商私有推理链。

### 研究报告

- 结论、正面证据、反证、风险、缺口和失效条件；
- 点击结论定位证据和原始数据；
- 人工审核、历史版本、模型对比和导出。

### 模型与成本管理

- Provider 健康、能力、限频和失败率；
- 模型路由、评测、质量、延迟和成本；
- 密钥配置状态、数据政策和供应商启停。

## 9. 评测与发布门槛

平台自己保存评测集、运行和 Grader，不依赖供应商托管评测作为长期唯一事实源。指标至少
包括：

- 输出 Schema 合规率；
- 引用存在率和引用支持度；
- 数值准确率；
- 点时信息违规率；
- 证据覆盖率和反证覆盖率；
- 幻觉率人工抽检；
- 人工通过、驳回和重跑率；
- 平均/分位延迟、Token 和成本；
- Provider 错误和自动降级成功率。

新模型、新模型版本或新提示词只有通过对应研究模板的回归评测后，才能进入正式路由。

## 10. MVP 范围

第一版严格限定：

- 策略：黄金坑；
- 对象：单只候选股票；
- 首选模型：DeepSeek；
- 降级模型：通义千问；
- 模板：候选证据研究；
- 工具：策略规则、候选详情、财务序列、数据质量、证据搜索；
- 输出：`ResearchReport v1`；
- 写入：研究草稿；
- 发布：必须人工审核。

在 MVP 的引用准确性、权限、成本和稳定性达到门槛前，不开放全市场批量研究、任意 SQL、
AI 自动修改策略或 AI 交易权限。

## 11. 官方实现参考

以下资料用于实现适配器和兼容性测试。接口能力与模型版本可能变化，开发时应重新核对：

- [DeepSeek：OpenAI/Anthropic 兼容调用](https://api-docs.deepseek.com/zh-cn/guides/function_calling/)
- [DeepSeek：Tool Calls](https://api-docs.deepseek.com/zh-cn/guides/tool_calls)
- [DeepSeek：JSON Output](https://api-docs.deepseek.com/zh-cn/guides/json_mode/)
- [通义千问：OpenAI 兼容 Responses API](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-responses)
- [通义千问：Function Calling](https://help.aliyun.com/zh/model-studio/qwen-function-calling)
- [通义千问：结构化输出](https://help.aliyun.com/zh/model-studio/qwen-structured-output)
- [OpenAI：Function Calling](https://developers.openai.com/api/docs/guides/function-calling)
- [OpenAI：Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
