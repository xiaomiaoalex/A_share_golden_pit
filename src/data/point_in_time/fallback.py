"""Fail-closed fallback chain for point-in-time providers.

Fallbacks may fill a missing source, but they never alter metric definitions or
screening thresholds.  The returned envelope retains a trace of every attempted
provider so an upstream failure is not silently hidden.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from .contracts import DataEnvelope, FetchStatus


class FallbackPointInTimeProvider:
    def __init__(self, *providers, configuration_warnings=None):
        if not providers:
            raise ValueError("至少需要一个点时数据提供方")
        self.providers = providers
        self.today = providers[0].today
        self.configuration_warnings = list(configuration_warnings or [])

    @property
    def provider_names(self) -> list[str]:
        return [provider.provider_name for provider in self.providers]

    def close(self) -> None:
        for provider in self.providers:
            close = getattr(provider, "close", None)
            if callable(close):
                close()

    @staticmethod
    def exchange_for(symbol: str) -> str:
        code = str(symbol).zfill(6)
        if code.startswith(("4", "8", "92")):
            return "BJ"
        return "SH" if code.startswith("6") else "SZ"

    @staticmethod
    def _trace(envelope: DataEnvelope) -> dict:
        return {
            "provider": envelope.provider,
            "endpoint": envelope.endpoint,
            "status": envelope.status.value,
            "error_type": envelope.error_type,
            "error_message": envelope.error_message,
        }

    def _call(self, method: str, *args) -> DataEnvelope:
        attempts = []
        last = None
        for provider in self.providers:
            envelope = getattr(provider, method)(*args)
            attempts.append(self._trace(envelope))
            last = envelope
            # EMPTY with a non-None data object is a verified semantic value,
            # e.g. no dividend records => TTM cash dividend equals zero.
            if envelope.usable or (
                envelope.status == FetchStatus.EMPTY and envelope.data is not None
            ):
                warnings = list(envelope.quality_warnings)
                if len(attempts) > 1:
                    warnings.append(
                        f"主数据源不可用，采用第{len(attempts)}数据源；筛选口径未放宽"
                    )
                return replace(
                    envelope,
                    quality_warnings=warnings,
                    raw_payload={
                        "selected_payload": envelope.raw_payload,
                        "fallback_trace": attempts,
                    },
                )
        assert last is not None
        status = (
            FetchStatus.ERROR
            if any(item["status"] in {"ERROR", "SCHEMA_ERROR"} for item in attempts)
            else FetchStatus.EMPTY
        )
        return replace(
            last,
            status=status,
            data=None,
            provider="fallback-chain",
            error_type="ALL_SOURCES_UNAVAILABLE" if status == FetchStatus.ERROR else None,
            error_message=(
                "全部点时数据源失败或不满足Schema" if status == FetchStatus.ERROR else None
            ),
            quality_warnings=list(last.quality_warnings),
            raw_payload={"fallback_trace": attempts},
        )

    def get_universe(self, as_of_date: date):
        return self._call("get_universe", as_of_date)

    def get_market_snapshot(self, symbol: str, as_of_date: date):
        return self._call("get_market_snapshot", symbol, as_of_date)

    def get_financial_facts(self, symbol: str, as_of_date: date):
        return self._call("get_financial_facts", symbol, as_of_date)

    def get_dividend_bundle(self, symbol: str, as_of_date: date):
        return self._call("get_dividend_bundle", symbol, as_of_date)

    def get_risk_warning_status(self, symbol: str, stock_name: str, as_of_date: date):
        return self._call("get_risk_warning_status", symbol, stock_name, as_of_date)
