"""① 日足取得

yfinance経由で、指定した証券コードの日足OHLCVを取得する。
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf

DEFAULT_START = "2015-01-01"


def fetch_daily(code: str, start: str = DEFAULT_START) -> pd.DataFrame:
    """指定コード(4桁)の東証銘柄の日足を取得する。

    Returns: Date インデックス、Open/High/Low/Close/Volume 列のDataFrame。
    分割・併合は yfinance の auto_adjust により調整済み。
    """
    ticker = f"{code}.T"
    df = yf.Ticker(ticker).history(start=start, auto_adjust=True)

    if df.empty:
        raise ValueError(f"{ticker}: データが取得できませんでした(コードや上場状況を確認してください)")

    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.index = df.index.tz_localize(None)
    df.index.name = "Date"
    return df
