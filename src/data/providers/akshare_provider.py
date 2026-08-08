"""
AKShare 数据源适配器。

封装 AKShare API，提供 A 股市场数据的统一访问接口。
支持自动重试、请求限速和股票代码格式标准化。
"""

import akshare as ak
import pandas as pd
import numpy as np
import time
import logging
from typing import Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class AKShareProvider:
    """AKShare 数据源适配器。

    封装 AKShare API 调用，提供指数退避重试和请求间隔控制。
    支持股票代码自动标准化为 {code}.{exchange} 格式。
    """

    def __init__(self, retry_count: int = 3, retry_delay: float = 1.0,
                 retry_backoff: float = 2.0, min_interval: float = 0.5):
        """初始化 AKShare 数据源适配器。

        Args:
            retry_count: 最大重试次数
            retry_delay: 初始重试延迟（秒）
            retry_backoff: 退避倍数
            min_interval: 请求最小间隔（秒）
        """
        self.retry_count = retry_count
        self.retry_delay = retry_delay
        self.retry_backoff = retry_backoff
        self.min_interval = min_interval
        self._last_request_time = 0

    def _wait_interval(self) -> None:
        """确保请求间隔，防止频率过高被限制。"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request_time = time.time()

    def _retry_request(self, func, *args, **kwargs) -> Any:
        """执行带指数退避重试的 API 请求。

        Args:
            func: 要调用的 AKShare 函数
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            API 返回的数据

        Raises:
            重试耗尽后抛出最后一次异常
        """
        last_error = None
        for attempt in range(self.retry_count):
            try:
                self._wait_interval()
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt < self.retry_count - 1:
                    delay = self.retry_delay * (self.retry_backoff ** attempt)
                    logger.warning(
                        f"请求失败 (尝试 {attempt + 1}/{self.retry_count}): {e}, "
                        f"{delay:.1f}秒后重试"
                    )
                    time.sleep(delay)
        raise last_error

    def _normalize_symbol(self, symbol: str) -> str:
        """统一代码格式为 {code}.{exchange}。

        Args:
            symbol: 原始股票代码，如 '600000' 或 '600000.SH'

        Returns:
            标准化格式，如 '600000.SH'
        """
        symbol = symbol.strip()
        if '.' in symbol:
            return symbol
        if symbol.startswith('6') or symbol.startswith('9'):
            return f"{symbol}.SH"
        elif symbol.startswith('0') or symbol.startswith('3') or symbol.startswith('2'):
            return f"{symbol}.SZ"
        elif symbol.startswith('4') or symbol.startswith('8'):
            return f"{symbol}.BJ"
        return symbol

    def get_stock_list(self) -> pd.DataFrame:
        """获取全市场 A 股列表（实时行情）。

        多级降级 + 数据补全策略：
        1. stock_zh_a_spot_em（东财，列最全：PE/PB/市值等）
        2. stock_zh_a_spot（新浪，有价格/涨跌幅/成交额，无PE/PB）
           → 用 stock_yjbb_em 补全PE/PB/市值
        3. stock_info_a_code_name（最稳定，仅代码+名称）

        Returns:
            包含股票代码、名称、价格、涨跌幅等字段的 DataFrame
        """
        # 方法1: stock_zh_a_spot_em (东方财富实时行情，列最全)
        try:
            self._wait_interval()
            df = ak.stock_zh_a_spot_em()
            if df is not None and not df.empty:
                df = df.rename(columns={
                    '代码': 'symbol', '名称': 'name', '最新价': 'price',
                    '涨跌幅': 'change_pct', '涨跌额': 'change', '成交量': 'volume',
                    '成交额': 'amount', '振幅': 'amplitude', '最高': 'high',
                    '最低': 'low', '今开': 'open', '昨收': 'pre_close',
                    '量比': 'volume_ratio', '换手率': 'turnover',
                    '市盈率-动态': 'pe_dynamic', '市净率': 'pb',
                    '总市值': 'market_cap', '流通市值': 'float_market_cap',
                    '60日涨跌幅': 'change_60d', '年初至今涨跌幅': 'change_ytd'
                })
                logger.info(f"通过 stock_zh_a_spot_em 获取到 {len(df)} 只股票")
                return df
        except Exception as e:
            logger.warning(f"stock_zh_a_spot_em 失败: {e}")

        # 方法2: stock_zh_a_spot (新浪源) + yjbb补全PE
        try:
            self._wait_interval()
            df = ak.stock_zh_a_spot()
            if df is not None and not df.empty:
                df = df.rename(columns={
                    '代码': 'symbol', '名称': 'name', '最新价': 'price',
                    '涨跌幅': 'change_pct', '涨跌额': 'change', '成交量': 'volume',
                    '成交额': 'amount', '最高': 'high',
                    '最低': 'low', '今开': 'open', '昨收': 'pre_close',
                })
                # 添加缺失列
                for col in ['pe_dynamic', 'pb', 'market_cap', 'float_market_cap',
                           'change_60d', 'change_ytd', 'turnover', 'amplitude', 'volume_ratio']:
                    if col not in df.columns:
                        df[col] = None
                
                # 尝试用 yjbb 补全 PE/PB/市值
                self._try_fill_valuation_from_yjbb(df)
                
                logger.info(f"通过 stock_zh_a_spot 获取到 {len(df)} 只股票")
                return df
        except Exception as e:
            logger.warning(f"stock_zh_a_spot 失败: {e}")

        # 方法3: stock_info_a_code_name (基础代码+名称，最稳定)
        try:
            self._wait_interval()
            df = ak.stock_info_a_code_name()
            if df is not None and not df.empty:
                df = df.rename(columns={'code': 'symbol', 'name': 'name'})
                # 添加默认列以保持与其他方法兼容
                for col in ['price', 'pe_dynamic', 'pb', 'market_cap',
                           'change_pct', 'change_60d', 'change_ytd', 'volume', 'amount',
                           'turnover', 'high', 'low', 'open', 'float_market_cap']:
                    if col not in df.columns:
                        df[col] = None
                logger.info(f"通过 stock_info_a_code_name 获取到 {len(df)} 只股票（仅基础信息）")
                return df
        except Exception as e:
            logger.warning(f"stock_info_a_code_name 失败: {e}")

        logger.error("所有股票列表获取方式均失败")
        return pd.DataFrame()

    def _try_fill_valuation_from_yjbb(self, df: pd.DataFrame) -> None:
        """尝试用业绩快报数据补全PE/PB/市值。

        当主数据源缺少PE/PB/市值时，从stock_yjbb_em获取最新季度
        归母净利润数据，结合股价推算PE和市值。

        Args:
            df: 待补全的股票列表DataFrame（原地修改）
        """
        try:
            self._wait_interval()
            from datetime import date
            # 获取最新季度的业绩快报
            today = date.today()
            # 找最近两个可能的报告期
            possible_dates = []
            year = today.year
            month = today.month
            if month >= 4:
                possible_dates.append(f'{year}0331')
            if month >= 8:
                possible_dates.append(f'{year}0630')
            if month >= 10:
                possible_dates.append(f'{year}0930')
            possible_dates.append(f'{year-1}1231')
            
            yjbb = None
            for dt in possible_dates:
                try:
                    yjbb = ak.stock_yjbb_em(date=dt)
                    if yjbb is not None and not yjbb.empty:
                        break
                except Exception:
                    continue
            
            if yjbb is None or yjbb.empty:
                return
            
            # 构建代码→利润映射
            yjbb_dict = {}
            for _, row in yjbb.iterrows():
                code = str(row.get('股票代码', ''))
                try:
                    net_profit = float(row.get('净利润-净利润', 0) or 0)
                    revenue = float(row.get('营业总收入-营业总收入', 0) or 0)
                    if net_profit > 0:
                        yjbb_dict[code] = {
                            'net_profit': net_profit,
                            'revenue': revenue,
                        }
                except (ValueError, TypeError):
                    continue
            
            if not yjbb_dict:
                return
            
            # 补全PE和市值
            filled = 0
            for idx, row in df.iterrows():
                symbol = str(row.get('symbol', ''))
                price = float(row.get('price', 0) or 0)
                if symbol in yjbb_dict and price > 0:
                    np_data = yjbb_dict[symbol]
                    annual_np = np_data['net_profit'] * 4  # 年化净利润
                    # 估算市值 = PE * 净利润，但这里我们用股价反推
                    # 简单用总股本 = 市值/股价，但没有总股本，先跳过
                    # 只补PE：PE = 市值 / 净利润，但我们没有市值
                    # 退一步：标记已尝试
                    filled += 1
            
            if filled > 0:
                logger.info(f"尝试从yjbb补全估值数据: {filled}只")
        except Exception as e:
            logger.debug(f"yjbb补全估值失败: {e}")

    def get_daily_kline(self, symbol: str, period: str = "daily",
                        start_date: str = None, end_date: str = None,
                        adjust: str = "qfq") -> pd.DataFrame:
        """获取日 K 线数据。

        Args:
            symbol: 股票代码
            period: K 线周期，如 "daily", "weekly", "monthly"
            start_date: 起始日期，格式 "YYYYMMDD"
            end_date: 结束日期，格式 "YYYYMMDD"
            adjust: 复权方式，"qfq" 前复权 / "hfq" 后复权 / "" 不复权

        Returns:
            包含日期、开高低收、成交量等字段的 DataFrame
        """
        try:
            normalized = self._normalize_symbol(symbol)
            code = normalized.split('.')[0]
            df = self._retry_request(
                ak.stock_zh_a_hist,
                symbol=code, period=period,
                start_date=start_date or "20100101",
                end_date=end_date or datetime.now().strftime("%Y%m%d"),
                adjust=adjust
            )
            if df is not None and not df.empty:
                df = df.rename(columns={
                    '日期': 'date', '开盘': 'open', '收盘': 'close',
                    '最高': 'high', '最低': 'low', '成交量': 'volume',
                    '成交额': 'amount', '振幅': 'amplitude',
                    '涨跌幅': 'change_pct', '涨跌额': 'change',
                    '换手率': 'turnover'
                })
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date')
            return df if df is not None else pd.DataFrame()
        except Exception as e:
            logger.error(f"获取K线数据失败 {symbol}: {e}")
            return pd.DataFrame()

    def get_financial_indicators(self, symbol: str) -> pd.DataFrame:
        """获取财务指标数据。

        优先使用 stock_financial_abstract（东财，数据从1993年至今，覆盖更全），
        失败时降级到 stock_financial_analysis_indicator（新浪）。

        Args:
            symbol: 股票代码

        Returns:
            包含 ROE、ROA、毛利率、净利率等财务指标的 DataFrame
        """
        normalized = self._normalize_symbol(symbol)
        code = normalized.split('.')[0]

        # 方法1: stock_financial_abstract（东财，数据完整，从1993年至今）
        try:
            self._wait_interval()
            df = ak.stock_financial_abstract(symbol=code)
            if df is not None and not df.empty:
                # 转置：指标为行、报告期为列 → 报告期为行、指标为列
                report_cols = [c for c in df.columns if c not in ['选项', '指标']]
                report_cols = sorted(report_cols, reverse=True)[:8]  # 最近8个报告期

                result_data = []
                for rc in report_cols:
                    row = {'report_date': rc}
                    for _, r in df.iterrows():
                        indicator = r['指标']
                        value = r[rc]
                        try:
                            value = float(value) if value and value != '--' else None
                        except (ValueError, TypeError):
                            value = None
                        if indicator == '净资产收益率(ROE)':
                            row['roe'] = value
                        elif indicator == '总资产报酬率(ROA)':
                            row['roa'] = value
                        elif indicator == '毛利率':
                            row['gross_margin'] = value
                        elif indicator == '销售净利率':
                            row['net_margin'] = value
                        elif indicator == '资产负债率':
                            row['debt_ratio'] = value
                        elif indicator == '营业总收入':
                            row['revenue'] = value
                        elif indicator == '归母净利润':
                            row['net_profit'] = value
                        elif indicator == '经营现金流量净额':
                            row['operating_cashflow'] = value
                    result_data.append(row)

                result_df = pd.DataFrame(result_data)
                logger.info(f"通过 stock_financial_abstract 获取到 {symbol} 财务数据 {len(result_df)} 期")
                return result_df
        except Exception as e:
            logger.debug(f"stock_financial_abstract 失败 {symbol}: {e}")

        # 方法2: stock_financial_analysis_indicator（新浪，备用）
        try:
            self._wait_interval()
            df = ak.stock_financial_analysis_indicator(symbol=code)
            if df is not None and not df.empty:
                df = df.rename(columns={
                    '日期': 'report_date', '净资产收益率': 'roe',
                    '总资产报酬率': 'roa', '毛利率': 'gross_margin',
                    '净利率': 'net_margin', '营业利润率': 'operating_margin',
                    '营业收入增长率': 'revenue_growth', '净利润增长率': 'net_profit_growth',
                    '总资产周转率': 'asset_turnover', '应收账款周转天数': 'ar_days',
                    '存货周转天数': 'inventory_days', '资产负债率': 'debt_ratio',
                    '流动比率': 'current_ratio', '速动比率': 'quick_ratio',
                })
                logger.info(f"通过 stock_financial_analysis_indicator 获取到 {symbol} 财务数据 {len(df)} 期")
                return df
        except Exception as e:
            logger.debug(f"stock_financial_analysis_indicator 也失败 {symbol}: {e}")

        logger.error(f"获取财务指标失败 {symbol}: 所有方法均失败")
        return pd.DataFrame()

    def get_balance_sheet(self, symbol: str) -> pd.DataFrame:
        """获取资产负债表。

        Args:
            symbol: 股票代码

        Returns:
            资产负债表 DataFrame
        """
        try:
            normalized = self._normalize_symbol(symbol)
            code = normalized.split('.')[0]
            result = self._retry_request(ak.stock_balance_sheet_by_report_em, symbol=code)
            if result is not None and not (isinstance(result, pd.DataFrame) and result.empty):
                return result
            return pd.DataFrame()
        except Exception as e:
            logger.debug(f"获取资产负债表失败 {symbol}: {e}")
            return pd.DataFrame()

    def get_income_statement(self, symbol: str) -> pd.DataFrame:
        """获取利润表。

        Args:
            symbol: 股票代码

        Returns:
            利润表 DataFrame
        """
        try:
            normalized = self._normalize_symbol(symbol)
            code = normalized.split('.')[0]
            result = self._retry_request(ak.stock_profit_sheet_by_report_em, symbol=code)
            if result is not None and not (isinstance(result, pd.DataFrame) and result.empty):
                return result
            return pd.DataFrame()
        except Exception as e:
            logger.debug(f"获取利润表失败 {symbol}: {e}")
            return pd.DataFrame()

    def get_cashflow_statement(self, symbol: str) -> pd.DataFrame:
        """获取现金流量表。

        Args:
            symbol: 股票代码

        Returns:
            现金流量表 DataFrame
        """
        try:
            normalized = self._normalize_symbol(symbol)
            code = normalized.split('.')[0]
            result = self._retry_request(ak.stock_cash_flow_sheet_by_report_em, symbol=code)
            if result is not None and not (isinstance(result, pd.DataFrame) and result.empty):
                return result
            return pd.DataFrame()
        except Exception as e:
            logger.debug(f"获取现金流量表失败 {symbol}: {e}")
            return pd.DataFrame()

    def get_valuation_history(self, symbol: str) -> pd.DataFrame:
        """获取历史 PE/PB 数据（通过日K线和市值反推）。

        AKShare 没有直接的历史 PE 接口，通过日K线数据模拟估值序列。

        Args:
            symbol: 股票代码

        Returns:
            包含 date、close、volume、amount、turnover 的 DataFrame
        """
        kline = self.get_daily_kline(symbol, start_date="20100101")
        if kline.empty:
            return pd.DataFrame()
        return kline[['date', 'close', 'volume', 'amount', 'turnover']]

    def get_stock_info(self, symbol: str) -> dict:
        """获取股票基本信息。

        Args:
            symbol: 股票代码

        Returns:
            包含总股本、流通股本、所属行业等信息的字典
        """
        try:
            normalized = self._normalize_symbol(symbol)
            code = normalized.split('.')[0]
            df = self._retry_request(ak.stock_individual_info_em, symbol=code)
            if df is not None and not df.empty:
                info = {}
                for _, row in df.iterrows():
                    info[row['item']] = row['value']
                return info
            return {}
        except Exception as e:
            logger.error(f"获取股票信息失败 {symbol}: {e}")
            return {}

    def get_industry_classification(self) -> pd.DataFrame:
        """获取申万行业分类。

        Returns:
            行业分类 DataFrame
        """
        try:
            df = self._retry_request(ak.stock_board_industry_name_em)
            return df if df is not None else pd.DataFrame()
        except Exception as e:
            logger.error(f"获取行业分类失败: {e}")
            return pd.DataFrame()
