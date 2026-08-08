"""高値・安値系指標。"""

from __future__ import annotations

import pandas as pd

from lib.indicators.registry import register


@register("high52w", "52週高値", kind="line")
def high52w(weekly: pd.DataFrame) -> pd.Series:
    return weekly["High"].rolling(window=52, min_periods=1).max()


@register("high13w", "13週高値", kind="line")
def high13w(weekly: pd.DataFrame) -> pd.Series:
    return weekly["High"].rolling(window=13, min_periods=1).max()


@register("close_vs_high52w_pct", "52週高値からの乖離率", kind="feature", unit="%")
def close_vs_high52w_pct(weekly: pd.DataFrame) -> pd.Series:
    h = weekly["High"].rolling(window=52, min_periods=1).max()
    return (weekly["Close"] / h - 1) * 100
