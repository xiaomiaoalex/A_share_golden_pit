"""Production provider-chain construction without embedding credentials."""

from __future__ import annotations

import os
from datetime import date
from typing import Mapping, Optional, Protocol

from .akshare_adapter import AKSharePointInTimeProvider
from .baostock_adapter import BaoStockPointInTimeProvider
from .fallback import FallbackPointInTimeProvider
from .tushare_adapter import TusharePointInTimeProvider


class ProviderWindowConfig(Protocol):
    current_supplier_window_days: int


def build_point_in_time_provider(
    config: Optional[ProviderWindowConfig] = None,
    *,
    environment: Optional[Mapping[str, str]] = None,
    today: Optional[date] = None,
    ak_module=None,
    tushare_client=None,
    baostock_client=None,
) -> FallbackPointInTimeProvider:
    current_window_days = config.current_supplier_window_days if config else 7
    environment = os.environ if environment is None else environment
    requested = [
        item.strip().lower()
        for item in environment.get(
            "GOLDEN_PIT_DATA_SOURCES",
            environment.get("TIER1_DATA_SOURCES", "akshare,tushare,baostock"),
        ).split(",")
        if item.strip()
    ]
    allowed = {"akshare", "tushare", "baostock"}
    unknown = sorted(set(requested).difference(allowed))
    if unknown:
        raise ValueError(f"黄金坑策略存在未知数据源: {unknown}")
    if not requested:
        raise ValueError("GOLDEN_PIT_DATA_SOURCES 至少需要一个数据源")

    providers = []
    warnings = []
    for source in requested:
        if source == "akshare":
            providers.append(
                AKSharePointInTimeProvider(
                    ak_module=ak_module,
                    today=today,
                    current_window_days=current_window_days,
                )
            )
        elif source == "tushare":
            token = environment.get("TUSHARE_TOKEN", "").strip()
            if tushare_client is None and not token:
                warnings.append("TUSHARE_TOKEN未配置，Tushare数据源本次未启用")
                continue
            providers.append(
                TusharePointInTimeProvider(
                    tushare_client,
                    token=token,
                    today=today,
                    current_window_days=current_window_days,
                )
            )
        elif source == "baostock":
            providers.append(
                BaoStockPointInTimeProvider(
                    baostock_client,
                    today=today,
                    current_window_days=current_window_days,
                )
            )
    if not providers:
        raise ValueError("没有可启用的Tier1数据源")
    return FallbackPointInTimeProvider(*providers, configuration_warnings=warnings)
