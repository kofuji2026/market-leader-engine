"""① 銘柄登録(Watchlist / Market Leader候補DB)

証券コード・銘柄名・テーマを登録する。100銘柄まで想定。
登録すると同時に日足→週足データを取得してCSVに保存する(Chart/Entry画面で使うため)。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from lib import db  # noqa: E402
from lib.fetch import fetch_daily  # noqa: E402
from lib.io_utils import save_csv  # noqa: E402
from lib.transform import build_weekly  # noqa: E402

RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"

st.set_page_config(page_title="Watchlist | Market Leader Engine", page_icon="📋", layout="wide")
db.init_db()

st.title("📋 Watchlist(銘柄登録)")
st.caption("監視したい銘柄を証券コードで登録する。登録と同時に週足データを取得する。")


def fetch_and_save(code: str) -> tuple[bool, str]:
    try:
        daily = fetch_daily(code)
        save_csv(daily, RAW_DIR / f"{code}_daily.csv")
        weekly = build_weekly(daily)
        save_csv(weekly, PROCESSED_DIR / f"{code}_weekly.csv")
        return True, f"週足{len(weekly)}件を取得しました({weekly.index.min().date()}〜{weekly.index.max().date()})"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


tab_add, tab_import, tab_list = st.tabs(["個別追加", "CSV一括登録", "登録済み一覧"])

with tab_add:
    with st.form("add_stock_form"):
        c1, c2, c3 = st.columns([1, 2, 2])
        code = c1.text_input("証券コード", placeholder="例: 6920")
        name = c2.text_input("銘柄名", placeholder="例: レーザーテック")
        theme = c3.text_input("テーマ(任意)", placeholder="例: 半導体検査装置")
        submitted = st.form_submit_button("登録してデータ取得", type="primary")

    if submitted:
        if not code or not name:
            st.error("証券コードと銘柄名は必須です。")
        else:
            with st.spinner(f"{code} {name} のデータを取得中…"):
                ok, msg = fetch_and_save(code)
            if ok:
                db.add_stock(code, name, theme=theme or None)
                st.success(f"{code} {name} を登録しました。{msg}")
                st.rerun()
            else:
                st.error(f"データ取得に失敗しました: {msg}")

with tab_import:
    st.markdown("`code,name,theme` の列を持つCSVをアップロードすると、一括で登録・データ取得します。")
    uploaded = st.file_uploader("CSVファイル", type="csv")
    if uploaded is not None:
        df = pd.read_csv(uploaded, dtype={"code": str})
        st.dataframe(df, use_container_width=True)
        if st.button("この内容で一括登録", type="primary"):
            progress = st.progress(0, text="登録中…")
            results = []
            for i, row in df.iterrows():
                code, name = str(row["code"]), row["name"]
                theme = row.get("theme")
                ok, msg = fetch_and_save(code)
                if ok:
                    db.add_stock(code, name, theme=theme if pd.notna(theme) else None)
                results.append({"code": code, "name": name, "ok": ok, "msg": msg})
                progress.progress((i + 1) / len(df), text=f"{code} {name} 処理中…")
            progress.empty()
            n_ok = sum(r["ok"] for r in results)
            st.success(f"{n_ok}/{len(results)} 件を登録しました。")
            st.dataframe(pd.DataFrame(results), use_container_width=True)
            st.rerun()

with tab_list:
    stocks = db.list_stocks()
    if stocks.empty:
        st.info("まだ銘柄が登録されていません。")
    else:
        st.write(f"登録済み: {len(stocks)}件")
        for _, row in stocks.iterrows():
            has_data = (PROCESSED_DIR / f"{row['code']}_weekly.csv").exists()
            c1, c2, c3, c4, c5 = st.columns([1, 2, 2, 1, 1])
            c1.write(f"**{row['code']}**")
            c2.write(row["name"])
            c3.write(row["theme"] or "—")
            c4.write("✅データ有" if has_data else "⚠️未取得")
            if c5.button("削除", key=f"del_{row['code']}"):
                db.delete_stock(row["code"])
                st.rerun()
