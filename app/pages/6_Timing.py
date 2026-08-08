"""急騰タイミング分析(Timing)

各銘柄の「谷→2倍/3倍以上になった山」の区間を検出し、まず急騰"前"のチャートだけを見せる。
「次の週へ」を押すと1週ずつ未来が明らかになっていき、実際にその時点で知り得た情報だけを
見ながら「ここでエントリー」「ここでイグジット」を記録できる、週送りシミュレーション画面。
(開発方針: いきなり売買ルールを作らず、まず人の目で仮説を作れる材料を揃える)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import random  # noqa: E402

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402
from plotly.subplots import make_subplots  # noqa: E402

import lib.indicators  # noqa: E402, F401 — 指標登録のため
from lib import db, features  # noqa: E402
from lib.indicators import registry  # noqa: E402
from lib.screener import detect_surge_periods, random_period  # noqa: E402

st.set_page_config(page_title="Timing | Market Leader Engine", page_icon="🎯", layout="wide")
db.init_db()

MIN_TURNOVER = 1_000_000_000  # 週間売買代金がこれ未満の週は、実弾で買えないとみなしエントリー対象外にする

st.title("🎯 Timing(急騰タイミング分析)")
st.caption(
    "急騰「前」のチャートだけを見ながら、1週ずつ先を明らかにしていく。"
    "その時点で本当に知り得た情報だけでエントリー・イグジットを判断する練習ができる画面。"
)

stocks = db.list_stocks()
if stocks.empty:
    st.info("まだ銘柄が登録されていません。「Watchlist」画面から登録してください。")
    st.stop()

col_a, col_b, col_c = st.columns(3)
min_multiple = col_a.select_slider("最小倍率", options=[1.5, 2.0, 2.5, 3.0, 4.0, 5.0], value=2.0)
before_weeks = col_b.select_slider("急騰前に表示する週数", options=[60, 70, 80, 90, 100, 110, 120], value=60)
after_weeks = col_c.select_slider("急騰後、進められる週数", options=[5, 10, 15, 20], value=10)

display_mode = st.radio(
    "表示順",
    ["倍率が大きい順", "急騰区間をランダム順", "全期間からランダム抽出(急騰しなかったケースも含む)"],
    horizontal=True,
    help="急騰した区間だけを見ていると、成功パターンばかり学習してしまう(生存者バイアス)。"
    "ランダム抽出なら、初動が似ていても大相場にならなかったケースも自然に混ざる。",
)


@st.cache_data(show_spinner="全銘柄をスキャン中…")
def _scan_all(codes_and_names: tuple, min_multiple: float):
    rows = []
    for code, name, theme in codes_and_names:
        try:
            weekly = features.load_weekly(code)
        except features.FeatureExtractionError:
            continue
        periods = detect_surge_periods(weekly, min_multiple=min_multiple)
        for p in periods:
            rows.append({"code": code, "name": name, "theme": theme, "period": p})
    rows.sort(key=lambda r: r["period"].multiple, reverse=True)
    return rows


@st.cache_data(show_spinner="ランダムな区間を生成中…")
def _generate_random(codes_and_names: tuple, before_weeks: int, after_weeks: int, n: int, seed: int):
    rng = random.Random(seed)
    codes = list(codes_and_names)
    rows = []
    attempts = 0
    while len(rows) < n and attempts < n * 5:
        attempts += 1
        code, name, theme = rng.choice(codes)
        try:
            weekly = features.load_weekly(code)
        except features.FeatureExtractionError:
            continue
        period = random_period(weekly, before_weeks, after_weeks, rng)
        if period is None:
            continue
        rows.append({"code": code, "name": name, "theme": theme, "period": period})
    return rows


codes_and_names = tuple((r["code"], r["name"], r["theme"]) for _, r in stocks.iterrows())

if display_mode == "倍率が大きい順":
    all_surges = _scan_all(codes_and_names, min_multiple)
    order_note = "倍率が大きい順に並んでいます。"
elif display_mode == "急騰区間をランダム順":
    shuffle_key = f"timing_shuffle_seed_{min_multiple}"
    if shuffle_key not in st.session_state:
        st.session_state[shuffle_key] = random.randint(0, 1_000_000)
    if st.button("🔀 シャッフルし直す"):
        st.session_state[shuffle_key] = random.randint(0, 1_000_000)
        st.session_state[f"timing_idx_{display_mode}_{min_multiple}"] = 0
        st.rerun()
    base = _scan_all(codes_and_names, min_multiple)
    rng = random.Random(st.session_state[shuffle_key])
    all_surges = base.copy()
    rng.shuffle(all_surges)
    order_note = "検出済みの急騰区間(最小倍率以上)を、ランダムな順に並べています。"
else:
    random_seed_key = "timing_random_seed"
    if random_seed_key not in st.session_state:
        st.session_state[random_seed_key] = random.randint(0, 1_000_000)
    if st.button("🔀 シャッフルし直す"):
        st.session_state[random_seed_key] = random.randint(0, 1_000_000)
        st.session_state[f"timing_idx_{display_mode}_{min_multiple}"] = 0
        st.rerun()
    all_surges = _generate_random(
        codes_and_names, before_weeks, after_weeks, 200, st.session_state[random_seed_key]
    )
    order_note = "全期間からランダムに抽出しています(急騰しなかったケースも含みます)。"

if not all_surges:
    st.info("条件に合う区間が見つかりませんでした。設定を変えてみてください。")
    st.stop()

st.write(f"{len(all_surges)}区間を対象にしています。{order_note}")

idx_key = f"timing_idx_{display_mode}_{min_multiple}"
if idx_key not in st.session_state:
    st.session_state[idx_key] = 0
st.session_state[idx_key] = max(0, min(st.session_state[idx_key], len(all_surges) - 1))
idx = st.session_state[idx_key]

current = all_surges[idx]
code, name, theme, period = current["code"], current["name"], current["theme"], current["period"]

# 区間ごとの週送り・エントリー/イグジット状態。
# 1つの急騰区間の中でも複数回エントリーできるように、確定したペアは records に積んでいき、
# entry_week/exit_week は「今まさに記録しようとしている1回分」だけを保持する。
sim_key = f"sim_{display_mode}_{idx}_{min_multiple}_{before_weeks}_{after_weeks}"
if sim_key not in st.session_state:
    st.session_state[sim_key] = {
        "reveal": 0,
        "entry_week": None,
        "entry_id": None,
        "records": [],  # 完全クローズ済みの過去分: [{"entry_week", "exit_events":[{exit_week, exit_percentage}]}]
    }
sim = st.session_state[sim_key]
sim.setdefault("records", [])

nav1, nav2, nav3 = st.columns([1, 1, 4])
if nav1.button("← 前の区間", disabled=(idx == 0)):
    st.session_state[idx_key] -= 1
    st.rerun()
if nav2.button("次の区間 →", disabled=(idx == len(all_surges) - 1)):
    st.session_state[idx_key] += 1
    st.rerun()
nav3.write(f"**{idx + 1} / {len(all_surges)}区間目**")

st.subheader(f"{code} {name} ({theme or '—'})")


@st.cache_data(show_spinner=False)
def _load_and_compute(code: str):
    """週足データ+全指標の計算結果をキャッシュする。「次の週へ」等で銘柄が変わらない限り、
    17種類の指標を毎回再計算する必要がなくなり、体感速度が上がる。"""
    weekly = features.load_weekly(code)
    computed = registry.compute_all(weekly)
    computed["close_pct_change"] = computed["Close"].pct_change() * 100
    return computed


computed = _load_and_compute(code)

idx_all = computed.index
trough_pos = idx_all.get_indexer([period.trough_date])[0]
peak_pos = idx_all.get_indexer([period.peak_date])[0]

start_pos = max(0, trough_pos - before_weeks)
max_end_pos = min(len(idx_all), peak_pos + after_weeks + 1)
# reveal=0の時点ではtrough週(急騰の起点)の直前までしか見せない = 急騰"前"のみ
end_pos = min(max_end_pos, trough_pos + sim["reveal"])
view = computed.iloc[start_pos:end_pos]

fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.5, 0.2, 0.3])
fig.add_trace(
    go.Candlestick(
        x=view.index,
        open=view["Open"],
        high=view["High"],
        low=view["Low"],
        close=view["Close"],
        name=code,
        increasing_line_color="#d64550",
        decreasing_line_color="#2f6690",
        customdata=view["close_pct_change"].apply(
            lambda x: f"{x:+.1f}%" if pd.notna(x) else "—"
        ).to_numpy(),
        hovertemplate=(
            "%{x|%Y-%m-%d}<br>"
            "始値: %{open:,.1f}<br>"
            "高値: %{high:,.1f}<br>"
            "安値: %{low:,.1f}<br>"
            "終値: %{close:,.1f}<br>"
            "前週比: %{customdata}"
            "<extra></extra>"
        ),
    ),
    row=1,
    col=1,
)
fig.add_trace(
    go.Scatter(x=view.index, y=view["ema16"], name="EMA16", mode="lines", line=dict(width=1.5, color="#e0a13a")),
    row=1,
    col=1,
)
fig.add_trace(
    go.Scatter(x=view.index, y=view["rsi10"], name="RSI10", mode="lines", line=dict(width=1.5, color="#5c7cfa")),
    row=2,
    col=1,
)
fig.add_trace(
    go.Bar(x=view.index, y=view["turnover"], name="週間売買代金", marker_color="#7a8ba3"),
    row=3,
    col=1,
)

all_entry_weeks = [r["entry_week"] for r in sim["records"]] + (
    [sim["entry_week"]] if sim["entry_week"] else []
)
all_exit_weeks = [e["exit_week"] for r in sim["records"] for e in r["exit_events"]]
if sim["entry_id"]:
    current_exit_events = db.get_exit_events(sim["entry_id"])
    if not current_exit_events.empty:
        all_exit_weeks.extend(current_exit_events["exit_week"].tolist())

entry_ts_list = [pd.Timestamp(w) for w in all_entry_weeks if pd.Timestamp(w) in view.index]
if entry_ts_list:
    fig.add_trace(
        go.Scatter(
            x=entry_ts_list,
            y=[view.loc[t, "Close"] for t in entry_ts_list],
            mode="markers",
            marker=dict(symbol="triangle-up", size=14, color="#2f9e44"),
            name="エントリー",
        ),
        row=1,
        col=1,
    )
exit_ts_list = [pd.Timestamp(w) for w in all_exit_weeks if pd.Timestamp(w) in view.index]
if exit_ts_list:
    fig.add_trace(
        go.Scatter(
            x=exit_ts_list,
            y=[view.loc[t, "Close"] for t in exit_ts_list],
            mode="markers",
            marker=dict(symbol="triangle-down", size=14, color="#e03131"),
            name="イグジット",
        ),
        row=1,
        col=1,
    )

# 損切りラインをチャートに表示し、実際に週の安値が下回っていないか確認する
existing_stop_loss = None
stop_loss_breached_week = None
if sim["entry_id"]:
    entry_row = db.get_entry(sim["entry_id"])
    if entry_row and entry_row.get("stop_loss_price"):
        existing_stop_loss = float(entry_row["stop_loss_price"])
        fig.add_hline(
            y=existing_stop_loss,
            line_dash="dash",
            line_color="#e03131",
            annotation_text=f"損切りライン {existing_stop_loss:,.0f}円",
            annotation_position="bottom right",
            row=1,
            col=1,
        )
        entry_ts = pd.Timestamp(sim["entry_week"])
        after_entry = view[view.index >= entry_ts]
        breached = after_entry[after_entry["Low"] <= existing_stop_loss]
        if not breached.empty:
            stop_loss_breached_week = breached.index[0]

fig.update_yaxes(type="log", autorange=True, row=1, col=1)
fig.update_yaxes(range=[50, 100], title_text="RSI10", row=2, col=1)
fig.update_yaxes(type="linear", autorange=True, title_text="売買代金", row=3, col=1)
# Candlestickはデフォルトで下にレンジスライダー(ミニチャート)を表示するため、明示的に消す
fig.update_xaxes(rangeslider_visible=False, row=1, col=1)
fig.update_xaxes(rangeslider_visible=False, row=2, col=1)
fig.update_xaxes(rangeslider_visible=False, row=3, col=1)
fig.update_layout(
    height=380,
    margin=dict(t=25, b=10, l=10, r=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.0, font=dict(size=10)),
    dragmode="zoom",
    hovermode="x",
)
st.plotly_chart(
    fig,
    use_container_width=True,
    key=f"timing_chart_{idx}_{sim['reveal']}_{min_multiple}_{before_weeks}_{after_weeks}",
    config={"displayModeBar": False},
)
if stop_loss_breached_week is not None:
    st.error(
        f"⚠️ {stop_loss_breached_week.strftime('%Y-%m-%d')}週の安値が"
        f"損切りライン({existing_stop_loss:,.0f}円)を下回りました。"
    )

# ---- 操作パネル ----
# 「この週のローソク足を見て判断する」→ 実際に売買が成立するのは翌営業週の寄付になるため、
# DBに記録するentry_week/exit_weekは判断した週(latest_week)の1つ先の週(next_week)にする。
# 特徴量の計算だけは判断週(latest_week)時点の情報を使う(ルックアヘッド防止)。
latest_week = view.index[-1] if not view.empty else None
next_week = idx_all[end_pos] if end_pos < len(idx_all) else None
at_max = end_pos >= max_end_pos

if latest_week is not None:
    latest_week_str = latest_week.strftime("%Y-%m-%d")
    next_week_str = next_week.strftime("%Y-%m-%d") if next_week is not None else None
    latest_turnover = float(view.loc[latest_week, "turnover"]) if latest_week in view.index else None
    liquidity_ok = latest_turnover is not None and latest_turnover >= MIN_TURNOVER

    if sim["entry_week"] is None:
        if next_week_str is not None:
            ecol1, ecol2 = st.columns([2, 1])
            entry_comment = ecol1.text_area(
                "なぜこの週にエントリーしたいと思ったか",
                key=f"entry_comment_{idx}_{sim['reveal']}",
                placeholder="例: EMA16を上から下に割らずに反発、出来高も増加",
                height=68,
            )
            stop_loss_price = ecol2.number_input(
                "損切りライン(円、必須)",
                min_value=0.0,
                value=0.0,
                step=1.0,
                key=f"stop_loss_{idx}_{sim['reveal']}",
                help=f"参考: 判断週終値 {view.loc[latest_week, 'Close']:,.1f}円",
            )
            if latest_turnover is not None:
                liquidity_note = (
                    ""
                    if liquidity_ok
                    else "　⚠️ 10億円未満のため、実弾で買いにくい銘柄としてエントリー対象外です"
                )
                st.caption(f"判断週の週間売買代金: {latest_turnover:,.0f}円{liquidity_note}")
    else:
        total_exit_pct_preview = db.total_exit_percentage(sim["entry_id"])
        remaining_pct_preview = round(100 - total_exit_pct_preview, 4)
        if (
            remaining_pct_preview > 0
            and latest_week_str >= sim["entry_week"]
            and next_week_str is not None
        ):
            exit_comment = st.text_area(
                "なぜここでイグジットする判断をしたか",
                key=f"exit_comment_{idx}_{sim['entry_id']}_{sim['reveal']}",
                height=68,
                placeholder="例: RSIが70を超えて過熱、上ヒゲが目立ってきた",
            )

c0, c1, c2, c3 = st.columns(4)

if c0.button("← 前の週へ", disabled=(sim["reveal"] <= 0), type="secondary"):
    sim["reveal"] -= 1
    st.rerun()

if c1.button("次の週へ →", disabled=at_max, type="secondary"):
    sim["reveal"] += 1
    st.rerun()

if latest_week is not None:
    if sim["entry_week"] is None:
        if next_week_str is None:
            c2.button("ここでエントリー", disabled=True, help="翌週(約定週)のデータがまだ存在しません")
        elif not liquidity_ok:
            c2.button("ここでエントリー", disabled=True, help="判断週の週間売買代金が10億円未満のため対象外です")
        elif stop_loss_price <= 0:
            c2.button("ここでエントリー", disabled=True, help="損切りライン(円)を入力してください")
        else:
            if c2.button(f"ここでエントリー(判断週{latest_week_str}→約定{next_week_str}寄付)", type="primary"):
                entry_id = db.add_entry(
                    code, next_week_str, comment=entry_comment, stop_loss_price=stop_loss_price
                )
                feats, _ = features.extract_features_for_entry(code, latest_week_str)
                db.save_entry_features(entry_id, feats)
                sim["entry_week"] = next_week_str
                sim["entry_id"] = entry_id
                st.rerun()
    else:
        # 部分イグジット(分割決済)対応: 残りポジションが0%になるまで、何度でもイグジットできる
        total_exit_pct = db.total_exit_percentage(sim["entry_id"])
        remaining_pct = round(100 - total_exit_pct, 4)

        if remaining_pct <= 0:
            exit_events_df = db.get_exit_events(sim["entry_id"])
            trade_return = features.compute_trade_return_multi(
                code, sim["entry_week"], exit_events_df[["exit_week", "exit_percentage"]].to_dict("records")
            )
            return_text = f"　【加重平均 {trade_return['weighted_return_pct']:+.1f}%】" if trade_return else ""
            legs_text = " / ".join(
                f"{r['exit_week']}({r['exit_percentage']:.0f}%)" for _, r in exit_events_df.iterrows()
            )
            c2.success(f"エントリー(約定) {sim['entry_week']} → 完全クローズ: {legs_text}{return_text}")
        elif latest_week_str < sim["entry_week"]:
            c2.button("ここでイグジット", disabled=True, help="エントリー(約定)週以降に進んでから押せます")
        elif next_week_str is None:
            c2.button("ここでイグジット", disabled=True, help="翌週(約定週)のデータがまだ存在しません")
        else:
            pct_choices = sorted({p for p in [100, 75, 50, 25] if p <= remaining_pct} | {remaining_pct}, reverse=True)
            chosen_pct = c2.selectbox(
                f"イグジットする割合(残り{remaining_pct:.0f}%)",
                pct_choices,
                format_func=lambda p: f"{p:.0f}%",
                key=f"exit_pct_{idx}_{sim['entry_id']}_{sim['reveal']}",
            )
            if c2.button(
                f"ここで{chosen_pct:.0f}%イグジット(判断週{latest_week_str}→約定{next_week_str}寄付)",
                type="primary",
            ):
                db.add_exit_event(sim["entry_id"], next_week_str, chosen_pct, comment=exit_comment)
                st.rerun()

if sim["entry_id"] and db.total_exit_percentage(sim["entry_id"]) >= 100:
    if c3.button("次の区間へ進む →", type="primary"):
        st.session_state[idx_key] = min(idx + 1, len(all_surges) - 1)
        st.rerun()

    c4, _ = st.columns([1, 3])
    if c4.button("この区間でもう一度エントリーする", type="secondary"):
        exit_events_df = db.get_exit_events(sim["entry_id"])
        sim["records"].append(
            {
                "entry_week": sim["entry_week"],
                "exit_events": exit_events_df[["exit_week", "exit_percentage"]].to_dict("records"),
            }
        )
        sim["entry_week"] = None
        sim["entry_id"] = None
        st.rerun()

if sim["records"]:
    st.caption(f"この区間ではすでに{len(sim['records'])}件のエントリー/イグジットを記録済みです。")

is_fully_closed = sim["entry_id"] is not None and db.total_exit_percentage(sim["entry_id"]) >= 100
never_entered_this_visit = sim["entry_week"] is None

# 表示できる範囲の上限まで来て、なおかつ今回一度もエントリーしていない場合。
# 「エントリーしなかった」判断も、理由を残さないと生存者バイアス(成功例しか記録に残らない)の
# 原因になるため、全週を見終えた後に見送り理由を記録できるようにする。
if at_max and not is_fully_closed and never_entered_this_visit and latest_week is not None:
    if sim["records"]:
        # この区間では過去にエントリー済み(今回訪問分は見送っただけ)なので、理由記入は不要。
        st.info("この区間で表示できる範囲の上限まで進みました。")
        if st.button("次の区間へ進む →", type="primary", key=f"skip_next_with_records_{idx}"):
            st.session_state[idx_key] = min(idx + 1, len(all_surges) - 1)
            st.rerun()
    else:
        existing_skip = db.get_skip(code, latest_week_str)
        st.warning("この区間では全期間を見てもエントリーしませんでした。見送った理由を記録してください。")
        skip_comment = st.text_area(
            "なぜこの銘柄・この区間ではエントリーしなかったか",
            value=(existing_skip["comment"] if existing_skip else "") or "",
            key=f"skip_comment_{idx}_{sim['reveal']}",
            placeholder="例: 出来高が伴わず、上ヒゲが多かったため様子見",
            height=68,
        )
        skip_col1, skip_col2 = st.columns([1, 3])
        if skip_col1.button("理由を保存して次の区間へ", type="primary", key=f"skip_save_next_{idx}"):
            if not skip_comment.strip():
                st.error("理由を入力してください。")
            else:
                db.add_skip(code, latest_week_str, comment=skip_comment)
                st.session_state[idx_key] = min(idx + 1, len(all_surges) - 1)
                st.rerun()
        if skip_col2.button("理由だけ保存する", key=f"skip_save_only_{idx}"):
            if not skip_comment.strip():
                st.error("理由を入力してください。")
            else:
                db.add_skip(code, latest_week_str, comment=skip_comment)
                st.success("見送り理由を保存しました。")
elif at_max and not is_fully_closed:
    st.info("この区間で表示できる範囲の上限まで進みました。エントリー/イグジットを記録するか、次の区間に進んでください。")

with st.expander("この銘柄の記録済みエントリー"):
    existing_entries = db.list_entries(stock_code=code)
    if existing_entries.empty:
        st.caption("まだありません。")
    else:
        st.caption("週の変更やコメント編集は「Entry」画面から行えます。ここでは削除のみできます。")
        for _, erow in existing_entries.iterrows():
            ecol1, ecol2 = st.columns([5, 1])
            exit_events_df = db.get_exit_events(erow["id"])
            if exit_events_df.empty:
                exit_text = ""
                return_text = ""
            else:
                legs_text = " / ".join(
                    f"{r['exit_week']}({r['exit_percentage']:.0f}%)" for _, r in exit_events_df.iterrows()
                )
                exit_text = f" → イグジット: {legs_text}"
                trade_return = features.compute_trade_return_multi(
                    code,
                    erow["entry_week"],
                    exit_events_df[["exit_week", "exit_percentage"]].to_dict("records"),
                )
                return_text = f"　【加重平均 {trade_return['weighted_return_pct']:+.1f}%】" if trade_return else ""
            ecol1.write(f"{erow['entry_week']}{exit_text}{return_text}")
            ecol1.caption(f"エントリー理由: {erow['comment'] or '(コメントなし)'}")
            if not exit_events_df.empty:
                for _, ev in exit_events_df.iterrows():
                    if ev["comment"]:
                        ecol1.caption(f"　{ev['exit_week']}({ev['exit_percentage']:.0f}%)の理由: {ev['comment']}")
            if ecol2.button("削除", key=f"timing_del_entry_{erow['id']}"):
                db.delete_entry(erow["id"])
                if sim.get("entry_id") == erow["id"]:
                    sim["entry_week"] = None
                    sim["entry_id"] = None
                st.rerun()

with st.expander("この銘柄の記録済み見送り理由"):
    existing_skips = db.list_skips(stock_code=code)
    if existing_skips.empty:
        st.caption("まだありません。")
    else:
        for _, srow in existing_skips.iterrows():
            scol1, scol2 = st.columns([5, 1])
            scol1.write(f"{srow['week']} — {srow['comment'] or '(理由なし)'}")
            if scol2.button("削除", key=f"timing_del_skip_{srow['id']}"):
                db.delete_skip(srow["id"])
                st.rerun()
