"""Market Leader Engine — ホーム

日本株の週足トレード専用の研究基盤。2週間MVPスコープ:
  ① 銘柄登録(Watchlist)
  ② エントリー週記録
  ③ 特徴量取得(Feature Extractor)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from lib import db  # noqa: E402

st.set_page_config(page_title="Market Leader Engine", page_icon="📈", layout="wide")

db.init_db()

st.title("📈 Market Leader Engine")
st.caption("その時々の「市場の主役」だけを買う。週足トレード専用の研究基盤。")

stocks = db.list_stocks()
entries = db.list_entries()

col1, col2, col3 = st.columns(3)
col1.metric("登録銘柄数", f"{len(stocks)}")
col2.metric("エントリー記録数", f"{len(entries)}")
n_featured = 0
if not entries.empty:
    features_wide = db.get_all_entry_features_wide()
    n_featured = int(features_wide.filter(regex="ema16|rsi10").notna().any(axis=1).sum()) if not features_wide.empty else 0
col3.metric("特徴量抽出済み", f"{n_featured}")

st.divider()

st.markdown(
    """
### このMVPでできること
1. **銘柄登録**(サイドバー「Watchlist」) — 監視したい銘柄をコード・テーマ付きで登録する
2. **チャート確認**(サイドバー「Chart」) — 週足ローソク足+EMA16等の指標をON/OFFしながら眺める
3. **エントリー記録**(サイドバー「Entry」) — 「この銘柄のこの週なら買いたい」を記録すると、
   その週時点で取得可能だった情報だけを使って特徴量が自動計算される(ルックアヘッドバイアス防止)
4. **特徴量一覧**(サイドバー「Features」) — 記録した全エントリーの特徴量を横並びで比較する

左のサイドバーから各画面に移動してください。
"""
)

if stocks.empty:
    st.info("まだ銘柄が登録されていません。「Watchlist」画面から登録してください。")
