"""出来高・売買代金系指標。"""

from __future__ import annotations

import pandas as pd

from lib.indicators.registry import register


@register("volume", "週間出来高", kind="panel")
def volume(weekly: pd.DataFrame) -> pd.Series:
    return weekly["Volume"]


@register("turnover", "週間売買代金", kind="panel", unit="円")
def turnover(weekly: pd.DataFrame) -> pd.Series:
    return weekly["Turnover"]


@register("volume_ratio_26w", "出来高の26週平均比", kind="feature", unit="倍")
def volume_ratio_26w(weekly: pd.DataFrame) -> pd.Series:
    avg = weekly["Volume"].rolling(window=26, min_periods=1).mean()
    return weekly["Volume"] / avg
