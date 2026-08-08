"""トレンド系指標: EMA(指数移動平均)。"""

from __future__ import annotations

import pandas as pd

from lib.indicators.registry import register


@register("ema16", "EMA16", kind="line")
def ema16(weekly: pd.DataFrame) -> pd.Series:
    return weekly["Close"].ewm(span=16, adjust=False).mean()


@register("ema25", "EMA25", kind="line")
def ema25(weekly: pd.DataFrame) -> pd.Series:
    return weekly["Close"].ewm(span=25, adjust=False).mean()


@register("close_vs_ema16_pct", "終値のEMA16乖離率", kind="feature", unit="%")
def close_vs_ema16_pct(weekly: pd.DataFrame) -> pd.Series:
    ema = weekly["Close"].ewm(span=16, adjust=False).mean()
    return (weekly["Close"] / ema - 1) * 100
