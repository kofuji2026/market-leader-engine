"""③ Feature Extractor

Entry登録された週について、その週時点で取得可能だった情報だけを使って特徴量抽出する。

ルックアヘッドバイアス防止の核心:
    entry_week「より後」の行は、指標を計算する前に物理的に取り除く。
    rolling/ewmなど指標側の実装はすべて過去方向のウィンドウしか見ないため、
    これでentry_week時点で本当に知り得た値だけを使った計算になる。
    (indicators側の実装だけに頼らず、ここでもデータを削ることで二重に安全側に倒している)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import lib.indicators  # noqa: F401 — importするだけで各指標が登録される
from lib.indicators import registry

ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"


class FeatureExtractionError(Exception):
    pass


def load_weekly(code: str) -> pd.DataFrame:
    path = PROCESSED_DIR / f"{code}_weekly.csv"
    if not path.exists():
        raise FeatureExtractionError(
            f"{code}: 週足データが見つかりません({path.name})。先にデータ取得を実行してください。"
        )
    df = pd.read_csv(path, index_col="Date", parse_dates=True)
    return df


def extract_features_for_entry(
    code: str, entry_week: str
) -> tuple[dict[str, tuple[str, float, str]], pd.Timestamp]:
    """entry_week時点で取得可能だった情報だけを使って全指標を計算する。

    Returns:
        (features, actual_week_used)
        features: {feature_key: (表示名, 値, 単位)}
        actual_week_used: 実際に特徴量計算に使った週足の日付
                           (entry_weekが週足の実在日と一致しない場合、直近の既知週になる)
    """
    weekly = load_weekly(code)
    entry_ts = pd.Timestamp(entry_week)

    # ルックアヘッド防止: entry_week以前の行だけに絞ってから指標計算する
    past_only = weekly.loc[weekly.index <= entry_ts]
    if past_only.empty:
        raise FeatureExtractionError(f"{code}: {entry_week}以前の週足データがありません")

    actual_week_used = past_only.index[-1]

    computed = registry.compute_all(past_only)
    last_row = computed.iloc[-1]

    result: dict[str, tuple[str, float, str]] = {}
    for key, indicator in registry.all_indicators().items():
        value = last_row.get(key)
        if pd.isna(value):
            continue
        result[key] = (indicator.label, float(value), indicator.unit)
    return result, actual_week_used


def compute_trade_return(code: str, entry_week: str, exit_week: str | None) -> dict | None:
    """entry_week週の始値(翌週寄付)でエントリーし、exit_week週の始値(翌週寄付)でイグジットした
    場合の騰落率を計算する。exit_weekが未設定、またはどちらかの週が週足データに存在しない場合はNone。
    """
    if not exit_week:
        return None
    weekly = load_weekly(code)
    entry_ts = pd.Timestamp(entry_week)
    exit_ts = pd.Timestamp(exit_week)
    if entry_ts not in weekly.index or exit_ts not in weekly.index:
        return None
    entry_price = float(weekly.loc[entry_ts, "Open"])
    exit_price = float(weekly.loc[exit_ts, "Open"])
    if entry_price <= 0:
        return None
    return {
        "entry_price": entry_price,
        "exit_price": exit_price,
        "return_pct": (exit_price / entry_price - 1) * 100,
    }
