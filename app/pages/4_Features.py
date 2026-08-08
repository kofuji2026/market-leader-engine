"""③ 特徴量一覧・比較

記録した全エントリーの特徴量を横並びで比較する。仮説検証の起点になる画面。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from lib import db, features  # noqa: E402

st.set_page_config(page_title="Features | Market Leader Engine", page_icon="🔬", layout="wide")
db.init_db()

st.title("🔬 特徴量一覧・比較")
st.caption("記録した全エントリーの特徴量を横並びで比較する。")

wide = db.get_all_entry_features_wide()

if wide.empty:
    st.info("まだエントリー記録がありません。「Entry」画面から登録してください。")
    st.stop()

all_exit_events = db.get_all_exit_events()


def _weighted_return(row):
    if all_exit_events.empty:
        events = []
    else:
        events = all_exit_events[all_exit_events["entry_id"] == row["entry_id"]][
            ["exit_week", "exit_percentage"]
        ].to_dict("records")
    result = features.compute_trade_return_multi(row["stock_code"], row["entry_week"], events)
    return result["weighted_return_pct"] if result else None


wide["return_pct"] = wide.apply(_weighted_return, axis=1)

meta_cols = ["stock_code", "stock_name", "entry_week", "return_pct", "comment"]
feature_cols = [c for c in wide.columns if c not in meta_cols + ["entry_id"]]

st.write(f"エントリー記録: {len(wide)}件 / 特徴量: {len(feature_cols)}種類")

display_cols = st.multiselect("表示する特徴量", feature_cols, default=feature_cols[: min(8, len(feature_cols))])

table = wide[meta_cols + display_cols].sort_values("entry_week", ascending=False)

if display_cols:
    styled = table.style.background_gradient(subset=display_cols, cmap="RdYlGn", axis=0)
    st.dataframe(styled, use_container_width=True, hide_index=True)
else:
    st.dataframe(table, use_container_width=True, hide_index=True)

st.download_button(
    "CSVダウンロード",
    table.to_csv(index=False).encode("utf-8-sig"),
    file_name="entry_features.csv",
    mime="text/csv",
)
