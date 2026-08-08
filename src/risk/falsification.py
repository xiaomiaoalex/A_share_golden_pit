"""证伪条件生成器"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class FalsificationGenerator:
    """证伪条件生成器：生成可被数据证伪的投资逻辑条件

    核心思想：在买入前，先明确"什么情况下我的投资逻辑是错的"。
    通过预设可验证的证伪条件，建立投资纪律，避免持有逻辑失效的仓位。
    """

    def __init__(self, risk_checker=None, redflag_detector=None):
        """初始化证伪条件生成器

        Args:
            risk_checker: AShareRiskChecker 实例（可选），用于获取风险检测结果
            redflag_detector: FinancialRedFlagDetector 实例（可选），用于获取红旗检测结果
        """
        self.risk_checker = risk_checker
        self.redflag_detector = redflag_detector

    def generate_conditions(self, symbol: str, basic_info: dict = None) -> List[dict]:
        """生成证伪条件清单

        为指定股票生成一组可被数据验证的证伪条件。
        如果这些条件被触发，意味着原始投资逻辑可能不再成立。

        Args:
            symbol: 股票代码
            basic_info: 基础信息字典，包含 pe_dynamic, pb 等字段

        Returns:
            [
                {
                    'condition': str,        # 证伪条件描述
                    'type': str,             # 类型：基本面/估值/市场/风险/财务质量/竞争优势/行业风险/治理风险
                    'severity': str,         # 严重性：致命/重要/一般
                    'monitor_method': str,    # 监控方法
                    'current_status': str,   # 当前状态
                },
                ...
            ]
        """
        pe = float(basic_info.get('pe_dynamic', 0) or 0) if basic_info else 0
        pb = float(basic_info.get('pb', 0) or 0) if basic_info else 0

        conditions = [
            {
                'condition': f'ROE跌破8%（当前隐含ROE≈{pb / pe * 100 if pe > 0 else 0:.1f}%）',
                'type': '基本面',
                'severity': '致命',
                'monitor_method': '每季度跟踪财报ROE',
                'current_status': '待确认' if pe > 0 else '数据不足',
            },
            {
                'condition': '连续两个季度营收同比下滑超过15%',
                'type': '基本面',
                'severity': '致命',
                'monitor_method': '每季度跟踪营收数据',
                'current_status': '待确认',
            },
            {
                'condition': '毛利率连续3个季度下滑超过5个百分点',
                'type': '基本面',
                'severity': '重要',
                'monitor_method': '每季度跟踪毛利率',
                'current_status': '待确认',
            },
            {
                'condition': '经营现金流/净利润连续低于0.5',
                'type': '财务质量',
                'severity': '重要',
                'monitor_method': '每季度跟踪现金流表',
                'current_status': '待确认',
            },
            {
                'condition': '核心客户流失或市场份额明显下降',
                'type': '竞争优势',
                'severity': '致命',
                'monitor_method': '跟踪行业报告和公司公告',
                'current_status': '待确认',
            },
            {
                'condition': '大股东大比例减持或质押比例超过60%',
                'type': '治理风险',
                'severity': '重要',
                'monitor_method': '跟踪股东变动公告',
                'current_status': '待确认',
            },
            {
                'condition': '行业出现颠覆性技术替代',
                'type': '行业风险',
                'severity': '致命',
                'monitor_method': '持续跟踪行业技术动态',
                'current_status': '待确认',
            },
        ]

        # 根据PE添加额外条件
        if pe > 0:
            conditions.append({
                'condition': f'股价跌破净资产（当前PB={pb:.2f}）',
                'type': '估值',
                'severity': '重要',
                'monitor_method': '每日跟踪股价',
                'current_status': '已触发' if pb < 1.0 else '未触发',
            })

        return conditions

    def check_triggered_conditions(self, symbol: str, basic_info: dict = None) -> dict:
        """检查当前是否有证伪条件已触发

        基于当前行情数据快速判断是否已有证伪条件被触发。
        如果PE为负、PB极端低位或PE畸高，说明投资逻辑可能需要重新评估。

        Args:
            symbol: 股票代码
            basic_info: 基础信息字典，包含 pe_dynamic, pb 等字段

        Returns:
            {
                'triggered': bool,           # 是否有触发
                'triggered_conditions': list, # 已触发的条件
                'assessment': str,           # 评估
            }
        """
        pe = float(basic_info.get('pe_dynamic', 0) or 0) if basic_info else 0
        pb = float(basic_info.get('pb', 0) or 0) if basic_info else 0

        triggered = []

        if pe <= 0:
            triggered.append('当前亏损，投资逻辑需重新评估')

        if 0 < pb < 0.5:
            triggered.append('PB极端低位，需排查资产质量')

        if pe > 100:
            triggered.append('PE畸高，安全边际严重不足')

        is_triggered = len(triggered) > 0

        if is_triggered:
            assessment = f'发现{len(triggered)}个已触发的证伪条件，建议暂不参与或降低仓位'
        else:
            assessment = '当前未触发致命证伪条件'

        return {
            'triggered': is_triggered,
            'triggered_conditions': triggered if triggered else ['无'],
            'assessment': assessment,
        }
