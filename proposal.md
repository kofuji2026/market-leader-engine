# Market Leader Engine — 実装前提案

作成日: 2026-08-05
ステータス: **承認待ち(実装未着手)**

## このプロジェクトが何であるか(認識合わせ)

- バックテストソフトではない
- チャートビューアだけのツールでもない
- AIに勝ち方を考えさせるツールでもない
- **本人が仮説を考え、検証し、改善するための「研究プラットフォーム」**
- 最終ゴール(まだ実装しない): 毎週日曜30分で、その週に買うべき3〜5銘柄・エントリー候補・損切りラインが提示される
- 今回作るのはその手前の**研究基盤**(①〜⑤)のみ。スコアリング・全銘柄スキャンは半年ロードマップの先

最優先事項は速度と柔軟性: 「仮説を思いついたその日のうちに検証できる」こと。拡張性・保守性を、見た目の作り込みより優先する。

---

## 1. システム全体アーキテクチャ

### 技術選定とその理由

| 領域 | 選定 | 理由 |
|---|---|---|
| UI/アプリ | **Streamlit** | Python単体で完結し、チェックボックス(指標ON/OFF)・テーブル編集・グラフ表示が数行で書ける。個人の研究ツールとして「思いついたその日に画面に反映する」速度に最適。Dash等はより柔軟だが、その分ボイラープレートが増え、今回の目的(研究速度)には過剰 |
| チャート描画 | **plotly** | ローソク足+複数指標のオーバーレイ、ON/OFFの動的切り替えがしやすく、Streamlitとの相性が良い |
| データ処理 | **pandas** | 既存資産(前回のMVP)をそのまま流用できる |
| テクニカル指標 | **pandas-ta**(土台)+ 自前関数(独自指標) | EMA/RSI/ADX/ATR/MACDは`pandas-ta`に標準実装があり信頼性が高い。実体率・上ヒゲ率など独自指標は自前のプラグイン関数として追加する設計にする |
| DB | **SQLite**(標準ライブラリ`sqlite3`) | 個人利用規模には十分で、ファイル1つで完結し、バックアップ・移動が容易。将来必要ならPostgreSQLへの移行も難しくない設計にする |
| データ取得 | **yfinance**(既存)、将来的にJ-Quants/EDINETを追加 | 前回のMVPと同じ方針を継続 |

### 「プラグインのように追加できる」仕組み

指標(③④で使う)は、**レジストリパターン**で管理する。

```python
# lib/indicators/__init__.py のイメージ
INDICATORS = {}

def register(name):
    def decorator(func):
        INDICATORS[name] = func
        return func
    return decorator

# lib/indicators/ema.py
@register("EMA16")
def ema16(weekly_df):
    return weekly_df["Close"].ewm(span=16, adjust=False).mean()
```

新しい指標を追加したい時は、`lib/indicators/`に1ファイル(1関数)を足すだけで、Chart ViewerのON/OFFリストにもFeature Extractorにも自動的に反映される(両方が同じレジストリを参照するため)。DB migrationやUIの手直しは不要。

---

## 2. ディレクトリ構成

```
market-leader-engine/
  config/
    watchlist.csv                 # 銘柄マスタ(前回のjp-stock-superperformer-researchから引き継ぎ)
  data/
    raw/                          # 日足生データ(CSV、前回資産を流用)
    processed/                    # 週足OHLCV(CSV)
  db/
    market_leader.db              # SQLite本体(①②④⑤すべてここに集約)
    schema.sql                    # テーブル定義(バージョン管理用に平文でも保持)
  lib/
    fetch.py                      # ①日足取得(前回資産を流用)
    transform.py                  # 週足変換(前回資産を流用)
    indicators/                   # プラグイン置き場
      __init__.py                 # レジストリ本体
      ema.py                      # EMA16/25/75
      rsi.py
      adx.py
      atr.py
      macd.py
      high_low.py                 # 52週高値・13週高値
      candle.py                   # 実体率・上ヒゲ率・下ヒゲ率
      volume.py                   # 出来高・売買代金の派生指標
    features.py                   # ④Feature Extractor本体
    db/
      connection.py                # DB接続ヘルパー
      market_leaders.py             # ①CRUD
      entries.py                     # ②CRUD
      hypotheses.py                   # ⑤CRUD
  app/
    Home.py                        # Streamlitエントリーポイント
    pages/
      1_Market_Leaders.py           # ①候補DBの一覧・登録・編集
      2_Entries.py                   # ②エントリー登録・一覧
      3_Chart_Viewer.py               # ③チャートビューア(最重要画面)
      4_Feature_Extractor.py           # ④特徴量の一覧・再計算
      5_Hypotheses.py                   # ⑤仮説管理
  scripts/
    fetch_all.py                    # watchlist全銘柄の週足を一括更新するバッチ
  tests/
    test_indicators.py               # 指標計算のロジックが壊れていないかの回帰テスト
  requirements.txt
```

---

## 3. DB設計

SQLite。**「項目を自由に追加できる」要件**には、テーブルに`extra`という**JSON列**を1つ持たせる方式で対応する(固定でよく使う項目は普通の列にしつつ、想定外の項目はJSONに逃がす)。これによりDBのスキーマ変更(マイグレーション)なしに項目を増やせる。

**特徴量(④)だけは別の考え方をする**: 特徴量は種類がどんどん増えていくものなので、横に列を増やす代わりに「1行=1特徴量」の**縦持ち(tidy)形式**にする。新しい指標を追加しても、テーブル構造を変えずに行を増やすだけで済む。

```sql
-- ①Market Leader Database
CREATE TABLE market_leaders (
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  theme TEXT,
  comment TEXT,
  start_date DATE,
  end_date DATE,              -- NULLなら継続中
  max_return_pct REAL,
  max_drawdown_pct REAL,
  holding_period_days INTEGER,
  is_ongoing BOOLEAN,
  extra JSON,                  -- 自由項目
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP
);

-- ②Entry Database(「ここなら買いたい」週の登録)
CREATE TABLE entries (
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL,
  name TEXT,
  entry_week DATE NOT NULL,    -- その週の週足基準日(例: 週末金曜)
  comment TEXT,                 -- なぜ買いたいと思ったか
  extra JSON,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ④特徴量(tidy形式、entriesに従属)
CREATE TABLE entry_features (
  id INTEGER PRIMARY KEY,
  entry_id INTEGER REFERENCES entries(id),
  feature_name TEXT NOT NULL,   -- 例: "EMA16", "RSI14", "High52W"
  feature_value REAL,
  computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ⑤Hypothesis Manager
CREATE TABLE hypotheses (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  content TEXT,
  status TEXT CHECK(status IN ('未検証','検証中','採用','却下')) DEFAULT '未検証',
  comment TEXT,
  extra JSON,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP
);

-- 銘柄マスタ(watchlist.csvと同期、または将来これに一本化)
CREATE TABLE stocks (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 週足価格(Chart Viewerが頻繁に参照するのでDB化しておくとクエリが楽)
CREATE TABLE price_weekly (
  code TEXT NOT NULL,
  date DATE NOT NULL,
  open REAL, high REAL, low REAL, close REAL,
  volume INTEGER, turnover REAL,
  PRIMARY KEY (code, date)
);
```

---

## 4. 使用ライブラリ

```
yfinance      # ①日足取得
pandas        # データ処理全般
pandas-ta     # EMA/RSI/ADX/ATR/MACD等の標準テクニカル指標
plotly        # チャート描画
streamlit     # アプリ本体・UI
pytest        # 指標計算の回帰テスト
```

(SQLiteはPython標準の`sqlite3`で足りるため追加ライブラリ不要。将来DBを本格的に育てるならSQLAlchemyの追加を検討)

---

## 5. データフロー

1. `config/watchlist.csv`に銘柄を登録(手動)
2. `scripts/fetch_all.py`実行 → `lib/fetch.py`(日足取得)→`lib/transform.py`(週足変換)→`price_weekly`テーブルへ保存
3. Streamlitアプリ(`streamlit run app/Home.py`)を開いて研究サイクルを回す
   - **①Market Leaders画面**: 過去の「市場の主役」だった銘柄(キオクシア、フジクラ等)を登録・閲覧
   - **②Entries画面**: 「この銘柄のこの週なら買いたかった」を登録(例: フジクラ 2024-02-05)
   - **③Chart Viewer画面**: 銘柄を選ぶ→週足チャート表示→EMA16・出来高・売買代金など`lib/indicators/`のレジストリにある指標をチェックボックスでON/OFF
   - **④Feature Extractor画面**: Entry DBの各行について、**その週時点で使えたデータだけ**を使い、レジストリ内の全指標を計算して`entry_features`に保存
   - **⑤Hypotheses画面**: 仮説を自由記述で登録、ステータス管理
4. (半年後以降・未実装) `scripts/weekly_scan.py`が全銘柄×最新週の特徴量を一括計算し、スコアリングモデルでランキング化して日曜に表示

### 重要な設計上の注意: ルックアヘッドバイアスの防止

④の特徴量抽出は、**必ず「entry_week時点で確定していたデータ」だけ**を使う。具体的には、`entry_week`以前の週足データだけを切り出してから指標を計算する(52週高値なら「entry_week以前の52週分」のウィンドウ、EMAも同様に過去データのみで計算)。未来のデータが1行でも混入すると、検証結果全体が信用できなくなるため、Feature Extractorの実装では最優先でテストを書く箇所にする。

---

## 6. 今後半年間の開発ロードマップ

| 月 | 内容 |
|---|---|
| **Month 1** | DB設計を実装(SQLite+スキーマ)。①Market Leader DB のCRUD+Streamlit画面。前回資産(fetch/transform)を`lib/`に統合 |
| **Month 2** | ②Entry DB のCRUD+Streamlit画面。③Chart Viewer実装(ローソク足+EMA16+出来高+売買代金のON/OFF)。indicatorsレジストリの土台を作り、EMA25/75・RSI・ADX・ATR・MACDを順次プラグイン追加 |
| **Month 3** | ④Feature Extractor実装。ルックアヘッドバイアス防止のロジックとテストを重点実装。Entry登録→特徴量自動計算のフローを確立 |
| **Month 4** | ⑤Hypothesis Manager実装。過去の市場の主役銘柄(例に挙がった10銘柄程度)で実際にEntry登録→特徴量抽出→仮説記録、という研究サイクルを一通り回してみる |
| **Month 5** | 対象銘柄を拡大する準備。週次バッチの高速化・エラーハンドリング強化。過去の「市場の主役」候補をさらに追加登録 |
| **Month 6** | 週次全銘柄スキャンの土台を作る(全銘柄分の週足データを安定的に更新できる状態まで)。**スコアリングモデルの実装はここでは行わず、次フェーズに持ち越す** |

---

## 前回プロジェクト(jp-stock-superperformer-research)との関係

前回作った`fetch.py`(①日足取得)・`transform.py`(週足変換)はロジックがほぼそのまま使えるため、`lib/`にコピーして再利用する。前回のプロジェクトフォルダ自体は残し、今回は別フォルダ(`market-leader-engine`)として独立させる(思想が異なるプロジェクトのため)。

---

## 承認いただきたいポイント

1. 技術選定(Streamlit + plotly + pandas-ta + SQLite)でよいか
2. DB設計(固定列+JSON自由項目、特徴量だけtidy縦持ち)の方針でよいか
3. 半年ロードマップの粒度・順序でよいか(①②→③→④→⑤→拡大→スキャン土台、という順番)
