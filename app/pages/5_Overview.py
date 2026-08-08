"""複数銘柄一覧(Overview)

登録銘柄の週足チャートをグリッド状に並べて一覧する。「大相場を作った銘柄群」を
まとめて眺めながら、個別に深掘りする価値があるか(=Chart/Entry画面で追う価値があるか)を
素早く判断するための画面。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from lib import db, features  # noqa: E402

st.set_page_config(page_title="Overview | Market Leader Engine", page_icon="🗂️", layout="wide")
db.init_db()

st.title("🗂️ Overview(複数銘柄一覧)")
st.caption("登録銘柄の週足チャートを並べて眺め、研究対象として深掘りする価値があるか判断する。")

stocks = db.list_stocks()
if stocks.empty:
    st.info("まだ銘柄が登録されていません。「Watchlist」画面から登録してください。")
    st.stop()


@st.cache_data(show_spinner=False)
def _load_weekly_cached(code: str):
    try:
        return features.load_weekly(code)
    except features.FeatureExtractionError:
        return None


period_options = {"直近1年": 52, "直近2年": 104, "直近3年": 156, "全期間": None}
col_a, col_b, col_c = st.columns([2, 2, 3])
period_label = col_a.selectbox("表示期間", list(period_options.keys()), index=1)
n_cols = col_b.selectbox("列数", [2, 3, 4], index=1)
theme_filter = col_c.text_input("テーマで絞り込み(部分一致、空欄で全件)", placeholder="例: 半導体")

filtered = stocks
if theme_filter:
    filtered = stocks[stocks["theme"].fillna("").str.contains(theme_filter, case=False)]

st.write(f"{len(filtered)}銘柄を表示中(登録済み{len(stocks)}銘柄中)")

weeks = period_options[period_label]
cols = st.columns(n_cols)

for i, (_, row) in enumerate(filtered.iterrows()):
    code, name, theme = row["code"], row["name"], row["theme"]
    weekly = _load_weekly_cached(code)
    with cols[i % n_cols]:
        if weekly is None or weekly.empty:
            st.warning(f"**{code} {name}**\n\n週足データ未取得")
            continue

        view = weekly if weeks is None else weekly.tail(weeks)
        first_close = view["Close"].iloc[0]
        last_close = view["Close"].iloc[-1]
        change_pct = (last_close / first_close - 1) * 100

        fig = go.Figure(
            go.Candlestick(
                x=view.index,
                open=view["Open"],
                high=view["High"],
                low=view["Low"],
                close=view["Close"],
                increasing_line_color="#d64550",
                decreasing_line_color="#2f6690",
                showlegend=False,
            )
        )
        fig.update_layout(
            height=220,
            margin=dict(t=8, b=8, l=8, r=8),
            xaxis_rangeslider_visible=False,
            xaxis_visible=False,
            yaxis_visible=False,
        )
        fig.update_yaxes(type="log")

        arrow = "▲" if change_pct >= 0 else "▼"
        color = "#d64550" if change_pct >= 0 else "#2f6690"
        st.markdown(
            f"**{code} {name}**  \n"
            f"<span style='color:#888;font-size:0.85em'>{theme or ''}</span>  \n"
            f"<span style='color:{color};font-weight:600'>{arrow} {change_pct:+.1f}%</span>"
            f"<span style='color:#888;font-size:0.85em'>({period_label})</span>",
            unsafe_allow_html=True,
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False}, key=f"chart_{code}")
