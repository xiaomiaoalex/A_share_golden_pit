# 路线图验收矩阵

本矩阵记录当前仓库对 `development_roadmap.md` 的可执行验收。第三方框架和真实模型调用均
通过平台契约接入；没有 API Key 时使用 Mock Provider 验证治理闭环，不伪造线上调用。

| 阶段 | 已交付 | 自动验收 |
| --- | --- | --- |
| 0 | LIMITED 质量闸门、续租与 fencing、追加式决策、分页 API、显式迁移、CI | `test_tier1_*`、`test_web_dashboard.py` |
| 1 | 策略参数/上下文/发布清单、统一信号、第二策略、AI 研究状态机与 Mock Provider | `test_strategy_registry.py`、`test_research_contracts.py` |
| 2 | 永久证券 ID、代码/状态/财报版本、交易日历、公司行动、不可变 Parquet、DuckDB 白名单查询、证据索引与字段外发策略 | `test_point_in_time_foundation.py`、`test_evidence_retrieval.py` |
| 3 | 持久化优先级任务、DAG、暂停/恢复/取消、重试预算、熔断、死信、心跳与复现元数据；DeepSeek/Qwen Provider、有限降级和本地校验 | `test_job_registry.py`、`test_durable_orchestration.py`、`test_ai_providers.py` |
| 4 | Qlib 产物隔离适配、walk-forward、IC/Rank IC/分组收益/自相关/换手、AI 本地 Grader、晋级门槛和版本化评测产物 | `test_advanced_analytics.py`、`test_ai_evaluation.py` |
| 5 | 回测规范及 T+1、整手、涨跌停、停牌、费用、冲击、容量黄金场景，以及 vn.py 隔离适配和双引擎差异定位 | `test_research_backtest_portfolio_governance.py`、`test_signal_materialization_and_adapters.py` |
| 6 | 等权/信号/风险平价/均值方差/BL/HRP、流动性、个股/行业/Beta/波动/换手硬约束和确定性不可行原因 | `test_advanced_analytics.py`、`test_research_backtest_portfolio_governance.py` |
| 7 | 草稿→验证→Shadow→生产生命周期、RBAC、追加式审计、AI 注入/工具/预算治理、漂移监控、可恢复备份和人工控制 Shadow OMS | `test_ai_governance.py`、`test_shadow_oms.py`、`test_operational_readiness.py` |

## 外部依赖说明

- DeepSeek、通义 API 只有后端环境变量配置后才会发起真实请求；API Key 不进入浏览器或日志。
- Qlib、vn.py、OpenBB、CVXPY/PyPortfolioOpt 保持可选适配器边界。当前确定性核心和黄金场景不依赖
  这些大型框架，因此离线 CI 可重复运行；生产采用这些框架时必须新增独立适配器 PR 和
  双引擎/约束对照验收。
- 券商网关和真实下单不在默认启用范围内。路线图将其定义为可选闭环，AI 永远不获得直接
  下单权限。
- GLM、Kimi 和 OpenAI 已具备相同端口的配置驱动适配器；未配置密钥时不会发起网络请求。
  境外 Provider 还必须同时通过模型政策和字段外发政策。

## 安全边界

- `MASK_BEFORE_SEND` 字段只有生成独立、可审计的脱敏快照后才可发布；仅配置掩码规则不会
  把原始 Parquet 外发。
- 所有变更 API 在配置 `PLATFORM_API_TOKEN` 后要求 `X-Platform-Token`；密钥仅保存在后端。
- AI 只能生成追加式研究草稿或策略变更提案，不能覆盖量化事实、发布策略或直接创建订单。

## 运行验收

```bash
python main.py migrate
python deploy_check.py
python -m pytest -q
python -m ruff check --select F,I main.py web_app.py deploy_check.py src tests
node --check src/web/static/app.js
python scripts/dependency_inventory.py
python scripts/backup_database.py data/db/strategy_platform.db output/strategy_platform.backup.db
```
