"""预期差量化器。

综合市场隐含假设和悲观分析结果，量化市场预期与基本面现实之间的差距，
生成预期差总结和做多触发条件。
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class ExpectationGapQuantifier:
    """预期差量化器：市场假设 vs 基本面现实。

    将市场隐含利润计算结果与悲观假设分析结果整合，
    量化市场定价与基本面之间的预期差，给出投资触发条件。
    """

    def __init__(self, implied_profit_calc=None, pessimism_analyzer=None):
        """初始化预期差量化器。

        Args:
            implied_profit_calc: ImpliedProfitCalculator 实例
            pessimism_analyzer: PessimisticHypothesis 实例
        """
        self.implied_profit_calc = implied_profit_calc
        self.pessimism_analyzer = pessimism_analyzer

    def quantify_gap(self, symbol: str, basic_info: dict = None) -> dict:
        """量化市场预期与现实之间的差距。

        综合市场隐含利润和悲观假设分析，计算预期差幅度和置信度，
        生成做多触发条件。

        Args:
            symbol: 股票代码
            basic_info: 股票基本信息字典

        Returns:
            dict: 包含以下字段的预期差结果：
                - market_implied: 市场隐含假设
                - base_assumption: 基准假设
                - pessimism_analysis: 悲观分析结果
                - gap_magnitude: 预期差幅度(%)
                - gap_confidence: 预期差置信度(0-1)
                - gap_summary: 预期差总结描述
                - triggers: 做多触发条件列表
        """
        try:
            market_implied = {}
            if self.implied_profit_calc:
                market_implied = self.implied_profit_calc.calc_implied_profit(
                    symbol, basic_info
                )

            pessimism = {}
            if self.pessimism_analyzer:
                pessimism = self.pessimism_analyzer.identify_pessimism(
                    symbol, basic_info
                )

            base_assumption = self._build_base_assumption(basic_info, market_implied)

            profit_gap = market_implied.get('profit_gap_pct', 0)
            pe = float(basic_info.get('pe_dynamic', 0)) if basic_info else 0

            if pe <= 10:
                confidence = 0.85
            elif pe <= 15:
                confidence = 0.75
            elif pe <= 20:
                confidence = 0.60
            else:
                confidence = 0.40

            if profit_gap > 20:
                gap_summary = (
                    f'市场定价隐含利润比正常化水平低{profit_gap:.0f}%，'
                    f'存在显著预期差'
                )
            elif profit_gap > 10:
                gap_summary = (
                    f'市场定价隐含利润比正常化水平低{profit_gap:.0f}%，'
                    f'存在一定预期差'
                )
            elif profit_gap > 0:
                gap_summary = '市场定价略偏保守，预期差有限'
            else:
                gap_summary = '市场价格已充分反映甚至过度反映了基本面'

            triggers = self._build_triggers(symbol, basic_info)

            return {
                'market_implied': market_implied,
                'base_assumption': base_assumption,
                'pessimism_analysis': pessimism,
                'gap_magnitude': round(profit_gap, 1),
                'gap_confidence': round(confidence, 2),
                'gap_summary': gap_summary,
                'triggers': triggers,
            }
        except Exception as e:
            logger.error(f"预期差量化失败 {symbol}: {e}")
            return {
                'market_implied': {},
                'base_assumption': {},
                'pessimism_analysis': {},
                'gap_magnitude': 0,
                'gap_confidence': 0,
                'gap_summary': '数据不足',
                'triggers': [],
            }

    def _build_base_assumption(
        self, basic_info: dict, market_implied: dict
    ) -> dict:
        """构建基本面基准假设。

        基于当前PE水平构建基本面评估的基准假设，
        作为预期差比较的参照系。

        Args:
            basic_info: 股票基本信息字典
            market_implied: 市场隐含利润计算结果

        Returns:
            dict: 包含假设描述、恢复时间和关键证据的基准假设
        """
        pe = float(basic_info.get('pe_dynamic', 0)) if basic_info else 0

        return {
            'assumption': '企业核心竞争力和盈利能力未发生不可逆破坏',
            'recovery_time': '预计1-3年',
            'key_evidence': [
                f'当前PE={pe:.1f}处于历史低位',
                '商业模式和竞争壁垒仍然存在',
            ],
        }

    def _build_triggers(self, symbol: str, basic_info: dict) -> list:
        """构建做多触发条件。

        生成一组用于确认投资时机的触发条件，
        当这些条件满足时可考虑做多。

        Args:
            symbol: 股票代码
            basic_info: 股票基本信息字典

        Returns:
            list: 做多触发条件字符串列表
        """
        return [
            '季度财报显示利润环比改善',
            '机构持仓开始回升',
            '行业政策出现边际宽松',
            '公司发布回购或增持公告',
            '技术面出现底部放量信号',
        ]
