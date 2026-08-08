"""オシレーター系指標: RSI・ATR・MACD・ADX。

pandas-ta はこの環境では numba/llvmlite の共有ライブラリ読み込みに失敗して動かなかったため、
標準的な計算式(Wilder方式の平滑化)をpandasだけで自前実装している。週足ベースで計算する。
"""

from __future__ import annotations

import pandas as pd

from lib.indicators.registry import register

RSI_LEN = 10
ATR_LEN = 14
ADX_LEN = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9


def _true_range(weekly: pd.DataFrame) -> pd.Series:
    prev_close = weekly["Close"].shift(1)
    tr = pd.concat(
        [
            weekly["High"] - weekly["Low"],
            (weekly["High"] - prev_close).abs(),
            (weekly["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


@register("rsi10", "RSI(10週)", kind="panel")
def rsi10(weekly: pd.DataFrame) -> pd.Series:
    delta = weekly["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / RSI_LEN, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / RSI_LEN, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


@register("atr14", "ATR(14週)", kind="feature", unit="円")
def atr14(weekly: pd.DataFrame) -> pd.Series:
    tr = _true_range(weekly)
    return tr.ewm(alpha=1 / ATR_LEN, adjust=False).mean()


@register("macd_hist", "MACDヒストグラム(12,26,9)", kind="panel")
def macd_hist(weekly: pd.DataFrame) -> pd.Series:
    ema_fast = weekly["Close"].ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow = weekly["Close"].ewm(span=MACD_SLOW, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal = macd_line.ewm(span=MACD_SIGNAL, adjust=False).mean()
    return macd_line - signal


@register("adx14", "ADX(14週、トレンドの強さ)", kind="feature")
def adx14(weekly: pd.DataFrame) -> pd.Series:
    up_move = weekly["High"].diff()
    down_move = -weekly["Low"].diff()
    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move

    tr = _true_range(weekly)
    atr = tr.ewm(alpha=1 / ADX_LEN, adjust=False).mean()

    plus_di = 100 * (plus_dm.ewm(alpha=1 / ADX_LEN, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / ADX_LEN, adjust=False).mean() / atr)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, pd.NA)
    return dx.ewm(alpha=1 / ADX_LEN, adjust=False).mean()
