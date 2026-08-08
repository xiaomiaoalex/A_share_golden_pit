"""财务造假红旗检测器"""

import logging
from typing import Dict, List

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class FinancialRedFlagDetector:
    """财务造假红旗检测器

    通过多个维度的财务数据分析，检测可能存在的财务造假信号：
    - 收入质量（应收账款/营收比率）
    - 毛利率异常波动（变异系数）
    - 经营现金流与净利润背离
    - PE/PB合理性
    """

    def __init__(self, fetcher, settings=None):
        """初始化红旗检测器

        Args:
            fetcher: 数据获取器实例，需提供 get_income_statement、get_balance_sheet、
                     get_cashflow_statement、get_financial_indicators 等方法
            settings: 配置对象（可选）
        """
        self.fetcher = fetcher
        self.settings = settings

    def detect_all(self, symbol: str, basic_info: dict = None) -> dict:
        """执行全部红旗检测

        Args:
            symbol: 股票代码
            basic_info: 基础信息字典，包含 pe_dynamic, pb 等字段

        Returns:
            {
                'red_flags': list,           # 触发的红旗列表
                'red_flag_count': int,       # 红旗数量
                'fraud_risk_level': str,     # 造假风险等级：极高/高/中/低/未知
                'checks': dict,              # 各检查项详情
            }
        """
        try:
            red_flags = []
            checks = {}

            # 1. 收入质量
            revenue_check = self._check_revenue_quality(symbol)
            checks['revenue_quality'] = revenue_check
            if revenue_check.get('flag', False):
                red_flags.append('收入质量存疑')

            # 2. 毛利率异常
            margin_check = self._check_margin_anomaly(symbol)
            checks['margin_anomaly'] = margin_check
            if margin_check.get('flag', False):
                red_flags.append('毛利率异常波动')

            # 3. 经营现金流/净利润
            cfo_check = self._check_cfo_ratio(symbol)
            checks['cfo_ratio'] = cfo_check
            if cfo_check.get('flag', False):
                red_flags.append('经营现金流与净利润严重背离')

            # 4. PE/PB合理性
            pe = float(basic_info.get('pe_dynamic', 0) or 0) if basic_info else 0
            pb = float(basic_info.get('pb', 0) or 0) if basic_info else 0
            if pe > 100:
                red_flags.append('PE畸高，盈利质量存疑')
            if pb > 20:
                red_flags.append('PB畸高，资产质量存疑')

            # 风险等级
            count = len(red_flags)
            if count >= 3:
                fraud_level = '极高'
            elif count >= 2:
                fraud_level = '高'
            elif count >= 1:
                fraud_level = '中'
            else:
                fraud_level = '低'

            return {
                'red_flags': red_flags if red_flags else ['未发现明显红旗'],
                'red_flag_count': count,
                'fraud_risk_level': fraud_level,
                'checks': checks,
            }
        except Exception as e:
            logger.error(f"红旗检测失败 {symbol}: {e}")
            return {
                'red_flags': ['检测失败'],
                'red_flag_count': 0,
                'fraud_risk_level': '未知',
                'checks': {},
            }

    def _check_revenue_quality(self, symbol: str) -> dict:
        """收入质量检查

        通过比较应收账款与营业收入的比例，判断收入质量。
        应收账款/营收比率过高可能意味着：
        - 虚增收入（确认收入但未实际回款）
        - 回款周期过长，现金流压力大

        Args:
            symbol: 股票代码

        Returns:
            {'flag': bool, 'ar_revenue_ratio': float, 'detail': str}
        """
        try:
            income = self.fetcher.get_income_statement(symbol)
            balance = self.fetcher.get_balance_sheet(symbol)

            if income.empty or balance.empty:
                return {'flag': False, 'detail': '数据不足'}

            # 查找营业收入
            revenue = None
            for col in income.columns:
                if '营业' in str(col) and '收入' in str(col):
                    revenue = pd.to_numeric(income[col].iloc[0], errors='coerce')
                    break

            # 查找应收账款
            ar = None
            for col in balance.columns:
                if '应收' in str(col):
                    ar = pd.to_numeric(balance[col].iloc[0], errors='coerce')
                    break

            if pd.notna(revenue) and pd.notna(ar) and revenue > 0:
                ratio = ar / revenue
                flag = ratio > 0.50
                return {
                    'flag': flag,
                    'ar_revenue_ratio': round(ratio, 2),
                    'detail': f'应收/营收={ratio:.1%}' + ('(异常)' if flag else ''),
                }
        except Exception:
            pass
        return {'flag': False, 'detail': '数据不足'}

    def _check_margin_anomaly(self, symbol: str) -> dict:
        """毛利率异常检查

        通过计算毛利率的变异系数（标准差/均值），检测毛利率是否存在异常波动。
        毛利率异常波动可能意味着：
        - 成本确认方式不一致
        - 收入确认政策变更
        - 业务模式发生重大变化

        Args:
            symbol: 股票代码

        Returns:
            {'flag': bool, 'margin_cv': float, 'avg_margin': float, 'detail': str}
        """
        try:
            financial = self.fetcher.get_financial_indicators(symbol)
            if financial.empty or 'gross_margin' not in financial.columns:
                return {'flag': False, 'detail': '数据不足'}

            margins = pd.to_numeric(financial['gross_margin'], errors='coerce').dropna()
            if len(margins) < 3:
                return {'flag': False, 'detail': '数据点不足'}

            cv = margins.std() / margins.mean() if margins.mean() > 0 else 0
            flag = cv > 0.5  # 变异系数>0.5视为异常

            return {
                'flag': flag,
                'margin_cv': round(cv, 2),
                'avg_margin': round(float(margins.mean()), 1),
                'detail': f'毛利率CV={cv:.2f}' + ('(异常波动)' if flag else ''),
            }
        except Exception:
            pass
        return {'flag': False, 'detail': '数据不足'}

    def _check_cfo_ratio(self, symbol: str) -> dict:
        """经营现金流/净利润比率检查

        检查经营现金流与净利润的匹配程度。
        经营现金流长期低于净利润可能意味着：
        - 利润含金量低（大量应收账款或存货）
        - 虚增利润（账面盈利但无现金流入）

        Args:
            symbol: 股票代码

        Returns:
            {'flag': bool, 'cfo_ni_ratio': float, 'detail': str}
        """
        try:
            cashflow = self.fetcher.get_cashflow_statement(symbol)
            income = self.fetcher.get_income_statement(symbol)

            if cashflow.empty or income.empty:
                return {'flag': False, 'detail': '数据不足'}

            # 查找经营活动现金流
            cfo = None
            for col in cashflow.columns:
                if '经营' in str(col) and ('现金流' in str(col) or '现金' in str(col)):
                    cfo = pd.to_numeric(cashflow[col].iloc[0], errors='coerce')
                    break

            # 查找净利润
            ni = None
            for col in income.columns:
                if '净利润' in str(col):
                    ni = pd.to_numeric(income[col].iloc[0], errors='coerce')
                    break

            if pd.notna(cfo) and pd.notna(ni) and ni > 0:
                ratio = cfo / ni
                flag = ratio < 0.5  # 经营现金流不足净利润50%
                return {
                    'flag': flag,
                    'cfo_ni_ratio': round(ratio, 2),
                    'detail': f'经营现金流/净利润={ratio:.1%}' + ('(严重背离)' if flag else ''),
                }
        except Exception:
            pass
        return {'flag': False, 'detail': '数据不足'}
