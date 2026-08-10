# 多策略选股架构

本项目把“选股平台”和“具体选股策略”视为两个不同的变化轴。当前 Stage A/B/C
黄金坑流程是首个策略模块，不是平台的固定工作流。策略规则可以独立升级；新增策略
不应要求修改通用 HTTP 路由、后台任务执行器或首页代码。

## 分层边界

| 层 | 目录 | 职责 | 不应承担 |
| --- | --- | --- | --- |
| 数据层 | `src/data/`、`src/storage/` | 点时数据契约、数据源适配、质量评估和持久化 | 选股阈值、页面文案 |
| 策略层 | `src/strategies/<strategy_id>/` | 策略元数据、规则编排、动作校验和结果读模型 | HTTP、线程或进程管理 |
| 执行层 | `src/execution/` | 通用后台任务生命周期和可观测状态 | 理解 Stage A/B/C 等策略语义 |
| 接口层 | `src/web/server.py` | 根据策略 ID 路由查询和动作，返回统一 HTTP 响应 | 拼装具体策略命令或直接读业务表 |
| 展示层 | `src/web/static/app.js`、`src/web/static/strategies/` | 平台策略总览、策略模块装载和各策略独立交互 | 数据抓取和业务规则计算 |

依赖方向是平台契约指向具体模块，而不是核心服务器引用黄金坑实现：

```text
Web shell ──> StrategyRegistry ──> StrategyModule
                                      ├── read model ──> storage
                                      └── operation  ──> JobRegistry
```

## 策略契约

每个策略实现 `src/strategies/contracts.py` 中的 `StrategyModule`：

- `descriptor`：稳定 ID、名称、版本、独立前端模块和能力说明；
- `catalog_entry()`：首页所需的小型策略摘要；
- `overview(run_id)`：该策略自己的完整结果投影；
- `running_runs()`：供通用任务中心聚合运行状态；
- `handle_action(action, body)`：校验策略动作并返回命令或同步结果。

通用服务器只识别以下形式的接口：

```text
GET  /api/strategies
GET  /api/strategies/{strategy_id}/overview
POST /api/strategies/{strategy_id}/actions/{action}
```

旧黄金坑 API 暂时作为兼容别名保留，新代码应使用按策略 ID 隔离的接口。

## 新增策略

1. 在 `src/strategies/<strategy_id>/` 实现策略模块和独立读模型。
2. 复用稳定的数据契约；需要新数据时，在数据层增加 provider 能力，不在策略中直接
   调第三方接口。
3. 在 `build_strategy_registry()` 这一处组合根注册模块。
4. 在 `src/web/static/strategies/<strategy_id>.js` 提供独立展示模块，通过
   `window.StrategyConsole.register()` 注册。
5. 为策略注册、动作派发、读模型和独立 UI 资源补测试。

新增策略不应在 `server.py` 添加专属 `if/elif` 路由。策略规则调整也不应修改通用执行
器或其他策略的数据投影。

## 黄金坑模块

当前黄金坑策略位于 `src/strategies/golden_pit/`：

- `module.py` 拥有策略元数据和 Stage A/B/C 动作映射；
- `presentation.py` 只负责把黄金坑正式表投影为该策略页面所需结果；
- 具体筛选、证据研究和风险终审规则仍分别由现有 screening/risk 领域模块实现；
- `src/web/static/strategies/golden-pit.js` 独立管理黄金坑页面交互。

当阈值、阶段或研究流程调整时，变更应限制在黄金坑策略及其领域实现内，不改变其他
策略的接口和展示。
