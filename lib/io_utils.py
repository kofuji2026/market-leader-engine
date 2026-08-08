"""⑦ CSV保存"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def save_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, encoding="utf-8-sig")
