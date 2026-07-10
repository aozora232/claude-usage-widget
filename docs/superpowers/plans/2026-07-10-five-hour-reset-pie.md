# 5時間リセットパイモニタ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 折りたたみ行に5時間ウィンドウの残り時間を示す12×12pxのグレーパイを追加する(文字なし・高さ増なし・API呼び出し増なし)。

**Architecture:** 純粋関数2つ(`session_resets_at` / `reset_remaining_fraction`)で取得済みスナップショットから残り割合を計算し、`_Bar` と同型の小クラス `_ResetPie` がCanvasに描画する。再描画は `apply_snapshot` 時と `root.after` による60秒ローカルタイマーの2経路。

**Tech Stack:** Python 3.10+ / tkinter(標準ライブラリのみ、新規依存なし)/ pytest

**Spec:** `docs/superpowers/specs/2026-07-10-five-hour-reset-pie-design.md`

## Global Constraints

- 対象ファイルは `claude_usage_widget.pyw`(単一ファイル構成を維持)と `tests/test_core.py` と `README.md` のみ。
- 折りたたみ行の高さ12pxを維持: パイのCanvasは `ICON_SIZE`(=12)px、文字・Labelは追加しない。
- API呼び出しは一切増やさない(usage APIはレート制限が厳しい)。パイはローカル計算のみ。
- パイの色は `FG_DIM`(#8b949e)固定。緑/黄/赤は使わない。
- パイはクリック不可: `cursor` オプションは指定しない(hand2にしない)。
- コミットメッセージは既存スタイル(`feat:` / `test:` / `docs:`)+ 末尾に `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。
- テスト実行は常にリポジトリルートで `python -m pytest tests/ -v`。

---

### Task 1: 残り割合の純粋関数2つ

**Files:**
- Modify: `claude_usage_widget.pyw`(`extra_percent` 関数の直後、`fmt_reset` の前に追加。現在の行番号で186〜195付近)
- Test: `tests/test_core.py`(末尾に追加)

**Interfaces:**
- Consumes: 既存の `UsageSnapshot`(`limits: list[LimitEntry]`, `five_hour_resets: datetime | None`)、`LimitEntry`(`kind: str`, `resets_at: datetime | None`)
- Produces:
  - `FIVE_HOUR_WINDOW_SEC: int = 5 * 3600`(モジュール定数)
  - `session_resets_at(snap: UsageSnapshot | None) -> datetime | None`
  - `reset_remaining_fraction(resets_at: datetime | None, now: datetime, window_sec: float = FIVE_HOUR_WINDOW_SEC) -> float | None`
  - Task 2 はこの2つを `reset_remaining_fraction(session_resets_at(self.snapshot), now)` の形で呼ぶ。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_core.py` の末尾に追加(`SAMPLE`・`pytest`・`datetime`/`timezone` は同ファイルでimport済み):

```python
def _dt(h, m=0, tz=timezone.utc):
    return datetime(2026, 7, 10, h, m, tzinfo=tz)


def test_reset_remaining_fraction_none_and_clamp():
    now = _dt(12)
    assert w.reset_remaining_fraction(None, now) is None
    assert w.reset_remaining_fraction(_dt(11), now) == 0.0   # 過去→0
    assert w.reset_remaining_fraction(_dt(17), now) == 1.0   # ちょうど5時間先
    assert w.reset_remaining_fraction(
        datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc), now) == 1.0  # 超過→1にクランプ


def test_reset_remaining_fraction_midpoint_and_tz():
    now = _dt(12)
    assert w.reset_remaining_fraction(_dt(14, 30), now) == pytest.approx(0.5)
    # +09:00 の 23:30 は UTC 14:30 と同じ
    jst = timezone(timedelta(hours=9))
    assert w.reset_remaining_fraction(
        datetime(2026, 7, 10, 23, 30, tzinfo=jst), now) == pytest.approx(0.5)


def test_session_resets_at_prefers_session_limit():
    s = w.parse_usage(SAMPLE)  # limits[0] が kind=="session"
    assert w.session_resets_at(s) == s.limits[0].resets_at


def test_session_resets_at_fallbacks():
    assert w.session_resets_at(None) is None
    assert w.session_resets_at(w.UsageSnapshot()) is None
    fh = _dt(15)
    # limitsが空 → five_hour_resets にフォールバック
    assert w.session_resets_at(w.UsageSnapshot(five_hour_resets=fh)) == fh
    # sessionエントリはあるが resets_at=None → フォールバック
    snap = w.UsageSnapshot(five_hour_resets=fh)
    snap.limits.append(w.LimitEntry(kind="session", label="5時間", percent=10,
                                    severity="normal", resets_at=None))
    assert w.session_resets_at(snap) == fh
```

`timedelta` を同ファイルのimportに追加する:

```python
from datetime import datetime, timedelta, timezone
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_core.py -v -k "reset_remaining or session_resets"`
Expected: 4件FAIL(`AttributeError: module 'claude_usage_widget' has no attribute 'reset_remaining_fraction'` など)

- [ ] **Step 3: 最小実装を書く**

`claude_usage_widget.pyw` の `extra_percent` 関数の直後に追加:

```python
FIVE_HOUR_WINDOW_SEC = 5 * 3600


def session_resets_at(snap: UsageSnapshot | None) -> datetime | None:
    """5時間ウィンドウのリセット時刻。session limitを優先、なければfive_hour。"""
    if snap is None:
        return None
    for e in snap.limits:
        if e.kind == "session" and e.resets_at is not None:
            return e.resets_at
    return snap.five_hour_resets


def reset_remaining_fraction(resets_at: datetime | None, now: datetime,
                             window_sec: float = FIVE_HOUR_WINDOW_SEC) -> float | None:
    """リセットまでの残りをウィンドウ長に対する0.0〜1.0で返す。不明ならNone。"""
    if resets_at is None:
        return None
    remain = (resets_at - now).total_seconds() / window_sec
    return max(0.0, min(1.0, remain))
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/ -v`
Expected: 全件PASS(既存テスト含む)

- [ ] **Step 5: コミット**

```bash
git add claude_usage_widget.pyw tests/test_core.py
git commit -m "feat: pure helpers for 5-hour reset remaining fraction

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: _ResetPie クラスとUI組み込み

**Files:**
- Modify: `claude_usage_widget.pyw`
  - `_Bar` クラスの直後に `_ResetPie` クラスを追加(現在の行番号で267付近)
  - `UsageWidget.__init__`: `bar_extra` のpack直後にパイを配置、末尾でタイマー開始
  - `UsageWidget.apply_snapshot`: パイ再描画を追加
  - `UsageWidget` に `_redraw_reset_pie` / `_tick_reset_pie` メソッド追加

**Interfaces:**
- Consumes: Task 1 の `session_resets_at(snap)` と `reset_remaining_fraction(resets_at, now)`、既存定数 `ICON_SIZE`, `BG`, `FG_DIM`
- Produces: `_ResetPie`(`__init__(parent)`, `update(fraction: float | None)`)、`UsageWidget.reset_pie` 属性。後続タスクからの依存はなし。

- [ ] **Step 1: _ResetPie クラスを追加**

`_Bar` クラス定義の直後に追加:

```python
class _ResetPie:
    """5時間ウィンドウの残り時間パイ(12時位置から時計回りに残り分を塗る)。"""

    def __init__(self, parent: tk.Widget):
        self.canvas = tk.Canvas(parent, width=ICON_SIZE, height=ICON_SIZE,
                                bg=BG, highlightthickness=0)

    def update(self, fraction: float | None):
        c = self.canvas
        c.delete("all")
        box = (1, 1, ICON_SIZE - 2, ICON_SIZE - 2)
        c.create_oval(*box, outline=FG_DIM)
        if fraction is None or fraction <= 0:
            return  # 不明・リセット済み=輪郭のみの空円
        extent = -360 * fraction
        if extent <= -359.9:
            # tkのarcは±360ちょうどだと0扱いで何も描かれないため満円はovalで
            c.create_oval(*box, fill=FG_DIM, outline=FG_DIM)
        else:
            c.create_arc(*box, start=90, extent=extent, style="pieslice",
                         fill=FG_DIM, outline=FG_DIM)
```

- [ ] **Step 2: UsageWidget にパイを組み込む**

`UsageWidget.__init__` の `self.bar_extra.canvas.pack(side="left", padx=(6, 0))` の直後に追加:

```python
        self.reset_pie = _ResetPie(self.bar_row)
        self.reset_pie.canvas.pack(side="left", padx=(6, 0))
```

`__init__` の末尾(`self._place_window()` の直後)に追加:

```python
        self._tick_reset_pie()
```

`apply_snapshot` の `self.bar_extra.update(...)` の直後に1行追加:

```python
        self._redraw_reset_pie()
```

`UsageWidget` に2メソッド追加(`set_status` の直前に置く):

```python
    def _redraw_reset_pie(self):
        now = datetime.now(timezone.utc)
        self.reset_pie.update(
            reset_remaining_fraction(session_resets_at(self.snapshot), now))

    def _tick_reset_pie(self):
        try:
            self._redraw_reset_pie()
            self.root.after(60_000, self._tick_reset_pie)
        except tk.TclError:
            pass  # ウィンドウ破棄後のタイマー発火は無視(再スケジュールしない)
```

注意: `_mark_stale` には手を入れない(パイは元々グレーでstale表現不要。通信エラー中も手元の `resets_at` で動き続けるのが仕様)。

- [ ] **Step 3: コンパイルと既存テストの回帰確認**

Run: `python -m py_compile claude_usage_widget.pyw ; python -m pytest tests/ -v`
Expected: コンパイルエラーなし、全テストPASS

- [ ] **Step 4: 目視スモークテスト**

Run: `python claude_usage_widget.pyw`(手動またはユーザーに依頼)
確認項目:
- 3本目のバーの右にグレーの円が出る(行の高さは12pxのまま)
- fetch成功後、残り時間に応じた扇形が塗られる(直近にClaude使用開始があれば満タン近く)
- パイをクリックしても何も起きない(ドラッグ移動は従来どおり)
確認後ウィンドウを閉じる(トレイの「終了」)。

- [ ] **Step 5: コミット**

```bash
git add claude_usage_widget.pyw
git commit -m "feat: gray pie in collapsed row showing time to 5-hour reset

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: README 追記

**Files:**
- Modify: `README.md`(冒頭の機能リスト、現在の6〜9行目)

**Interfaces:**
- Consumes: なし(ドキュメントのみ)
- Produces: なし

- [ ] **Step 1: 機能リストを更新**

現在の行:

```markdown
- 折りたたみ時はバー3本と⟳(手動更新)▼(展開)のみのスリム表示
```

を以下の2行に置き換える:

```markdown
- 折りたたみ時はバー3本+リセットパイと⟳(手動更新)▼(展開)のみのスリム表示
- リセットパイ(グレーの円): 5時間ウィンドウのリセットまでの残り時間。
  満タン=リセット直後、空=まもなくリセット(1分ごとに自動更新、API呼び出しなし)
```

- [ ] **Step 2: コミット**

```bash
git add README.md
git commit -m "docs: README entry for 5-hour reset pie

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
