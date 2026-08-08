"""
黄金坑数据库模板字段组装器。

将扫描系统产出的原始数据（行情、财务、估值、评分、风险）
组装成《黄金坑数据库》模板要求的 56 列完整记录格式。

设计原则：
1. 系统自动计算所有可量化字段（估值、预期差、赔率、评分等）
2. 人工判断字段给出系统初稿并标注「待人工复核」，或留空
3. 所有数据自动标注来源与日期
"""

import logging
from datetime import date
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ============ 模板列定义（深度观察池/核心黄金坑，56列） ============
FULL_COLUMNS = [
    # 【基础信息】
    '股票代码', '公司名称', '行业', '数据更新日期',
    # 【市场与估值现状】
    '当前股价(元)', '总市值(亿元)', 'PE(TTM)', 'PB', 'EV/EBIT',
    '股息率(%)', '历史估值分位(%)', '近期最大回撤(%)',
    # 【盈利质量】
    'ROE(%)', 'ROIC(%)', '自由现金流(亿元)', '净现金(+)/净负债(-)(亿元)',
    # 【黄金坑判断】
    '黄金坑评级', '黄金坑原因(具体利空)', '市场悲观逻辑', '基本面是否破坏',
    '终端需求趋势', '市场份额趋势', '核心竞争优势',
    # 【市场预期差模块】
    '市场隐含利润(亿元)', '隐含利润反推口径', '市场核心悲观假设',
    '我的基准假设-正常化利润(亿元)', '预期差(基准÷隐含)',
    # 【三情景估值】
    '正常化利润(亿元)', '悲观估值(亿元)', '合理估值(亿元)', '乐观估值(亿元)',
    '潜在下跌空间(%)', '合理上涨空间(%)', '赔率(合理估值÷市值)',
    # 【SOR3.0四变量】
    '概率(低/中/高)', '赔率等级(低/中/高/极高)', '预计周期(短/中/长)',
    '仓位适配度', '建议最大仓位(%)',
    # 【催化剂与风险】
    '主要催化剂', '核心风险', '证伪条件(3-5条)', '关键跟踪指标',
    # 【十项评分】
    '评分-商业质量', '评分-竞争优势', '评分-长期需求确定性', '评分-管理层',
    '评分-财务质量', '评分-估值安全边际', '评分-赔率', '评分-基本面可预测性',
    '评分-市场悲观程度', '评分-反转可验证性', '致命缺陷备注(单项≤3必填)',
    # 【来源】
    '信息来源(含日期与口径)',
]

# ============ 雷达池列定义（17列） ============
RADAR_COLUMNS = [
    '股票代码', '公司名称', '行业', '扫描日期',
    '当前股价(元)', '总市值(亿元)', 'PE(TTM)', 'PB', '股息率(%)',
    'ROE(%)', '历史估值分位(%)', '近期最大回撤(%)',
    '初步利空/回撤原因', '初筛质量判断', '初筛结论',
    '信息来源(含日期与口径)', '备注',
]

# ============ 价值陷阱列定义（10列） ============
TRAP_COLUMNS = [
    '股票代码', '公司名称', '行业', '判定日期', '判定理由', '关键证据',
    '复盘日期', '复盘结论', '信息来源(含日期与口径)', '备注',
]

# ============ 证伪日志列定义（10列） ============
FALSIFICATION_COLUMNS = [
    '记录日期', '股票代码', '公司名称', '证伪条件', '触发阈值',
    '当前读数', '状态', '证据来源(含日期)', '处理动作', '备注',
]

# 十项评分键名 → 模板列名
SCORE_KEY_MAP = {
    'business_quality': '评分-商业质量',
    'competitive_advantage': '评分-竞争优势',
    'demand_certainty': '评分-长期需求确定性',
    'management': '评分-管理层',
    'financial_quality': '评分-财务质量',
    'valuation_margin': '评分-估值安全边际',
    'odds': '评分-赔率',
    'predictability': '评分-基本面可预测性',
    'market_pessimism': '评分-市场悲观程度',
    'reversal_verifiability': '评分-反转可验证性',
}


def _safe_float(value, default=None) -> Optional[float]:
    """安全转 float"""
    try:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return default
        return float(value)
    except (ValueError, TypeError):
        return default


def _r2(value, default=None):
    """保留2位小数"""
    v = _safe_float(value)
    return round(v, 2) if v is not None else default


def _r1(value, default=None):
    """保留1位小数"""
    v = _safe_float(value)
    return round(v, 1) if v is not None else default


def _to_yi(value, default=None) -> Optional[float]:
    """元 → 亿元"""
    v = _safe_float(value)
    return round(v / 1e8, 2) if v is not None else default


def _pct(value, default=None) -> Optional[float]:
    """0-1小数 → 百分数"""
    v = _safe_float(value)
    return round(v * 100, 2) if v is not None else default


class RecordBuilder:
    """模板记录组装器

    将各模块产出的分析结果组装为模板格式的记录行。
    """

    def __init__(self, fetcher=None, scan_date: Optional[date] = None):
        """初始化

        Args:
            fetcher: DataFetcher 实例（用于补充数据，可选）
            scan_date: 扫描日期，默认今天
        """
        self.fetcher = fetcher
        self.scan_date = scan_date or date.today()
        self.date_str = self.scan_date.strftime('%Y-%m-%d')

    # =========================================================
    # 雷达池记录（17列，轻量）
    # =========================================================
    def build_radar_record(self, row: pd.Series) -> Dict[str, Any]:
        """组装雷达池记录

        Args:
            row: 雷达扫描结果行（含 symbol/name/price/pe/pb/market_cap 等）

        Returns:
            17列字典
        """
        symbol = str(row.get('symbol', ''))
        name = str(row.get('name', ''))
        price = _safe_float(row.get('price'))
        pe = _safe_float(row.get('pe_dynamic'))
        pb = _safe_float(row.get('pb'))
        market_cap_yi = _to_yi(row.get('market_cap'))
        drawdown = _safe_float(row.get('drawdown_52w') or row.get('change_60d'))
        pe_pct = _safe_float(row.get('pe_percentile'))

        # 隐含ROE代理：PB/PE
        implied_roe = None
        if pe and pe > 0 and pb and pb > 0:
            implied_roe = round(pb / pe * 100, 2)

        # 股息率（若有）
        div_yield = _safe_float(row.get('dividend_yield'))

        # 初筛质量判断
        quality_notes = []
        if implied_roe and implied_roe >= 15:
            quality_notes.append('隐含ROE≥15%')
        elif implied_roe and implied_roe >= 10:
            quality_notes.append('隐含ROE≥10%')
        if pe and 0 < pe <= 15:
            quality_notes.append(f'PE={pe:.1f}低位')
        if pb and 0 < pb <= 1.5:
            quality_notes.append(f'PB={pb:.2f}低位')
        quality_judge = '；'.join(quality_notes) if quality_notes else '数据不足'

        # 初步利空原因（系统推断）
        reason_parts = []
        if drawdown and drawdown <= -30:
            reason_parts.append(f'60日下跌{abs(drawdown):.0f}%')
        if pe_pct and pe_pct <= 20:
            reason_parts.append(f'估值历史分位{pe_pct:.0f}%')
        reason = '；'.join(reason_parts) if reason_parts else '待人工核实具体利空'

        return {
            '股票代码': symbol,
            '公司名称': name,
            '行业': str(row.get('industry', '') or ''),
            '扫描日期': self.date_str,
            '当前股价(元)': _r2(price),
            '总市值(亿元)': market_cap_yi,
            'PE(TTM)': _r2(pe),
            'PB': _r2(pb),
            '股息率(%)': _r2(div_yield),
            'ROE(%)': implied_roe,
            '历史估值分位(%)': _r1(pe_pct),
            '近期最大回撤(%)': _r1(drawdown),
            '初步利空/回撤原因': reason,
            '初筛质量判断': quality_judge,
            '初筛结论': '通过雷达初筛，待深度验证',
            '信息来源(含日期与口径)': f'AKShare行情快照({self.date_str})；PE为动态口径',
            '备注': '',
        }

    # =========================================================
    # 完整记录（56列）
    # =========================================================
    def build_full_record(
        self,
        row: pd.Series,
        valuation: Optional[Dict] = None,
        expectation: Optional[Dict] = None,
        scores: Optional[Dict] = None,
        risk: Optional[Dict] = None,
        rating: Optional[str] = None,
        odds_info: Optional[Dict] = None,
        financial: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """组装深度观察池/核心黄金坑完整记录

        Args:
            row: 基础行情行
            valuation: 三情景估值结果 {pessimistic, base, optimistic, ...}
            expectation: 预期差结果 {implied_profit, base_assumption, gap, ...}
            scores: 十项评分 {business_quality: x, ...}
            risk: 风险检查结果 {overall_risk_level, risk_flags, ...}
            rating: 黄金坑评级 S/A/B/C/价值陷阱
            odds_info: 赔率信息 {odds_ratio, probability, cycle, ...}
            financial: 财务数据 {roe, roic, fcf, net_cash, dividend_yield, ...}

        Returns:
            56列字典
        """
        valuation = valuation or {}
        expectation = expectation or {}
        scores = scores or {}
        risk = risk or {}
        odds_info = odds_info or {}
        financial = financial or {}

        symbol = str(row.get('symbol', ''))
        name = str(row.get('name', ''))
        price = _safe_float(row.get('price'))
        pe = _safe_float(row.get('pe_dynamic'))
        pb = _safe_float(row.get('pb'))
        mc_yi = _to_yi(row.get('market_cap'))

        # ---- 盈利质量 ----
        roe = _safe_float(financial.get('roe'))
        roic = _safe_float(financial.get('roic'))
        fcf_yi = _to_yi(financial.get('free_cashflow'))
        net_cash_yi = _to_yi(financial.get('net_cash'))
        div_yield = _safe_float(financial.get('dividend_yield') or row.get('dividend_yield'))

        # ROE 代理：PB/PE
        if roe is None and pe and pe > 0 and pb and pb > 0:
            roe = round(pb / pe * 100, 2)

        # ---- 估值分位/回撤 ----
        pe_pct = _safe_float(row.get('pe_percentile'))
        drawdown = _safe_float(row.get('drawdown_52w') or row.get('change_60d'))

        # ---- 预期差模块 ----
        # 市场隐含利润 = 当前市值 ÷ 当前PE（市场当前定价所隐含的利润水平）
        implied_profit = _r2(expectation.get('implied_profit'))
        implied_method = expectation.get('implied_method') or ''
        if implied_profit is None and mc_yi and pe and pe > 0:
            implied_profit = round(mc_yi / pe, 2)
            implied_method = f'市值÷当前PE(TTM)={pe:.1f}x'

        # 我的基准假设-正常化利润：优先使用基于历史财报的真实正常化利润
        base_profit = _r2(
            expectation.get('base_assumption_profit')
            or expectation.get('normalized_earnings')
            or financial.get('normalized_profit')
        )
        gap = None
        if base_profit and implied_profit and implied_profit > 0:
            gap = round(base_profit / implied_profit, 2)
        pessimistic_hyp = expectation.get('market_pessimism') or ''

        # ---- 三情景估值（仅有正常化利润时计算，否则留空）----
        norm_profit = base_profit
        pess_val = _r2(valuation.get('pessimistic_value'))
        base_val = _r2(valuation.get('base_value') or valuation.get('fair_value'))
        opt_val = _r2(valuation.get('optimistic_value'))

        if norm_profit and norm_profit > 0:
            # 系统初算：悲观10x / 合理=历史中枢PE / 乐观=中枢+50%
            fair_pe = _safe_float(valuation.get('fair_pe')) or 15
            if pess_val is None:
                pess_val = round(norm_profit * max(8, fair_pe * 0.7), 2)
            if base_val is None:
                base_val = round(norm_profit * fair_pe, 2)
            if opt_val is None:
                opt_val = round(norm_profit * fair_pe * 1.4, 2)

        downside = None
        upside = None
        odds_ratio = _r2(odds_info.get('odds_ratio'))
        if mc_yi and mc_yi > 0:
            if pess_val:
                downside = round((pess_val / mc_yi - 1) * 100, 1)
            if base_val:
                upside = round((base_val / mc_yi - 1) * 100, 1)
            if odds_ratio is None and base_val:
                odds_ratio = round(base_val / mc_yi, 2)

        # ---- SOR3.0 四变量 ----
        probability = odds_info.get('probability') or self._infer_probability(scores, risk)
        odds_level = self._infer_odds_level(odds_ratio)
        cycle = odds_info.get('cycle') or '中'
        position_type, max_position = self._infer_position(
            rating, odds_ratio, probability, risk.get('overall_risk_level'))

        # ---- 评分 ----
        score_cols = {}
        fatal_notes = []
        for key, col in SCORE_KEY_MAP.items():
            v = scores.get(key)
            v = int(round(v)) if v is not None else None
            score_cols[col] = v
            if v is not None and v <= 3:
                label = col.replace('评分-', '')
                fatal_notes.append(f'{label}仅{v}分')

        fatal_note = '；'.join(fatal_notes) if fatal_notes else ''

        # ---- 风险 ----
        risk_level = risk.get('overall_risk_level', '')
        risk_flags = risk.get('risk_flags') or {}
        core_risks = []
        if isinstance(risk_flags, dict):
            for k, v in risk_flags.items():
                if v:
                    core_risks.append(str(k))
        core_risk_text = '；'.join(core_risks[:4]) if core_risks else (
            f'整体风险:{risk_level}' if risk_level else '待人工复核')

        # ---- 黄金坑判断（系统初稿）----
        pit_reason = self._infer_pit_reason(row, drawdown, pe_pct, financial)
        pessimism_logic = pessimistic_hyp or self._infer_pessimism(row, pe, pe_pct)
        fundamental_damage = self._infer_damage(scores, risk, financial)

        # ---- 证伪条件与跟踪指标 ----
        falsification = self._build_falsification(row, financial, valuation)
        tracking = self._build_tracking(financial)

        # ---- 来源 ----
        source = (f'AKShare行情+财务({self.date_str})；'
                  f'PE动态口径；预期差/估值为系统初算，'
                  f'评级与判断字段需人工复核')

        record = {
            # 基础信息
            '股票代码': symbol,
            '公司名称': name,
            '行业': str(row.get('industry', '') or ''),
            '数据更新日期': self.date_str,
            # 市场与估值现状
            '当前股价(元)': _r2(price),
            '总市值(亿元)': mc_yi,
            'PE(TTM)': _r2(pe),
            'PB': _r2(pb),
            'EV/EBIT': _r2(financial.get('ev_ebit')),
            '股息率(%)': _r2(div_yield),
            '历史估值分位(%)': _r1(pe_pct),
            '近期最大回撤(%)': _r1(drawdown),
            # 盈利质量
            'ROE(%)': _r2(roe),
            'ROIC(%)': _r2(roic),
            '自由现金流(亿元)': fcf_yi,
            '净现金(+)/净负债(-)(亿元)': net_cash_yi,
            # 黄金坑判断
            '黄金坑评级': rating or '暂无法判断',
            '黄金坑原因(具体利空)': pit_reason,
            '市场悲观逻辑': pessimism_logic,
            '基本面是否破坏': fundamental_damage,
            '终端需求趋势': '',
            '市场份额趋势': '',
            '核心竞争优势': '',
            # 市场预期差模块
            '市场隐含利润(亿元)': implied_profit,
            '隐含利润反推口径': implied_method,
            '市场核心悲观假设': pessimistic_hyp,
            '我的基准假设-正常化利润(亿元)': base_profit,
            '预期差(基准÷隐含)': gap,
            # 三情景估值
            '正常化利润(亿元)': _r2(norm_profit),
            '悲观估值(亿元)': pess_val,
            '合理估值(亿元)': base_val,
            '乐观估值(亿元)': opt_val,
            '潜在下跌空间(%)': downside,
            '合理上涨空间(%)': upside,
            '赔率(合理估值÷市值)': odds_ratio,
            # SOR3.0
            '概率(低/中/高)': probability,
            '赔率等级(低/中/高/极高)': odds_level,
            '预计周期(短/中/长)': cycle,
            '仓位适配度': position_type,
            '建议最大仓位(%)': max_position,
            # 催化剂与风险
            '主要催化剂': '',
            '核心风险': core_risk_text,
            '证伪条件(3-5条)': falsification,
            '关键跟踪指标': tracking,
            # 十项评分
            **score_cols,
            '致命缺陷备注(单项≤3必填)': fatal_note,
            # 来源
            '信息来源(含日期与口径)': source,
        }
        return record

    # =========================================================
    # 价值陷阱记录（10列）
    # =========================================================
    def build_trap_record(self, row: pd.Series, reason: str,
                          evidence: str) -> Dict[str, Any]:
        """组装价值陷阱记录"""
        return {
            '股票代码': str(row.get('symbol', '')),
            '公司名称': str(row.get('name', '')),
            '行业': str(row.get('industry', '') or ''),
            '判定日期': self.date_str,
            '判定理由': reason,
            '关键证据': evidence,
            '复盘日期': '',
            '复盘结论': '',
            '信息来源(含日期与口径)': f'AKShare({self.date_str})，系统初判待人工复核',
            '备注': '',
        }

    # =========================================================
    # 证伪日志记录（10列）
    # =========================================================
    def build_falsification_log(self, row: pd.Series,
                                conditions: List[Dict]) -> List[Dict[str, Any]]:
        """组装证伪日志记录

        Args:
            row: 股票基础行
            conditions: 证伪条件列表 [{condition, threshold, current, triggered}, ...]
        """
        logs = []
        for c in conditions:
            triggered = c.get('triggered', False)
            logs.append({
                '记录日期': self.date_str,
                '股票代码': str(row.get('symbol', '')),
                '公司名称': str(row.get('name', '')),
                '证伪条件': c.get('condition', ''),
                '触发阈值': c.get('threshold', ''),
                '当前读数': c.get('current', ''),
                '状态': '已触发' if triggered else '未触发',
                '证据来源(含日期)': f'AKShare({self.date_str})',
                '处理动作': '降级并复核' if triggered else '持续跟踪',
                '备注': '',
            })
        return logs

    # =========================================================
    # 内部推断方法（系统初稿，均需人工复核）
    # =========================================================
    def _infer_probability(self, scores: Dict, risk: Dict) -> str:
        """根据评分与风险推断概率等级"""
        if not scores:
            return '中'
        vals = [v for v in scores.values() if isinstance(v, (int, float))]
        if not vals:
            return '中'
        avg = np.mean(vals)
        if risk.get('overall_risk_level') == '高':
            return '低'
        if avg >= 7:
            return '高'
        if avg >= 5:
            return '中'
        return '低'

    def _infer_odds_level(self, odds_ratio: Optional[float]) -> str:
        """赔率数值 → 等级"""
        if odds_ratio is None:
            return '低'
        if odds_ratio >= 3:
            return '极高'
        if odds_ratio >= 2:
            return '高'
        if odds_ratio >= 1.3:
            return '中'
        return '低'

    def _infer_position(self, rating, odds_ratio, probability, risk_level):
        """推断仓位适配度与上限"""
        if risk_level == '极高' or rating in ('价值陷阱',):
            return '观察', 0
        if rating == 'S' and odds_ratio and odds_ratio >= 2.5 and probability == '高':
            return '核心仓', 20
        if rating in ('S', 'A') and odds_ratio and odds_ratio >= 2:
            return '中仓', 12
        if rating in ('A', 'B') and odds_ratio and odds_ratio >= 1.5:
            return '小仓', 6
        return '观察', 3

    def _infer_pit_reason(self, row, drawdown, pe_pct, financial) -> str:
        """推断黄金坑原因（具体利空）"""
        parts = []
        if drawdown and drawdown <= -40:
            parts.append(f'股价60日大幅回撤{abs(drawdown):.0f}%')
        elif drawdown and drawdown <= -30:
            parts.append(f'股价60日回撤{abs(drawdown):.0f}%')
        if pe_pct and pe_pct <= 10:
            parts.append(f'估值处历史{pe_pct:.0f}%极低位')
        elif pe_pct and pe_pct <= 20:
            parts.append(f'估值处历史{pe_pct:.0f}%低位')
        ng = _safe_float(financial.get('net_profit_growth'))
        if ng is not None and ng < 0:
            parts.append(f'净利润同比下滑{abs(ng):.0f}%')
        if not parts:
            return '待人工核实具体利空（禁止笼统归因市场情绪）'
        return '；'.join(parts) + '（系统初判，待人工核实）'

    def _infer_pessimism(self, row, pe, pe_pct) -> str:
        """推断市场悲观逻辑"""
        if pe and pe < 10:
            return f'PE仅{pe:.1f}x，市场隐含利润大幅下滑预期（系统初判）'
        if pe_pct and pe_pct <= 15:
            return '估值处历史极低分位，市场定价隐含深度悲观（系统初判）'
        return '待人工调研市场核心悲观假设'

    def _infer_damage(self, scores, risk, financial) -> str:
        """初判基本面是否破坏"""
        fq = scores.get('financial_quality')
        if risk.get('overall_risk_level') == '极高':
            return '是(永久性)'
        if fq is not None and fq <= 3:
            return '待验证'
        return '否(暂时性)'

    def _build_falsification(self, row, financial, valuation) -> str:
        """生成证伪条件（3-5条，含阈值）"""
        conds = []
        roe = _safe_float(financial.get('roe'))
        if roe:
            conds.append(f'ROE连续2年跌破{max(5, roe*0.5):.0f}%')
        else:
            conds.append('ROE连续2年跌破8%')
        conds.append('经营现金流/净利润连续2年<50%')
        conds.append('毛利率较3年均值下降超20%（相对值）')
        conds.append('营收连续2年负增长')
        conds.append('核心产品市占率连续下滑（人工跟踪）')
        return '；'.join(conds[:5])

    def _build_tracking(self, financial) -> str:
        """生成关键跟踪指标"""
        return ('季度营收/净利同比；毛利率；经营现金流；'
                'ROE(TTM)；行业景气与市占率数据（人工）')
