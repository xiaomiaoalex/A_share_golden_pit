"""10维度评分引擎"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class DimensionScorer:
    """10维度评分引擎：对每只股票从10个维度独立评分"""

    def __init__(self, fetcher, settings=None):
        """初始化评分引擎

        Args:
            fetcher: 数据获取器实例
            settings: 配置对象（可选）
        """
        self.fetcher = fetcher
        self.settings = settings

    def score_all(self, symbol: str, basic_info: dict = None) -> Dict[str, float]:
        """计算所有10个维度的评分

        Args:
            symbol: 股票代码
            basic_info: 基础信息字典，包含 pe_dynamic, pb, market_cap, change_60d, turnover 等字段

        Returns:
            {
                'business_quality': 0-10,          # 商业质量
                'competitive_advantage': 0-10,     # 竞争优势
                'demand_certainty': 0-10,          # 长期需求确定性
                'management': 0-10,                # 管理层
                'financial_quality': 0-10,         # 财务质量
                'valuation_margin': 0-10,          # 估值安全边际
                'odds': 0-10,                      # 赔率
                'predictability': 0-10,            # 基本面可预测性
                'market_pessimism': 0-10,          # 市场悲观程度
                'reversal_verifiability': 0-10,    # 反转可验证性
            }
        """
        scores = {}

        # 从basic_info提取关键指标
        pe = float(basic_info.get('pe_dynamic', 0) or 0) if basic_info else 0
        pb = float(basic_info.get('pb', 0) or 0) if basic_info else 0
        market_cap = float(basic_info.get('market_cap', 0) or 0) if basic_info else 0
        change_60d = float(basic_info.get('change_60d', 0) or 0) if basic_info else 0
        turnover = float(basic_info.get('turnover', 0) or 0) if basic_info else 0

        # 1. 商业质量 (基于ROE/PE隐含)
        scores['business_quality'] = self._score_business_quality(pe, pb, basic_info)

        # 2. 竞争优势 (基于市值和PB)
        scores['competitive_advantage'] = self._score_competitive_advantage(pe, pb, market_cap)

        # 3. 长期需求确定性
        scores['demand_certainty'] = self._score_demand_certainty(pe, basic_info)

        # 4. 管理层
        scores['management'] = self._score_management(pe, pb, basic_info)

        # 5. 财务质量
        scores['financial_quality'] = self._score_financial_quality(pe, pb, basic_info)

        # 6. 估值安全边际
        scores['valuation_margin'] = self._score_valuation_margin(pe, pb)

        # 7. 赔率
        scores['odds'] = self._score_odds(pe, pb, change_60d)

        # 8. 基本面可预测性
        scores['predictability'] = self._score_predictability(pe, market_cap)

        # 9. 市场悲观程度
        scores['market_pessimism'] = self._score_market_pessimism(pe, change_60d, turnover)

        # 10. 反转可验证性
        scores['reversal_verifiability'] = self._score_reversal_verifiability(pe, basic_info)

        return scores

    def _score_business_quality(self, pe: float, pb: float, info: dict) -> float:
        """商业质量评分

        基于PE、PB和市值综合评估公司商业质量。
        PE在5-50之间且PB在1-8之间说明商业模式健康。
        大市值公司通常有更成熟的商业模式。

        Args:
            pe: 动态市盈率
            pb: 市净率
            info: 基础信息字典

        Returns:
            0-10的评分
        """
        score = 5.0  # 基准分

        # PE为正且合理
        if 5 < pe < 50:
            score += 1.5
        elif pe > 0:
            score += 0.5

        # PB合理
        if 1 < pb < 8:
            score += 1.0

        # 市值大加分
        market_cap = float(info.get('market_cap', 0) or 0) if info else 0
        if market_cap > 1000_0000_0000:  # 千亿以上
            score += 2.0
        elif market_cap > 200_0000_0000:  # 两百亿以上
            score += 1.0

        return round(max(0, min(10, score)), 1)

    def _score_competitive_advantage(self, pe: float, pb: float, market_cap: float) -> float:
        """竞争优势评分

        通过隐含ROE（PB/PE）评估企业竞争壁垒。
        ROE>25%说明有强竞争优势，>15%说明有中等竞争优势。
        大市值通常意味着更强的竞争地位和规模优势。

        Args:
            pe: 动态市盈率
            pb: 市净率
            market_cap: 总市值

        Returns:
            0-10的评分
        """
        score = 5.0

        # ROE(PB/PE)高意味着竞争优势
        if pe > 0 and pb > 0:
            roe = pb / pe
            if roe > 0.25:
                score += 2.5
            elif roe > 0.15:
                score += 1.5
            elif roe > 0.10:
                score += 0.5

        # 大市值通常意味着更强的竞争地位
        if market_cap > 1000_0000_0000:
            score += 2.0
        elif market_cap > 500_0000_0000:
            score += 1.0

        return round(max(0, min(10, score)), 1)

    def _score_demand_certainty(self, pe: float, info: dict) -> float:
        """长期需求确定性评分

        评估公司产品/服务的长期需求确定性。
        PE在10-25之间说明盈利稳定，长期需求可预期。
        大市值公司通常业务更稳定，需求波动更小。

        Args:
            pe: 动态市盈率
            info: 基础信息字典

        Returns:
            0-10的评分
        """
        score = 5.0

        # PE稳定意味着盈利可预测
        if 10 <= pe <= 25:
            score += 2.0
        elif 5 <= pe <= 35:
            score += 1.0

        # 大市值通常意味着需求更稳定
        market_cap = float(info.get('market_cap', 0) or 0) if info else 0
        if market_cap > 500_0000_0000:
            score += 1.5

        return round(max(0, min(10, score)), 1)

    def _score_management(self, pe: float, pb: float, info: dict) -> float:
        """管理层评分

        通过ROE和市值评估管理层能力。
        ROE是管理层资本配置能力的核心指标。
        大市值公司通常有更专业的管理团队。

        Args:
            pe: 动态市盈率
            pb: 市净率
            info: 基础信息字典

        Returns:
            0-10的评分
        """
        score = 5.0

        # ROE是管理层能力的代理指标
        if pe > 0 and pb > 0:
            roe = pb / pe
            if roe > 0.20:
                score += 2.0
            elif roe > 0.12:
                score += 1.0

        # 市值规模
        market_cap = float(info.get('market_cap', 0) or 0) if info else 0
        if market_cap > 200_0000_0000:
            score += 1.0

        return round(max(0, min(10, score)), 1)

    def _score_financial_quality(self, pe: float, pb: float, info: dict) -> float:
        """财务质量评分

        评估公司的财务健康状况。
        PE为正说明公司有盈利能力。
        PB在1-10之间说明资产质量合理。
        有一定市值规模说明财务数据可靠性更高。

        Args:
            pe: 动态市盈率
            pb: 市净率
            info: 基础信息字典

        Returns:
            0-10的评分
        """
        score = 5.0

        # PE为正
        if pe > 0:
            score += 2.0

        # PB为正且合理
        if 1 <= pb <= 10:
            score += 1.5

        # 有市值数据
        market_cap = float(info.get('market_cap', 0) or 0) if info else 0
        if market_cap > 50_0000_0000:
            score += 1.0

        return round(max(0, min(10, score)), 1)

    def _score_valuation_margin(self, pe: float, pb: float) -> float:
        """估值安全边际评分

        评估当前估值的安全边际。PE越低、PB越接近破净，安全边际越高。
        这是价值投资中最重要的维度之一。

        Args:
            pe: 动态市盈率
            pb: 市净率

        Returns:
            0-10的评分
        """
        score = 5.0

        # PE越低安全边际越高
        if pe <= 5:
            score += 4.0
        elif pe <= 10:
            score += 3.0
        elif pe <= 15:
            score += 2.0
        elif pe <= 20:
            score += 1.0
        elif pe <= 30:
            score += 0.0
        else:
            score -= 1.0

        # PB破净加分
        if 0 < pb <= 1.0:
            score += 2.0
        elif 1.0 < pb <= 1.5:
            score += 1.0

        return round(max(0, min(10, score)), 1)

    def _score_odds(self, pe: float, pb: float, change_60d: float) -> float:
        """赔率评分

        评估投资赔率（潜在回报/潜在损失）。
        低PE意味着潜在收益空间大，大幅回撤提供更好的买点。
        注意：赔率高不代表确定性高，需结合其他维度使用。

        Args:
            pe: 动态市盈率
            pb: 市净率（未直接使用，保留接口一致性）
            change_60d: 60日涨跌幅（百分比）

        Returns:
            0-10的评分
        """
        score = 5.0

        # 低PE意味着高赔率
        if pe <= 8:
            score += 3.0
        elif pe <= 12:
            score += 2.0
        elif pe <= 18:
            score += 1.0

        # 大幅回撤意味着赔率更高（前提是基本面没坏）
        if change_60d <= -40:
            score += 2.0
        elif change_60d <= -25:
            score += 1.0

        return round(max(0, min(10, score)), 1)

    def _score_predictability(self, pe: float, market_cap: float) -> float:
        """基本面可预测性评分

        评估公司未来基本面的可预测程度。
        大市值公司通常有更多分析师覆盖，信息更透明。
        PE在合理范围内说明盈利模式稳定。

        Args:
            pe: 动态市盈率
            market_cap: 总市值

        Returns:
            0-10的评分
        """
        score = 5.0

        # 大市值通常意味着更多分析师覆盖
        if market_cap > 1000_0000_0000:
            score += 3.0
        elif market_cap > 500_0000_0000:
            score += 2.0
        elif market_cap > 200_0000_0000:
            score += 1.0

        # PE在合理范围
        if 10 <= pe <= 25:
            score += 1.0

        return round(max(0, min(10, score)), 1)

    def _score_market_pessimism(self, pe: float, change_60d: float, turnover: float) -> float:
        """市场悲观程度评分（越悲观分数越高，意味着逆向机会越大）

        市场悲观是逆向投资者的机会。PE极低、股价大幅下跌、
        换手率低迷都说明市场情绪悲观，此时逆向买入赔率较高。

        Args:
            pe: 动态市盈率
            change_60d: 60日涨跌幅（百分比）
            turnover: 换手率（百分比）

        Returns:
            0-10的评分
        """
        score = 5.0

        # PE极低 = 极度悲观
        if pe <= 8:
            score += 3.0
        elif pe <= 12:
            score += 2.0
        elif pe <= 16:
            score += 1.0

        # 大幅下跌 = 市场悲观
        if change_60d <= -35:
            score += 2.0
        elif change_60d <= -20:
            score += 1.0

        # 低换手 = 无人关注
        if 0 < turnover <= 1.0:
            score += 1.0

        return round(max(0, min(10, score)), 1)

    def _score_reversal_verifiability(self, pe: float, info: dict) -> float:
        """反转可验证性评分

        评估投资反转的可验证程度。
        PE为正意味着有盈利数据可以跟踪验证反转进程。
        大市值公司信息透明度高，更容易验证反转是否成立。

        Args:
            pe: 动态市盈率
            info: 基础信息字典

        Returns:
            0-10的评分
        """
        score = 5.0

        # PE为正意味着有盈利可以跟踪
        if pe > 0:
            score += 2.0

        # 大市值意味着更多公开信息
        market_cap = float(info.get('market_cap', 0) or 0) if info else 0
        if market_cap > 200_0000_0000:
            score += 2.0

        return round(max(0, min(10, score)), 1)
