"""watchlist一括データ取得: ①日足取得 → ②週足変換 → ③CSV保存 → ④DBへの銘柄登録

実行方法:
    python scripts/fetch_all.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib import db  # noqa: E402
from lib.fetch import fetch_daily  # noqa: E402
from lib.io_utils import save_csv  # noqa: E402
from lib.transform import build_weekly  # noqa: E402

WATCHLIST_PATH = ROOT / "config" / "watchlist.csv"
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"


def load_watchlist() -> pd.DataFrame:
    return pd.read_csv(WATCHLIST_PATH, dtype={"code": str})


def run() -> None:
    db.init_db()
    watchlist = load_watchlist()
    print(f"対象銘柄: {len(watchlist)}件")

    results = []
    for _, row in watchlist.iterrows():
        code, name = row["code"], row["name"]
        theme = row.get("theme")
        print(f"\n[{code}] {name} を処理中…")
        try:
            # ① 日足取得
            daily = fetch_daily(code)
            save_csv(daily, RAW_DIR / f"{code}_daily.csv")
            print(f"  日足: {len(daily)}件 ({daily.index.min().date()} 〜 {daily.index.max().date()})")

            # ② 週足変換
            weekly = build_weekly(daily)
            save_csv(weekly, PROCESSED_DIR / f"{code}_weekly.csv")
            print(f"  週足: {len(weekly)}件 → data/processed/{code}_weekly.csv")

            # ④ DBへ銘柄登録(Watchlist = Market Leader候補)
            db.add_stock(code, name, theme=theme)

            results.append({"code": code, "name": name, "status": "OK", "rows": len(weekly)})
        except Exception as e:  # noqa: BLE001
            print(f"  失敗: {e}")
            results.append({"code": code, "name": name, "status": "ERROR", "rows": 0, "error": str(e)})

    print("\n=== 結果サマリー ===")
    for r in results:
        status_label = "OK" if r["status"] == "OK" else f"ERROR: {r.get('error', '')}"
        print(f"  {r['code']} {r['name']}: {status_label}")


if __name__ == "__main__":
    run()
