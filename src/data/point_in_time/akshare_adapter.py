"""AKShare point-in-time adapter for Tier1 v2.

No provider exception is converted into an empty success.  Every response is
classified as success, empty, transport/error, or schema error so downstream
screening can remain fail-closed.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime
from typing import Any, Optional

import pandas as pd

from src.screening.tier1_v2.contracts import (
    CorporateAction,
    DividendEvent,
    FinancialReportFact,
    MarketSnapshot,
    RiskWarningStatus,
)

from .contracts import DataEnvelope, DividendBundle, FetchStatus, UniverseItem


def _hash_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _schema_hash(df: pd.DataFrame) -> str:
    schema = [(str(column), str(dtype)) for column, dtype in zip(df.columns, df.dtypes)]
    return _hash_json(schema)


def _number(value: object) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.replace(",", "").strip()
        if not value or value in {"-", "--"}:
            return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _date(value: object) -> Optional[date]:
    if value is None or (
        not isinstance(value, (str, date, datetime)) and pd.isna(value)
    ):
        return None
    try:
        parsed = pd.to_datetime(value, errors="coerce")
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed.date()


def _datetime(value: object) -> Optional[datetime]:
    parsed = _date(value)
    if parsed is None:
        return None
    return datetime.combine(parsed, datetime.min.time())


class AKSharePointInTimeProvider:
    """Small, auditable AKShare adapter used only by Tier1 v2."""

    provider_name = "AKShare"

    def __init__(
        self,
        ak_module=None,
        today: Optional[date] = None,
        current_window_days: int = 7,
    ):
        if ak_module is None:
            import akshare as ak_module
        self.ak = ak_module
        self.today = today or date.today()
        self.current_window_days = current_window_days
        self._current_st_symbols: Optional[set[str]] = None
        self._current_st_error: Optional[str] = None
        self._sz_name_changes: Optional[pd.DataFrame] = None
        self._sz_name_changes_error: Optional[str] = None

    @staticmethod
    def exchange_for(symbol: str) -> str:
        code = str(symbol).zfill(6)
        if code.startswith(("4", "8", "92")):
            return "BJ"
        if code.startswith("6"):
            return "SH"
        return "SZ"

    @classmethod
    def market_symbol(cls, symbol: str) -> str:
        code = str(symbol).zfill(6)
        return f"{cls.exchange_for(code)}{code}"

    def _error(self, endpoint: str, request: dict, exc: Exception) -> DataEnvelope:
        return DataEnvelope(
            status=FetchStatus.ERROR,
            data=None,
            provider=self.provider_name,
            endpoint=endpoint,
            request=request,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )

    def _schema_error(
        self, endpoint: str, request: dict, df: pd.DataFrame, missing: set[str]
    ) -> DataEnvelope:
        return DataEnvelope(
            status=FetchStatus.SCHEMA_ERROR,
            data=None,
            provider=self.provider_name,
            endpoint=endpoint,
            request=request,
            row_count=len(df),
            schema_hash=_schema_hash(df),
            error_type="MissingColumns",
            error_message=f"缺少必要列: {sorted(missing)}",
            raw_payload={"columns": list(map(str, df.columns))},
        )

    def get_universe(self, as_of_date: date) -> DataEnvelope[list[UniverseItem]]:
        endpoint = "stock_info_a_code_name"
        request = {"as_of_date": as_of_date.isoformat()}
        try:
            df = self.ak.stock_info_a_code_name()
        except Exception as exc:
            return self._error(endpoint, request, exc)
        if df is None or df.empty:
            return DataEnvelope(
                FetchStatus.EMPTY,
                None,
                self.provider_name,
                endpoint,
                request,
                row_count=0,
            )
        code_col = (
            "code" if "code" in df.columns else "代码" if "代码" in df.columns else None
        )
        name_col = (
            "name" if "name" in df.columns else "名称" if "名称" in df.columns else None
        )
        if not code_col or not name_col:
            return self._schema_error(endpoint, request, df, {"code", "name"})
        items = [
            UniverseItem(
                symbol=str(row[code_col]).strip().zfill(6),
                name=str(row[name_col]).strip(),
                exchange=self.exchange_for(str(row[code_col]).strip()),
            )
            for _, row in df.iterrows()
            if str(row[code_col]).strip()
        ]
        warnings: list[str] = []
        if as_of_date < self.today:
            warnings.append(
                "当前代码表用于历史as-of可能存在退市样本缺失；建议传入点时股票池"
            )
        payload = {"columns": list(map(str, df.columns)), "row_count": len(df)}
        return DataEnvelope(
            FetchStatus.SUCCESS,
            items,
            self.provider_name,
            endpoint,
            request,
            row_count=len(items),
            schema_hash=_schema_hash(df),
            payload_hash=_hash_json(payload),
            quality_warnings=warnings,
            raw_payload=payload,
        )

    def get_market_snapshot(
        self, symbol: str, as_of_date: date
    ) -> DataEnvelope[MarketSnapshot]:
        endpoint = "stock_value_em"
        request = {"symbol": symbol, "as_of_date": as_of_date.isoformat()}
        try:
            df = self.ak.stock_value_em(symbol=str(symbol).zfill(6))
        except Exception as exc:
            return self._error(endpoint, request, exc)
        if df is None or df.empty:
            return DataEnvelope(
                FetchStatus.EMPTY,
                None,
                self.provider_name,
                endpoint,
                request,
                row_count=0,
            )
        required = {"数据日期", "当日收盘价", "总市值", "总股本", "PE(TTM)"}
        missing = required.difference(df.columns)
        if missing:
            return self._schema_error(endpoint, request, df, missing)
        working = df.copy()
        working["_date"] = pd.to_datetime(working["数据日期"], errors="coerce")
        working = working[working["_date"].dt.date <= as_of_date]
        working = working.dropna(subset=["_date"]).sort_values("_date")
        if working.empty:
            return DataEnvelope(
                FetchStatus.EMPTY,
                None,
                self.provider_name,
                endpoint,
                request,
                row_count=0,
                schema_hash=_schema_hash(df),
                quality_warnings=["as_of_date之前无行情记录"],
            )
        row = working.iloc[-1]
        price_date = row["_date"].date()
        snapshot = MarketSnapshot(
            symbol=str(symbol).zfill(6),
            price_date=price_date,
            close_price=_number(row["当日收盘价"]),
            market_cap=_number(row["总市值"]),
            total_shares=_number(row["总股本"]),
            supplier_pe_ttm=_number(row["PE(TTM)"]),
            source=f"{self.provider_name}:{endpoint}",
        )
        raw = {
            str(key): value
            for key, value in row.drop(labels=["_date"]).to_dict().items()
        }
        return DataEnvelope(
            FetchStatus.SUCCESS,
            snapshot,
            self.provider_name,
            endpoint,
            request,
            available_at=price_date,
            row_count=len(df),
            schema_hash=_schema_hash(df),
            payload_hash=_hash_json(raw),
            raw_payload=raw,
        )

    def get_financial_facts(
        self, symbol: str, as_of_date: date
    ) -> DataEnvelope[list[FinancialReportFact]]:
        endpoint = "stock_profit_sheet_by_report_em"
        market_symbol = self.market_symbol(symbol)
        request = {"symbol": market_symbol, "as_of_date": as_of_date.isoformat()}
        try:
            df = self.ak.stock_profit_sheet_by_report_em(symbol=market_symbol)
        except Exception as exc:
            return self._error(endpoint, request, exc)
        if df is None or df.empty:
            return DataEnvelope(
                FetchStatus.EMPTY,
                None,
                self.provider_name,
                endpoint,
                request,
                row_count=0,
            )
        required = {"REPORT_DATE", "NOTICE_DATE", "OPERATE_INCOME", "PARENT_NETPROFIT"}
        missing = required.difference(df.columns)
        if missing:
            return self._schema_error(endpoint, request, df, missing)
        facts: list[FinancialReportFact] = []
        for _, row in df.iterrows():
            report_period = _date(row.get("REPORT_DATE"))
            announcement_date = _date(row.get("NOTICE_DATE"))
            revision_at = _datetime(row.get("UPDATE_DATE"))
            if report_period is None or announcement_date is None:
                continue
            if announcement_date > as_of_date:
                continue
            # 供应商接口通常只保留当前修订版。若修订发生在as_of之后，
            # 不能把修订值带回历史；缺少旧版本时宁可返回点时数据不完整。
            if revision_at is not None and revision_at.date() > as_of_date:
                continue
            raw = {str(key): value for key, value in row.to_dict().items()}
            facts.append(
                FinancialReportFact(
                    symbol=str(symbol).zfill(6),
                    report_period=report_period,
                    announcement_date=announcement_date,
                    operating_revenue=_number(row.get("OPERATE_INCOME")),
                    parent_net_profit=_number(row.get("PARENT_NETPROFIT")),
                    source=f"{self.provider_name}:{endpoint}",
                    revision_at=revision_at,
                    raw=raw,
                )
            )
        if not facts:
            return DataEnvelope(
                FetchStatus.EMPTY,
                None,
                self.provider_name,
                endpoint,
                request,
                row_count=0,
                schema_hash=_schema_hash(df),
                quality_warnings=["as_of_date之前无已公告正式利润表"],
            )
        payload = {
            "columns": list(map(str, df.columns)),
            "fact_count": len(facts),
            "latest_report": max(item.report_period for item in facts).isoformat(),
        }
        return DataEnvelope(
            FetchStatus.SUCCESS,
            facts,
            self.provider_name,
            endpoint,
            request,
            available_at=max(
                max(item.announcement_date, item.revision_at.date())
                if item.revision_at is not None
                else item.announcement_date
                for item in facts
            ),
            row_count=len(facts),
            schema_hash=_schema_hash(df),
            payload_hash=_hash_json(payload),
            raw_payload=payload,
        )

    def get_dividend_bundle(
        self, symbol: str, as_of_date: date
    ) -> DataEnvelope[DividendBundle]:
        endpoint = "stock_fhps_detail_em"
        request = {"symbol": symbol, "as_of_date": as_of_date.isoformat()}
        try:
            df = self.ak.stock_fhps_detail_em(symbol=str(symbol).zfill(6))
        except Exception as exc:
            return self._error(endpoint, request, exc)
        if df is None or df.empty:
            return DataEnvelope(
                FetchStatus.EMPTY,
                DividendBundle(events=(), actions=()),
                self.provider_name,
                endpoint,
                request,
                row_count=0,
                quality_warnings=["无分红送转记录，按TTM现金分红0处理"],
            )
        required = {
            "报告期",
            "现金分红-现金分红比例",
            "送转股份-送转总比例",
            "除权除息日",
            "方案进度",
            "最新公告日期",
        }
        missing = required.difference(df.columns)
        if missing:
            return self._schema_error(endpoint, request, df, missing)
        events: list[DividendEvent] = []
        actions: list[CorporateAction] = []
        for _, row in df.iterrows():
            ex_date = _date(row.get("除权除息日"))
            announcement_date = _date(row.get("最新公告日期"))
            if ex_date is None or ex_date > as_of_date:
                continue
            if announcement_date and announcement_date > as_of_date:
                continue
            status = str(row.get("方案进度") or "")
            raw = {str(key): value for key, value in row.to_dict().items()}
            cash_per_ten = _number(row.get("现金分红-现金分红比例"))
            if cash_per_ten is not None and cash_per_ten >= 0 and "实施" in status:
                events.append(
                    DividendEvent(
                        symbol=str(symbol).zfill(6),
                        ex_date=ex_date,
                        raw_cash_per_share_pre_tax=cash_per_ten / 10.0,
                        status=status,
                        source=f"{self.provider_name}:{endpoint}",
                        provider_adjusted=False,
                        announcement_date=announcement_date,
                        report_period=_date(row.get("报告期")),
                        raw=raw,
                    )
                )
            transfer_per_ten = _number(row.get("送转股份-送转总比例"))
            if (
                transfer_per_ten is not None
                and transfer_per_ten > 0
                and "实施" in status
            ):
                actions.append(
                    CorporateAction(
                        symbol=str(symbol).zfill(6),
                        effective_date=ex_date,
                        share_factor=1.0 + transfer_per_ten / 10.0,
                        source=f"{self.provider_name}:{endpoint}",
                        provider_adjusted=False,
                        raw=raw,
                    )
                )
        payload = {
            "columns": list(map(str, df.columns)),
            "event_count": len(events),
            "action_count": len(actions),
        }
        return DataEnvelope(
            FetchStatus.SUCCESS,
            DividendBundle(events=tuple(events), actions=tuple(actions)),
            self.provider_name,
            endpoint,
            request,
            available_at=as_of_date,
            row_count=len(df),
            schema_hash=_schema_hash(df),
            payload_hash=_hash_json(payload),
            raw_payload=payload,
        )

    @staticmethod
    def _is_st_name(name: Optional[str]) -> Optional[bool]:
        if name is None:
            return None
        normalized = re.sub(r"\s+", "", str(name)).upper()
        return bool(re.search(r"(?:^S?\*?ST)|退市", normalized))

    def _load_current_st_symbols(self) -> None:
        if self._current_st_symbols is not None or self._current_st_error is not None:
            return
        try:
            df = self.ak.stock_zh_a_st_em()
            if df is None:
                self._current_st_symbols = set()
                return
            code_col = (
                "代码"
                if "代码" in df.columns
                else "证券代码"
                if "证券代码" in df.columns
                else None
            )
            if code_col is None:
                raise ValueError(f"ST列表缺少代码列: {list(df.columns)}")
            self._current_st_symbols = {
                str(value).strip().zfill(6) for value in df[code_col].tolist()
            }
        except Exception as exc:
            self._current_st_error = f"{type(exc).__name__}: {exc}"

    def _load_sz_name_changes(self) -> None:
        if self._sz_name_changes is not None or self._sz_name_changes_error is not None:
            return
        try:
            df = self.ak.stock_info_sz_change_name(symbol="简称变更")
            required = {"变更日期", "证券代码", "变更前简称", "变更后简称"}
            missing = required.difference(df.columns)
            if missing:
                raise ValueError(f"深交所名称变更表缺少列: {sorted(missing)}")
            self._sz_name_changes = df.copy()
            self._sz_name_changes["_date"] = pd.to_datetime(
                self._sz_name_changes["变更日期"], errors="coerce"
            )
            self._sz_name_changes["_symbol"] = (
                self._sz_name_changes["证券代码"].astype(str).str.zfill(6)
            )
        except Exception as exc:
            self._sz_name_changes_error = f"{type(exc).__name__}: {exc}"

    def get_risk_warning_status(
        self,
        symbol: str,
        stock_name: Optional[str],
        as_of_date: date,
    ) -> DataEnvelope[RiskWarningStatus]:
        code = str(symbol).zfill(6)
        # Current ST lists are not point-in-time history.  Even a recent past
        # as-of date must use an effective-dated source or remain unavailable.
        is_current = as_of_date == self.today
        if is_current:
            self._load_current_st_symbols()
            by_name = self._is_st_name(stock_name)
            if self._current_st_symbols is not None:
                is_warning = code in self._current_st_symbols or bool(by_name)
                status = RiskWarningStatus(
                    symbol=code,
                    as_of_date=as_of_date,
                    is_risk_warning=is_warning,
                    security_name=stock_name,
                    source="AKShare:stock_zh_a_st_em+current_name",
                    effective_date=as_of_date,
                )
                return DataEnvelope(
                    FetchStatus.SUCCESS,
                    status,
                    self.provider_name,
                    "stock_zh_a_st_em",
                    {"as_of_date": as_of_date.isoformat()},
                    row_count=len(self._current_st_symbols),
                )
            if by_name is not None:
                status = RiskWarningStatus(
                    symbol=code,
                    as_of_date=as_of_date,
                    is_risk_warning=by_name,
                    security_name=stock_name,
                    source="current_security_name_fallback",
                    effective_date=as_of_date,
                    reason=self._current_st_error,
                )
                return DataEnvelope(
                    FetchStatus.SUCCESS,
                    status,
                    self.provider_name,
                    "current_security_name_fallback",
                    {"symbol": code, "as_of_date": as_of_date.isoformat()},
                    quality_warnings=["ST板块接口失败，使用当前证券简称交叉判断"],
                )
            return DataEnvelope(
                FetchStatus.ERROR,
                None,
                self.provider_name,
                "stock_zh_a_st_em",
                {"symbol": code, "as_of_date": as_of_date.isoformat()},
                error_type="RiskStatusUnavailable",
                error_message=self._current_st_error,
            )

        if self.exchange_for(code) == "SZ":
            self._load_sz_name_changes()
            if self._sz_name_changes is None:
                return DataEnvelope(
                    FetchStatus.ERROR,
                    None,
                    self.provider_name,
                    "stock_info_sz_change_name",
                    {"symbol": code, "as_of_date": as_of_date.isoformat()},
                    error_type="HistoricalRiskStatusUnavailable",
                    error_message=self._sz_name_changes_error,
                )
            rows = self._sz_name_changes[
                self._sz_name_changes["_symbol"] == code
            ].sort_values("_date")
            if rows.empty:
                historical_name = stock_name
                effective_date = None
            else:
                first = rows.iloc[0]
                if as_of_date < first["_date"].date():
                    historical_name = str(first["变更前简称"])
                    effective_date = None
                else:
                    eligible = rows[rows["_date"].dt.date <= as_of_date]
                    latest = eligible.iloc[-1]
                    historical_name = str(latest["变更后简称"])
                    effective_date = latest["_date"].date()
            is_warning = self._is_st_name(historical_name)
            status = RiskWarningStatus(
                symbol=code,
                as_of_date=as_of_date,
                is_risk_warning=is_warning,
                security_name=historical_name,
                source="SZSE:stock_info_sz_change_name",
                effective_date=effective_date,
            )
            return DataEnvelope(
                FetchStatus.SUCCESS,
                status,
                self.provider_name,
                "stock_info_sz_change_name",
                {"symbol": code, "as_of_date": as_of_date.isoformat()},
                row_count=len(rows),
            )

        return DataEnvelope(
            FetchStatus.EMPTY,
            None,
            self.provider_name,
            "historical_risk_warning_status",
            {"symbol": code, "as_of_date": as_of_date.isoformat()},
            quality_warnings=[
                "沪市/北交所历史风险警示生效区间暂无可靠免费点时源，严格留待补数"
            ],
        )
