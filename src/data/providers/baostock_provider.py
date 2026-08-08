"""
baostock 数据源适配器（备用数据源）。

当 AKShare 数据不可用时，通过 baostock 获取基本面数据。
主要提供分红、成长能力、盈利能力、营运能力和偿债能力等数据。
"""

import baostock as bs
import pandas as pd
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class BaostockProvider:
    """baostock 数据源适配器。

    作为备用数据源，主要提供基本面数据（分红、成长、盈利、营运、偿债等）。
    使用前需要先调用 login() 登录。
    """

    def __init__(self):
        """初始化 baostock 适配器。"""
        self._logged_in = False

    def login(self) -> bool:
        """登录 baostock。

        Returns:
            是否登录成功
        """
        if not self._logged_in:
            lg = bs.login()
            if lg.error_code == '0':
                self._logged_in = True
                logger.info("baostock登录成功")
            else:
                logger.error(f"baostock登录失败: {lg.error_msg}")
        return self._logged_in

    def logout(self) -> None:
        """登出 baostock，释放连接资源。"""
        if self._logged_in:
            bs.logout()
            self._logged_in = False

    def _normalize_symbol(self, symbol: str) -> str:
        """转换为 baostock 格式: sh.600000 或 sz.000001。

        Args:
            symbol: 原始股票代码，如 '600000', '600000.SH', 'sh.600000'

        Returns:
            baostock 格式代码
        """
        symbol = symbol.strip()
        if symbol.startswith('sh.') or symbol.startswith('sz.'):
            return symbol
        if '.' in symbol:
            code, exchange = symbol.split('.')
            prefix = 'sh' if exchange.upper() == 'SH' else 'sz'
            return f"{prefix}.{code}"
        if symbol.startswith('6') or symbol.startswith('9'):
            return f"sh.{symbol}"
        return f"sz.{symbol}"

    def get_dividend_data(self, symbol: str) -> pd.DataFrame:
        """获取分红数据。

        Args:
            symbol: 股票代码

        Returns:
            分红记录 DataFrame
        """
        if not self.login():
            return pd.DataFrame()
        try:
            bs_symbol = self._normalize_symbol(symbol)
            rs = bs.query_dividend_data(code=bs_symbol, year=None, yearType='report')
            if rs.error_code == '0':
                data = []
                while rs.next():
                    data.append(rs.get_row_data())
                return pd.DataFrame(data, columns=rs.fields)
        except Exception as e:
            logger.error(f"baostock分红数据获取失败 {symbol}: {e}")
        return pd.DataFrame()

    def get_growth_data(self, symbol: str, year: int = None,
                        quarter: int = None) -> pd.DataFrame:
        """获取成长能力数据。

        Args:
            symbol: 股票代码
            year: 年份，None 表示全部
            quarter: 季度（1-4），None 表示全部

        Returns:
            成长能力指标 DataFrame
        """
        if not self.login():
            return pd.DataFrame()
        try:
            bs_symbol = self._normalize_symbol(symbol)
            rs = bs.query_growth_data(code=bs_symbol, year=year, quarter=quarter)
            if rs.error_code == '0':
                data = []
                while rs.next():
                    data.append(rs.get_row_data())
                return pd.DataFrame(data, columns=rs.fields)
        except Exception as e:
            logger.error(f"baostock成长数据获取失败 {symbol}: {e}")
        return pd.DataFrame()

    def get_profit_data(self, symbol: str, year: int = None,
                        quarter: int = None) -> pd.DataFrame:
        """获取盈利能力数据。

        Args:
            symbol: 股票代码
            year: 年份，None 表示全部
            quarter: 季度（1-4），None 表示全部

        Returns:
            盈利能力指标 DataFrame
        """
        if not self.login():
            return pd.DataFrame()
        try:
            bs_symbol = self._normalize_symbol(symbol)
            rs = bs.query_profit_data(code=bs_symbol, year=year, quarter=quarter)
            if rs.error_code == '0':
                data = []
                while rs.next():
                    data.append(rs.get_row_data())
                return pd.DataFrame(data, columns=rs.fields)
        except Exception as e:
            logger.error(f"baostock利润数据获取失败 {symbol}: {e}")
        return pd.DataFrame()

    def get_operation_data(self, symbol: str, year: int = None,
                           quarter: int = None) -> pd.DataFrame:
        """获取营运能力数据。

        Args:
            symbol: 股票代码
            year: 年份，None 表示全部
            quarter: 季度（1-4），None 表示全部

        Returns:
            营运能力指标 DataFrame
        """
        if not self.login():
            return pd.DataFrame()
        try:
            bs_symbol = self._normalize_symbol(symbol)
            rs = bs.query_operation_data(code=bs_symbol, year=year, quarter=quarter)
            if rs.error_code == '0':
                data = []
                while rs.next():
                    data.append(rs.get_row_data())
                return pd.DataFrame(data, columns=rs.fields)
        except Exception as e:
            logger.error(f"baostock营运数据获取失败 {symbol}: {e}")
        return pd.DataFrame()

    def get_balance_data(self, symbol: str, year: int = None,
                         quarter: int = None) -> pd.DataFrame:
        """获取偿债能力数据。

        Args:
            symbol: 股票代码
            year: 年份，None 表示全部
            quarter: 季度（1-4），None 表示全部

        Returns:
            偿债能力指标 DataFrame
        """
        if not self.login():
            return pd.DataFrame()
        try:
            bs_symbol = self._normalize_symbol(symbol)
            rs = bs.query_balance_data(code=bs_symbol, year=year, quarter=quarter)
            if rs.error_code == '0':
                data = []
                while rs.next():
                    data.append(rs.get_row_data())
                return pd.DataFrame(data, columns=rs.fields)
        except Exception as e:
            logger.error(f"baostock偿债数据获取失败 {symbol}: {e}")
        return pd.DataFrame()
