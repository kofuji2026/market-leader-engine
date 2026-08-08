"""SQLite DB接続・スキーマ初期化・CRUDヘルパー。

設計方針(proposal.mdで承認済み):
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
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "market_leader.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks (
    code       TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    theme      TEXT,
    extra_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code  TEXT NOT NULL REFERENCES stocks(code) ON DELETE CASCADE,
    entry_week  TEXT NOT NULL,  -- 週足の週末日(YYYY-MM-DD)
    exit_week   TEXT,  -- 週足の週末日(YYYY-MM-DD)。未確定のうちはNULL
    comment     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(stock_code, entry_week)
);

CREATE TABLE IF NOT EXISTS entry_features (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id      INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    feature_key   TEXT NOT NULL,
    feature_label TEXT,
    feature_value REAL,
    feature_unit  TEXT,
    computed_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(entry_id, feature_key)
);

CREATE TABLE IF NOT EXISTS hypotheses (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    content    TEXT,
    status     TEXT NOT NULL DEFAULT '未検証',
    comment    TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


@contextmanager
def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        # 既存DBに後から追加した列のマイグレーション(既にあればスキップ)
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(entries)")}
        if "exit_week" not in existing_cols:
            conn.execute("ALTER TABLE entries ADD COLUMN exit_week TEXT")


# ---------- stocks (① 銘柄登録) ----------

def add_stock(code: str, name: str, theme: str | None = None, extra: dict | None = None) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO stocks (code, name, theme, extra_json) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(code) DO UPDATE SET name=excluded.name, theme=excluded.theme, "
            "extra_json=excluded.extra_json",
            (code, name, theme, json.dumps(extra or {}, ensure_ascii=False)),
        )


def delete_stock(code: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM stocks WHERE code = ?", (code,))


def list_stocks() -> pd.DataFrame:
    with get_connection() as conn:
        df = pd.read_sql_query("SELECT * FROM stocks ORDER BY created_at DESC", conn)
    return df


def stock_exists(code: str) -> bool:
    with get_connection() as conn:
        row = conn.execute("SELECT 1 FROM stocks WHERE code = ?", (code,)).fetchone()
    return row is not None


# ---------- entries (② エントリー週記録) ----------

def add_entry(stock_code: str, entry_week: str, comment: str = "") -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO entries (stock_code, entry_week, comment) VALUES (?, ?, ?) "
            "ON CONFLICT(stock_code, entry_week) DO UPDATE SET comment=excluded.comment",
            (stock_code, entry_week, comment),
        )
        if cur.lastrowid:
            return cur.lastrowid
        row = conn.execute(
            "SELECT id FROM entries WHERE stock_code = ? AND entry_week = ?",
            (stock_code, entry_week),
        ).fetchone()
        return row["id"]


def set_exit_week(entry_id: int, exit_week: str | None) -> None:
    """exit_week に None を渡すと未設定に戻せる(クリア)。"""
    with get_connection() as conn:
        conn.execute("UPDATE entries SET exit_week = ? WHERE id = ?", (exit_week, entry_id))


def update_entry(entry_id: int, entry_week: str, comment: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE entries SET entry_week = ?, comment = ? WHERE id = ?",
            (entry_week, comment, entry_id),
        )


def delete_entry(entry_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))


def list_entries(stock_code: str | None = None) -> pd.DataFrame:
    query = (
        "SELECT entries.*, stocks.name AS stock_name FROM entries "
        "JOIN stocks ON stocks.code = entries.stock_code"
    )
    params: tuple = ()
    if stock_code:
        query += " WHERE entries.stock_code = ?"
        params = (stock_code,)
    query += " ORDER BY entries.entry_week DESC"
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn, params=params)
    return df


# ---------- entry_features (③ 特徴量、縦持ち) ----------

def save_entry_features(entry_id: int, features: dict[str, tuple[str, float, str]]) -> None:
    """features: {feature_key: (label, value, unit)}"""
    with get_connection() as conn:
        for key, (label, value, unit) in features.items():
            conn.execute(
                "INSERT INTO entry_features (entry_id, feature_key, feature_label, "
                "feature_value, feature_unit) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(entry_id, feature_key) DO UPDATE SET "
                "feature_label=excluded.feature_label, feature_value=excluded.feature_value, "
                "feature_unit=excluded.feature_unit, computed_at=datetime('now')",
                (entry_id, key, label, value, unit),
            )


def get_entry_features(entry_id: int) -> pd.DataFrame:
    with get_connection() as conn:
        df = pd.read_sql_query(
            "SELECT * FROM entry_features WHERE entry_id = ? ORDER BY feature_key",
            conn,
            params=(entry_id,),
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
        cur = conn.execute(
            "INSERT INTO hypotheses (title, content, status) VALUES (?, ?, ?)",
            (title, content, status),
        )
        return cur.lastrowid


def list_hypotheses() -> pd.DataFrame:
    with get_connection() as conn:
        df = pd.read_sql_query("SELECT * FROM hypotheses ORDER BY updated_at DESC", conn)
    return df
