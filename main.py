#!/usr/bin/env python3
"""
A股黄金坑股票数据库 - CLI主入口

使用方法:
    python main.py workflow --as-of 2026-08-10 --symbols 000651
    python main.py legacy-scan --i-understand-this-uses-legacy-rules
    python main.py stock 000002   # 单股票深度分析
    python main.py show --tier 3  # 查看Tier3结果
    python main.py report         # 生成报告
    python main.py stats          # 数据库统计
"""

import argparse
import json
import logging
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import settings
from config.thresholds import RadarThreshold, DeepScreenThreshold, CoreConfirmThreshold

logger = logging.getLogger(__name__)


def _load_legacy_components():
    """仅在调用旧三层命令时加载旧系统及其可选依赖。"""
    global CacheManager, DataFetcher, RadarScanner, DeepScreener, CoreConfirmer
    global HistoricalValuation, ScenarioValuation, ReverseDCF, OddsCalculator
    global ImpliedProfitCalculator, PessimisticHypothesis, ExpectationGapQuantifier
    global DimensionScorer, ScoreAggregator, AShareRiskChecker
    global FinancialRedFlagDetector, FalsificationGenerator, DatabaseManager
    global StockDAO, ExcelReporter, HTMLDashboard, StockDetailReport

    from src.data.cache import CacheManager
    from src.data.fetcher import DataFetcher
    from src.screening.radar import RadarScanner
    from src.screening.deep_screen import DeepScreener
    from src.screening.core_confirm import CoreConfirmer
    from src.valuation.historical import HistoricalValuation
    from src.valuation.scenarios import ScenarioValuation
    from src.valuation.reverse_dcf import ReverseDCF
    from src.valuation.odds_calculator import OddsCalculator
    from src.expectation.implied_profit import ImpliedProfitCalculator
    from src.expectation.pessimistic import PessimisticHypothesis
    from src.expectation.gap_quantifier import ExpectationGapQuantifier
    from src.scoring.dimensions import DimensionScorer
    from src.scoring.aggregator import ScoreAggregator
    from src.risk.ashares_risk import AShareRiskChecker
    from src.risk.financial_redflags import FinancialRedFlagDetector
    from src.risk.falsification import FalsificationGenerator
    from src.storage.database import DatabaseManager
    from src.storage.dao import StockDAO
    from src.report.excel_report import ExcelReporter
    from src.report.html_dashboard import HTMLDashboard
    from src.report.stock_detail import StockDetailReport


def setup_logging():
    """配置日志"""
    log_dir = settings.LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / f"golden_pit_{date.today().strftime('%Y%m%d')}.log"

    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL),
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(),
        ]
    )


class GoldenPitApp:
    """黄金坑系统主应用

    协调三层筛选流程、估值分析、预期差分析、
    评分计算、风险评估和报告生成等全部模块。
    """

    def __init__(self):
        """初始化黄金坑应用，创建所有子模块实例"""
        self.settings = settings
        self.cache = CacheManager(
            cache_dir=str(settings.CACHE_DIR),
            default_ttl=86400
        )
        self.fetcher = DataFetcher(cache_manager=self.cache, settings=settings)
        self.db = DatabaseManager(settings.DB_PATH)
        self.db.initialize()

        # 筛选器
        self.radar = RadarScanner(self.fetcher, RadarThreshold())
        self.deep_screener = DeepScreener(self.fetcher, DeepScreenThreshold(), db=self.db)

        # 估值引擎
        self.historical_val = HistoricalValuation(self.fetcher, settings)
        self.scenario_val = ScenarioValuation(self.fetcher, settings)
        self.reverse_dcf = ReverseDCF(self.fetcher, settings)
        self.odds_calc = OddsCalculator(self.scenario_val)

        # 预期差
        self.implied_profit = ImpliedProfitCalculator(self.fetcher, settings)
        self.pessimism = PessimisticHypothesis(self.fetcher, settings)
        self.gap_quantifier = ExpectationGapQuantifier(self.implied_profit, self.pessimism)

        # 评分
        self.dim_scorer = DimensionScorer(self.fetcher, settings)
        self.aggregator = ScoreAggregator(settings)

        # 风险
        self.risk_checker = AShareRiskChecker(self.fetcher, settings)
        self.redflag_detector = FinancialRedFlagDetector(self.fetcher, settings)
        self.falsification = FalsificationGenerator(self.risk_checker, self.redflag_detector)

        # 核心确认器
        self.core_confirmer = CoreConfirmer(
            fetcher=self.fetcher,
            valuation_engine=self,
            scorer=self.dim_scorer,
            risk_checker=self.risk_checker,
            expectation_analyzer=self.gap_quantifier,
            thresholds=CoreConfirmThreshold(),
            db=self.db,
        )

        # 报告
        self.excel_reporter = ExcelReporter(
            db=self.db, output_dir=settings.OUTPUT_DIR / 'reports'
        )
        self.html_dashboard = HTMLDashboard(
            db=self.db, output_dir=settings.OUTPUT_DIR / 'dashboards'
        )
        self.stock_reporter = StockDetailReport(db=self.db, fetcher=self.fetcher)

        # DAO
        self.dao = StockDAO(self.db)

    def run_full_scan(self) -> dict:
        """执行完整三层扫描流程

        Returns:
            扫描结果摘要字典，包含各层级数量和报告路径
        """
        scan_date = date.today()
        logger.info(f"========== 开始全量扫描 {scan_date} ==========")
        start_time = time.time()

        # 步骤1: 获取股票列表
        logger.info("步骤1/6: 获取全市场股票列表...")
        stock_list = self.fetcher.get_stock_list()
        logger.info(f"获取到 {len(stock_list)} 只股票")

        if stock_list.empty:
            logger.error("无法获取股票列表，扫描终止")
            return {}

        # 步骤2: Tier1 雷达扫描
        logger.info("步骤2/6: Tier1 雷达扫描...")
        tier1 = self.radar.scan(stock_list)
        logger.info(f"Tier1 雷达池: {len(tier1)} 只")

        # 步骤3: Tier2 深度筛选
        tier2 = pd.DataFrame()
        if not tier1.empty:
            logger.info("步骤3/6: Tier2 深度筛选...")
            tier2 = self.deep_screener.screen(tier1.head(300))
            logger.info(f"Tier2 观察池: {len(tier2)} 只")

        # 步骤4: Tier3 核心确认
        tier3 = pd.DataFrame()
        if not tier2.empty:
            logger.info("步骤4/6: Tier3 核心确认...")
            tier3 = self.core_confirmer.confirm(tier2)
            logger.info(f"Tier3 核心黄金坑: {len(tier3)} 只")

        # 步骤5: 保存结果
        logger.info("步骤5/6: 保存结果到数据库...")
        self._save_results(scan_date, tier1, tier2, tier3)

        # 步骤6: 组装模板记录并生成报告
        logger.info("步骤6/6: 生成报告...")
        tier2_records, tier3_records, traps, fal_logs = self._enrich_records(
            tier2, tier3
        )
        excel_path = self.excel_reporter.generate_full_report(
            scan_date, tier1=tier1, tier2=tier2_records, tier3=tier3_records,
            traps=traps, falsification_logs=fal_logs, fetcher=self.fetcher,
        )
        html_path = self.html_dashboard.generate_dashboard(
            scan_date, tier1, tier2, tier3
        )

        elapsed = time.time() - start_time
        logger.info(f"========== 扫描完成 耗时 {elapsed:.1f}秒 ==========")

        return {
            'scan_date': scan_date,
            'tier1_count': len(tier1),
            'tier2_count': len(tier2),
            'tier3_count': len(tier3),
            'excel_report': str(excel_path),
            'html_dashboard': str(html_path),
            'elapsed_seconds': round(elapsed, 1),
        }

    def run_single_stock_analysis(self, symbol: str) -> dict:
        """执行单股票全量分析

        Args:
            symbol: 股票代码（如000002）

        Returns:
            分析结果字典，包含估值、评分、风险、报告路径等
        """
        logger.info(f"开始单股票分析: {symbol}")

        # 获取基础数据
        stock_list = self.fetcher.get_stock_list()
        if stock_list.empty:
            logger.error("无法获取股票列表")
            return {'error': '无法获取股票列表，请检查网络后重试'}
        
        # 支持多种symbol格式匹配
        symbol_clean = symbol.strip().replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
        stock_row = stock_list[stock_list['symbol'].astype(str).str.strip() == symbol_clean]
        
        # 如果精确匹配失败，尝试前6位匹配
        if stock_row.empty:
            stock_row = stock_list[stock_list['symbol'].astype(str).str[:6] == symbol_clean[:6]]

        if stock_row.empty:
            logger.error(f"未找到股票: {symbol}")
            return {'error': f'未找到股票: {symbol}'}

        basic_info = stock_row.iloc[0].to_dict()
        
        # 确保关键字段不为None
        if basic_info.get('price') is None:
            basic_info['price'] = 0
        if basic_info.get('pe_dynamic') is None:
            basic_info['pe_dynamic'] = 0
        if basic_info.get('pb') is None:
            basic_info['pb'] = 0
        if basic_info.get('market_cap') is None:
            basic_info['market_cap'] = 0
        if basic_info.get('name') is None:
            basic_info['name'] = symbol

        # 估值分析
        valuation = self.scenario_val.build_scenarios(symbol, basic_info)
        odds = self.odds_calc.calc_odds_ratio(valuation)

        # 预期差
        expectation = self.gap_quantifier.quantify_gap(symbol, basic_info)

        # 评分
        scores = self.dim_scorer.score_all(symbol, basic_info)
        aggregated = self.aggregator.aggregate(scores, odds.get('odds_ratio', 1.0))

        # 风险
        risk = self.risk_checker.check_all(symbol, basic_info)
        redflags = self.redflag_detector.detect_all(symbol, basic_info)
        falsification_conditions = self.falsification.generate_conditions(
            symbol, basic_info
        )
        triggered = self.falsification.check_triggered_conditions(symbol, basic_info)

        # 生成报告
        report_md = self.stock_reporter.generate(
            symbol, basic_info, scores, valuation, risk, expectation, odds
        )
        report_path = self.stock_reporter.save_report(symbol, report_md)

        result = {
            'symbol': symbol,
            'basic_info': basic_info,
            'valuation': valuation,
            'odds': odds,
            'expectation': expectation,
            'scores': scores,
            'aggregated': aggregated,
            'risk': risk,
            'redflags': redflags,
            'falsification_conditions': falsification_conditions,
            'triggered_conditions': triggered,
            'report_path': report_path,
        }

        logger.info(f"单股票分析完成: {symbol}")
        return result

    def _enrich_records(self, tier2: pd.DataFrame, tier3: pd.DataFrame):
        """将扫描结果组装为模板56列完整记录

        Args:
            tier2: 深度观察池原始数据
            tier3: 核心黄金坑原始数据

        Returns:
            (tier2_records, tier3_records, traps, falsification_logs)
        """
        from src.report.record_builder import RecordBuilder
        builder = RecordBuilder(fetcher=self.fetcher, scan_date=date.today())

        tier2_records = []
        tier3_records = []
        traps = []
        fal_logs = []

        for target_list, df, rating_default in [
            (tier2_records, tier2, 'B'),
            (tier3_records, tier3, 'A'),
        ]:
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                try:
                    # 从行内提取已计算的分析结果
                    dim_scores = row.get('dimension_scores')
                    if not isinstance(dim_scores, dict):
                        dim_scores = {}

                    valuation = {
                        'pessimistic_value': row.get('pessimistic_value'),
                        'base_value': row.get('fair_value') or row.get('base_value'),
                        'optimistic_value': row.get('optimistic_value'),
                    }
                    expectation = {
                        'implied_profit': row.get('implied_earnings'),
                        'normalized_earnings': row.get('normalized_earnings'),
                        'expectation_gap': row.get('expectation_gap_pct'),
                        'market_pessimism': row.get('market_pessimism'),
                    }
                    odds_info = {
                        'odds_ratio': row.get('odds_ratio'),
                    }
                    risk = {
                        'overall_risk_level': row.get('overall_risk_level', '中'),
                    }
                    financial = {
                        'roe': row.get('implied_roe') or row.get('roe'),
                    }

                    # 评级：优先行内评级，其次按层级默认
                    rating = row.get('rating')
                    if not rating or rating not in ('S', 'A', 'B', 'C', '价值陷阱'):
                        score = row.get('total_score') or 0
                        odds = row.get('odds_ratio') or 1
                        if score >= 8 and odds >= 2.5:
                            rating = 'S'
                        elif score >= 6.5 and odds >= 2:
                            rating = 'A'
                        elif score >= 5:
                            rating = 'B'
                        else:
                            rating = rating_default

                    record = builder.build_full_record(
                        row, valuation=valuation, expectation=expectation,
                        scores=dim_scores, risk=risk, rating=rating,
                        odds_info=odds_info, financial=financial,
                    )
                    target_list.append(record)

                    # 证伪日志：为每只入池股票登记系统证伪条件
                    conds = [
                        {'condition': 'ROE(TTM)跌破阈值', 'threshold': '8%',
                         'current': f"{financial.get('roe') or '暂无'}%",
                         'triggered': False},
                        {'condition': '经营现金流/净利润<50%', 'threshold': '50%',
                         'current': '待人工核对', 'triggered': False},
                        {'condition': '毛利率较3年均值降超20%',
                         'threshold': '-20%(相对)', 'current': '待人工核对',
                         'triggered': False},
                    ]
                    fal_logs.extend(builder.build_falsification_log(row, conds))
                except Exception as e:
                    logger.debug(f"记录组装异常 {row.get('symbol')}: {e}")

        return tier2_records, tier3_records, traps, fal_logs

    def _save_results(self, scan_date: date, tier1: pd.DataFrame,
                      tier2: pd.DataFrame, tier3: pd.DataFrame):
        """保存筛选结果到数据库

        Args:
            scan_date: 扫描日期
            tier1: 雷达扫描池数据
            tier2: 深度观察池数据
            tier3: 核心黄金坑数据
        """
        # 保存股票基本信息
        for df in [tier1, tier2, tier3]:
            if df is not None and not df.empty:
                stocks = []
                for _, row in df.iterrows():
                    stocks.append({
                        'symbol': str(row.get('symbol', '')),
                        'name': str(row.get('name', '')),
                        'market_cap': float(row.get('market_cap', 0) or 0),
                        'updated_at': datetime.now(),
                    })
                if stocks:
                    try:
                        self.db.upsert_stocks(stocks)
                    except Exception as e:
                        logger.debug(f"保存股票信息异常: {e}")

        # 保存筛选结果
        for tier, df in [(1, tier1), (2, tier2), (3, tier3)]:
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    try:
                        result = row.to_dict()
                        result['scan_date'] = scan_date
                        self.db.save_screening_result(
                            str(row.get('symbol', '')), tier, result
                        )
                    except Exception as e:
                        logger.debug(f"保存筛选结果异常: {e}")


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
  python main.py legacy-scan --i-understand-this-uses-legacy-rules
  python main.py stock 000002          # 分析万科A
  python main.py show --tier 3         # 查看核心黄金坑
  python main.py report                # 生成报告
  python main.py stats                 # 数据库统计
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

    legacy_scan_parser = subparsers.add_parser(
        'legacy-scan', help='兼容旧版三层扫描（不使用正式A/B/C口径）'
    )
    legacy_scan_parser.add_argument('--quick', action='store_true', help='旧版快速扫描模式')
    legacy_scan_parser.add_argument(
        '--i-understand-this-uses-legacy-rules',
        action='store_true',
        help='确认结果不得作为正式黄金坑数据库结论',
    )

    # stock 命令
    stock_parser = subparsers.add_parser('stock', help='单股票分析')
    stock_parser.add_argument('symbol', help='股票代码（如000002）')

    # show 命令
    show_parser = subparsers.add_parser('show', help='查看筛选结果')
    show_parser.add_argument('--tier', type=int, choices=[1, 2, 3],
                             default=3, help='查看层级')
    show_parser.add_argument('--limit', type=int, default=20, help='显示数量')

    # report 命令
    report_parser = subparsers.add_parser('report', help='生成报告')
    report_parser.add_argument('--format', choices=['excel', 'html', 'all'],
                               default='all', help='报告格式')

    # stats 命令
    subparsers.add_parser('stats', help='数据库统计信息')

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
    from src.data.point_in_time.contracts import UniverseItem
    from src.data.point_in_time.akshare_adapter import AKSharePointInTimeProvider

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


def main():
    """主入口函数"""
    setup_logging()
    parser = build_parser()
    if len(sys.argv) > 1 and sys.argv[1] == 'scan':
        parser.error(
            "scan是已停用的旧入口；正式流程请使用workflow。"
            "如确需兼容旧算法，请显式使用legacy-scan并确认风险"
        )
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == 'screen-tier1':
            _run_tier1_command(args)
            return
        if args.command == 'show-tier1':
            _show_tier1_command(args)
            return
        if args.command == 'verify-tier1-sources':
            _verify_tier1_sources_command(args)
            return
        if args.command == 'tier1-migrate':
            _migrate_tier1_command(args)
            return
        if args.command == 'export-tier2':
            _export_tier2_command(args)
            return
        if args.command == 'import-tier2':
            _import_tier2_command(args)
            return
        if args.command == 'review-tier2':
            _review_tier2_command(args)
            return
        if args.command == 'tier2-migrate':
            _migrate_tier2_command(args)
            return
        if args.command == 'export-tier3':
            _export_tier3_command(args)
            return
        if args.command == 'import-tier3':
            _import_tier3_command(args)
            return
        if args.command == 'review-tier3':
            _review_tier3_command(args)
            return
        if args.command == 'tier3-migrate':
            _migrate_tier3_command(args)
            return
        if args.command == 'workflow':
            _formal_workflow_command(args)
            return
        if (
            args.command == 'legacy-scan'
            and not args.i_understand_this_uses_legacy_rules
        ):
            raise ValueError(
                "legacy-scan必须提供--i-understand-this-uses-legacy-rules"
            )
    except (TypeError, ValueError, OSError) as exc:
        parser.error(str(exc))

    _load_legacy_components()
    app = GoldenPitApp()

    try:
        if args.command == 'legacy-scan':
            print("\n开始执行A股黄金坑全量扫描...\n")
            result = app.run_full_scan()
            print("\n扫描完成!")
            print(f"   Tier1 雷达池: {result.get('tier1_count', 0)} 只")
            print(f"   Tier2 观察池: {result.get('tier2_count', 0)} 只")
            print(f"   Tier3 核心黄金坑: {result.get('tier3_count', 0)} 只")
            print(f"   耗时: {result.get('elapsed_seconds', 0):.1f} 秒")
            print(f"   Excel报告: {result.get('excel_report', '')}")
            print(f"   HTML仪表盘: {result.get('html_dashboard', '')}")

        elif args.command == 'stock':
            print(f"\n分析股票: {args.symbol}\n")
            result = app.run_single_stock_analysis(args.symbol)
            if 'error' in result:
                print(f"[ERROR] {result['error']}")
            else:
                agg = result.get('aggregated', {})
                odds = result.get('odds', {})
                print("\n分析完成!")
                print(f"   综合评分: {agg.get('total_score', 0):.1f}/10")
                print(f"   评级: {agg.get('rating', 'N/A')}")
                print(f"   赔率: {odds.get('odds_ratio', 0):.2f}x")
                print(f"   仓位建议: {agg.get('position_type', 'N/A')} "
                      f"({agg.get('position_pct', 0) * 100:.0f}%)")
                print(f"   风险等级: {result.get('risk', {}).get('overall_risk_level', 'N/A')}")
                print(f"   详细报告: {result.get('report_path', '')}")

        elif args.command == 'show':
            tier = args.tier
            limit = args.limit
            tier_names = {1: '雷达池', 2: '观察池', 3: '核心黄金坑'}
            print(f"\nTier{tier} {tier_names[tier]} 结果:\n")

            results = app.db.get_screening_by_tier(tier)
            if results and len(results) > 0:
                # 将 ScreeningResult 对象列表转换为可显示的字典列表
                display_data = []
                for r in results:
                    row = {
                        'symbol': r.symbol,
                        'total_score': r.total_score,
                        'odds_ratio': r.odds_ratio,
                        'confidence': r.confidence,
                        'expectation_gap': r.expectation_gap,
                        'valuation_base': r.valuation_base,
                        'valuation_pessimistic': r.valuation_pessimistic,
                        'valuation_optimistic': r.valuation_optimistic,
                    }
                    # 从 score_breakdown JSON 中提取 rating 和 position_type
                    if r.score_breakdown and isinstance(r.score_breakdown, dict):
                        row['rating'] = r.score_breakdown.get('rating', 'N/A')
                        row['position_type'] = r.score_breakdown.get('position_type', 'N/A')
                    else:
                        row['rating'] = 'N/A'
                        row['position_type'] = 'N/A'
                    display_data.append(row)
                
                df = pd.DataFrame(display_data)
                display_cols = ['symbol', 'total_score', 'odds_ratio', 'rating', 'position_type',
                                'confidence', 'expectation_gap', 'valuation_base']
                available = [c for c in display_cols if c in df.columns]
                print(df[available].head(limit).to_string(index=False))
                print(f"\n共 {len(results)} 条记录")
            else:
                print("暂无数据，请先运行 scan 命令")

        elif args.command == 'report':
            print("\n生成报告...\n")
            tier1 = app.db.get_screening_by_tier(1)
            tier2 = app.db.get_screening_by_tier(2)
            tier3 = app.db.get_screening_by_tier(3)

            # ORM 对象列表 → DataFrame
            def orm_to_df(results):
                if not results:
                    return pd.DataFrame()
                rows = []
                for r in results:
                    d = {'symbol': r.symbol, 'total_score': r.total_score,
                         'odds_ratio': r.odds_ratio, 'confidence': r.confidence,
                         'expectation_gap': r.expectation_gap,
                         'valuation_base': r.valuation_base,
                         'valuation_pessimistic': r.valuation_pessimistic,
                         'valuation_optimistic': r.valuation_optimistic}
                    if r.stock:
                        d['name'] = r.stock.name
                        d['market_cap'] = r.stock.market_cap
                        d['industry'] = r.stock.industry
                    if r.score_breakdown and isinstance(r.score_breakdown, dict):
                        d.update(r.score_breakdown)
                    rows.append(d)
                return pd.DataFrame(rows)

            tier1_df = orm_to_df(tier1)
            tier2_df = orm_to_df(tier2)
            tier3_df = orm_to_df(tier3)

            if args.format in ('excel', 'all'):
                t2r, t3r, traps, fal = app._enrich_records(tier2_df, tier3_df)
                path = app.excel_reporter.generate_full_report(
                    date.today(), tier1=tier1_df, tier2=t2r, tier3=t3r,
                    traps=traps, falsification_logs=fal, fetcher=app.fetcher,
                )
                print(f"   Excel报告: {path}")

            if args.format in ('html', 'all'):
                path = app.html_dashboard.generate_dashboard(
                    date.today(), tier1_df, tier2_df, tier3_df
                )
                print(f"   HTML仪表盘: {path}")

            print("\n报告生成完成!")

        elif args.command == 'stats':
            stats = app.db.get_statistics()
            print("\n数据库统计:\n")
            for key, value in stats.items():
                print(f"   {key}: {value}")

    finally:
        app.fetcher.close()


if __name__ == '__main__':
    main()
