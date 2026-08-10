"""Point-in-time data provider contracts and adapters."""

from .akshare_adapter import AKSharePointInTimeProvider
from .baostock_adapter import BaoStockPointInTimeProvider
from .contracts import DataEnvelope, FetchStatus, UniverseItem
from .fallback import FallbackPointInTimeProvider
from .provider_factory import build_point_in_time_provider
from .tushare_adapter import TusharePointInTimeProvider

__all__ = [
    "AKSharePointInTimeProvider",
    "BaoStockPointInTimeProvider",
    "DataEnvelope",
    "FallbackPointInTimeProvider",
    "FetchStatus",
    "TusharePointInTimeProvider",
    "UniverseItem",
    "build_point_in_time_provider",
]
