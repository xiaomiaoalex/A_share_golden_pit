from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class BacktestSpecification:
    specification_id: str
    strategy_release_id: str
    data_snapshot_id: str
    start_date: date
    end_date: date
    initial_cash: float
    lot_size: int = 100
    commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.0005
    participation_rate: float = 0.1
    signal_delay_days: int = 1


@dataclass(frozen=True)
class OrderIntent:
    order_id: str
    security_id: str
    side: OrderSide
    quantity: int
    signal_date: date


@dataclass(frozen=True)
class MarketBar:
    security_id: str
    trade_date: date
    close: float
    volume: int
    suspended: bool = False
    limit_up: bool = False
    limit_down: bool = False


@dataclass(frozen=True)
class ExecutionResult:
    order_id: str
    status: str
    filled_quantity: int
    price: float | None
    commission: float
    stamp_tax: float
    reason: str | None = None
