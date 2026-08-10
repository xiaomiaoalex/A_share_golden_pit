"""Shared normalization helpers for point-in-time provider adapters."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from typing import Any, Optional

import pandas as pd


def hash_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def schema_hash(frame: pd.DataFrame) -> str:
    schema = [
        (str(column), str(dtype)) for column, dtype in zip(frame.columns, frame.dtypes)
    ]
    return hash_json(schema)


def number(value: object) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.replace(",", "").strip()
        if not value or value in {"-", "--", "None", "nan"}:
            return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def parse_date(value: object) -> Optional[date]:
    if value is None:
        return None
    if not isinstance(value, (str, date, datetime)) and pd.isna(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def parse_datetime(value: object) -> Optional[datetime]:
    parsed = parse_date(value)
    return datetime.combine(parsed, datetime.min.time()) if parsed else None


def result_to_frame(result) -> pd.DataFrame:
    """Convert a BaoStock ResultData or compatible fake to a DataFrame."""

    if hasattr(result, "get_data"):
        frame = result.get_data()
        if isinstance(frame, pd.DataFrame):
            return frame
    rows = []
    while result.next():
        rows.append(result.get_row_data())
    return pd.DataFrame(rows, columns=list(result.fields))


def years_before(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, day=28)
