"""指標レジストリ。

@register(...) で登録された指標を一元管理する。Chart Viewer・Feature Extractorは
このレジストリを見るだけで、個別の指標の存在を知らなくてよい(プラグイン構造)。
"""

from __future__ import annotations

import pandas as pd

from lib.indicators.base import Indicator

_REGISTRY: dict[str, Indicator] = {}


def register(key: str, label: str, kind: str = "line", unit: str = ""):
    """指標を登録するデコレータ。

    使い方:
        @register("ema16", "EMA16", kind="line")
        def compute(weekly: pd.DataFrame) -> pd.Series:
            return weekly["Close"].ewm(span=16, adjust=False).mean()
    """

    def decorator(func):
        _REGISTRY[key] = Indicator(key=key, label=label, func=func, kind=kind, unit=unit)
        return func

    return decorator


def all_indicators() -> dict[str, Indicator]:
    return dict(_REGISTRY)


def get(key: str) -> Indicator:
    return _REGISTRY[key]


def compute_all(weekly: pd.DataFrame) -> pd.DataFrame:
    """登録済み全指標を計算し、weeklyに列を追加したDataFrameを返す。"""
    out = weekly.copy()
    for indicator in _REGISTRY.values():
        try:
            out[indicator.key] = indicator.func(weekly)
        except Exception:  # noqa: BLE001 — 1指標の失敗で全体を止めない
            out[indicator.key] = pd.NA
    return out
