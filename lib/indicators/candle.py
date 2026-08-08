"""週足ローソク足の形状に関する指標。実体率・ヒゲ比率・週間騰落率。"""

from __future__ import annotations

import pandas as pd

from lib.indicators.registry import register


def _range(weekly: pd.DataFrame) -> pd.Series:
    r = weekly["High"] - weekly["Low"]
    return r.replace(0, pd.NA)


@register("weekly_return_pct", "週間騰落率", kind="feature", unit="%")
def weekly_return_pct(weekly: pd.DataFrame) -> pd.Series:
    return (weekly["Close"] / weekly["Open"] - 1) * 100


@register("body_ratio_pct", "実体率(値幅に対する実体の割合)", kind="feature", unit="%")
def body_ratio_pct(weekly: pd.DataFrame) -> pd.Series:
    body = (weekly["Close"] - weekly["Open"]).abs()
    return (body / _range(weekly)) * 100


@register("upper_wick_ratio_pct", "上ヒゲ比率", kind="feature", unit="%")
def upper_wick_ratio_pct(weekly: pd.DataFrame) -> pd.Series:
    upper_wick = weekly["High"] - weekly[["Open", "Close"]].max(axis=1)
    return (upper_wick / _range(weekly)) * 100


@register("lower_wick_ratio_pct", "下ヒゲ比率", kind="feature", unit="%")
def lower_wick_ratio_pct(weekly: pd.DataFrame) -> pd.Series:
    lower_wick = weekly[["Open", "Close"]].min(axis=1) - weekly["Low"]
    return (lower_wick / _range(weekly)) * 100
