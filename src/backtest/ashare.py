from __future__ import annotations

from datetime import timedelta

from .contracts import (
    BacktestSpecification,
    ExecutionResult,
    MarketBar,
    OrderIntent,
    OrderSide,
)


class AshareExecutionSimulator:
    def __init__(self, specification: BacktestSpecification) -> None:
        self.specification = specification

    def execute(self, order: OrderIntent, bar: MarketBar) -> ExecutionResult:
        if bar.trade_date < order.signal_date + timedelta(
            days=self.specification.signal_delay_days
        ):
            return self._reject(order, "SIGNAL_DELAY")
        if bar.suspended:
            return self._reject(order, "SUSPENDED")
        if order.side == OrderSide.BUY and bar.limit_up:
            return self._reject(order, "LIMIT_UP")
        if order.side == OrderSide.SELL and bar.limit_down:
            return self._reject(order, "LIMIT_DOWN")
        rounded = order.quantity // self.specification.lot_size * self.specification.lot_size
        capacity = int(bar.volume * self.specification.participation_rate)
        capacity = capacity // self.specification.lot_size * self.specification.lot_size
        filled = min(rounded, capacity)
        if filled <= 0:
            return self._reject(order, "LOT_OR_LIQUIDITY")
        notional = filled * bar.close
        return ExecutionResult(
            order_id=order.order_id,
            status="FILLED" if filled == rounded else "PARTIAL",
            filled_quantity=filled,
            price=bar.close,
            commission=notional * self.specification.commission_rate,
            stamp_tax=(
                notional * self.specification.stamp_tax_rate
                if order.side == OrderSide.SELL
                else 0.0
            ),
        )

    @staticmethod
    def _reject(order: OrderIntent, reason: str) -> ExecutionResult:
        return ExecutionResult(order.order_id, "REJECTED", 0, None, 0.0, 0.0, reason)
