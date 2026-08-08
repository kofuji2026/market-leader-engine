"""急騰区間の自動検出。

週足の値動きから「谷(安値)からX倍以上になった山(高値)」の区間を機械的に見つける。
ここでの目的は「買いシグナル」を作ることではなく、「主役だった期間」を素早く洗い出して、
そこにどのタイミングで入れたかを人が見て判断する材料を用意すること
(開発方針: いきなり売買ルールを作らず、まず人が仮説を作れる土台を用意する)。
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class SurgePeriod:
    trough_date: pd.Timestamp  # 谷(安値)の週
    peak_date: pd.Timestamp  # 山(高値)の週
    trough_price: float
    peak_price: float
    multiple: float  # peak_price / trough_price


def _find_troughs(close: pd.Series, window: int) -> list[int]:
    """前後window週の中で最小値になっている週(=谷)のindex位置一覧を返す。"""
    troughs = []
    n = len(close)
    for i in range(n):
        lo = max(0, i - window)
        hi = min(n, i + window + 1)
        if close.iloc[i] == close.iloc[lo:hi].min():
            troughs.append(i)
    return troughs


def detect_surge_periods(
    weekly: pd.DataFrame,
    min_multiple: float = 2.0,
    trough_window: int = 13,
    max_horizon: int = 156,
    overlap_threshold: float = 0.6,
) -> list[SurgePeriod]:
    """週足DataFrame(Close列必須)から「min_multiple倍以上になった区間」を検出する。

    Args:
        min_multiple: これ以上の倍率になった区間だけを対象にする(2.0なら2倍以上)
        trough_window: 谷判定に使う前後の週数
        max_horizon: 谷から何週先まで高値を探すか(156週=3年)
        overlap_threshold: 区間同士がこの割合以上重なったら、倍率が低い方を除外する
    """
    close = weekly["Close"]
    n = len(close)
    if n < 4:
        return []

    troughs = _find_troughs(close, trough_window)

    candidates: list[SurgePeriod] = []
    for i in troughs:
        low = close.iloc[i]
        if low <= 0:
            continue
        hi_idx_end = min(n, i + max_horizon + 1)
        window = close.iloc[i:hi_idx_end]
        peak_pos_in_window = window.values.argmax()
        j = i + peak_pos_in_window
        high = close.iloc[j]
        multiple = high / low
        if multiple >= min_multiple and j > i:
            candidates.append(
                SurgePeriod(
                    trough_date=close.index[i],
                    peak_date=close.index[j],
                    trough_price=float(low),
                    peak_price=float(high),
                    multiple=float(multiple),
                )
            )

    # 倍率が大きい順に見て、既採用区間と大きく重なるものは除外する
    candidates.sort(key=lambda p: p.multiple, reverse=True)
    accepted: list[SurgePeriod] = []
    for cand in candidates:
        overlaps = False
        for acc in accepted:
            latest_start = max(cand.trough_date, acc.trough_date)
            earliest_end = min(cand.peak_date, acc.peak_date)
            overlap_len = (earliest_end - latest_start).days
            if overlap_len <= 0:
                continue
            cand_len = (cand.peak_date - cand.trough_date).days or 1
            acc_len = (acc.peak_date - acc.trough_date).days or 1
            if overlap_len / min(cand_len, acc_len) >= overlap_threshold:
                overlaps = True
                break
        if not overlaps:
            accepted.append(cand)

    accepted.sort(key=lambda p: p.trough_date)
    return accepted


def random_period(
    weekly: pd.DataFrame, before_weeks: int, after_weeks: int, rng: random.Random
) -> SurgePeriod | None:
    """急騰したかどうかを問わず、ランダムな週を1つ選んで疑似的な区間を作る。

    detect_surge_periodsは「min_multiple倍以上になった」区間しか返さないため、
    急騰しなかった(≒ダマシだった)ケースを検証に混ぜたい場合はこちらを使う。
    選んだ週を仮の「谷」、そこからafter_weeks進んだ週を仮の「山」として扱うが、
    実際には下落しているケースも当然含まれる(multipleが1.0未満になることもある)。
    """
    n = len(weekly)
    lo = before_weeks
    hi = n - after_weeks - 1
    if hi <= lo:
        return None
    trough_pos = rng.randint(lo, hi)
    peak_pos = min(trough_pos + after_weeks, n - 1)
    trough_price = float(weekly["Close"].iloc[trough_pos])
    peak_price = float(weekly["Close"].iloc[peak_pos])
    if trough_price <= 0:
        return None
    return SurgePeriod(
        trough_date=weekly.index[trough_pos],
        peak_date=weekly.index[peak_pos],
        trough_price=trough_price,
        peak_price=peak_price,
        multiple=peak_price / trough_price,
    )


def surge_period_view(
    weekly: pd.DataFrame, period: SurgePeriod, before_weeks: int = 60, after_weeks: int = 10
) -> pd.DataFrame:
    """区間の前後を含めて週足を切り出す。

    before_weeks: 谷(急騰前)より前に含める週数。急騰前の下地・仕込み期間を見るため
                  デフォルトを長め(60週)に取っている。
    after_weeks: 山(急騰後)より後に含める週数。
    """
    idx = weekly.index
    trough_pos = idx.get_indexer([period.trough_date])[0]
    peak_pos = idx.get_indexer([period.peak_date])[0]
    start = max(0, trough_pos - before_weeks)
    end = min(len(idx), peak_pos + after_weeks + 1)
    return weekly.iloc[start:end]
