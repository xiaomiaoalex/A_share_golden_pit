"""市场悲观假设识别器。

从PE、PB、价格动量三个维度识别市场对股票的悲观定价，
量化悲观强度并提取核心悲观主题。
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class PessimisticHypothesis:
    """市场悲观假设识别器。

    通过PE、PB和价格动量三个维度评估市场对股票的悲观程度，
    识别核心悲观主题并生成市场叙事。
    """

    def __init__(self, fetcher, settings=None):
        """初始化悲观假设识别器。

        Args:
            fetcher: 数据获取器实例
            settings: 可选配置对象
        """
        self.fetcher = fetcher
        self.settings = settings

    def identify_pessimism(self, symbol: str, basic_info: dict = None) -> dict:
        """识别市场核心悲观假设。

        从PE估值、PB估值和价格动量三个维度综合评估市场悲观程度，
        识别核心悲观主题。

        Args:
            symbol: 股票代码
            basic_info: 股票基本信息字典，需包含 pe_dynamic、pb、
                       change_60d 字段

        Returns:
            dict: 包含以下字段的悲观识别结果：
                - pessimism_intensity: 悲观强度（0-1，越高越悲观）
                - core_pessimism_themes: 核心悲观主题列表
                - fear_indicators: 恐惧指标字典
                - market_narrative: 市场叙事描述
        """
        try:
            pe = float(basic_info.get('pe_dynamic', 0)) if basic_info else 0
            pb = float(basic_info.get('pb', 0)) if basic_info else 0
            change_60d = float(basic_info.get('change_60d', 0)) if basic_info else 0

            intensity = 0.0
            themes = []
            fear_indicators = {}

            # PE维度评估
            if pe <= 0:
                intensity += 0.3
                themes.append('市场定价亏损预期')
                fear_indicators['pe'] = '亏损'
            elif pe <= 10:
                intensity += 0.25
                themes.append('市场定价利润大幅下滑')
                fear_indicators['pe'] = f'{pe:.1f}（极度低位）'
            elif pe <= 15:
                intensity += 0.15
                themes.append('市场定价利润温和下滑')
                fear_indicators['pe'] = f'{pe:.1f}（偏低）'
            else:
                fear_indicators['pe'] = f'{pe:.1f}（正常）'

            # PB维度评估
            if pb <= 0:
                intensity += 0.2
                themes.append('资不抵债风险')
                fear_indicators['pb'] = '负资产'
            elif pb <= 1.0:
                intensity += 0.2
                themes.append('市场定价资产清算价值')
                fear_indicators['pb'] = f'{pb:.2f}（破净）'
            elif pb <= 1.5:
                intensity += 0.1
                themes.append('市场质疑资产质量')
                fear_indicators['pb'] = f'{pb:.2f}（偏低）'
            else:
                fear_indicators['pb'] = f'{pb:.2f}（正常）'

            # 价格动量维度评估
            if change_60d <= -40:
                intensity += 0.25
                themes.append('恐慌性抛售')
                fear_indicators['momentum'] = f'{change_60d:.1f}%（恐慌）'
            elif change_60d <= -20:
                intensity += 0.15
                themes.append('持续资金流出')
                fear_indicators['momentum'] = f'{change_60d:.1f}%（悲观）'
            else:
                fear_indicators['momentum'] = f'{change_60d:.1f}%'

            intensity = min(1.0, intensity)

            if intensity >= 0.7:
                narrative = '市场极度悲观，定价了多重利空叠加的极端情景'
            elif intensity >= 0.4:
                narrative = '市场明显悲观，定价了盈利下滑和资产质量恶化的情景'
            elif intensity >= 0.2:
                narrative = '市场偏谨慎，存在一定的悲观定价'
            else:
                narrative = '市场定价相对中性'

            return {
                'pessimism_intensity': round(intensity, 2),
                'core_pessimism_themes': themes if themes else ['无明显悲观主题'],
                'fear_indicators': fear_indicators,
                'market_narrative': narrative,
            }
        except Exception as e:
            logger.error(f"悲观假设识别失败 {symbol}: {e}")
            return {
                'pessimism_intensity': 0,
                'core_pessimism_themes': ['无法识别'],
                'fear_indicators': {},
                'market_narrative': '数据不足',
            }
