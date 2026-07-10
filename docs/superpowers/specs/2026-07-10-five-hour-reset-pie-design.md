# 5時間リセットモニタ(パイ表示) 設計書

日付: 2026-07-10
対象: `claude_usage_widget.pyw`

## 目的

5時間ウィンドウのリセットタイミングを折りたたみ状態でも把握できるようにする。
文字は使わず(行の高さ12pxを維持)、既存の水平バー3本と混同しない
グラフィックで表示する。

モックアップ比較(パイ / リング / 縦ミニバー)の結果、実寸12pxで唯一
視認性が成立した**パイ(円形タイマー)**を採用。リングは弧が細すぎて⟳とも
紛らわしく、縦ミニバーは点にしか見えなかった。

## 折りたたみ時のレイアウト

```
┌──────────────────────────────────┐
│ ████░░░ ███░░░░ █░░░░░░ ◔  ⟳ ▼ │
└──────────────────────────────────┘
   5h      週     追加     リセット
                           パイ
```

- 3本目のバー(追加クレジット)の右、⟳ の左に 12×12px の Canvas を配置。
  左に padx=(6, 0) の間隔(バー間と同じ)。
- パイは12時位置から時計回りに**残り時間**の割合を塗る
  (ポモドーロタイマー風。開始直後=満タン → リセット直前=ほぼ空)。
- 色は `FG_DIM` 固定+同色1px輪郭の円。使用率バーの緑/黄/赤と意味が
  競合しないようにする。stale 表現も不要(元々グレーのため)。
- クリック操作なし(純粋な表示)。カーソルはデフォルトのまま
  (hand2 にしない=ボタンと誤認させない)。

## 残り割合の計算

- 純粋関数 `reset_remaining_fraction(resets_at, now, window_sec=5*3600)
  -> float | None` を追加。
  - `resets_at` が None → None(空円=輪郭のみ描画)。
  - `(resets_at - now) / window` を 0.0〜1.0 にクランプ。
    過去時刻 → 0.0(空)、5時間超先 → 1.0(満タン)。
  - 引数は timezone-aware datetime 前提(APIの `resets_at` は +00:00 付き、
    now は `datetime.now(timezone.utc)` 等を渡す)。
- データ源はスナップショットの `limits` から `kind == "session"` の
  `resets_at` を優先し、なければ `snap.five_hour_resets` にフォールバック。
  取り出しはヘルパー `session_resets_at(snap) -> datetime | None` として
  切り出し単体テスト可能にする(スナップショット None も None を返す)。

## 再描画タイミング

1. `apply_snapshot()` 時(fetch成功のたび)。
2. `root.after` による60秒ごとのローカルタイマー(`UsageWidget` 内、
   `__init__` でスケジュール開始し、コールバック末尾で再スケジュール)。

API呼び出しは一切増えない(残り時間は取得済み `resets_at` からの純計算)。
usage API はレート制限が厳しいため、ポーリング頻度には触れない。

- リセット時刻を過ぎたら空円のまま次の fetch 成功を待つ。新しい
  `resets_at` が来れば自動的に満タンへ戻る(タイマー側で fetch は誘発しない)。
- 通信エラー・レート制限中もパイは手元の `resets_at` で動き続ける
  (バーの stale グレー化とは独立)。

## 実装構造

- `_Bar` と同様の小クラス `_ResetPie` を追加:
  - `__init__(parent)`: 12×12 Canvas 生成(bg=BG, highlightthickness=0)。
  - `update(fraction: float | None)`: 全消去 → 輪郭円
    (`create_oval`, outline=FG_DIM)→ fraction が None/0 でなければ
    `create_arc(style="pieslice", start=90, extent=-360*fraction,
    fill=FG_DIM)`(tk は反時計回りが正なので負の extent で時計回り)。
  - 注意: tk の arc は extent がちょうど ±360 だと 0 扱いになり何も
    描かれない。fraction が 1.0 近傍(extent ≦ -359.9)の場合は
    `create_oval` の塗りつぶしで満円を描く。
- `UsageWidget.__init__` で `bar_extra` の直後に pack。
- `UsageWidget._tick_reset_pie()`: `session_resets_at` → 
  `reset_remaining_fraction` → `_ResetPie.update`、最後に
  `root.after(60_000, self._tick_reset_pie)`。TclError はウィンドウ破棄時
  なので握りつぶして再スケジュールしない。

## 変更しない点

- 展開後の詳細パネル(リセット絶対時刻の表示を含む)は現行のまま。
- ポーリング間隔・エラー処理・トレイ・ドラッグ移動の挙動。
- 週間リセットは対象外(詳細パネルの時刻表示で足りる)。

## テスト

- `reset_remaining_fraction()`: None → None、過去時刻 → 0.0、
  ちょうど5時間先 → 1.0、5時間超先 → 1.0 にクランプ、
  2.5時間先 → 0.5、tz付き入力で正しく計算。
- `session_resets_at()`: session エントリあり → その時刻、
  limits 空 → `five_hour_resets` フォールバック、両方なし → None、
  スナップショット None → None。
- 描画(`_ResetPie`)はテストしない(既存UI層と同じ方針)。

## README 追記

折りたたみ表示の説明にパイ(5時間リセットまでの残り時間)を1行追加。
