"""② エントリー週記録

「この銘柄のこの週なら買いたい」を記録する。登録すると同時に、
その週時点で取得可能だった情報だけを使って特徴量を自動計算する(③Feature Extractor)。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from lib import db, features  # noqa: E402

st.set_page_config(page_title="Entry | Market Leader Engine", page_icon="✏️", layout="wide")
db.init_db()

st.title("✏️ エントリー週記録")
st.caption(
    "「ここなら買いたい」と思った週のローソク足を見て記録すると、その週時点の特徴量が自動計算されます。"
    "実際の売買は翌週の寄付になるため、記録される「エントリー週」は選んだ週の翌週です。"
)

stocks = db.list_stocks()
if stocks.empty:
    st.info("まだ銘柄が登録されていません。「Watchlist」画面から登録してください。")
    st.stop()

label_to_code = {f"{r['code']} {r['name']}": r["code"] for _, r in stocks.iterrows()}
selected_label = st.selectbox("銘柄", list(label_to_code.keys()))
code = label_to_code[selected_label]

try:
    weekly = features.load_weekly(code)
except features.FeatureExtractionError as e:
    st.error(str(e))
    st.stop()

week_options = [d.strftime("%Y-%m-%d") for d in weekly.index[::-1]]  # 新しい週が上に来るように

with st.form("add_entry_form"):
    decision_week = st.selectbox("判断に使った週(このローソク足を見てエントリーを決めた週)", week_options)
    comment = st.text_area("コメント(なぜこの週に買いたいと思ったか)", placeholder="例: EMA16を上から下に割らずに反発、出来高も増加")
    submitted = st.form_submit_button("登録して特徴量を計算", type="primary")

if submitted:
    decision_pos = weekly.index.get_indexer([pd.Timestamp(decision_week)])[0]
    if decision_pos + 1 >= len(weekly.index):
        st.error(f"{decision_week}の翌週のデータがまだないため、実際の約定週を記録できません。")
    else:
        actual_entry_week = weekly.index[decision_pos + 1].strftime("%Y-%m-%d")
        entry_id = db.add_entry(code, actual_entry_week, comment=comment)
        feats, _ = features.extract_features_for_entry(code, decision_week)
        db.save_entry_features(entry_id, feats)
        st.success(
            f"判断週{decision_week} → 翌週{actual_entry_week}の寄付でのエントリーとして記録し、"
            f"{len(feats)}個の特徴量を計算しました。"
        )

st.divider()
st.subheader(f"{selected_label} のエントリー記録")

entries = db.list_entries(stock_code=code)
if entries.empty:
    st.caption("まだ記録がありません。")
else:
    for _, row in entries.iterrows():
        exit_events_df = db.get_exit_events(row["id"])
        total_pct = db.total_exit_percentage(row["id"])
        exit_records = (
            exit_events_df[["exit_week", "exit_percentage"]].to_dict("records")
            if not exit_events_df.empty
            else []
        )
        trade_return = features.compute_trade_return_multi(code, row["entry_week"], exit_records)

        if exit_records:
            legs_text = " / ".join(f"{r['exit_week']}({r['exit_percentage']:.0f}%)" for r in exit_records)
            exit_label = f" → {legs_text}"
        else:
            exit_label = ""
        return_label = f"  【加重平均{trade_return['weighted_return_pct']:+.1f}%】" if trade_return else ""

        with st.expander(f"{row['entry_week']}{exit_label}{return_label} — {row['comment'] or '(コメントなし)'}"):
            if trade_return:
                st.metric("加重平均騰落率", f"{trade_return['weighted_return_pct']:+.1f}%")

            # ---- イグジット記録(部分イグジット対応) ----
            st.markdown(f"**イグジット記録**(累計 {total_pct:.0f}%)")
            if not exit_events_df.empty:
                for _, ev in exit_events_df.iterrows():
                    ev_col1, ev_col2 = st.columns([4, 1])
                    ev_col1.write(f"{ev['exit_week']} — {ev['exit_percentage']:.0f}%")
                    if ev["comment"]:
                        ev_col1.caption(f"理由: {ev['comment']}")
                    if ev_col2.button("削除", key=f"del_exit_{ev['id']}"):
                        db.delete_exit_event(ev["id"])
                        st.rerun()

            remaining_pct = round(100 - total_pct, 4)
            exit_week_options = [w for w in week_options if w > row["entry_week"]]
            if remaining_pct > 0 and exit_week_options:
                with st.form(f"add_exit_{row['id']}"):
                    new_exit_week = st.selectbox(
                        "イグジット週", exit_week_options, key=f"new_exit_week_{row['id']}"
                    )
                    new_exit_pct = st.number_input(
                        f"イグジット割合(残り{remaining_pct:.0f}%まで)",
                        min_value=1.0,
                        max_value=float(remaining_pct),
                        value=float(min(50.0, remaining_pct)),
                        step=1.0,
                        key=f"new_exit_pct_{row['id']}",
                    )
                    new_exit_comment = st.text_area(
                        "なぜここでイグジットする判断をしたか",
                        placeholder="例: RSIが70を超えて過熱、上ヒゲが目立ってきた",
                        key=f"new_exit_comment_{row['id']}",
                    )
                    add_exit_clicked = st.form_submit_button("イグジットを追加")
                if add_exit_clicked:
                    db.add_exit_event(row["id"], new_exit_week, new_exit_pct, comment=new_exit_comment)
                    st.rerun()

            st.divider()

            # ---- エントリー週・コメント編集 ----
            with st.form(f"edit_entry_{row['id']}"):
                st.caption("エントリー週=実際に約定した(翌週寄付の)週。特徴量はその前週の情報で再計算されます。")
                new_entry_week = st.selectbox(
                    "エントリー週(約定週)",
                    week_options,
                    index=week_options.index(row["entry_week"]) if row["entry_week"] in week_options else 0,
                    key=f"edit_entry_week_{row['id']}",
                )
                new_comment = st.text_area(
                    "コメント", value=row["comment"] or "", key=f"edit_comment_{row['id']}"
                )
                col_save, col_delete = st.columns(2)
                save_clicked = col_save.form_submit_button("この内容で更新", type="primary")
                delete_clicked = col_delete.form_submit_button("この記録を削除")

            if save_clicked:
                try:
                    db.update_entry(row["id"], new_entry_week, new_comment)
                    if new_entry_week != row["entry_week"]:
                        # 約定週(new_entry_week)の前週=判断週の情報で特徴量を計算し直す
                        entry_pos = weekly.index.get_indexer([pd.Timestamp(new_entry_week)])[0]
                        decision_week_for_calc = (
                            weekly.index[entry_pos - 1].strftime("%Y-%m-%d")
                            if entry_pos > 0
                            else new_entry_week
                        )
                        feats, _ = features.extract_features_for_entry(code, decision_week_for_calc)
                        db.save_entry_features(row["id"], feats)
                    st.success("更新しました。")
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(f"更新に失敗しました: {e}")

            if delete_clicked:
                db.delete_entry(row["id"])
                st.rerun()

            feat_df = db.get_entry_features(row["id"])
            if feat_df.empty:
                st.caption("特徴量が計算されていません。")
            else:
                st.dataframe(
                    feat_df[["feature_label", "feature_value", "feature_unit"]].rename(
                        columns={"feature_label": "指標", "feature_value": "値", "feature_unit": "単位"}
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
