"""③ Chart Viewer(最重要画面)

登録銘柄の週足チャート+指標をON/OFF切り替えながら眺める。
指標は lib/indicators/ のレジストリから動的に読み込むため、指標ファイルを1つ追加するだけで
ここにも自動でチェックボックスが増える。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402
from plotly.subplots import make_subplots  # noqa: E402

import lib.indicators  # noqa: E402, F401 — 指標登録のため
from lib import db, features  # noqa: E402
from lib.indicators import registry  # noqa: E402

st.set_page_config(page_title="Chart | Market Leader Engine", page_icon="📊", layout="wide")
db.init_db()

st.title("📊 Chart Viewer")

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

computed = registry.compute_all(weekly)

all_indicators = registry.all_indicators()
line_indicators = {k: v for k, v in all_indicators.items() if v.kind == "line"}
panel_indicators = {k: v for k, v in all_indicators.items() if v.kind == "panel"}

st.sidebar.subheader("指標のON/OFF")
st.sidebar.caption("価格チャートに重ねる指標")
selected_lines = [
    k for k, v in line_indicators.items() if st.sidebar.checkbox(v.label, value=(k == "ema16"), key=f"line_{k}")
]
st.sidebar.caption("別パネルに表示する指標")
selected_panels = [
    k for k, v in panel_indicators.items() if st.sidebar.checkbox(v.label, value=(k == "volume"), key=f"panel_{k}")
]

n_rows = 1 + len(selected_panels)
row_heights = [0.55] + [0.45 / max(len(selected_panels), 1)] * len(selected_panels)
fig = make_subplots(
    rows=n_rows,
    cols=1,
    shared_xaxes=True,
    vertical_spacing=0.03,
    row_heights=row_heights,
)

fig.add_trace(
    go.Candlestick(
        x=computed.index,
        open=computed["Open"],
        high=computed["High"],
        low=computed["Low"],
        close=computed["Close"],
        name=code,
        increasing_line_color="#d64550",
        decreasing_line_color="#2f6690",
    ),
    row=1,
    col=1,
)

for key in selected_lines:
    ind = all_indicators[key]
    fig.add_trace(
        go.Scatter(x=computed.index, y=computed[key], name=ind.label, mode="lines", line=dict(width=1.5)),
        row=1,
        col=1,
    )

# 登録済みエントリー週をマーカー表示
entries = db.list_entries(stock_code=code)
if not entries.empty:
    import pandas as pd  # noqa: E402

    entry_dates = pd.to_datetime(entries["entry_week"])
    entry_closes = computed["Close"].reindex(entry_dates, method="nearest")
    fig.add_trace(
        go.Scatter(
            x=entry_dates,
            y=entry_closes * 1.03,
            mode="markers",
            marker=dict(symbol="triangle-down", size=12, color="#e0a13a"),
            name="エントリー記録",
            hovertext=entries["comment"].fillna(""),
        ),
        row=1,
        col=1,
    )

for i, key in enumerate(selected_panels, start=2):
    ind = all_indicators[key]
    fig.add_trace(
        go.Bar(x=computed.index, y=computed[key], name=ind.label) if key in ("volume", "turnover")
        else go.Scatter(x=computed.index, y=computed[key], name=ind.label, mode="lines"),
        row=i,
        col=1,
    )
    fig.update_yaxes(title_text=ind.label, row=i, col=1)

# 週足を604件など全期間分そのまま表示するとローソクが潰れて線に見えてしまうため、
# 初期表示は直近1年(52週)程度に絞る。rangesliderから全期間にもアクセスできる。
default_weeks = 52
if len(computed.index) > default_weeks:
    default_start = computed.index[-default_weeks]
else:
    default_start = computed.index[0]
default_end = computed.index[-1]

fig.update_layout(
    height=550 + 180 * len(selected_panels),
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
    margin=dict(t=40, b=20, l=10, r=10),
)
fig.update_xaxes(
    range=[default_start, default_end],
    autorange=False,
    rangeslider_visible=True,
    rangeslider_thickness=0.06,
    row=1,
    col=1,
)
for i in range(2, n_rows + 1):
    fig.update_xaxes(rangeslider_visible=False, row=i, col=1)

# 価格パネルは対数軸で表示する(2倍・3倍といった「倍率」の変化を直感的に比較しやすいため)
fig.update_yaxes(type="log", row=1, col=1)

st.plotly_chart(fig, use_container_width=True)

with st.expander("この銘柄のエントリー記録"):
    if entries.empty:
        st.caption("まだこの銘柄のエントリー記録はありません。「Entry」画面から登録できます。")
    else:
        st.dataframe(entries[["entry_week", "comment"]], use_container_width=True, hide_index=True)
