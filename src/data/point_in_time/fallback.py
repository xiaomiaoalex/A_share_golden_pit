"""Fail-closed fallback chain for point-in-time providers.

Fallbacks may fill a missing source, but they never alter metric definitions or
screening thresholds.  The returned envelope retains a trace of every attempted
provider so an upstream failure is not silently hidden.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from time import monotonic

from src.data.quality.registry import capability_for
from src.data.quality.types import CapabilityLevel

from .contracts import DataEnvelope, FetchStatus


class FallbackPointInTimeProvider:
    def __init__(
        self,
        *providers,
        configuration_warnings=None,
        circuit_failure_threshold: int = 3,
        circuit_cooldown_seconds: float = 60.0,
    ):
        if not providers:
            raise ValueError("至少需要一个点时数据提供方")
        self.providers = providers
        self.today = providers[0].today
        self.configuration_warnings = list(configuration_warnings or [])
        self.circuit_failure_threshold = max(1, circuit_failure_threshold)
        self.circuit_cooldown_seconds = max(0.0, circuit_cooldown_seconds)
        self._circuit_state: dict[tuple[str, str], dict[str, float | int]] = {}

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

    @staticmethod
    def _capability_rank(provider, field_group: str) -> int:
        """Prefer contract-complete sources without discarding operator order."""
        capability = capability_for(
            getattr(provider, "provider_name", ""), field_group
        )
        return {
            CapabilityLevel.EXACT: 0,
            CapabilityLevel.LIMITED: 1,
            CapabilityLevel.UNKNOWN: 2,
            CapabilityLevel.UNSUPPORTED: 3,
        }[capability]

    def _call(
        self, method: str, *args, field_group: str, providers=None
    ) -> DataEnvelope:
        attempts = []
        last = None
        selected_providers = self.providers if providers is None else list(providers)
        selected_providers = sorted(
            selected_providers,
            key=lambda provider: self._capability_rank(provider, field_group),
        )
        for provider in selected_providers:
            provider_name = getattr(provider, "provider_name", type(provider).__name__)
            circuit_key = (provider_name, method)
            state = self._circuit_state.get(circuit_key, {})
            open_until = float(state.get("open_until", 0.0))
            if open_until > monotonic():
                attempts.append(
                    {
                        "provider": provider_name,
                        "endpoint": method,
                        "status": FetchStatus.ERROR.value,
                        "error_type": "CIRCUIT_OPEN",
                        "error_message": "数据源连续失败，熔断冷却中",
                    }
                )
                continue
            envelope = getattr(provider, method)(*args)
            attempts.append(self._trace(envelope))
            last = envelope
            # EMPTY with a non-None data object is a verified semantic value,
            # e.g. no dividend records => TTM cash dividend equals zero.
            if envelope.usable or (
                envelope.status == FetchStatus.EMPTY and envelope.data is not None
            ):
                self._circuit_state.pop(circuit_key, None)
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
            if envelope.status in {FetchStatus.ERROR, FetchStatus.SCHEMA_ERROR}:
                failures = int(state.get("failures", 0)) + 1
                self._circuit_state[circuit_key] = {
                    "failures": failures,
                    "open_until": (
                        monotonic() + self.circuit_cooldown_seconds
                        if failures >= self.circuit_failure_threshold
                        else 0.0
                    ),
                }
        if last is None:
            return DataEnvelope(
                status=FetchStatus.ERROR,
                data=None,
                provider="fallback-chain",
                endpoint=method,
                request={"args": [str(item) for item in args]},
                error_type="NO_QUALIFIED_SOURCE",
                error_message="没有满足点时能力要求的数据源",
                quality_warnings=list(self.configuration_warnings),
                raw_payload={"fallback_trace": attempts},
            )
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
        if as_of_date < self.today:
            exact = [
                provider
                for provider in self.providers
                if capability_for(provider.provider_name, "universe")
                == CapabilityLevel.EXACT
            ]
            return self._call(
                "get_universe", as_of_date, field_group="universe", providers=exact
            )
        return self._call("get_universe", as_of_date, field_group="universe")

    def get_market_snapshot(self, symbol: str, as_of_date: date):
        return self._call(
            "get_market_snapshot", symbol, as_of_date, field_group="market"
        )

    def get_financial_facts(self, symbol: str, as_of_date: date):
        return self._call(
            "get_financial_facts",
            symbol,
            as_of_date,
            field_group="financial_statements",
        )

    def get_dividend_bundle(self, symbol: str, as_of_date: date):
        return self._call(
            "get_dividend_bundle",
            symbol,
            as_of_date,
            field_group="dividend_and_actions",
        )

    def get_risk_warning_status(self, symbol: str, stock_name: str, as_of_date: date):
        return self._call(
            "get_risk_warning_status",
            symbol,
            stock_name,
            as_of_date,
            field_group="risk_warning_status",
        )
