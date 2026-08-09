"""急騰区間の自動検出。

週足の値動きから「谷(安値)からX倍以上になった山(高値)」の区間を機械的に見つける。
ここでの目的は「買いシグナル」を作ることではなく、「主役だった期間」を素早く洗い出して、
そこにどのタイミングで入れたかを人が見て判断する材料を用意すること
(開発方針: いきなり売買ルールを作らず、まず人が仮説を作れる土台を用意する)。
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import numpy as np
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


def _early_shape(close: pd.Series, start_pos: int, window: int) -> np.ndarray | None:
    """start_posからwindow週分のCloseを、開始値=1.0になるよう正規化した配列を返す。

    「初動の形」を比較するための材料。残り週数が足りない場合はNoneを返す。
    """
    end = start_pos + window
    if end > len(close):
        return None
    base = close.iloc[start_pos]
    if base <= 0:
        return None
    return (close.iloc[start_pos:end] / base).to_numpy()


def find_lookalike_failures(
    weekly_by_code: dict[str, pd.DataFrame],
    name_theme_by_code: dict[str, tuple[str, str | None]],
    surge_rows: list[dict],
    window: int = 8,
    max_horizon: int = 156,
    trough_window: int = 13,
    failure_multiple: float = 1.3,
    max_distance: float = 0.12,
    top_k: int = 3,
) -> list[dict]:
    """「大相場になった区間(A=surge_rows)」それぞれについて、初動(谷からwindow週分の
    値動きの形)は似ているのに、結局failure_multiple倍にもならなかった区間(B=いわゆる
    「だまし」)を他銘柄・他期間から探して返す。

    生存者バイアス対策の一環: Aだけを見ていると「この形になれば大相場になる」と
    誤学習しやすいため、初動そっくりでも不発だった実例をセットで見せる。

    Args:
        weekly_by_code: {証券コード: 週足DataFrame}。探索対象になる全銘柄分を渡す
            (Aに含まれる銘柄だけでなく、登録銘柄全体が望ましい)。
        name_theme_by_code: {証券コード: (銘柄名, テーマ)}。表示用。
        surge_rows: [{"code","name","theme","period": SurgePeriod}, ...] (Group A)
        window: 初動として比較する週数。
        failure_multiple: これ未満の倍率にしかならなかった区間を「不発」とみなす。
        max_distance: 初動の形の距離(正規化終値のRMS差)がこれ以下なら「似ている」とみなす。
        top_k: 1つのA区間につき、似ている不発区間を最大何件まで採用するか。

    Returns:
        surge_rowsと同じ形式のリスト(Group B)。同じ(code, trough_date)の重複は除去済み。
    """
    # 1. 候補プール: 全銘柄の全「谷」のうち、結局failure_multiple倍未満で終わったもの
    candidates: list[tuple[str, np.ndarray, SurgePeriod]] = []
    for code, weekly in weekly_by_code.items():
        close = weekly["Close"]
        n = len(close)
        if n < 4:
            continue
        for i in _find_troughs(close, trough_window):
            low = close.iloc[i]
            if low <= 0:
                continue
            shape = _early_shape(close, i, window)
            if shape is None:
                continue
            hi_end = min(n, i + max_horizon + 1)
            seg = close.iloc[i:hi_end]
            j = i + int(seg.values.argmax())
            high = close.iloc[j]
            multiple = high / low
            if multiple >= failure_multiple or j <= i:
                continue
            candidates.append(
                (
                    code,
                    shape,
                    SurgePeriod(
                        trough_date=close.index[i],
                        peak_date=close.index[j],
                        trough_price=float(low),
                        peak_price=float(high),
                        multiple=float(multiple),
                    ),
                )
            )

    if not candidates:
        return []

    seen: set[tuple[str, pd.Timestamp]] = set()
    results: list[dict] = []

    for row in surge_rows:
        code, period = row["code"], row["period"]
        weekly = weekly_by_code.get(code)
        if weekly is None:
            continue
        close = weekly["Close"]
        pos = close.index.get_indexer([period.trough_date])
        if len(pos) == 0 or pos[0] == -1:
            continue
        a_shape = _early_shape(close, pos[0], window)
        if a_shape is None:
            continue

        scored = []
        for cand_code, cand_shape, cand_period in candidates:
            if cand_code == code:
                continue  # 同一銘柄は除外(同じ相場の一部を別の失敗例と誤認しないため)
            dist = float(np.sqrt(np.mean((a_shape - cand_shape) ** 2)))
            if dist <= max_distance:
                scored.append((dist, cand_code, cand_period))
        scored.sort(key=lambda t: t[0])

        for _dist, cand_code, cand_period in scored[:top_k]:
            key = (cand_code, cand_period.trough_date)
            if key in seen:
                continue
            seen.add(key)
            name, theme = name_theme_by_code.get(cand_code, (cand_code, None))
            results.append({"code": cand_code, "name": name, "theme": theme, "period": cand_period})

    return results


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
