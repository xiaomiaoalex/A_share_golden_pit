"""Professional backtest contracts and A-share execution simulator."""

from .ashare import AshareExecutionSimulator
from .contracts import BacktestSpecification, MarketBar, OrderIntent

__all__ = [
    "AshareExecutionSimulator",
    "BacktestSpecification",
    "MarketBar",
    "OrderIntent",
    "compare_execution_results",
]
from .comparison import compare_execution_results
