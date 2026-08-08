"""
单股票深度分析报告生成器

为单只股票生成格式化的Markdown深度分析报告，
包含投资摘要、10维度评分、估值分析、预期差分析、
风险清单和赔率仓位建议等完整内容。
"""

import logging
from pathlib import Path
from datetime import date
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class StockDetailReport:
    """单股票深度分析报告生成器

    为单只股票生成结构化的Markdown深度分析报告，
    覆盖估值、评分、风险、赔率等多个维度。
    """

    def __init__(self, db=None, fetcher=None):
        """初始化股票深度报告生成器

        Args:
            db: 数据库连接实例（可选）
            fetcher: 数据获取器实例（可选）
        """
        self.db = db
        self.fetcher = fetcher

    def generate(self, symbol: str,
                 basic_info: Optional[dict] = None,
                 scores: Optional[dict] = None,
                 valuation: Optional[dict] = None,
                 risk: Optional[dict] = None,
                 expectation: Optional[dict] = None,
                 odds: Optional[dict] = None) -> str:
        """生成深度分析Markdown报告

        Args:
            symbol: 股票代码
            basic_info: 基础信息字典
            scores: 10维度评分字典
            valuation: 三情景估值结果
            risk: 风险评估结果
            expectation: 预期差分析结果
            odds: 赔率计算结果

        Returns:
            完整的Markdown格式报告字符串
        """
        name = basic_info.get('name', symbol) if basic_info else symbol
        pe = float(basic_info.get('pe_dynamic', 0) or 0) if basic_info else 0
        pb = float(basic_info.get('pb', 0) or 0) if basic_info else 0
        price = float(basic_info.get('price', 0) or 0) if basic_info else 0
        market_cap = float(basic_info.get('market_cap', 0) or 0) if basic_info else 0

        report = f"""# {name} ({symbol}) 深度分析报告

> 生成日期: {date.today().strftime('%Y-%m-%d')}
>
> **⚠️ 本报告仅供研究参考，不构成投资建议**

---

## 一、投资摘要

| 指标 | 数值 |
|------|------|
| 最新价格 | {price:.2f} 元 |
| 总市值 | {market_cap / 1e8:.0f} 亿 |
| PE(TTM) | {pe:.1f} |
| PB | {pb:.2f} |
| 隐含ROE | {pb / pe * 100 if pe > 0 else 0:.1f}% |

"""

        # 评分详情
        if scores:
            report += """
## 二、10维度评分

| 维度 | 评分 | 说明 |
|------|------|------|
"""
            dim_names = {
                'business_quality': '商业质量',
                'competitive_advantage': '竞争优势',
                'demand_certainty': '长期需求确定性',
                'management': '管理层',
                'financial_quality': '财务质量',
                'valuation_margin': '估值安全边际',
                'odds': '赔率',
                'predictability': '基本面可预测性',
                'market_pessimism': '市场悲观程度',
                'reversal_verifiability': '反转可验证性',
            }
            for dim, score_val in scores.items():
                bar = '█' * int(score_val) + '░' * (10 - int(score_val))
                report += f"| {dim_names.get(dim, dim)} | {bar} {score_val:.1f} | |\n"

        # 估值分析
        if valuation:
            report += f"""
## 三、估值分析

### 三情景估值

| 情景 | 合理价值 | 潜在收益 | 概率 |
|------|----------|----------|------|
| 悲观 | {valuation.get('pessimistic', {}).get('fair_value', 0):.2f} | {valuation.get('pessimistic', {}).get('upside_pct', 0):.1f}% | {valuation.get('pessimistic', {}).get('probability', 0) * 100:.0f}% |
| 基准 | {valuation.get('base', {}).get('fair_value', 0):.2f} | {valuation.get('base', {}).get('upside_pct', 0):.1f}% | {valuation.get('base', {}).get('probability', 0) * 100:.0f}% |
| 乐观 | {valuation.get('optimistic', {}).get('fair_value', 0):.2f} | {valuation.get('optimistic', {}).get('upside_pct', 0):.1f}% | {valuation.get('optimistic', {}).get('probability', 0) * 100:.0f}% |

- **加权合理价值**: {valuation.get('weighted_fair_value', 0):.2f} 元
- **期望收益**: {valuation.get('expected_return', 0):.1f}%
- **安全边际**: {valuation.get('margin_of_safety', 0):.1f}%
"""

        # 预期差
        if expectation:
            gap = expectation.get('gap_summary', '暂无数据')
            report += f"""
## 四、市场预期差分析

**核心结论**: {gap}

"""
            if 'market_implied' in expectation:
                mi = expectation['market_implied']
                report += f"""| 指标 | 数值 |
|------|------|
| 市场隐含利润 | {mi.get('implied_annual_profit', 0):.2f} 亿 |
| 正常化利润 | {mi.get('fair_annual_profit', 0):.2f} 亿 |
| 利润预期差 | {mi.get('profit_gap_pct', 0):.1f}% |
| 评估 | {mi.get('assessment', '暂无')} |
"""

        # 风险
        if risk:
            report += f"""
## 五、风险清单

- **综合风险等级**: {risk.get('overall_risk_level', '未知')}
- **红旗**: {', '.join(risk.get('risk_flags', ['无']))}
"""

        # 赔率
        if odds:
            report += f"""
## 六、赔率与仓位

| 指标 | 数值 |
|------|------|
| 赔率 | {odds.get('odds_ratio', 0):.2f}x |
| 期望收益 | {odds.get('expected_return', 0):.1f}% |
| 最大上涨空间 | {odds.get('max_upside', 0):.1f}% |
| 最大下跌空间 | {odds.get('max_downside', 0):.1f}% |
| 风险回报等级 | {odds.get('risk_reward_grade', '未知')} |
| 凯利仓位 | {odds.get('kelly_position', 0):.1f}% |
"""

        report += """
---

## 免责声明

本报告基于公开数据和量化模型自动生成，所有评分和结论仅供参考研究之用，不构成任何形式的投资建议。股市有风险，投资需谨慎。历史表现不代表未来收益。
"""

        return report

    def save_report(self, symbol: str, report_content: str,
                    output_dir: Optional[str] = None) -> str:
        """保存报告到文件

        Args:
            symbol: 股票代码
            report_content: Markdown报告内容
            output_dir: 输出目录，默认为 /workspace/output/reports

        Returns:
            保存的文件路径字符串
        """
        output_dir = Path(output_dir or '/workspace/output/reports')
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{symbol}_深度分析_{date.today().strftime('%Y%m%d')}.md"
        filepath = output_dir / filename
        filepath.write_text(report_content, encoding='utf-8')

        logger.info(f"深度报告已保存: {filepath}")
        return str(filepath)
