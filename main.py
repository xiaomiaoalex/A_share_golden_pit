#!/usr/bin/env python3
"""A股黄金坑股票数据库正式 Stage A/B/C CLI。"""

import argparse
import json
import logging
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from config.settings import settings


def setup_logging() -> None:
    """配置正式工作流日志。"""
    settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = settings.LOG_DIR / f"golden_pit_{date.today():%Y%m%d}.log"
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def build_parser() -> argparse.ArgumentParser:
    """构建CLI参数解析器

    Returns:
        配置好的ArgumentParser实例
    """
    parser = argparse.ArgumentParser(
        description='A股黄金坑股票数据库 - 量化价值投资筛选系统',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py screen-tier1 --as-of 2026-08-10 --symbols 000651 600519
  python main.py verify-tier1-sources --as-of 2026-08-10 --symbols 000651
  python main.py show-tier1 --run-id RUN_ID
  python main.py export-tier2 --run-id RUN_ID
  python main.py import-tier2 --file ai_results.json
  python main.py review-tier2 --run-id RUN_ID
  python main.py export-tier3 --run-id RUN_ID --classification-file industries.json
  python main.py import-tier3 --file tier3_results.json
  python main.py review-tier3 --run-id RUN_ID
  python main.py workflow --as-of 2026-08-10 --symbols 000651
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='可用命令')

    # Stage A 独立命令；不加载或调用旧Tier2/Tier3。
    tier1_parser = subparsers.add_parser(
        'screen-tier1', help='执行严格、点时、fail-closed的Tier1 v2筛选'
    )
    tier1_parser.add_argument('--as-of', required=True, help='筛选日期 YYYY-MM-DD')
    tier1_parser.add_argument('--symbols', nargs='+', help='可选股票代码列表')
    tier1_parser.add_argument(
        '--universe-file', help='可选CSV股票池，需含symbol/stock_code/code列'
    )
    tier1_parser.add_argument('--limit', type=int, help='仅处理前N只，供人工验收')
    tier1_parser.add_argument('--db', default=str(settings.DB_PATH), help='SQLite数据库路径')

    verify_sources_parser = subparsers.add_parser(
        'verify-tier1-sources', help='对指定股票执行Tier1多源口径交叉验证'
    )
    verify_sources_parser.add_argument('--as-of', required=True, help='验证日期 YYYY-MM-DD')
    verify_sources_parser.add_argument('--symbols', nargs='+', required=True, help='股票代码列表')
    verify_sources_parser.add_argument('--output', help='可选JSON输出文件')
    verify_sources_parser.add_argument(
        '--db', default=str(settings.DB_PATH), help='质量验证记录SQLite路径'
    )
    verify_sources_parser.add_argument('--run-id', help='可选：绑定已有Tier1筛选运行')
    verify_sources_parser.add_argument(
        '--no-persist', action='store_true', help='仅输出结果，不写入质量验证记录'
    )

    show_tier1_parser = subparsers.add_parser('show-tier1', help='查看Tier1 v2某次运行结果')
    show_tier1_parser.add_argument('--run-id', required=True, help='筛选运行ID')
    show_tier1_parser.add_argument('--db', default=str(settings.DB_PATH), help='SQLite数据库路径')

    migrate_tier1_parser = subparsers.add_parser(
        'tier1-migrate', help='应用或回滚Stage A新增表迁移'
    )
    migrate_tier1_parser.add_argument('--rollback', action='store_true', help='仅删除Stage A新增表')
    migrate_tier1_parser.add_argument('--db', default=str(settings.DB_PATH), help='SQLite数据库路径')

    export_tier2_parser = subparsers.add_parser(
        'export-tier2', help='为Tier1 PASS候选生成逐股Tier2证据包'
    )
    export_tier2_parser.add_argument('--run-id', required=True, help='已完成的Tier1运行ID')
    export_tier2_parser.add_argument('--symbols', nargs='+', help='可选：仅导出指定PASS股票')
    export_tier2_parser.add_argument('--output-dir', help='输出目录，默认output/tier2/RUN_ID')
    export_tier2_parser.add_argument('--db', default=str(settings.DB_PATH), help='SQLite数据库路径')

    import_tier2_parser = subparsers.add_parser(
        'import-tier2', help='校验并原子导入Tier2 AI JSON结果'
    )
    import_tier2_parser.add_argument('--file', required=True, help='AI JSON结果文件')
    import_tier2_parser.add_argument('--db', default=str(settings.DB_PATH), help='SQLite数据库路径')

    review_tier2_parser = subparsers.add_parser(
        'review-tier2', help='查看Tier2状态或记录人工最终复核'
    )
    review_tier2_parser.add_argument('--run-id', required=True, help='Tier1运行ID')
    review_tier2_parser.add_argument('--symbol', help='要复核的股票代码')
    review_tier2_parser.add_argument('--assessment-id', help='可选AI评估ID；默认取该股票最新评估')
    review_tier2_parser.add_argument('--decision', choices=['PASS', 'REVIEW', 'REJECT'])
    review_tier2_parser.add_argument('--reviewer', help='人工复核人')
    review_tier2_parser.add_argument('--rationale', help='人工复核理由，不得为空')
    review_tier2_parser.add_argument('--output', help='可选Markdown复核报告路径')
    review_tier2_parser.add_argument('--db', default=str(settings.DB_PATH), help='SQLite数据库路径')

    migrate_tier2_parser = subparsers.add_parser(
        'tier2-migrate', help='应用当前迁移或仅回滚Stage B新增表'
    )
    migrate_tier2_parser.add_argument('--rollback', action='store_true', help='仅删除Stage B新增表')
    migrate_tier2_parser.add_argument('--db', default=str(settings.DB_PATH), help='SQLite数据库路径')

    export_tier3_parser = subparsers.add_parser(
        'export-tier3', help='为Stage B人工PASS股票生成行业化风险研究模板'
    )
    export_tier3_parser.add_argument('--run-id', required=True, help='Tier1/Stage B运行ID')
    export_tier3_parser.add_argument(
        '--classification-file', required=True, help='显式行业分类JSON文件'
    )
    export_tier3_parser.add_argument('--output-dir', help='默认output/tier3/RUN_ID')
    export_tier3_parser.add_argument('--db', default=str(settings.DB_PATH), help='SQLite数据库路径')

    import_tier3_parser = subparsers.add_parser(
        'import-tier3', help='校验、行业化评估并原子导入Stage C风险输入'
    )
    import_tier3_parser.add_argument('--file', required=True, help='已完成的风险研究JSON')
    import_tier3_parser.add_argument('--db', default=str(settings.DB_PATH), help='SQLite数据库路径')

    review_tier3_parser = subparsers.add_parser(
        'review-tier3', help='查看Stage C结果或记录人工最终复核'
    )
    review_tier3_parser.add_argument('--run-id', required=True, help='运行ID')
    review_tier3_parser.add_argument('--symbol', help='要复核的股票代码')
    review_tier3_parser.add_argument('--risk-assessment-id', help='默认取该股票最新风险评估')
    review_tier3_parser.add_argument('--decision', choices=['PASS', 'REVIEW', 'REJECT'])
    review_tier3_parser.add_argument('--reviewer', help='人工复核人')
    review_tier3_parser.add_argument('--rationale', help='复核理由')
    review_tier3_parser.add_argument('--output', help='可选Markdown报告路径')
    review_tier3_parser.add_argument('--db', default=str(settings.DB_PATH), help='SQLite数据库路径')

    migrate_tier3_parser = subparsers.add_parser(
        'tier3-migrate', help='应用当前迁移或仅回滚Stage C新增表'
    )
    migrate_tier3_parser.add_argument('--rollback', action='store_true', help='仅删除Stage C新增表')
    migrate_tier3_parser.add_argument('--db', default=str(settings.DB_PATH), help='SQLite数据库路径')

    workflow_parser = subparsers.add_parser(
        'workflow', help='启动或检查正式Stage A→B→C工作流'
    )
    workflow_parser.add_argument('--as-of', help='新建工作流时的筛选日期 YYYY-MM-DD')
    workflow_parser.add_argument('--run-id', help='检查已有正式工作流')
    workflow_parser.add_argument('--symbols', nargs='+', help='新建工作流时的股票代码列表')
    workflow_parser.add_argument('--universe-file', help='新建工作流时的点时股票池CSV')
    workflow_parser.add_argument('--limit', type=int, help='新建工作流时仅处理前N只')
    workflow_parser.add_argument('--db', default=str(settings.DB_PATH), help='SQLite数据库路径')

    return parser


def _parse_as_of(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("--as-of 必须是有效的 YYYY-MM-DD 日期") from exc


def _normalize_symbol(value: object) -> str:
    raw = str(value).strip().upper()
    if raw.endswith((".SH", ".SZ", ".BJ")):
        raw = raw[:-3]
    for prefix in ("SH", "SZ", "BJ"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break
    if not re.fullmatch(r"\d{1,6}", raw):
        raise ValueError(f"无效股票代码: {value}")
    return raw.zfill(6)


def _load_universe_file(path: str):
    from src.data.point_in_time.akshare_adapter import AKSharePointInTimeProvider
    from src.data.point_in_time.contracts import UniverseItem

    frame = pd.read_csv(path, dtype=str)
    columns = {str(column).strip().lower(): column for column in frame.columns}
    symbol_column = next(
        (columns[key] for key in ('symbol', 'stock_code', 'code') if key in columns),
        None,
    )
    if symbol_column is None:
        raise ValueError("股票池CSV缺少 symbol、stock_code 或 code 列")
    name_column = next(
        (columns[key] for key in ('name', 'stock_name') if key in columns), None
    )
    exchange_column = columns.get('exchange')
    items = []
    seen = set()
    for _, row in frame.iterrows():
        raw_symbol = str(row[symbol_column]).strip()
        if not raw_symbol or raw_symbol.lower() == 'nan':
            continue
        symbol = _normalize_symbol(raw_symbol)
        if symbol in seen:
            continue
        seen.add(symbol)
        name = str(row[name_column]).strip() if name_column else symbol
        if not name or name.lower() == 'nan':
            name = symbol
        exchange = (
            str(row[exchange_column]).strip().upper()
            if exchange_column and pd.notna(row[exchange_column])
            else AKSharePointInTimeProvider.exchange_for(symbol)
        )
        items.append(UniverseItem(symbol=symbol, name=name, exchange=exchange))
    if not items:
        raise ValueError("股票池CSV没有有效股票代码")
    return items


def _run_tier1_command(args) -> dict:
    from src.data.point_in_time.provider_factory import build_point_in_time_provider
    from src.screening.tier1_v2.pipeline import Tier1Pipeline
    from src.storage.tier1_repository import Tier1Repository

    as_of_date = _parse_as_of(args.as_of)
    repository = Tier1Repository(args.db)
    from config.tier1 import Tier1Config

    tier1_config = Tier1Config()
    provider = build_point_in_time_provider(tier1_config)
    if as_of_date > provider.today:
        raise ValueError("--as-of 不得晚于当前日期")
    historical_universe = as_of_date < provider.today
    if historical_universe and not args.universe_file and not args.symbols:
        raise ValueError(
            "历史全市场筛选必须通过--universe-file提供点时股票池；"
            "也可用--symbols做指定股票历史复算"
        )
    universe_items = _load_universe_file(args.universe_file) if args.universe_file else None
    symbols = [_normalize_symbol(value) for value in args.symbols] if args.symbols else None
    try:
        result = Tier1Pipeline(provider, repository, tier1_config).run(
            as_of_date,
            symbols=symbols,
            universe_items=universe_items,
            limit=args.limit,
        )
    finally:
        provider.close()
    print(f"data_sources: {provider.provider_names}")
    for warning in provider.configuration_warnings:
        print(f"source_warning: {warning}")
    print(f"run_id: {result['run_id']}")
    print(f"status: {result['status']}")
    print(f"universe_size: {result.get('universe_size', 0)}")
    print(f"summary: {result.get('summary', {})}")
    print(f"data_quality: {result.get('data_quality', {})}")
    if result.get('errors'):
        print(f"errors: {result['errors']}")
    return result


def _formal_workflow_command(args) -> None:
    from src.storage.tier1_repository import Tier1Repository
    from src.storage.tier2_repository import Tier2Repository
    from src.storage.tier3_repository import Tier3Repository

    if bool(args.as_of) == bool(args.run_id):
        raise ValueError("workflow必须二选一提供--as-of（启动）或--run-id（检查）")
    run_id = args.run_id
    if args.as_of:
        result = _run_tier1_command(args)
        run_id = result["run_id"]

    tier1 = Tier1Repository(args.db)
    run = tier1.run_record(run_id)
    if run is None:
        raise ValueError(f"未知正式工作流run_id: {run_id}")
    decisions = tier1.decisions(run_id)
    tier1_pass = [row for row in decisions if row["screen_status"] == "PASS"]
    tier2_rows = Tier2Repository(args.db).review_summary(run_id)
    tier3_rows = Tier3Repository(args.db).summary(run_id)
    tier1_pass_symbols = {row["symbol"] for row in tier1_pass}
    tier2_symbols = {row["symbol"] for row in tier2_rows}
    missing_tier2 = sorted(tier1_pass_symbols - tier2_symbols)
    tier2_pass_symbols = {
        row["symbol"] for row in tier2_rows if row.get("human_decision") == "PASS"
    }
    current_tier3_rows = [
        row for row in tier3_rows if row["symbol"] in tier2_pass_symbols
    ]
    tier3_symbols = {row["symbol"] for row in current_tier3_rows}
    missing_tier3 = sorted(tier2_pass_symbols - tier3_symbols)

    if str(run["status"]) not in {"FINISHED", "FINISHED_WITH_ERRORS"}:
        next_action = "等待或重新执行Stage A"
    elif not tier1_pass:
        next_action = "Stage A无PASS候选；工作流结束"
    elif missing_tier2:
        symbols = " ".join(missing_tier2)
        next_action = (
            f"python main.py export-tier2 --run-id {run_id} --symbols {symbols}"
        )
    elif any(
        row.get("system_recommendation") is None
        for row in tier2_rows
        if row["symbol"] in tier1_pass_symbols
    ):
        next_action = "完成人工AI研究后执行 import-tier2"
    elif any(
        row.get("human_decision") is None
        for row in tier2_rows
        if row["symbol"] in tier1_pass_symbols
    ):
        next_action = f"python main.py review-tier2 --run-id {run_id}"
    elif not tier2_pass_symbols:
        next_action = "Stage B无人工PASS候选；工作流结束"
    elif missing_tier3:
        symbols = " ".join(missing_tier3)
        next_action = (
            f"为以下股票准备industries.json：{symbols}；然后执行 python main.py "
            f"export-tier3 --run-id {run_id} --classification-file industries.json；"
            "填写后执行 import-tier3"
        )
    elif any(int(row.get("upstream_current", 0)) != 1 for row in current_tier3_rows):
        next_action = "Stage B上游证据已变化；重新导出、研究并导入Stage C"
    elif any(row.get("human_decision") is None for row in current_tier3_rows):
        next_action = f"python main.py review-tier3 --run-id {run_id}"
    else:
        next_action = "正式A→B→C工作流已完成"

    summary = {
        "run_id": run_id,
        "stage_a": {
            "run_status": run["status"],
            "decision_count": len(decisions),
            "pass_count": len(tier1_pass),
        },
        "stage_b": {
            "expected_count": len(tier1_pass_symbols),
            "candidate_count": len(tier2_rows),
            "human_pass_count": len(tier2_pass_symbols),
        },
        "stage_c": {
            "eligible_count": len(tier2_pass_symbols),
            "assessment_count": len(current_tier3_rows),
            "human_pass_count": sum(
                row.get("human_decision") == "PASS" for row in current_tier3_rows
            ),
        },
        "next_action": next_action,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _show_tier1_command(args) -> None:
    from src.storage.tier1_repository import Tier1Repository

    repository = Tier1Repository(args.db)
    rows = repository.decisions(args.run_id)
    if not rows:
        print("未找到该run_id的Tier1 v2结果")
        return
    run_record = repository.run_record(args.run_id)
    if run_record and run_record.get('data_quality_summary_json'):
        print(f"data_quality: {run_record['data_quality_summary_json']}")
    columns = [
        'symbol', 'stock_name', 'screen_status', 'business_status', 'data_status',
        'selected_pe_ttm', 'dividend_yield_ttm', 'trend_quarters_json',
        'revenue_yoy_sequence_json', 'parent_np_yoy_sequence_json',
        'failed_conditions_json', 'pending_fields_json', 'error_fields_json',
        'secondary_queues_json',
    ]
    print(pd.DataFrame(rows)[columns].to_string(index=False))


def _verify_tier1_sources_command(args) -> None:
    from config.tier1 import Tier1Config
    from src.data.point_in_time.provider_factory import build_point_in_time_provider
    from src.data.point_in_time.reconciliation import verify_symbol_sources
    from src.storage.tier1_repository import Tier1Repository

    as_of_date = _parse_as_of(args.as_of)
    config = Tier1Config()
    provider = build_point_in_time_provider(config)
    if as_of_date > provider.today:
        provider.close()
        raise ValueError("--as-of 不得晚于当前日期")
    try:
        reports = [
            verify_symbol_sources(provider.providers, _normalize_symbol(symbol), as_of_date)
            for symbol in args.symbols
        ]
    finally:
        provider.close()
    output = {
        "configured_sources": provider.provider_names,
        "configuration_warnings": provider.configuration_warnings,
        "reports": reports,
    }
    if not args.no_persist:
        repository = Tier1Repository(args.db)
        output["persisted_verification_ids"] = [
            repository.save_source_verification(report, run_id=args.run_id)
            for report in reports
        ]
    serialized = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(serialized + "\n", encoding="utf-8")
        print(f"多源验证结果已写入: {args.output}")
    else:
        print(serialized)


def _migrate_tier1_command(args) -> None:
    from src.storage.tier1_repository import Tier1Repository

    repository = Tier1Repository(args.db)
    if args.rollback:
        repository.rollback_stage_a()
        print(f"已回滚Stage A新增表: {args.db}")
    else:
        repository.migrate()
        print(f"已应用Stage A迁移: {args.db}")


def _export_tier2_command(args) -> None:
    from src.screening.tier2_human_ai import Tier2EvidenceExporter
    from src.storage.tier2_repository import Tier2Repository

    symbols = [_normalize_symbol(value) for value in args.symbols] if args.symbols else None
    output_dir = Path(args.output_dir) if args.output_dir else settings.OUTPUT_DIR / 'tier2' / args.run_id
    result = Tier2EvidenceExporter(Tier2Repository(args.db)).export_run(
        args.run_id, output_dir, symbols=symbols
    )
    print(f"Tier2证据包数量: {result['package_count']}")
    print(f"索引: {result['index_path']}")
    partial = sum(1 for item in result['packages'] if item['coverage_status'] == 'PARTIAL')
    print(f"证据不完整（必须审慎REVIEW）: {partial}")


def _import_tier2_command(args) -> None:
    from src.screening.tier2_human_ai import Tier2AssessmentImporter
    from src.storage.tier2_repository import Tier2Repository

    schema_path = settings.PROJECT_ROOT / 'config' / 'tier2_ai_schema.json'
    result = Tier2AssessmentImporter(
        Tier2Repository(args.db), schema_path
    ).import_file(args.file)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _review_tier2_command(args) -> None:
    from src.storage.tier2_repository import Tier2Repository

    repository = Tier2Repository(args.db)
    action_fields = [args.symbol, args.assessment_id, args.decision, args.reviewer, args.rationale]
    if any(value is not None for value in action_fields):
        if not args.decision or not args.reviewer or not args.rationale:
            raise ValueError("记录人工复核必须提供--decision、--reviewer和--rationale")
        assessment_id = args.assessment_id
        if assessment_id is None:
            if not args.symbol:
                raise ValueError("未提供--assessment-id时必须提供--symbol")
            latest = repository.latest_assessment(args.run_id, _normalize_symbol(args.symbol))
            if latest is None:
                raise ValueError("该股票尚无可复核的AI评估")
            assessment_id = latest['assessment_id']
        review_id = repository.save_human_review(
            assessment_id=assessment_id,
            decision=args.decision,
            reviewer=args.reviewer.strip(),
            rationale=args.rationale.strip(),
            expected_run_id=args.run_id,
            expected_symbol=_normalize_symbol(args.symbol) if args.symbol else None,
        )
        print(f"review_id: {review_id}")

    rows = repository.review_summary(args.run_id)
    if not rows:
        print("该运行尚未生成Tier2证据包")
        return
    display_columns = [
        'symbol', 'stock_name', 'coverage_status', 'ai_recommendation',
        'system_recommendation', 'human_decision', 'reviewer',
    ]
    print(pd.DataFrame(rows)[display_columns].to_string(index=False))
    if args.output:
        lines = [
            f"# Tier2人机协作复核报告 — {args.run_id}",
            "",
            "| 股票 | 公司 | 证据覆盖 | AI建议 | 系统结论 | 人工决定 | 复核人 |",
            "|---|---|---|---|---|---|---|",
        ]
        for row in rows:
            lines.append(
                f"| {row['symbol']} | {row['stock_name']} | {row['coverage_status']} | "
                f"{row.get('ai_recommendation') or '-'} | "
                f"{row.get('system_recommendation') or '-'} | "
                f"{row.get('human_decision') or '-'} | {row.get('reviewer') or '-'} |"
            )
        for row in rows:
            lines.extend(
                [
                    "",
                    f"## {row['symbol']} {row['stock_name']}",
                    "",
                    f"- 证据覆盖：{row['coverage_status']}",
                    f"- 系统结论：{row.get('system_recommendation') or '尚未导入AI结果'}",
                    f"- 人工决定：{row.get('human_decision') or '尚未复核'}",
                    f"- 缺失区块：{row.get('missing_sections_json') or '[]'}",
                    "",
                ]
            )
            if row.get('assessment_json'):
                assessment = json.loads(row['assessment_json'])
                lines.extend(
                    [
                        "| 维度 | 结论 | 置信度 | 推理摘要 |",
                        "|---|---|---:|---|",
                    ]
                )
                for dimension in assessment['dimensions']:
                    reasoning = str(dimension['reasoning_summary']).replace('|', '\\|')
                    lines.append(
                        f"| {dimension['dimension']} | {dimension['verdict']} | "
                        f"{dimension['confidence']:.2f} | {reasoning} |"
                    )
                lines.extend(
                    [
                        "",
                        "反方证据：",
                        "",
                        *[f"- {item}" for item in assessment['overall_counter_evidence']],
                        "",
                        "证伪条件：",
                        "",
                        *[f"- {item}" for item in assessment['falsification_conditions']],
                        "",
                    ]
                )
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(lines) + "\n", encoding='utf-8')
        print(f"复核报告: {output}")


def _migrate_tier2_command(args) -> None:
    from src.storage.tier2_repository import Tier2Repository

    repository = Tier2Repository(args.db)
    if args.rollback:
        repository.rollback_stage_b()
        print(f"已回滚Stage B新增表: {args.db}")
    else:
        repository.migrate()
        print(f"已应用当前数据库迁移（含Stage B）: {args.db}")


def _export_tier3_command(args) -> None:
    from src.risk.tier3.models import RiskModelRegistry
    from src.risk.tier3.template import Tier3TemplateExporter, load_classifications
    from src.storage.tier3_repository import Tier3Repository

    registry = RiskModelRegistry(settings.PROJECT_ROOT / 'config' / 'tier3_risk_rules.json')
    output_dir = Path(args.output_dir) if args.output_dir else settings.OUTPUT_DIR / 'tier3' / args.run_id
    result = Tier3TemplateExporter(
        Tier3Repository(args.db), registry
    ).export_run(
        args.run_id,
        load_classifications(args.classification_file),
        output_dir,
        classification_base_dir=Path(args.classification_file).resolve().parent,
    )
    print(f"Stage C风险研究模板数量: {result['template_count']}")
    print(f"规则版本: {result['rules_version']}")
    print(f"索引: {result['index_path']}")


def _import_tier3_command(args) -> None:
    from src.risk.tier3 import RiskModelRegistry, Tier3RiskImporter
    from src.storage.tier3_repository import Tier3Repository

    registry = RiskModelRegistry(settings.PROJECT_ROOT / 'config' / 'tier3_risk_rules.json')
    importer = Tier3RiskImporter(
        Tier3Repository(args.db),
        registry,
        settings.PROJECT_ROOT / 'config' / 'tier3_risk_input_schema.json',
    )
    print(json.dumps(importer.import_file(args.file), ensure_ascii=False, indent=2))


def _review_tier3_command(args) -> None:
    from src.storage.tier3_repository import Tier3Repository

    repository = Tier3Repository(args.db)
    action_fields = [
        args.symbol, args.risk_assessment_id, args.decision, args.reviewer, args.rationale
    ]
    if any(value is not None for value in action_fields):
        if not args.decision or not args.reviewer or not args.rationale:
            raise ValueError("记录Stage C人工复核必须提供decision、reviewer和rationale")
        assessment_id = args.risk_assessment_id
        symbol = _normalize_symbol(args.symbol) if args.symbol else None
        if assessment_id is None:
            if symbol is None:
                raise ValueError("未提供risk-assessment-id时必须提供symbol")
            latest = repository.latest_assessment(args.run_id, symbol)
            if latest is None:
                raise ValueError("该股票尚无Stage C风险评估")
            assessment_id = latest['risk_assessment_id']
        review_id = repository.save_human_review(
            risk_assessment_id=assessment_id,
            decision=args.decision,
            reviewer=args.reviewer,
            rationale=args.rationale,
            expected_run_id=args.run_id,
            expected_symbol=symbol,
        )
        print(f"review_id: {review_id}")

    rows = repository.summary(args.run_id)
    if not rows:
        print("该运行尚无Stage C风险评估")
        return
    display = [
        {
            'symbol': row['symbol'],
            'industry_model': row['industry_model'],
            'system_status': row['system_status'],
            'data_status': row['data_status'],
            'hard_vetoes': len(json.loads(row['hard_vetoes_json'])),
            'warnings': len(json.loads(row['risk_warnings_json'])),
            'unknown_checks': len(json.loads(row['unknown_checks_json'])),
            'upstream_current': bool(row['upstream_current']),
            'effective_status': row['system_status'] if row['upstream_current'] else 'STALE_UPSTREAM',
            'human_decision': row.get('human_decision'),
            'reviewer': row.get('reviewer'),
        }
        for row in rows
    ]
    print(pd.DataFrame(display).to_string(index=False))
    if args.output:
        lines = [
            f"# Stage C风险与价值陷阱报告 — {args.run_id}",
            "",
            "| 股票 | 行业模型 | 当前有效结论 | 数据状态 | 硬否决 | 警告 | 未知 | 人工决定 |",
            "|---|---|---|---|---:|---:|---:|---|",
        ]
        for item in display:
            lines.append(
                f"| {item['symbol']} | {item['industry_model']} | {item['effective_status']} | "
                f"{item['data_status']} | {item['hard_vetoes']} | {item['warnings']} | "
                f"{item['unknown_checks']} | {item['human_decision'] or '-'} |"
            )
        for row in rows:
            hard = json.loads(row['hard_vetoes_json'])
            warnings = json.loads(row['risk_warnings_json'])
            traps = json.loads(row['value_trap_signals_json'])
            falsification = json.loads(row['falsification_conditions_json'])
            lines.extend([
                "",
                f"## {row['symbol']} — {row['industry_model_class']}",
                "",
            f"- 系统结论：{row['system_status']}",
            f"- 上游有效：{'是' if row['upstream_current'] else '否（Stage B已变化）'}",
                f"- 人工决定：{row.get('human_decision') or '尚未复核'}",
                f"- 规则版本：{row['rules_version']}",
                "",
                "### 硬否决",
                "",
                *([f"- `{item['check_id']}`：{item['reasoning_summary']}" for item in hard] or ["- 无"]),
                "",
                "### 风险警告",
                "",
                *([f"- `{item['check_id']}`：{item['reasoning_summary']}" for item in warnings] or ["- 无"]),
                "",
                "### 价值陷阱信号",
                "",
                *([f"- `{item['check_id']}`：{item['reasoning_summary']}" for item in traps] or ["- 无"]),
                "",
                "### 证伪条件",
                "",
                *[f"- {item}" for item in falsification],
                "",
            ])
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(lines) + "\n", encoding='utf-8')
        print(f"Stage C报告: {output}")


def _migrate_tier3_command(args) -> None:
    from src.storage.tier3_repository import Tier3Repository

    repository = Tier3Repository(args.db)
    if args.rollback:
        repository.rollback_stage_c()
        print(f"已回滚Stage C新增表: {args.db}")
    else:
        repository.migrate()
        print(f"已应用当前数据库迁移（含Stage C）: {args.db}")


def main() -> None:
    """运行正式 Stage A/B/C 命令。"""
    setup_logging()
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    commands = {
        "screen-tier1": _run_tier1_command,
        "show-tier1": _show_tier1_command,
        "verify-tier1-sources": _verify_tier1_sources_command,
        "tier1-migrate": _migrate_tier1_command,
        "export-tier2": _export_tier2_command,
        "import-tier2": _import_tier2_command,
        "review-tier2": _review_tier2_command,
        "tier2-migrate": _migrate_tier2_command,
        "export-tier3": _export_tier3_command,
        "import-tier3": _import_tier3_command,
        "review-tier3": _review_tier3_command,
        "tier3-migrate": _migrate_tier3_command,
        "workflow": _formal_workflow_command,
    }
    try:
        commands[args.command](args)
    except (TypeError, ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
