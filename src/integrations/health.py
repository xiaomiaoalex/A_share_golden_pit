from __future__ import annotations

import importlib.util

OPTIONAL_COMPONENTS = {
    "QlibAdapter": "qlib",
    "VnpyAdapter": "vnpy",
    "CVXPYAdapter": "cvxpy",
    "PyPortfolioOptAdapter": "pypfopt",
    "PolarsAdapter": "polars",
    "OpenBBAdapter": "openbb",
}


def integration_health() -> list[dict[str, str]]:
    return [
        {
            "component": adapter,
            "status": "AVAILABLE" if importlib.util.find_spec(module) else "OPTIONAL_NOT_INSTALLED",
            "detail": module,
        }
        for adapter, module in OPTIONAL_COMPONENTS.items()
    ]
