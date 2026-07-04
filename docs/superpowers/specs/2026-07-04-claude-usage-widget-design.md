# claude-usage-widget 設計書

日付: 2026-07-04
ステータス: 承認待ち

## 目的

Claudeサブスクリプション(Pro/Max)の使用量残量を、Windowsデスクトップ上で常時モニタリングできる常駐ツールを作る。GitHubで公開する。

表示対象:

1. **5時間セッション使用率** — バー+%表示、リセット時刻併記
2. **週間制限使用率** — バー+%表示、リセット日時併記
3. **追加使用クレジット (extra usage)** — 残額を実数(USD)表示、自動取得
4. **APIプリペイド残高 (Console)** — 実数(USD)表示、手動更新(公開APIが存在しないため)

## データ取得

### 使用量API(1〜3の情報源)

- エンドポイント: `GET https://api.anthropic.com/api/oauth/usage`
  (Claude Codeの`/usage`コマンドが使う非公開APIと同一。動作確認済み)
- ヘッダー: `Authorization: Bearer <accessToken>`、`anthropic-beta: oauth-2025-04-20`
- トークン: 毎ポーリング時に `~/.claude/.credentials.json` の `claudeAiOauth.accessToken` を読み取る
- 使用するレスポンスフィールド:
  - `five_hour.utilization` / `five_hour.resets_at`
  - `seven_day.utilization` / `seven_day.resets_at`
  - `limits[]` — kind/percent/severity/resets_at/scope を持つ配列。モデル別制限
    (例: Fable週間12%)もここに入る。**スコープを特定モデルにハードコードせず、
    配列を汎用的に列挙表示する**
  - `extra_usage.monthly_limit` / `extra_usage.used_credits` / `extra_usage.currency`
    (通貨最小単位。exponent=2ならセント。残額 = monthly_limit − used_credits)

### トークン期限切れの扱い

- **自前でのリフレッシュは行わない。** リフレッシュトークンはローテーションされるため、
  ウィジェット側でリフレッシュするとClaude Code本体のログインを破壊するリスクがある。
- `expiresAt`超過またはAPIが401を返した場合: ウィジェットに「⚠ Claude Codeを起動して
  ください」と表示し、以後のポーリングでcredentials.jsonの更新(Claude Code側の
  リフレッシュ)を検知したら自動復帰する。

### APIプリペイド残高(4の情報源)

- 公開APIなし(GitHub issue anthropics/claude-code#47574 参照)。
- ユーザーが詳細パネルから金額を手動入力。最終更新日を併記表示する。

## UI

### 通常時: 横長スリムバー(1行)

```
┌─────────────────────────────────────────────────────────┐
│ 5h ███████░░ 88% │ 週 ████░░░░ 43% │ 残$35.29 │ API $12.34 ▼│
└─────────────────────────────────────────────────────────┘
```

- 枠なし(overrideredirect)tkinterウィンドウ、約420×36px
- ドラッグで移動可、位置はconfigに保存
- 最前面固定(トレイメニューでON/OFF、状態を保存)
- バー色: 通常=アクセント色、80%以上=黄、95%以上=赤
  (APIの`severity`があればそれを優先)

### 展開時: 詳細パネル(▼クリックでスリムバーの下に展開)

- 5h / 週間: %とリセット日時
- `limits[]`の全エントリを汎用列挙(スコープ付き=モデル別制限も表示名で表示)
- 追加使用クレジット: 使用額 / 上限 / 残額
- APIプリペイド: 金額 + [編集]ボタン + 最終更新日
- 設定: ポーリング間隔(30秒/1分/2分/5分/10分のプルダウン)
- 再クリック(▲)で閉じる

### タスクトレイ(pystray)

- アイコン色 = 全項目の最悪severity(緑/黄/赤)。期限切れ・エラー時はグレー
- メニュー: ウィジェット表示/非表示、最前面固定、今すぐ更新、終了

## 設定ファイル

`%APPDATA%\claude-usage-widget\config.json`(リポジトリ外。個人データを
リポジトリに含めないため):

```json
{
  "poll_interval_sec": 60,
  "window_pos": [x, y],
  "always_on_top": true,
  "prepaid_balance": {"amount": 12.34, "currency": "USD", "updated_at": "2026-07-04"}
}
```

## エラー処理

- ネットワーク断・HTTP 5xx: 前回値をグレー表示+「更新失敗 HH:MM」。次回ポーリングで再試行
- HTTP 401: トークン期限切れ扱い(前述)
- レスポンス構造の変化(非公開APIのため起こりうる): 取れたフィールドだけ表示し、
  欠けた項目は「—」。例外でクラッシュさせない
- credentials.json不在: 「Claude Codeが見つかりません」表示

## リポジトリ構成(GitHub公開)

```
claude_badgets/
├── claude_usage_widget.py   # 本体(1ファイル完結)
├── requirements.txt          # requests, pystray, Pillow
├── README.md                 # セットアップ、自動起動(shell:startup)手順、
│                             #   非公開API利用の注意書き
├── LICENSE                   # MIT
├── .gitignore
└── docs/superpowers/specs/   # 本設計書
```

- トークン・残高等の個人データはコードにもリポジトリにも一切含めない
- READMEに「Claude Code内部の非公開APIを利用しており、予告なく動かなくなる
  可能性がある」旨を明記

## 依存関係

- Python 3.x(導入済み)
- `requests`(API呼び出し)、`pystray` + `Pillow`(トレイアイコン)
- UI は標準ライブラリの tkinter

## テスト方針

- API層(レスポンスのパース、残額計算、期限切れ判定)は関数として切り出し、
  実レスポンスのサンプルJSONでユニットテスト可能にする
- UI・トレイは手動確認(起動、ドラッグ、展開/収納、設定変更の永続化、
  ネットワーク断時の表示)

## 決定事項(やらないこと)

- OAuthトークンの自前リフレッシュ(Claude Codeのログインを壊すリスク)
- しきい値超過時のWindows通知(今回スコープ外。要望があれば後日)
- Consoleプリペイド残高の自動取得(公開APIが存在しない)
- Electron/Tauri等への移行(Pythonで確定)
