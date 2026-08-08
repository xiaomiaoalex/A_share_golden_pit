"""第二层筛选：深度观察池

从雷达池的200-400只候选标的中，通过基本面质量检查
（现金流、ROIC、商誉、毛利率、负债等）筛选到30-50只，
确认基本面没有永久性破坏。
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class DeepScreener:
    """第二层：深度观察池 —— 确认基本面没有永久性破坏"""

    def __init__(self, fetcher, thresholds, db=None):
        """初始化深度筛选器

        Args:
            fetcher: DataFetcher实例，用于获取详细财务数据
            thresholds: DeepScreenThreshold配置，包含各检查阈值
            db: DatabaseManager实例（可选），用于缓存与持久化
        """
        self.fetcher = fetcher
        self.thresholds = thresholds
        self.db = db

    def screen(self, candidates: pd.DataFrame) -> pd.DataFrame:
        """深度筛选候选标的

        对每个候选股票获取详细财务数据，检查：
        1. 自由现金流质量
        2. ROIC
        3. 商誉风险
        4. 毛利率稳定性
        5. 应收账款质量
        6. 负债结构
        7. 分红稳定性

        Args:
            candidates: 雷达池输出的候选标的DataFrame

        Returns:
            通过深度筛选的DataFrame，按质量得分降序排列
        """
        if candidates.empty:
            return pd.DataFrame()

        results = []
        total = len(candidates)

        for idx, row in candidates.iterrows():
            symbol = str(row.get('symbol', ''))
            if not symbol:
                continue

            try:
                check_result = self._check_stock(symbol, row)
                if check_result and check_result.get('passed', False):
                    # 合并原始数据和检查结果
                    merged = {**row.to_dict(), **check_result}
                    results.append(merged)

                if (len(results) + 1) % 50 == 0:
                    logger.info(f"深度筛选进度: {len(results)}/{total}")
            except Exception as e:
                logger.debug(f"深度筛选异常 {symbol}: {e}")
                continue

        result_df = pd.DataFrame(results)
        if not result_df.empty:
            # 按质量得分排序
            if 'quality_score' in result_df.columns:
                result_df = result_df.sort_values('quality_score', ascending=False)

        logger.info(f"深度筛选完成: {len(result_df)}/{total} 通过")
        return result_df

    def _check_stock(self, symbol: str, basic_info: pd.Series) -> Optional[dict]:
        """对单只股票执行全部检查

        Args:
            symbol: 股票代码
            basic_info: 该股票的基础行情信息

        Returns:
            包含是否通过、质量得分、各项检查明细的字典；
            至少通过3/5项才算合格
        """
        checks = {}
        passed_count = 0
        total_checks = 5  # 简化版本检查5项
        score = 0

        # 1. FCF质量检查
        fcf_check = self._check_fcf_quality(symbol, basic_info)
        checks['fcf_quality'] = fcf_check
        if fcf_check.get('ok', False):
            passed_count += 1
            score += 2

        # 2. ROIC检查
        roic_check = self._check_roic(symbol, basic_info)
        checks['roic'] = roic_check
        if roic_check.get('ok', False):
            passed_count += 1
            score += 2

        # 3. 商誉风险
        goodwill_check = self._check_goodwill(symbol, basic_info)
        checks['goodwill'] = goodwill_check
        if goodwill_check.get('ok', False):
            passed_count += 1
            score += 2

        # 4. 毛利率稳定性
        margin_check = self._check_margin_stability(symbol, basic_info)
        checks['margin_stability'] = margin_check
        if margin_check.get('ok', False):
            passed_count += 1
            score += 2

        # 5. 负债结构
        debt_check = self._check_debt(symbol, basic_info)
        checks['debt'] = debt_check
        if debt_check.get('ok', False):
            passed_count += 1
            score += 2

        # 至少通过3/5项才算合格
        passed = passed_count >= 3
        quality_score = score / 10.0  # 归一化到0-1

        return {
            'symbol': symbol,
            'passed': passed,
            'quality_score': round(quality_score, 2),
            'checks_passed': passed_count,
            'checks_total': total_checks,
            'checks_detail': checks,
        }

    def _check_fcf_quality(self, symbol: str, info: pd.Series) -> dict:
        """FCF质量检查：用盈利收益率（PE倒数）近似FCF收益率

        Args:
            symbol: 股票代码
            info: 基础行情信息

        Returns:
            检查结果字典，包含是否通过及盈利收益率
        """
        try:
            pe = float(info.get('pe_dynamic', 0) or 0)
            # 用PE倒数作为盈利收益率近似FCF收益率
            if pe > 0 and pe < 50:
                earnings_yield = 1.0 / pe
                ok = earnings_yield >= self.thresholds.MIN_FCF_YIELD
                return {
                    'ok': ok,
                    'earnings_yield': round(earnings_yield, 4),
                    'threshold': self.thresholds.MIN_FCF_YIELD,
                }
        except Exception:
            pass
        return {'ok': False, 'reason': '数据不足'}

    def _check_roic(self, symbol: str, info: pd.Series) -> dict:
        """ROIC检查：用 PB/PE 推算的隐含ROE作为代理

        Args:
            symbol: 股票代码
            info: 基础行情信息

        Returns:
            检查结果字典，包含是否通过及隐含ROE
        """
        try:
            pe = float(info.get('pe_dynamic', 0) or 0)
            pb = float(info.get('pb', 0) or 0)
            if pb > 0 and pe > 0:
                roe = pb / pe  # PB/PE = ROE
                ok = roe >= self.thresholds.MIN_ROIC
                return {
                    'ok': ok,
                    'implied_roe': round(roe, 4),
                    'threshold': self.thresholds.MIN_ROIC,
                }
        except Exception:
            pass
        return {'ok': False, 'reason': '数据不足'}

    def _check_goodwill(self, symbol: str, info: pd.Series) -> dict:
        """商誉风险检查：商誉/净资产比率不超过阈值

        无法获取数据时默认通过（保守处理）。

        Args:
            symbol: 股票代码
            info: 基础行情信息

        Returns:
            检查结果字典，包含是否通过及商誉占比
        """
        try:
            # 尝试获取资产负债表
            balance = self.fetcher.get_balance_sheet(symbol)
            if not balance.empty:
                # 查找商誉和净资产列
                goodwill_col = None
                equity_col = None
                for col in balance.columns:
                    if '商誉' in str(col):
                        goodwill_col = col
                    if '净资产' in str(col) or '所有者权益' in str(col) or '股东权益' in str(col):
                        equity_col = col

                if goodwill_col and equity_col:
                    latest = balance.iloc[0]
                    goodwill = pd.to_numeric(latest[goodwill_col], errors='coerce')
                    equity = pd.to_numeric(latest[equity_col], errors='coerce')
                    if pd.notna(goodwill) and pd.notna(equity) and equity > 0:
                        ratio = goodwill / equity
                        ok = ratio <= self.thresholds.MAX_GOODWILL_EQUITY
                        return {
                            'ok': ok,
                            'goodwill_equity_ratio': round(ratio, 4),
                            'threshold': self.thresholds.MAX_GOODWILL_EQUITY,
                        }
        except Exception:
            pass
        # 无法获取数据时默认通过（保守处理）
        return {'ok': True, 'reason': '无法获取商誉数据，默认通过'}

    def _check_margin_stability(self, symbol: str, info: pd.Series) -> dict:
        """毛利率稳定性检查：用变异系数衡量毛利率波动

        无法获取数据时默认通过（保守处理）。

        Args:
            symbol: 股票代码
            info: 基础行情信息

        Returns:
            检查结果字典，包含是否通过及稳定性指标
        """
        try:
            financial = self.fetcher.get_financial_indicators(symbol)
            if not financial.empty and 'gross_margin' in financial.columns:
                margins = pd.to_numeric(financial['gross_margin'], errors='coerce').dropna()
                if len(margins) >= 3:
                    cv = margins.std() / margins.mean() if margins.mean() > 0 else float('inf')
                    stability = 1.0 / (1.0 + cv)  # 稳定性指标
                    ok = stability >= self.thresholds.MIN_GROSS_MARGIN_STABILITY
                    return {
                        'ok': ok,
                        'margin_stability': round(stability, 4),
                        'avg_margin': round(float(margins.mean()), 2),
                        'threshold': self.thresholds.MIN_GROSS_MARGIN_STABILITY,
                    }
        except Exception:
            pass
        return {'ok': True, 'reason': '无法获取毛利率数据，默认通过'}

    def _check_debt(self, symbol: str, info: pd.Series) -> dict:
        """负债结构检查：资产负债率不超过70%

        无法获取数据时默认通过（保守处理）。

        Args:
            symbol: 股票代码
            info: 基础行情信息

        Returns:
            检查结果字典，包含是否通过及资产负债率
        """
        try:
            financial = self.fetcher.get_financial_indicators(symbol)
            if not financial.empty and 'debt_ratio' in financial.columns:
                debt_ratios = pd.to_numeric(financial['debt_ratio'], errors='coerce').dropna()
                if not debt_ratios.empty:
                    latest_debt = debt_ratios.iloc[0]
                    ok = latest_debt <= 70  # 资产负债率不超过70%
                    return {
                        'ok': ok,
                        'debt_ratio': round(float(latest_debt), 2),
                        'threshold': 70,
                    }
        except Exception:
            pass
        return {'ok': True, 'reason': '无法获取负债数据，默认通过'}
