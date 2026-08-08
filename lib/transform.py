"""② 週足変換

日足DataFrameから、週足OHLCV+週間売買代金のDataFrameを作る。
テクニカル指標(EMA16・52週高値等)はここでは計算しない。
指標は lib/indicators/ のプラグインとして分離し、Chart ViewerとFeature Extractorの
両方から共通のレジストリ(lib/indicators/registry.py)経由で計算する。
"""

from __future__ import annotations

import pandas as pd

WEEKLY_RULE = "W-FRI"  # 週足の締めを金曜日とする


def build_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """日足から週足OHLCVのDataFrameを作る。

    列: Open, High, Low, Close, Volume(週間出来高), Turnover(週間売買代金)
    """
    # 週売買代金は日足の Close×Volume を週単位で合計する(週足化する前に計算)
    daily = daily.copy()
    daily["Turnover"] = daily["Close"] * daily["Volume"]

    # 週足へ変換(週足出来高は Volume の週内合計)
    weekly = daily.resample(WEEKLY_RULE).agg(
        {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
            "Turnover": "sum",
        }
    )
    weekly = weekly.dropna(subset=["Open", "High", "Low", "Close"])
    # resampleのインデックスは週の終わり(金曜)になるため、週の始まり(月曜)のラベルに付け替える。
    # 集計対象の期間(月〜金)自体は変わらない。
    weekly.index = weekly.index - pd.Timedelta(days=4)
    weekly.index.name = "Date"
    return weekly
