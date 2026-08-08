"""PostgreSQL(Supabase) DB接続・スキーマ初期化・CRUDヘルパー。

2026-08-08、PCがなくても記録できるようにWebデプロイするため、SQLiteからSupabase(PostgreSQL)へ移行。
(旧SQLite版はlib/db_sqlite_backup.pyに残している)

設計方針(proposal.mdで承認済み、移行後も変更なし):
- 固定列でカバーできるもの(stocks/entries/hypotheses)は固定列+JSON自由項目(extra列)
- 種類が増え続ける特徴量(entry_features)だけは縦持ち(tidy)形式にして、
  新しい指標を追加するたびにテーブルのスキーマ変更が発生しないようにする

テーブル:
- stocks         : Market Leader候補(=Watchlist)。①100銘柄登録
- entries        : 「この銘柄のこの週なら買いたい」の記録。②エントリー週記録
- entry_features : entryごとに算出した特徴量(縦持ち)。③Feature Extractorの出力
- hypotheses     : 仮説管理(将来のHypothesis Manager用。MVPではテーブルのみ用意)
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager

import pandas as pd
import psycopg2
import psycopg2.extras

SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks (
    code       TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    theme      TEXT,
    extra_json TEXT,
    split      TEXT,  -- 'train' or 'validation'。特徴量やルールは訓練用銘柄だけを見て作り、検証用は最後の答え合わせに使う
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS entries (
    id              SERIAL PRIMARY KEY,
    stock_code      TEXT NOT NULL REFERENCES stocks(code) ON DELETE CASCADE,
    entry_week      TEXT NOT NULL,  -- 週足の週末日(YYYY-MM-DD)
    exit_week       TEXT,  -- 週足の週末日(YYYY-MM-DD)。未確定のうちはNULL
    stop_loss_price DOUBLE PRECISION,  -- エントリー時に決めた損切りライン(円)。必須運用
    comment         TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(stock_code, entry_week)
);

CREATE TABLE IF NOT EXISTS entry_features (
    id            SERIAL PRIMARY KEY,
    entry_id      INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    feature_key   TEXT NOT NULL,
    feature_label TEXT,
    feature_value DOUBLE PRECISION,
    feature_unit  TEXT,
    computed_at   TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(entry_id, feature_key)
);

CREATE TABLE IF NOT EXISTS hypotheses (
    id         SERIAL PRIMARY KEY,
    title      TEXT NOT NULL,
    content    TEXT,
    status     TEXT NOT NULL DEFAULT '未検証',
    comment    TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 部分イグジット(分割決済)。1つのentryに対して複数回のイグジットを記録できるようにする
-- (例: 50%を week1で利確、残り50%をweek2で利確)。全exit_percentageの合計が100になったら
-- ポジションは完全クローズとみなす。
CREATE TABLE IF NOT EXISTS exit_events (
    id              SERIAL PRIMARY KEY,
    entry_id        INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    exit_week       TEXT NOT NULL,
    exit_percentage DOUBLE PRECISION NOT NULL,
    comment         TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 「この銘柄のこの週は見送った」の記録。エントリーはentriesに残るが、見送った判断は
-- 何も残らないため、生存者バイアスを防ぐ目的でここに理由を記録できるようにする。
CREATE TABLE IF NOT EXISTS skips (
    id         SERIAL PRIMARY KEY,
    stock_code TEXT NOT NULL REFERENCES stocks(code) ON DELETE CASCADE,
    week       TEXT NOT NULL,  -- 見送りを判断した週(判断週。ローソク足を見て判断した週そのもの)
    comment    TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE entries ADD COLUMN IF NOT EXISTS exit_week TEXT;
ALTER TABLE exit_events ADD COLUMN IF NOT EXISTS comment TEXT;
ALTER TABLE entries ADD COLUMN IF NOT EXISTS stop_loss_price DOUBLE PRECISION;
ALTER TABLE stocks ADD COLUMN IF NOT EXISTS split TEXT;
"""


def _get_database_url() -> str:
    """接続文字列を取得する。Streamlit Cloud上ではst.secrets、ローカルスクリプトからの
    実行(scripts/配下)ではローカルの.streamlit/secrets.tomlか環境変数から読む。"""
    try:
        import streamlit as st

        if "DATABASE_URL" in st.secrets:
            return st.secrets["DATABASE_URL"]
    except Exception:  # noqa: BLE001 — streamlit実行コンテキスト外から呼ばれた場合など
        pass

    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    raise RuntimeError(
        "DATABASE_URLが見つかりません。.streamlit/secrets.toml に "
        '`DATABASE_URL = "postgresql://..."` を設定してください。'
    )


@contextmanager
def get_connection():
    # RealDictCursorをデフォルトにするとpandas.read_sql_queryの列名解決が壊れるため、
    # 通常のtupleカーソルを既定にし、辞書アクセスしたい箇所だけ個別にRealDictCursorを指定する。
    conn = psycopg2.connect(_get_database_url())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _dict_cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def init_db() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)


# ---------- stocks (① 銘柄登録) ----------

def add_stock(code: str, name: str, theme: str | None = None, extra: dict | None = None) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO stocks (code, name, theme, extra_json) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT(code) DO UPDATE SET name=excluded.name, theme=excluded.theme, "
                "extra_json=excluded.extra_json",
                (code, name, theme, json.dumps(extra or {}, ensure_ascii=False)),
            )


def delete_stock(code: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM stocks WHERE code = %s", (code,))


def list_stocks(split: str | None = None) -> pd.DataFrame:
    with get_connection() as conn:
        if split is None:
            df = pd.read_sql_query("SELECT * FROM stocks ORDER BY created_at DESC", conn)
        else:
            df = pd.read_sql_query(
                "SELECT * FROM stocks WHERE split = %s ORDER BY created_at DESC", conn, params=(split,)
            )
    return df


def stock_exists(code: str) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM stocks WHERE code = %s", (code,))
            row = cur.fetchone()
    return row is not None


def set_stock_split(code: str, split: str | None) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE stocks SET split = %s WHERE code = %s", (split, code))


def assign_splits(train_codes: list[str], validation_codes: list[str]) -> None:
    """銘柄コードのリストからtrain/validationの割り当てを一括反映する。"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE stocks SET split = %s WHERE code = %s",
                [("train", code) for code in train_codes] + [("validation", code) for code in validation_codes],
            )


# ---------- entries (② エントリー週記録) ----------

def add_entry(stock_code: str, entry_week: str, comment: str = "", stop_loss_price: float | None = None) -> int:
    with get_connection() as conn:
        with _dict_cursor(conn) as cur:
            cur.execute(
                "INSERT INTO entries (stock_code, entry_week, comment, stop_loss_price) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT(stock_code, entry_week) DO UPDATE SET comment=excluded.comment, "
                "stop_loss_price=excluded.stop_loss_price "
                "RETURNING id",
                (stock_code, entry_week, comment, stop_loss_price),
            )
            return cur.fetchone()["id"]


def set_exit_week(entry_id: int, exit_week: str | None) -> None:
    """exit_week に None を渡すと未設定に戻せる(クリア)。"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE entries SET exit_week = %s WHERE id = %s", (exit_week, entry_id))


def set_stop_loss_price(entry_id: int, stop_loss_price: float | None) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE entries SET stop_loss_price = %s WHERE id = %s", (stop_loss_price, entry_id)
            )


def update_entry(entry_id: int, entry_week: str, comment: str, stop_loss_price: float | None = None) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE entries SET entry_week = %s, comment = %s, stop_loss_price = %s WHERE id = %s",
                (entry_week, comment, stop_loss_price, entry_id),
            )


def delete_entry(entry_id: int) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM entries WHERE id = %s", (entry_id,))


def get_entry(entry_id: int) -> dict | None:
    with get_connection() as conn:
        with _dict_cursor(conn) as cur:
            cur.execute("SELECT * FROM entries WHERE id = %s", (entry_id,))
            row = cur.fetchone()
    return dict(row) if row else None


def list_entries(stock_code: str | None = None) -> pd.DataFrame:
    query = (
        "SELECT entries.*, stocks.name AS stock_name FROM entries "
        "JOIN stocks ON stocks.code = entries.stock_code"
    )
    params: tuple = ()
    if stock_code:
        query += " WHERE entries.stock_code = %s"
        params = (stock_code,)
    query += " ORDER BY entries.entry_week DESC"
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn, params=params)
    return df


# ---------- exit_events (部分イグジット/分割決済) ----------

def add_exit_event(entry_id: int, exit_week: str, exit_percentage: float, comment: str = "") -> int:
    """entry_idに対して部分(または全部)イグジットを1件追加する。
    同じ回のexit_percentageの合計が100を超えないかはUI側でチェックする想定。"""
    with get_connection() as conn:
        with _dict_cursor(conn) as cur:
            cur.execute(
                "INSERT INTO exit_events (entry_id, exit_week, exit_percentage, comment) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (entry_id, exit_week, exit_percentage, comment),
            )
            return cur.fetchone()["id"]


def delete_exit_event(exit_event_id: int) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM exit_events WHERE id = %s", (exit_event_id,))


def get_exit_events(entry_id: int) -> pd.DataFrame:
    with get_connection() as conn:
        df = pd.read_sql_query(
            "SELECT * FROM exit_events WHERE entry_id = %(entry_id)s ORDER BY exit_week",
            conn,
            params={"entry_id": entry_id},
        )
    return df


def get_all_exit_events() -> pd.DataFrame:
    with get_connection() as conn:
        df = pd.read_sql_query("SELECT * FROM exit_events ORDER BY entry_id, exit_week", conn)
    return df


def total_exit_percentage(entry_id: int) -> float:
    """このentryがこれまでに手仕舞いした割合の合計(0〜100)。"""
    events = get_exit_events(entry_id)
    if events.empty:
        return 0.0
    return float(events["exit_percentage"].sum())


# ---------- skips (見送り理由の記録) ----------

def add_skip(stock_code: str, week: str, comment: str = "") -> int:
    """同じ(stock_code, week)の見送り記録が既にあれば理由を上書きし、なければ新規作成する。"""
    with get_connection() as conn:
        with _dict_cursor(conn) as cur:
            cur.execute(
                "SELECT id FROM skips WHERE stock_code = %s AND week = %s", (stock_code, week)
            )
            existing = cur.fetchone()
            if existing:
                cur.execute("UPDATE skips SET comment = %s WHERE id = %s", (comment, existing["id"]))
                return existing["id"]
            cur.execute(
                "INSERT INTO skips (stock_code, week, comment) VALUES (%s, %s, %s) RETURNING id",
                (stock_code, week, comment),
            )
            return cur.fetchone()["id"]


def get_skip(stock_code: str, week: str) -> dict | None:
    with get_connection() as conn:
        with _dict_cursor(conn) as cur:
            cur.execute(
                "SELECT * FROM skips WHERE stock_code = %s AND week = %s", (stock_code, week)
            )
            row = cur.fetchone()
    return dict(row) if row else None


def delete_skip(skip_id: int) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM skips WHERE id = %s", (skip_id,))


def list_skips(stock_code: str | None = None) -> pd.DataFrame:
    query = (
        "SELECT skips.*, stocks.name AS stock_name FROM skips "
        "JOIN stocks ON stocks.code = skips.stock_code"
    )
    params: tuple = ()
    if stock_code:
        query += " WHERE skips.stock_code = %s"
        params = (stock_code,)
    query += " ORDER BY skips.week DESC"
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn, params=params)
    return df


# ---------- entry_features (③ 特徴量、縦持ち) ----------

def save_entry_features(entry_id: int, features: dict[str, tuple[str, float, str]]) -> None:
    """features: {feature_key: (label, value, unit)}"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            for key, (label, value, unit) in features.items():
                cur.execute(
                    "INSERT INTO entry_features (entry_id, feature_key, feature_label, "
                    "feature_value, feature_unit) VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT(entry_id, feature_key) DO UPDATE SET "
                    "feature_label=excluded.feature_label, feature_value=excluded.feature_value, "
                    "feature_unit=excluded.feature_unit, computed_at=NOW()",
                    (entry_id, key, label, value, unit),
                )


def get_entry_features(entry_id: int) -> pd.DataFrame:
    with get_connection() as conn:
        df = pd.read_sql_query(
            "SELECT * FROM entry_features WHERE entry_id = %(entry_id)s ORDER BY feature_key",
            conn,
            params={"entry_id": entry_id},
        )
    return df


def get_all_entry_features_wide() -> pd.DataFrame:
    """比較画面用: entryごとに特徴量を横持ちにしたDataFrame。"""
    with get_connection() as conn:
        entries = pd.read_sql_query(
            "SELECT entries.id AS entry_id, entries.stock_code, stocks.name AS stock_name, "
            "entries.entry_week, entries.exit_week, entries.comment FROM entries "
            "JOIN stocks ON stocks.code = entries.stock_code",
            conn,
        )
        features = pd.read_sql_query(
            "SELECT entry_id, feature_key, feature_value FROM entry_features", conn
        )
    if entries.empty:
        return entries
    if features.empty:
        return entries
    wide = features.pivot(index="entry_id", columns="feature_key", values="feature_value")
    return entries.merge(wide, on="entry_id", how="left")


# ---------- hypotheses (⑤ 仮説管理。MVPスコープ外だがスキーマのみ用意) ----------

def add_hypothesis(title: str, content: str = "", status: str = "未検証") -> int:
    with get_connection() as conn:
        with _dict_cursor(conn) as cur:
            cur.execute(
                "INSERT INTO hypotheses (title, content, status) VALUES (%s, %s, %s) RETURNING id",
                (title, content, status),
            )
            return cur.fetchone()["id"]


def list_hypotheses() -> pd.DataFrame:
    with get_connection() as conn:
        df = pd.read_sql_query("SELECT * FROM hypotheses ORDER BY updated_at DESC", conn)
    return df
