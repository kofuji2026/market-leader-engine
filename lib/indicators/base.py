"""指標プラグインの共通インターフェース。

各指標は「週足OHLCV+αのDataFrame」を受け取り、その指標の値をpd.Seriesで返す
compute(weekly)関数を持つ。rolling/ewmなど「その週までのデータしか見ない」計算のみを
使うことで、ルックアヘッドバイアス(未来の情報を混入させること)を防ぐ。

新しい指標を追加する手順:
  1. lib/indicators/にファイルを1つ追加(例: rsi.py)
  2. @register("表示名") を付けたcompute(weekly)関数を書く
  3. lib/indicators/__init__.pyでそのモジュールをimportする
  → Chart ViewerのON/OFF切り替えにも、Feature Extractorの特徴量一覧にも自動で反映される
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

IndicatorFunc = Callable[[pd.DataFrame], pd.Series]


@dataclass(frozen=True)
class Indicator:
    key: str  # 内部キー(英数字、DB保存・列名に使う)
    label: str  # 画面表示名
    func: IndicatorFunc
    kind: str = "line"  # "line"(価格チャート重ね書き) | "panel"(別パネル) | "feature"(特徴量のみ、チャート非表示)
    unit: str = ""  # 表示用の単位(%, 円 等)
