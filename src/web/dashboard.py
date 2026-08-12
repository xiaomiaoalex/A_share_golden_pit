"""Compatibility import for the former single-strategy dashboard service."""

from src.strategies.golden_pit.presentation import GoldenPitReadModel

DashboardService = GoldenPitReadModel

__all__ = ["DashboardService"]
