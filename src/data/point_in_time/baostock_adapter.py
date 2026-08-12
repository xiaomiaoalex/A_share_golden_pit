"""BaoStock point-in-time adapter for fields with verifiable Tier1 semantics.

BaoStock is deliberately not used for Tier1 financial statements because its
profitability API does not expose the exact cumulative operating revenue and
parent-attributable net profit pair required by the business contract.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import pandas as pd

from src.data.point_in_time.models import (
    CorporateAction,
    DividendEvent,
    MarketSnapshot,
    RiskWarningStatus,
)

from .contracts import DataEnvelope, DividendBundle, FetchStatus, UniverseItem
from .provider_utils import hash_json, number, parse_date, result_to_frame, schema_hash


class BaoStockPointInTimeProvider:
    provider_name = "BaoStock"

    def __init__(
        self,
        client=None,
        *,
        today: Optional[date] = None,
        current_window_days: int = 7,
    ):
        if client is None:
            import baostock as client
        self.client = client
        self.today = today or date.today()
        self.current_window_days = current_window_days
        self._logged_in = False
        self._history_cache = {}

    @staticmethod
    def exchange_for(symbol: str) -> str:
        code = str(symbol).zfill(6)
        if code.startswith(("4", "8", "92")):
            return "BJ"
        return "SH" if code.startswith("6") else "SZ"

    @classmethod
    def bs_code(cls, symbol: str) -> Optional[str]:
        exchange = cls.exchange_for(symbol)
        if exchange == "BJ":
            return None
        return f"{exchange.lower()}.{str(symbol).zfill(6)}"

    def _ensure_login(self) -> None:
        if self._logged_in:
            return
        result = self.client.login()
        if str(result.error_code) != "0":
            raise RuntimeError(
                f"BaoStock login: {result.error_code} {result.error_msg}"
            )
        self._logged_in = True

    def close(self) -> None:
        if self._logged_in:
            self.client.logout()
            self._logged_in = False

    def _error(self, endpoint: str, request: dict, exc: Exception) -> DataEnvelope:
        return DataEnvelope(
            FetchStatus.ERROR,
            None,
            self.provider_name,
            endpoint,
            request,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )

    def _query(self, endpoint: str, request: dict, fn, *args, **kwargs):
        self._ensure_login()
        result = fn(*args, **kwargs)
        if str(result.error_code) != "0":
            raise RuntimeError(
                f"{endpoint}: {result.error_code} {getattr(result, 'error_msg', '')}"
            )
        return result_to_frame(result)

    @staticmethod
    def _is_a_share_code(code: str) -> bool:
        if code.startswith("sh."):
            return code[3:].startswith(("600", "601", "603", "605", "688", "689"))
        if code.startswith("sz."):
            return code[3:].startswith(("000", "001", "002", "003", "300", "301"))
        return False

    def _latest_trade_date(self, as_of_date: date) -> date:
        start = as_of_date - timedelta(days=15)
        frame = self._query(
            "query_trade_dates",
            {"start_date": start.isoformat(), "end_date": as_of_date.isoformat()},
            self.client.query_trade_dates,
            start_date=start.isoformat(),
            end_date=as_of_date.isoformat(),
        )
        if frame.empty or not {"calendar_date", "is_trading_day"}.issubset(
            frame.columns
        ):
            raise RuntimeError("BaoStock交易日历为空或Schema不完整")
        frame["_date"] = frame["calendar_date"].map(parse_date)
        eligible = frame[
            (frame["is_trading_day"].astype(str) == "1") & frame["_date"].notna()
        ]
        if eligible.empty:
            raise RuntimeError("as_of_date之前15日内无BaoStock交易日")
        return max(eligible["_date"])

    def get_universe(self, as_of_date: date) -> DataEnvelope[list[UniverseItem]]:
        endpoint = "query_all_stock"
        request = {"as_of_date": as_of_date.isoformat()}
        try:
            trade_date = self._latest_trade_date(as_of_date)
            frame = self._query(
                endpoint,
                {**request, "trade_date": trade_date.isoformat()},
                self.client.query_all_stock,
                day=trade_date.isoformat(),
            )
        except Exception as exc:
            return self._error(endpoint, request, exc)
        required = {"code", "tradeStatus", "code_name"}
        missing = required.difference(frame.columns)
        if missing:
            return DataEnvelope(
                FetchStatus.SCHEMA_ERROR,
                None,
                self.provider_name,
                endpoint,
                request,
                row_count=len(frame),
                schema_hash=schema_hash(frame),
                error_type="MissingColumns",
                error_message=f"缺少必要列: {sorted(missing)}",
            )
        items = []
        for _, row in frame.iterrows():
            code = str(row.get("code", "")).lower()
            if not self._is_a_share_code(code):
                continue
            symbol = code.split(".", 1)[1]
            items.append(
                UniverseItem(
                    symbol=symbol,
                    name=str(row.get("code_name", symbol)),
                    exchange="SH" if code.startswith("sh.") else "SZ",
                )
            )
        payload = {
            "trade_date": trade_date.isoformat(),
            "rows_received": len(frame),
            "rows_selected": len(items),
            "metric_contract": "query_all_stock on latest trading day <= as_of",
        }
        return DataEnvelope(
            FetchStatus.SUCCESS,
            items,
            self.provider_name,
            endpoint,
            request,
            available_at=trade_date,
            row_count=len(items),
            schema_hash=schema_hash(frame),
            payload_hash=hash_json(payload),
            raw_payload=payload,
            quality_warnings=["BaoStock股票池不覆盖北交所；仅作为沪深补充源"],
        )

    def _history_frame(
        self, symbol: str, as_of_date: date
    ) -> tuple[pd.DataFrame, dict]:
        cache_key = (str(symbol).zfill(6), as_of_date)
        if cache_key in self._history_cache:
            frame, request = self._history_cache[cache_key]
            return frame.copy(), dict(request)
        code = self.bs_code(symbol)
        if code is None:
            return pd.DataFrame(), {"symbol": symbol, "unsupported_exchange": "BJ"}
        start = as_of_date - timedelta(days=31)
        request = {
            "code": code,
            "start_date": start.isoformat(),
            "end_date": as_of_date.isoformat(),
            "frequency": "d",
            "adjustflag": "3",
        }
        frame = self._query(
            "query_history_k_data_plus",
            request,
            self.client.query_history_k_data_plus,
            code,
            "date,code,close,peTTM,isST,tradestatus",
            start_date=start.isoformat(),
            end_date=as_of_date.isoformat(),
            frequency="d",
            adjustflag="3",
        )
        self._history_cache[cache_key] = (frame.copy(), dict(request))
        return frame, request

    def get_market_snapshot(
        self, symbol: str, as_of_date: date
    ) -> DataEnvelope[MarketSnapshot]:
        endpoint = "query_history_k_data_plus"
        try:
            frame, request = self._history_frame(symbol, as_of_date)
        except Exception as exc:
            return self._error(
                endpoint, {"symbol": symbol, "as_of_date": as_of_date.isoformat()}, exc
            )
        if frame.empty:
            return DataEnvelope(
                FetchStatus.EMPTY,
                None,
                self.provider_name,
                endpoint,
                request,
                row_count=0,
                quality_warnings=["BaoStock不覆盖北交所或窗口内无行情"],
            )
        required = {"date", "close", "peTTM", "isST", "tradestatus"}
        missing = required.difference(frame.columns)
        if missing:
            return DataEnvelope(
                FetchStatus.SCHEMA_ERROR,
                None,
                self.provider_name,
                endpoint,
                request,
                row_count=len(frame),
                schema_hash=schema_hash(frame),
                error_type="MissingColumns",
                error_message=f"缺少必要列: {sorted(missing)}",
            )
        working = frame.copy()
        working["_date"] = working["date"].map(parse_date)
        working = working[
            working["_date"].notna() & (working["_date"] <= as_of_date)
        ].sort_values("_date")
        if working.empty:
            return DataEnvelope(
                FetchStatus.EMPTY,
                None,
                self.provider_name,
                endpoint,
                request,
                row_count=0,
            )
        row = working.iloc[-1]
        snapshot = MarketSnapshot(
            symbol=str(symbol).zfill(6),
            price_date=row["_date"],
            close_price=number(row.get("close")),
            market_cap=None,
            total_shares=None,
            supplier_pe_ttm=number(row.get("peTTM")),
            source=f"{self.provider_name}:{endpoint}",
        )
        raw = {
            str(key): value
            for key, value in row.drop(labels=["_date"]).to_dict().items()
        }
        payload = {
            "raw": raw,
            "metric_contract": "unadjusted close (adjustflag=3), BaoStock rolling peTTM",
            "unit_contract": {"close": "CNY/share", "peTTM": "multiple"},
            "capability_limit": "market cap and total shares unavailable",
        }
        return DataEnvelope(
            FetchStatus.SUCCESS,
            snapshot,
            self.provider_name,
            endpoint,
            request,
            available_at=snapshot.price_date,
            row_count=len(frame),
            schema_hash=schema_hash(frame),
            payload_hash=hash_json(payload),
            raw_payload=payload,
            quality_warnings=[
                "BaoStock不提供点时总市值/总股本；历史自计算PE仍需其他来源"
            ],
        )

    def get_financial_facts(self, symbol: str, as_of_date: date) -> DataEnvelope:
        request = {"symbol": str(symbol).zfill(6), "as_of_date": as_of_date.isoformat()}
        return DataEnvelope(
            FetchStatus.EMPTY,
            None,
            self.provider_name,
            "unsupported_exact_financial_contract",
            request,
            row_count=0,
            quality_warnings=[
                "BaoStock财务接口缺少本项目要求的累计营业收入+归母净利润精确组合，禁止近似补数"
            ],
        )

    def get_dividend_bundle(
        self, symbol: str, as_of_date: date
    ) -> DataEnvelope[DividendBundle]:
        endpoint = "query_dividend_data"
        code = self.bs_code(symbol)
        request = {
            "code": code,
            "as_of_date": as_of_date.isoformat(),
            "yearType": "operate",
        }
        if code is None:
            return DataEnvelope(
                FetchStatus.EMPTY,
                None,
                self.provider_name,
                endpoint,
                request,
                quality_warnings=["BaoStock分红接口不覆盖北交所"],
            )
        frames = []
        try:
            for year in sorted({as_of_date.year - 1, as_of_date.year}):
                frame = self._query(
                    endpoint,
                    {**request, "year": year},
                    self.client.query_dividend_data,
                    code,
                    year=str(year),
                    yearType="operate",
                )
                if not frame.empty:
                    frames.append(frame)
        except Exception as exc:
            return self._error(endpoint, request, exc)
        if not frames:
            return DataEnvelope(
                FetchStatus.EMPTY,
                DividendBundle(events=(), actions=()),
                self.provider_name,
                endpoint,
                request,
                row_count=0,
                quality_warnings=["BaoStock无分红送转记录，按TTM现金分红0处理"],
            )
        frame = pd.concat(frames, ignore_index=True)
        required = {
            "dividPlanAnnounceDate",
            "dividPlanDate",
            "dividOperateDate",
            "dividCashPsBeforeTax",
            "dividStocksPs",
            "dividReserveToStockPs",
        }
        missing = required.difference(frame.columns)
        if missing:
            return DataEnvelope(
                FetchStatus.SCHEMA_ERROR,
                None,
                self.provider_name,
                endpoint,
                request,
                row_count=len(frame),
                schema_hash=schema_hash(frame),
                error_type="MissingColumns",
                error_message=f"缺少必要列: {sorted(missing)}",
            )
        events = []
        actions = []
        seen = set()
        for _, row in frame.iterrows():
            ex_date = parse_date(row.get("dividOperateDate"))
            availability_dates = [
                value
                for value in (
                    parse_date(row.get("dividPlanAnnounceDate")),
                    parse_date(row.get("dividPlanDate")),
                )
                if value is not None
            ]
            announced = max(availability_dates) if availability_dates else None
            if (
                ex_date is None
                or ex_date > as_of_date
                or announced is None
                or announced > as_of_date
            ):
                continue
            cash = number(row.get("dividCashPsBeforeTax"))
            stock = (number(row.get("dividStocksPs")) or 0) + (
                number(row.get("dividReserveToStockPs")) or 0
            )
            key = (ex_date, cash, stock)
            if key in seen:
                continue
            seen.add(key)
            raw = {
                **{str(k): v for k, v in row.to_dict().items()},
                "metric_contract": "dividCashPsBeforeTax + dividOperateDate",
                "unit_contract": "CNY/share and shares/share",
            }
            if cash is not None and cash >= 0:
                events.append(
                    DividendEvent(
                        symbol=str(symbol).zfill(6),
                        ex_date=ex_date,
                        raw_cash_per_share_pre_tax=cash,
                        status="实施分配",
                        source=f"{self.provider_name}:{endpoint}",
                        provider_adjusted=False,
                        announcement_date=announced,
                        raw=raw,
                    )
                )
            if stock > 0:
                actions.append(
                    CorporateAction(
                        symbol=str(symbol).zfill(6),
                        effective_date=ex_date,
                        share_factor=1 + stock,
                        source=f"{self.provider_name}:{endpoint}",
                        provider_adjusted=False,
                        raw=raw,
                    )
                )
        bundle = DividendBundle(tuple(events), tuple(actions))
        payload = {
            "rows_received": len(frame),
            "event_count": len(events),
            "action_count": len(actions),
            "metric_contract": "pre-tax cash/share implemented on ex-right date",
        }
        return DataEnvelope(
            FetchStatus.SUCCESS,
            bundle,
            self.provider_name,
            endpoint,
            request,
            available_at=as_of_date,
            row_count=len(frame),
            schema_hash=schema_hash(frame),
            payload_hash=hash_json(payload),
            raw_payload=payload,
        )

    def get_risk_warning_status(
        self, symbol: str, stock_name: Optional[str], as_of_date: date
    ) -> DataEnvelope[RiskWarningStatus]:
        endpoint = "query_history_k_data_plus"
        try:
            frame, request = self._history_frame(symbol, as_of_date)
        except Exception as exc:
            return self._error(
                endpoint, {"symbol": symbol, "as_of_date": as_of_date.isoformat()}, exc
            )
        if frame.empty:
            return DataEnvelope(
                FetchStatus.EMPTY,
                None,
                self.provider_name,
                endpoint,
                request,
                row_count=0,
                quality_warnings=["BaoStock不覆盖北交所或窗口内无历史ST状态"],
            )
        required = {"date", "isST"}
        missing = required.difference(frame.columns)
        if missing:
            return DataEnvelope(
                FetchStatus.SCHEMA_ERROR,
                None,
                self.provider_name,
                endpoint,
                request,
                row_count=len(frame),
                schema_hash=schema_hash(frame),
                error_type="MissingColumns",
                error_message=f"缺少必要列: {sorted(missing)}",
            )
        working = frame.copy()
        working["_date"] = working["date"].map(parse_date)
        working = working[
            working["_date"].notna() & (working["_date"] <= as_of_date)
        ].sort_values("_date")
        if working.empty:
            return DataEnvelope(
                FetchStatus.EMPTY,
                None,
                self.provider_name,
                endpoint,
                request,
                row_count=0,
            )
        row = working.iloc[-1]
        raw_st = str(row.get("isST", "")).strip()
        if raw_st not in {"0", "1"}:
            return DataEnvelope(
                FetchStatus.SCHEMA_ERROR,
                None,
                self.provider_name,
                endpoint,
                request,
                row_count=len(frame),
                error_type="InvalidIsST",
                error_message=f"isST不是0/1: {raw_st}",
            )
        status = RiskWarningStatus(
            symbol=str(symbol).zfill(6),
            as_of_date=as_of_date,
            is_risk_warning=raw_st == "1",
            security_name=stock_name,
            source=f"{self.provider_name}:{endpoint}",
            effective_date=row["_date"],
            reason="BaoStock daily isST",
        )
        payload = {
            "date": row["_date"].isoformat(),
            "isST": raw_st,
            "metric_contract": "daily isST at latest trading day <= as_of",
        }
        return DataEnvelope(
            FetchStatus.SUCCESS,
            status,
            self.provider_name,
            endpoint,
            request,
            available_at=row["_date"],
            row_count=len(frame),
            schema_hash=schema_hash(frame),
            payload_hash=hash_json(payload),
            raw_payload=payload,
        )
