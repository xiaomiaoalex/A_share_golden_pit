"""Point-in-time Tushare Pro adapter with explicit Tier1 metric contracts."""

from __future__ import annotations

import os
import re
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd

from src.data.point_in_time.models import (
    CorporateAction,
    DividendEvent,
    FinancialReportFact,
    MarketSnapshot,
    RiskWarningStatus,
)

from .contracts import DataEnvelope, DividendBundle, FetchStatus, UniverseItem
from .provider_utils import (
    hash_json,
    number,
    parse_date,
    schema_hash,
    years_before,
)


class TusharePointInTimeProvider:
    provider_name = "Tushare Pro"

    def __init__(
        self,
        pro_client=None,
        *,
        token: Optional[str] = None,
        today: Optional[date] = None,
        current_window_days: int = 7,
    ):
        if pro_client is None:
            token = token or os.getenv("TUSHARE_TOKEN")
            if not token:
                raise ValueError("TUSHARE_TOKEN未配置")
            import tushare as ts

            pro_client = ts.pro_api(token)
        self.pro = pro_client
        self.today = today or date.today()
        self.current_window_days = current_window_days

    @staticmethod
    def exchange_for(symbol: str) -> str:
        code = str(symbol).zfill(6)
        if code.startswith(("4", "8", "92")):
            return "BJ"
        return "SH" if code.startswith("6") else "SZ"

    @classmethod
    def ts_code(cls, symbol: str) -> str:
        exchange = cls.exchange_for(symbol)
        return f"{str(symbol).zfill(6)}.{exchange}"

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

    def _schema_error(
        self, endpoint: str, request: dict, frame: pd.DataFrame, missing: set[str]
    ) -> DataEnvelope:
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
            raw_payload={"columns": list(map(str, frame.columns))},
        )

    def get_universe(self, as_of_date: date) -> DataEnvelope[list[UniverseItem]]:
        endpoint = "stock_basic"
        request = {"as_of_date": as_of_date.isoformat(), "statuses": ["L", "D", "P"]}
        frames = []
        try:
            for status in request["statuses"]:
                frame = self.pro.stock_basic(
                    exchange="",
                    list_status=status,
                    fields="ts_code,symbol,name,exchange,list_status,list_date,delist_date",
                )
                if frame is not None and not frame.empty:
                    frames.append(frame)
        except Exception as exc:
            return self._error(endpoint, request, exc)
        if not frames:
            return DataEnvelope(
                FetchStatus.EMPTY,
                None,
                self.provider_name,
                endpoint,
                request,
                row_count=0,
            )
        frame = pd.concat(frames, ignore_index=True).drop_duplicates("ts_code")
        required = {"symbol", "name", "exchange", "list_date", "delist_date"}
        missing = required.difference(frame.columns)
        if missing:
            return self._schema_error(endpoint, request, frame, missing)

        items = []
        for _, row in frame.iterrows():
            listed = parse_date(row.get("list_date"))
            delisted = parse_date(row.get("delist_date"))
            if listed is None or listed > as_of_date:
                continue
            if delisted is not None and as_of_date >= delisted:
                continue
            symbol = str(row.get("symbol", "")).strip().zfill(6)
            exchange = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}.get(
                str(row.get("exchange", "")).upper(), self.exchange_for(symbol)
            )
            items.append(
                UniverseItem(
                    symbol=symbol, name=str(row.get("name", symbol)), exchange=exchange
                )
            )
        payload = {
            "metric_contract": "list_date <= as_of_date < delist_date",
            "unit_contract": "not_applicable",
            "rows_received": len(frame),
            "rows_selected": len(items),
        }
        return DataEnvelope(
            FetchStatus.SUCCESS,
            items,
            self.provider_name,
            endpoint,
            request,
            available_at=as_of_date,
            row_count=len(items),
            schema_hash=schema_hash(frame),
            payload_hash=hash_json(payload),
            raw_payload=payload,
            quality_warnings=[
                "历史股票名称为stock_basic当前简称；ST硬判断另用历史名称区间"
            ],
        )

    def get_market_snapshot(
        self, symbol: str, as_of_date: date
    ) -> DataEnvelope[MarketSnapshot]:
        endpoint = "daily_basic"
        ts_code = self.ts_code(symbol)
        start = date.fromordinal(max(1, as_of_date.toordinal() - 31))
        request = {
            "ts_code": ts_code,
            "start_date": start.strftime("%Y%m%d"),
            "end_date": as_of_date.strftime("%Y%m%d"),
        }
        try:
            frame = self.pro.daily_basic(
                **request,
                fields="ts_code,trade_date,close,pe_ttm,total_share,total_mv",
            )
        except Exception as exc:
            return self._error(endpoint, request, exc)
        if frame is None or frame.empty:
            return DataEnvelope(
                FetchStatus.EMPTY,
                None,
                self.provider_name,
                endpoint,
                request,
                row_count=0,
            )
        required = {"trade_date", "close", "pe_ttm", "total_share", "total_mv"}
        missing = required.difference(frame.columns)
        if missing:
            return self._schema_error(endpoint, request, frame, missing)
        working = frame.copy()
        working["_date"] = working["trade_date"].map(parse_date)
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
            market_cap=(
                number(row.get("total_mv")) * 10_000
                if number(row.get("total_mv")) is not None
                else None
            ),
            total_shares=(
                number(row.get("total_share")) * 10_000
                if number(row.get("total_share")) is not None
                else None
            ),
            supplier_pe_ttm=number(row.get("pe_ttm")),
            source=f"{self.provider_name}:{endpoint}",
        )
        raw = {
            str(key): value
            for key, value in row.drop(labels=["_date"]).to_dict().items()
        }
        payload = {
            "raw": raw,
            "metric_contract": "pe_ttm=total_mv/net_profit_ttm; loss PE is null",
            "unit_contract": {
                "total_mv": "10k CNY -> CNY",
                "total_share": "10k shares -> shares",
            },
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
        )

    def get_financial_facts(
        self, symbol: str, as_of_date: date
    ) -> DataEnvelope[list[FinancialReportFact]]:
        endpoint = "income"
        ts_code = self.ts_code(symbol)
        request = {
            "ts_code": ts_code,
            "start_date": years_before(as_of_date, 6).strftime("%Y%m%d"),
            "end_date": as_of_date.strftime("%Y%m%d"),
        }
        fields = (
            "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,"
            "revenue,n_income_attr_p,update_flag"
        )
        try:
            frame = self.pro.income(**request, fields=fields)
        except Exception as exc:
            return self._error(endpoint, request, exc)
        if frame is None or frame.empty:
            return DataEnvelope(
                FetchStatus.EMPTY,
                None,
                self.provider_name,
                endpoint,
                request,
                row_count=0,
            )
        required = {
            "ann_date",
            "f_ann_date",
            "end_date",
            "report_type",
            "revenue",
            "n_income_attr_p",
            "update_flag",
        }
        missing = required.difference(frame.columns)
        if missing:
            return self._schema_error(endpoint, request, frame, missing)

        candidates = []
        for _, row in frame.iterrows():
            report_type = str(row.get("report_type", "")).split(".", 1)[0]
            if report_type not in {"1", "4", "5"}:
                continue
            report_period = parse_date(row.get("end_date"))
            announced = parse_date(row.get("ann_date"))
            actual = parse_date(row.get("f_ann_date")) or announced
            if report_period is None or actual is None or actual > as_of_date:
                continue
            candidates.append((report_period, actual, report_type, row))
        if not candidates:
            return DataEnvelope(
                FetchStatus.EMPTY,
                None,
                self.provider_name,
                endpoint,
                request,
                row_count=0,
                schema_hash=schema_hash(frame),
            )

        selected = {}
        report_rank = {"5": 0, "1": 1, "4": 2}
        for item in candidates:
            period, actual, report_type, row = item
            key = (
                actual,
                int(number(row.get("update_flag")) or 0),
                report_rank[report_type],
            )
            if period not in selected or key > selected[period][0]:
                selected[period] = (key, item)

        facts = []
        for period in sorted(selected):
            _, (_, actual, report_type, row) = selected[period]
            raw = {str(key): value for key, value in row.to_dict().items()}
            facts.append(
                FinancialReportFact(
                    symbol=str(symbol).zfill(6),
                    report_period=period,
                    announcement_date=actual,
                    operating_revenue=number(row.get("revenue")),
                    parent_net_profit=number(row.get("n_income_attr_p")),
                    source=f"{self.provider_name}:{endpoint}",
                    revision_at=datetime.combine(actual, datetime.min.time()),
                    raw={
                        **raw,
                        "metric_contract": {
                            "operating_revenue": "Tushare income.revenue",
                            "parent_net_profit": "Tushare income.n_income_attr_p",
                            "report_scope": f"cumulative consolidated report_type={report_type}",
                        },
                        "unit_contract": "CNY",
                    },
                )
            )
        payload = {
            "rows_received": len(frame),
            "facts_selected": len(facts),
            "metric_contract": "revenue + n_income_attr_p; actual announcement <= as_of",
        }
        return DataEnvelope(
            FetchStatus.SUCCESS,
            facts,
            self.provider_name,
            endpoint,
            request,
            available_at=max(fact.announcement_date for fact in facts),
            row_count=len(facts),
            schema_hash=schema_hash(frame),
            payload_hash=hash_json(payload),
            raw_payload=payload,
        )

    def get_dividend_bundle(
        self, symbol: str, as_of_date: date
    ) -> DataEnvelope[DividendBundle]:
        endpoint = "dividend"
        request = {
            "ts_code": self.ts_code(symbol),
            "as_of_date": as_of_date.isoformat(),
        }
        fields = (
            "ts_code,end_date,ann_date,div_proc,stk_div,stk_bo_rate,stk_co_rate,"
            "cash_div_tax,ex_date,imp_ann_date"
        )
        try:
            frame = self.pro.dividend(ts_code=request["ts_code"], fields=fields)
        except Exception as exc:
            return self._error(endpoint, request, exc)
        if frame is None or frame.empty:
            return DataEnvelope(
                FetchStatus.EMPTY,
                DividendBundle(events=(), actions=()),
                self.provider_name,
                endpoint,
                request,
                row_count=0,
                quality_warnings=["Tushare无分红送转记录，按TTM现金分红0处理"],
            )
        required = {
            "end_date",
            "ann_date",
            "div_proc",
            "stk_div",
            "cash_div_tax",
            "ex_date",
            "imp_ann_date",
        }
        missing = required.difference(frame.columns)
        if missing:
            return self._schema_error(endpoint, request, frame, missing)
        events = []
        actions = []
        seen = set()
        for _, row in frame.iterrows():
            if "实施" not in str(row.get("div_proc", "")):
                continue
            ex_date = parse_date(row.get("ex_date"))
            announced = parse_date(row.get("ann_date"))
            implemented = parse_date(row.get("imp_ann_date")) or announced
            available = (
                max(value for value in (announced, implemented) if value is not None)
                if announced or implemented
                else None
            )
            if (
                ex_date is None
                or ex_date > as_of_date
                or available is None
                or available > as_of_date
            ):
                continue
            cash = number(row.get("cash_div_tax"))
            stock_dividend = number(row.get("stk_div"))
            if stock_dividend is None:
                stock_dividend = (number(row.get("stk_bo_rate")) or 0) + (
                    number(row.get("stk_co_rate")) or 0
                )
            key = (parse_date(row.get("end_date")), ex_date, cash, stock_dividend)
            if key in seen:
                continue
            seen.add(key)
            raw = {
                **{str(k): v for k, v in row.to_dict().items()},
                "metric_contract": "cash_div_tax=pre-tax cash/share; ex_date implemented",
                "unit_contract": "CNY/share and shares/share",
            }
            if cash is not None and cash >= 0:
                events.append(
                    DividendEvent(
                        symbol=str(symbol).zfill(6),
                        ex_date=ex_date,
                        raw_cash_per_share_pre_tax=cash,
                        status=str(row.get("div_proc")),
                        source=f"{self.provider_name}:{endpoint}",
                        provider_adjusted=False,
                        announcement_date=available,
                        report_period=parse_date(row.get("end_date")),
                        raw=raw,
                    )
                )
            if stock_dividend is not None and stock_dividend > 0:
                actions.append(
                    CorporateAction(
                        symbol=str(symbol).zfill(6),
                        effective_date=ex_date,
                        share_factor=1 + stock_dividend,
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
            "metric_contract": "implemented pre-tax cash/share on ex-date",
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

    @staticmethod
    def _is_st_name(name: str) -> bool:
        normalized = re.sub(r"\s+", "", str(name)).upper()
        return bool(re.search(r"(?:^S?\*?ST)|退市", normalized))

    def _namechange_risk_status(
        self, symbol: str, stock_name: Optional[str], as_of_date: date
    ) -> DataEnvelope[RiskWarningStatus]:
        endpoint = "namechange"
        request = {
            "ts_code": self.ts_code(symbol),
            "as_of_date": as_of_date.isoformat(),
        }
        try:
            frame = self.pro.namechange(
                ts_code=request["ts_code"],
                fields="ts_code,name,start_date,end_date,ann_date,change_reason",
            )
        except Exception as exc:
            return self._error(endpoint, request, exc)
        if frame is None or frame.empty:
            return DataEnvelope(
                FetchStatus.EMPTY,
                None,
                self.provider_name,
                endpoint,
                request,
                row_count=0,
            )
        required = {"name", "start_date", "end_date", "ann_date"}
        missing = required.difference(frame.columns)
        if missing:
            return self._schema_error(endpoint, request, frame, missing)
        eligible = []
        for _, row in frame.iterrows():
            start = parse_date(row.get("start_date"))
            end = parse_date(row.get("end_date"))
            announced = parse_date(row.get("ann_date"))
            if start is None or announced is None or announced > as_of_date:
                continue
            if start <= as_of_date and (end is None or as_of_date <= end):
                eligible.append((start, row))
        if not eligible:
            return DataEnvelope(
                FetchStatus.EMPTY,
                None,
                self.provider_name,
                endpoint,
                request,
                row_count=0,
                schema_hash=schema_hash(frame),
                quality_warnings=["历史名称区间未覆盖as_of_date，不能推定非ST"],
            )
        start, row = max(eligible, key=lambda item: item[0])
        name = str(row.get("name"))
        status = RiskWarningStatus(
            symbol=str(symbol).zfill(6),
            as_of_date=as_of_date,
            is_risk_warning=self._is_st_name(name),
            security_name=name,
            source=f"{self.provider_name}:{endpoint}",
            effective_date=start,
            reason=str(row.get("change_reason") or ""),
        )
        payload = {
            "name": name,
            "start_date": start.isoformat(),
            "end_date": str(row.get("end_date") or ""),
            "metric_contract": "security name effective interval at as_of_date",
        }
        return DataEnvelope(
            FetchStatus.SUCCESS,
            status,
            self.provider_name,
            endpoint,
            request,
            available_at=start,
            row_count=len(frame),
            schema_hash=schema_hash(frame),
            payload_hash=hash_json(payload),
            raw_payload=payload,
        )

    def get_risk_warning_status(
        self, symbol: str, stock_name: Optional[str], as_of_date: date
    ) -> DataEnvelope[RiskWarningStatus]:
        endpoint = "stock_st"
        ts_code = self.ts_code(symbol)
        start_date = as_of_date - timedelta(days=15)
        request = {
            "ts_code": ts_code,
            "as_of_date": as_of_date.isoformat(),
            "start_date": start_date.strftime("%Y%m%d"),
            "end_date": as_of_date.strftime("%Y%m%d"),
        }
        try:
            if as_of_date < date(2016, 1, 1):
                raise ValueError("Tushare stock_st仅覆盖2016-01-01以后")
            calendar = self.pro.trade_cal(
                exchange="",
                start_date=request["start_date"],
                end_date=request["end_date"],
                is_open="1",
                fields="cal_date,is_open",
            )
            if calendar is None or calendar.empty or "cal_date" not in calendar.columns:
                raise RuntimeError("Tushare交易日历为空或Schema不完整")
            trade_dates = [
                value
                for value in calendar["cal_date"].map(parse_date)
                if value is not None and value <= as_of_date
            ]
            if not trade_dates:
                raise RuntimeError("as_of_date之前15日内无Tushare交易日")
            trade_date = max(trade_dates)
            frame = self.pro.stock_st(
                ts_code=ts_code,
                trade_date=trade_date.strftime("%Y%m%d"),
                fields="ts_code,name,trade_date,type,type_name",
            )
        except Exception as exc:
            fallback = self._namechange_risk_status(symbol, stock_name, as_of_date)
            return replace(
                fallback,
                quality_warnings=[
                    f"stock_st不可用，回退历史名称区间: {type(exc).__name__}: {exc}",
                    *fallback.quality_warnings,
                ],
                raw_payload={
                    "stock_st_error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                    "selected_payload": fallback.raw_payload,
                },
            )

        if frame is None:
            frame = pd.DataFrame()
        required = {"ts_code", "name", "trade_date", "type", "type_name"}
        if not frame.empty:
            missing = required.difference(frame.columns)
            if missing:
                return self._schema_error(endpoint, request, frame, missing)
            matching = frame[frame["ts_code"].astype(str).str.upper() == ts_code]
        else:
            matching = frame

        is_risk_warning = not matching.empty
        row = matching.iloc[-1] if is_risk_warning else None
        name = str(row.get("name")) if row is not None else stock_name
        reason = (
            str(row.get("type_name") or row.get("type") or "")
            if row is not None
            else ""
        )
        status = RiskWarningStatus(
            symbol=str(symbol).zfill(6),
            as_of_date=as_of_date,
            is_risk_warning=is_risk_warning,
            security_name=name,
            source=f"{self.provider_name}:{endpoint}",
            effective_date=trade_date,
            reason=reason,
        )
        payload = {
            "trade_date": trade_date.isoformat(),
            "matched_rows": len(matching),
            "metric_contract": "official daily ST list at latest trading day <= as_of",
        }
        return DataEnvelope(
            FetchStatus.SUCCESS,
            status,
            self.provider_name,
            endpoint,
            request,
            available_at=trade_date,
            row_count=len(frame),
            schema_hash=schema_hash(frame),
            payload_hash=hash_json(payload),
            raw_payload=payload,
        )
