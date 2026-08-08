"""第三层筛选：核心黄金坑

从深度观察池的30-50只标的中，通过估值分析、预期差分析、
多维度评分与风险评估，确认高确定性 × 高赔率 × 长周期的
核心黄金坑标的（5-15只）。
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class CoreConfirmer:
    """第三层：核心黄金坑 —— 高确定性 × 高赔率 × 长周期"""

    def __init__(self, fetcher, valuation_engine=None, scorer=None,
                 risk_checker=None, expectation_analyzer=None, thresholds=None, db=None):
        """初始化核心确认器

        Args:
            fetcher: DataFetcher实例，用于获取行情与财务数据
            valuation_engine: 估值引擎（可选）
            scorer: 评分引擎（可选）
            risk_checker: 风险检查器（可选）
            expectation_analyzer: 预期差分析器（可选）
            thresholds: CoreConfirmThreshold配置，包含确认阈值
            db: DatabaseManager实例（可选）
        """
        self.fetcher = fetcher
        self.valuation_engine = valuation_engine
        self.scorer = scorer
        self.risk_checker = risk_checker
        self.expectation_analyzer = expectation_analyzer
        self.thresholds = thresholds
        self.db = db

    def confirm(self, watch_list: pd.DataFrame) -> pd.DataFrame:
        """核心确认筛选

        Args:
            watch_list: 深度观察池DataFrame

        Returns:
            核心黄金坑DataFrame（5-15只），按赔率降序排列
        """
        if watch_list.empty:
            return pd.DataFrame()

        results = []
        total = len(watch_list)

        for idx, row in watch_list.iterrows():
            symbol = str(row.get('symbol', ''))
            if not symbol:
                continue

            try:
                confirmation = self._confirm_stock(symbol, row)
                if confirmation and confirmation.get('confirmed', False):
                    merged = {**row.to_dict(), **confirmation}
                    results.append(merged)

                logger.info(f"核心确认进度: {len(results)}/{total} (当前: {symbol})")
            except Exception as e:
                logger.warning(f"核心确认异常 {symbol}: {e}")
                continue

        result_df = pd.DataFrame(results)
        if not result_df.empty:
            # 按赔率排序
            if 'odds_ratio' in result_df.columns:
                result_df = result_df.sort_values('odds_ratio', ascending=False)

            # 限制核心池数量在5-15只
            if len(result_df) > 15:
                result_df = result_df.head(15)

        logger.info(f"核心确认完成: {len(result_df)}/{total} 入选核心黄金坑")
        return result_df

    def _confirm_stock(self, symbol: str, basic_info: pd.Series) -> Optional[dict]:
        """确认单只股票是否为核心黄金坑

        依次执行估值分析、预期差分析、多维评分、风险评估，
        满足赔率与置信度阈值且风险非极高时确认入选。

        Args:
            symbol: 股票代码
            basic_info: 该股票的基础行情信息

        Returns:
            包含确认结果、评分明细、仓位建议的字典
        """
        result = {'symbol': symbol, 'confirmed': False}
        score_breakdown = {}
        total_score = 0

        # 1. 估值分析
        if self.valuation_engine:
            try:
                valuation = self._run_valuation(symbol, basic_info)
                result.update(valuation)
                score_breakdown['valuation'] = min(10, valuation.get('valuation_score', 5))
            except Exception as e:
                logger.debug(f"估值分析异常 {symbol}: {e}")

        # 2. 预期差分析
        if self.expectation_analyzer:
            try:
                gap = self._run_expectation_gap(symbol, basic_info)
                result.update(gap)
                score_breakdown['expectation_gap'] = min(10, gap.get('gap_score', 5))
            except Exception as e:
                logger.debug(f"预期差分析异常 {symbol}: {e}")

        # 3. 评分
        if self.scorer:
            try:
                scores = self._run_scoring(symbol, basic_info)
                result['dimension_scores'] = scores
                score_breakdown.update(scores)
                if scores:
                    total_score = np.mean(list(scores.values()))
            except Exception as e:
                logger.debug(f"评分异常 {symbol}: {e}")

        # 4. 风险评估
        if self.risk_checker:
            try:
                risk = self._run_risk_check(symbol, basic_info)
                result.update(risk)
            except Exception as e:
                logger.debug(f"风险评估异常 {symbol}: {e}")

        # 5. 综合判断
        odds = result.get('odds_ratio', 0)
        confidence = result.get('confidence', 0.5)
        risk_level = result.get('overall_risk_level', '中')

        # 确认条件：赔率 >= 2.0 且 置信度 >= 0.7 且 风险不极高
        if odds >= self.thresholds.MIN_ODDS_RATIO and confidence >= self.thresholds.MIN_CONFIDENCE:
            if risk_level != '极高':
                result['confirmed'] = True
                result['total_score'] = round(total_score, 1)
                result['score_breakdown'] = score_breakdown

                # 仓位建议
                result['position_advice'] = self._calc_position_advice(
                    total_score, odds, confidence, risk_level
                )

        return result

    def _run_valuation(self, symbol: str, info: pd.Series) -> dict:
        """执行估值分析：三情景估值法计算赔率

        以行业中枢PE为基准，悲观/基准/乐观三情景给出目标价，
        赔率 = 加权上涨空间 / 加权下跌空间。

        Args:
            symbol: 股票代码
            info: 基础行情信息

        Returns:
            估值结果字典，包含赔率、三情景目标价、置信度等
        """
        try:
            pe = float(info.get('pe_dynamic', 0) or 0)
            pb = float(info.get('pb', 0) or 0)
            price = float(info.get('price', 0) or 0)

            if pe <= 0 or price <= 0:
                return {'valuation_score': 5, 'odds_ratio': 1.0}

            # 简化估值：合理PE取行业中枢15-25倍
            fair_pe = 18
            earnings = price / pe  # 每股收益

            # 三情景
            pessimistic_value = earnings * 10  # PE=10悲观
            base_value = earnings * fair_pe  # PE=18基准
            optimistic_value = earnings * 25  # PE=25乐观

            # 赔率 = 加权上涨空间 / 加权下跌空间
            upside = (base_value / price - 1)
            downside = max(0.05, 1 - pessimistic_value / price)
            odds_ratio = upside / downside if downside > 0 else 2.0

            # 估值评分：PE越低分越高
            if pe <= 10:
                valuation_score = 9
            elif pe <= 15:
                valuation_score = 7
            elif pe <= 20:
                valuation_score = 5
            else:
                valuation_score = 3

            return {
                'valuation_score': valuation_score,
                'odds_ratio': round(odds_ratio, 2),
                'fair_value': round(base_value, 1),
                'pessimistic_value': round(pessimistic_value, 1),
                'optimistic_value': round(optimistic_value, 1),
                'upside_pct': round(upside * 100, 1),
                'downside_pct': round(downside * 100, 1),
                'confidence': round(min(0.95, 0.5 + 0.1 * (10 - min(10, pe))), 2),
            }
        except Exception as e:
            logger.debug(f"估值计算异常: {e}")
            return {'valuation_score': 5, 'odds_ratio': 1.0, 'confidence': 0.5}

    def _run_expectation_gap(self, symbol: str, info: pd.Series) -> dict:
        """市场预期差分析：比较市场隐含利润与正常化利润

        Args:
            symbol: 股票代码
            info: 基础行情信息

        Returns:
            预期差结果字典，包含隐含利润、正常化利润、悲观程度描述
        """
        try:
            pe = float(info.get('pe_dynamic', 0) or 0)
            price = float(info.get('price', 0) or 0)

            if pe <= 0 or price <= 0:
                return {'gap_score': 5}

            # 市场隐含利润
            implied_earnings = price / pe

            # 假设正常化利润比隐含高20-50%（基于保守估计）
            normalized_earnings = implied_earnings * 1.3

            # 预期差
            gap = (normalized_earnings / implied_earnings - 1) if implied_earnings > 0 else 0

            # 市场悲观假设
            if pe <= 10:
                pessimism = "市场定价极度悲观：隐含利润大幅下滑预期"
                gap_score = 9
            elif pe <= 15:
                pessimism = "市场定价偏悲观：隐含利润温和下滑预期"
                gap_score = 7
            elif pe <= 20:
                pessimism = "市场定价中性偏谨慎"
                gap_score = 5
            else:
                pessimism = "市场定价正常"
                gap_score = 3

            return {
                'implied_earnings': round(float(implied_earnings), 4),
                'normalized_earnings': round(float(normalized_earnings), 4),
                'expectation_gap_pct': round(float(gap * 100), 1),
                'market_pessimism': pessimism,
                'gap_score': gap_score,
            }
        except Exception as e:
            logger.debug(f"预期差分析异常: {e}")
            return {'gap_score': 5}

    def _run_scoring(self, symbol: str, info: pd.Series) -> dict:
        """执行多维度评分（委托外部评分引擎）

        Args:
            symbol: 股票代码
            info: 基础行情信息

        Returns:
            各维度评分字典；无评分引擎时返回空字典
        """
        if self.scorer:
            try:
                return self.scorer.score_all(symbol)
            except Exception:
                pass
        return {}

    def _run_risk_check(self, symbol: str, info: pd.Series) -> dict:
        """执行风险检查（委托外部风险检查器）

        Args:
            symbol: 股票代码
            info: 基础行情信息

        Returns:
            风险检查结果字典；无风险检查器时默认返回中等风险
        """
        if self.risk_checker:
            try:
                return self.risk_checker.check_all(symbol)
            except Exception:
                pass
        return {'overall_risk_level': '中'}

    def _calc_position_advice(self, score: float, odds: float,
                               confidence: float, risk_level: str) -> dict:
        """计算仓位建议：基于凯利公式简化版

        根据赔率与置信度分档给出建议仓位比例，
        单一标的仓位上限为20%。

        Args:
            score: 综合评分
            odds: 赔率
            confidence: 置信度
            risk_level: 风险等级

        Returns:
            仓位建议字典，包含仓位比例与类型
        """
        if risk_level == '极高':
            return {'position_pct': 0, 'position_type': '不参与'}

        # 凯利公式简化版
        if odds > 3 and confidence > 0.8:
            pct = 0.20
            ptype = '核心仓'
        elif odds > 2 and confidence > 0.7:
            pct = 0.12
            ptype = '中仓'
        elif odds > 1.5 and confidence > 0.6:
            pct = 0.06
            ptype = '小仓'
        else:
            pct = 0.03
            ptype = '观察'

        return {
            'position_pct': round(pct, 2),
            'position_type': ptype,
            'max_position': min(pct, 0.20),
        }
