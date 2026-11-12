"""
Conversion of pandas/numpy results into JSON-safe Python values.
"""

import math
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd


def to_jsonable(value: Any) -> Any:
    """Recursively convert numpy/pandas values; NaN and infinities become None."""
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, pd.DataFrame):
        return records(value)
    if isinstance(value, pd.Series):
        return to_jsonable(value.to_dict())
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, np.ndarray):
        return [to_jsonable(v) for v in value.tolist()]
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return None if math.isnan(number) or math.isinf(number) else number
    if value is pd.NaT:
        return None
    return value


def records(frame: pd.DataFrame) -> list:
    """DataFrame rows as a list of JSON-safe dicts (index dropped)."""
    if frame is None or frame.empty:
        return []
    return [to_jsonable(row) for row in frame.to_dict(orient='records')]


# Glossary names for fields that used older names. The old fields stay for one
# release as deprecated aliases (CHANGELOG, "Deprecated"): new name <- old name.
RANKED_ASSET_ALIASES = {'model_agreement': 'ml_confidence', 'pick_label': 'recommendation'}


def with_glossary_names(item: dict) -> dict:
    """A ranked asset with its glossary-named fields added next to the deprecated ones."""
    for new, old in RANKED_ASSET_ALIASES.items():
        if old in item:
            item.setdefault(new, item[old])
    return item


def snake(name: str) -> str:
    """'Composite_Score' -> 'composite_score'."""
    return name.lower()


def snake_records(frame: pd.DataFrame) -> list:
    """Like :func:`records` but with lower-snake-case keys, the API's convention."""
    return [{snake(k): v for k, v in row.items()} for row in records(frame)]
