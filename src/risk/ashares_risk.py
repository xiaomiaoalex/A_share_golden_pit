"""A股特殊风险检测器"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class AShareRiskChecker:
    """A股特殊风险检测器

    针对A股市场的特殊风险进行检测，包括：
    - 大股东质押风险
    - 商誉减值风险
    - 应收账款异常风险
    - 高负债风险
    - 亏损风险
    """

    def __init__(self, fetcher, settings=None):
        """初始化风险检测器

        Args:
            fetcher: 数据获取器实例，需提供 get_balance_sheet、get_financial_indicators 等方法
            settings: 配置对象（可选）
        """
        self.fetcher = fetcher
        self.settings = settings

    def check_all(self, symbol: str, basic_info: dict = None) -> dict:
        """执行全部A股特殊风险检查

        Args:
            symbol: 股票代码
            basic_info: 基础信息字典，包含 pe_dynamic, pb 等字段

        Returns:
            {
                'pledge_risk': dict,            # 质押风险
                'goodwill_risk': dict,          # 商誉风险
                'receivable_risk': dict,        # 应收账款风险
                'debt_risk': dict,              # 负债风险
                'overall_risk_level': str,      # 综合风险等级：极高/高/中/低/未知
                'risk_flags': list,             # 风险红旗列表
                'risk_score': float,            # 风险评分(0-10, 越高越危险)
            }
        """
        try:
            risks = {}
            risk_flags = []
            risk_score = 0

            # 提取基础指标
            pb = float(basic_info.get('pb', 0) or 0) if basic_info else 0
            pe = float(basic_info.get('pe_dynamic', 0) or 0) if basic_info else 0

            # 1. 质押风险（从行情数据无法直接获取，用PB间接判断）
            pledge_risk = self._check_pledge_risk(symbol, pb)
            risks['pledge_risk'] = pledge_risk
            if pledge_risk.get('level') == '高':
                risk_flags.append('大股东质押风险')
                risk_score += 3

            # 2. 商誉风险
            goodwill_risk = self._check_goodwill_risk(symbol)
            risks['goodwill_risk'] = goodwill_risk
            if goodwill_risk.get('level') == '高':
                risk_flags.append('商誉减值风险')
                risk_score += 2

            # 3. 应收账款风险
            ar_risk = self._check_receivable_risk(symbol)
            risks['receivable_risk'] = ar_risk
            if ar_risk.get('level') == '高':
                risk_flags.append('应收账款异常')
                risk_score += 2

            # 4. 负债风险
            debt_risk = self._check_debt_risk(symbol)
            risks['debt_risk'] = debt_risk
            if debt_risk.get('level') == '高':
                risk_flags.append('高负债风险')
                risk_score += 2

            # 5. PE异常
            if pe <= 0:
                risk_flags.append('当前亏损')
                risk_score += 3

            # 综合风险等级
            if risk_score >= 6:
                overall = '极高'
            elif risk_score >= 4:
                overall = '高'
            elif risk_score >= 2:
                overall = '中'
            else:
                overall = '低'

            return {
                'pledge_risk': pledge_risk,
                'goodwill_risk': goodwill_risk,
                'receivable_risk': ar_risk,
                'debt_risk': debt_risk,
                'overall_risk_level': overall,
                'risk_flags': risk_flags if risk_flags else ['无明显红旗'],
                'risk_score': round(risk_score, 1),
            }
        except Exception as e:
            logger.error(f"风险检查失败 {symbol}: {e}")
            return {
                'overall_risk_level': '未知',
                'risk_flags': ['检查失败'],
                'risk_score': 5,
            }

    def _check_pledge_risk(self, symbol: str, pb: float) -> dict:
        """质押风险检查（使用PB间接判断）

        大股东质押数据无法直接从AKShare获取，通过PB间接判断。
        PB为负或破净可能意味着资产质量存疑，间接反映质押等隐性风险。

        Args:
            symbol: 股票代码
            pb: 市净率

        Returns:
            {'level': str, 'detail': str, 'pb': float}
        """
        if pb <= 0:
            return {'level': '高', 'detail': 'PB为负，资产质量存疑', 'pb': pb}
        elif pb < 1.0:
            return {'level': '中', 'detail': 'PB<1（破净），需关注资产质量', 'pb': pb}
        else:
            return {'level': '低', 'detail': 'PB正常', 'pb': pb}

    def _check_goodwill_risk(self, symbol: str) -> dict:
        """商誉风险检查

        通过资产负债表计算商誉/净资产比率。
        商誉占比过高意味着并购溢价过高，存在商誉减值风险。

        Args:
            symbol: 股票代码

        Returns:
            {'level': str, 'detail': str, 'ratio': float}
        """
        try:
            balance = self.fetcher.get_balance_sheet(symbol)
            if balance.empty:
                return {'level': '低', 'detail': '无法获取数据'}

            # 查找商誉和净资产
            goodwill = None
            equity = None
            for col in balance.columns:
                col_str = str(col)
                if '商誉' in col_str:
                    goodwill = pd.to_numeric(balance[col].iloc[0], errors='coerce')
                if '所有者权益' in col_str or '股东权益' in col_str or '净资产' in col_str:
                    equity = pd.to_numeric(balance[col].iloc[0], errors='coerce')

            if pd.notna(goodwill) and pd.notna(equity) and equity > 0:
                ratio = goodwill / equity
                if ratio > 0.50:
                    return {'level': '高', 'detail': f'商誉/净资产={ratio:.1%}', 'ratio': ratio}
                elif ratio > 0.30:
                    return {'level': '中', 'detail': f'商誉/净资产={ratio:.1%}', 'ratio': ratio}
                else:
                    return {'level': '低', 'detail': f'商誉/净资产={ratio:.1%}', 'ratio': ratio}
        except Exception:
            pass
        return {'level': '低', 'detail': '数据不足，默认通过'}

    def _check_receivable_risk(self, symbol: str) -> dict:
        """应收账款风险检查

        通过资产负债表计算应收账款/总资产比率。
        应收账款占比过高可能意味着回款困难或虚增收入。

        Args:
            symbol: 股票代码

        Returns:
            {'level': str, 'detail': str, 'ratio': float}
        """
        try:
            balance = self.fetcher.get_balance_sheet(symbol)
            if balance.empty:
                return {'level': '低', 'detail': '无法获取数据'}

            # 查找应收账款和总资产
            ar = None
            total_assets = None
            for col in balance.columns:
                col_str = str(col)
                if '应收' in col_str and '账款' in col_str:
                    ar = pd.to_numeric(balance[col].iloc[0], errors='coerce')
                if '资产总计' in col_str or '总资产' in col_str:
                    total_assets = pd.to_numeric(balance[col].iloc[0], errors='coerce')

            if pd.notna(ar) and pd.notna(total_assets) and total_assets > 0:
                ratio = ar / total_assets
                if ratio > 0.30:
                    return {'level': '高', 'detail': f'应收/总资产={ratio:.1%}', 'ratio': ratio}
                elif ratio > 0.20:
                    return {'level': '中', 'detail': f'应收/总资产={ratio:.1%}', 'ratio': ratio}
                else:
                    return {'level': '低', 'detail': f'应收/总资产={ratio:.1%}', 'ratio': ratio}
        except Exception:
            pass
        return {'level': '低', 'detail': '数据不足，默认通过'}

    def _check_debt_risk(self, symbol: str) -> dict:
        """负债风险检查

        通过财务指标获取资产负债率。
        负债率过高意味着财务杠杆过大，偿债压力高。

        Args:
            symbol: 股票代码

        Returns:
            {'level': str, 'detail': str, 'ratio': float}
        """
        try:
            financial = self.fetcher.get_financial_indicators(symbol)
            if not financial.empty and 'debt_ratio' in financial.columns:
                debt = pd.to_numeric(financial['debt_ratio'].iloc[0], errors='coerce')
                if pd.notna(debt):
                    if debt > 80:
                        return {'level': '高', 'detail': f'资产负债率={debt:.1f}%', 'ratio': debt}
                    elif debt > 60:
                        return {'level': '中', 'detail': f'资产负债率={debt:.1f}%', 'ratio': debt}
                    else:
                        return {'level': '低', 'detail': f'资产负债率={debt:.1f}%', 'ratio': debt}
        except Exception:
            pass
        return {'level': '低', 'detail': '数据不足，默认通过'}
