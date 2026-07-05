# 折りたたみ時バーのみ表示 + 手動更新ボタン Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 折りたたみ時のウィジェットを文字なし・バー3本+⟳▼アイコンだけの低い1行にし、追加クレジットをバー化(月間制限=100%)、連打安全な手動更新ボタンを追加する。

**Architecture:** 単一ファイル `claude_usage_widget.py` の tkinter アプリ。`_Bar` をCanvasのみに簡素化し、スリムバー行から全ラベルを除去。追加クレジット使用率は純粋関数 `extra_percent()` に切り出す。`Poller` に `_in_flight` フラグを追加し、fetch スレッドの多重起動を防ぐ。

**Tech Stack:** Python 3.11+ / tkinter / pytest(既存 `tests/` は `import claude_usage_widget as w` スタイル)

**Spec:** `docs/superpowers/specs/2026-07-05-bars-only-collapsed-view-design.md`

## Global Constraints

- 折りたたみ時に文字を表示しない(通常時)。エラー時のステータス行(文字)は現行どおり表示する。
- 追加クレジットバーのN/A条件: `extra_enabled` 偽 / `extra_used` or `extra_limit` が None / `extra_limit <= 0` → グレーの空バー。
- バーCanvasは幅80px・高さ `BAR_HEIGHT = 8`。行の pady は 2。
- 展開後の詳細パネル・ドラッグ移動・トレイ・更新間隔設定の挙動は変更しない。
- コミットメッセージ末尾に `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` を付ける。
- テスト実行はリポジトリルートで `python -m pytest tests/ -v`。

---

### Task 1: extra_percent() 純粋関数

**Files:**
- Modify: `claude_usage_widget.py` (bar_color の直後、fmt_reset の前に追加)
- Test: `tests/test_core.py`(末尾に追加)

**Interfaces:**
- Consumes: `UsageSnapshot`(既存 dataclass: `extra_enabled: bool`, `extra_used: float | None`, `extra_limit: float | None`)
- Produces: `extra_percent(snap: UsageSnapshot) -> float | None` — Task 2 の `apply_snapshot` / `_mark_stale` が使用。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_core.py` の先頭付近の import に `import pytest` を追加し、末尾に追加:

```python
def test_extra_percent_normal():
    s = w.parse_usage(SAMPLE)  # used=12.34, limit=50.00
    assert w.extra_percent(s) == pytest.approx(24.68)


def test_extra_percent_disabled_or_missing():
    assert w.extra_percent(w.UsageSnapshot()) is None
    assert w.extra_percent(w.UsageSnapshot(
        extra_enabled=True, extra_used=1.0, extra_limit=None)) is None
    assert w.extra_percent(w.UsageSnapshot(
        extra_enabled=True, extra_used=None, extra_limit=10.0)) is None


def test_extra_percent_zero_limit():
    assert w.extra_percent(w.UsageSnapshot(
        extra_enabled=True, extra_used=0.0, extra_limit=0.0)) is None
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_core.py -v -k extra_percent`
Expected: FAIL 3件、`AttributeError: module 'claude_usage_widget' has no attribute 'extra_percent'`

- [ ] **Step 3: 最小実装**

`claude_usage_widget.py` の `bar_color()` の直後に追加:

```python
def extra_percent(snap: UsageSnapshot) -> float | None:
    """追加クレジット使用率(月間制限=100%)。表示不能ならNone。"""
    if not snap.extra_enabled:
        return None
    if snap.extra_used is None or snap.extra_limit is None:
        return None
    if snap.extra_limit <= 0:
        return None
    return snap.extra_used / snap.extra_limit * 100
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/test_core.py -v`
Expected: 全件 PASS(既存テスト含む)

- [ ] **Step 5: コミット**

```bash
git add claude_usage_widget.py tests/test_core.py
git commit -m "feat: add extra_percent() for extra-credit usage ratio

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: 折りたたみ行をバーのみ+⟳▼に作り替え

**Files:**
- Modify: `claude_usage_widget.py`(`_Bar` クラス、`UsageWidget.__init__` / `apply_snapshot` / `_mark_stale` / `refresh_prepaid` / `_edit_prepaid` / `_sep`)

**Interfaces:**
- Consumes: Task 1 の `extra_percent(snap) -> float | None`
- Produces:
  - `UsageWidget.set_refreshing(busy: bool) -> None` — Task 3 の Poller が呼ぶ。
  - `UsageWidget.on_refresh_clicked() -> None`(no-opフック)— Task 3 の main() が `poller.poll_now` に差し替える。
  - `UsageWidget.bar_extra: _Bar`

tkinter UIのため単体テストなし。Step 5 のスモークスクリプトで目視相当の検証を行う。

- [ ] **Step 1: _Bar をCanvasのみに簡素化**

`_Bar` クラス全体(現在の `class _Bar:` から `update()` の末尾まで)を以下に置き換え:

```python
BAR_HEIGHT = 8  # スリムバーのCanvas高さ(px)


class _Bar:
    """横バーのみのインジケーター(ラベル・%文字なし)。"""

    def __init__(self, parent: tk.Widget, width: int = 80):
        self.canvas = tk.Canvas(parent, width=width, height=BAR_HEIGHT, bg=BAR_BG,
                                highlightthickness=0)
        self._width = width

    def update(self, percent: float | None, severity: str | None, stale: bool = False):
        self.canvas.delete("all")
        if percent is None:
            return  # データなし=空バー(背景色のまま)
        color = COLOR_NA if stale else bar_color(percent, severity)
        fill = max(0, min(self._width, int(self._width * percent / 100)))
        self.canvas.create_rectangle(0, 0, fill, BAR_HEIGHT, fill=color, width=0)
```

- [ ] **Step 2: UsageWidget.__init__ のスリムバー部を置き換え**

「── スリムバー(1行) ──」ブロック(`self.bar_row = ...` から `self.toggle_btn.bind(...)` まで)を以下に置き換え。`_sep()` メソッドは削除する:

```python
        # ── スリムバー(バーのみ・文字なし) ─────────────
        self.bar_row = tk.Frame(root, bg=BG)
        self.bar_row.pack(fill="x", padx=8, pady=2)

        self.bar_5h = _Bar(self.bar_row)
        self.bar_5h.canvas.pack(side="left")
        self.bar_week = _Bar(self.bar_row)
        self.bar_week.canvas.pack(side="left", padx=(6, 0))
        self.bar_extra = _Bar(self.bar_row)
        self.bar_extra.canvas.pack(side="left", padx=(6, 0))

        self.toggle_btn = tk.Label(self.bar_row, text="▼", bg=BG, fg=FG_DIM,
                                   font=FONT_SMALL, cursor="hand2", pady=0)
        self.toggle_btn.pack(side="right", padx=(6, 0))
        self.toggle_btn.bind("<Button-1>", lambda e: self.toggle_detail())

        self.refresh_btn = tk.Label(self.bar_row, text="⟳", bg=BG, fg=FG_DIM,
                                    font=FONT_SMALL, cursor="hand2", pady=0)
        self.refresh_btn.pack(side="right", padx=(6, 0))
        self.refresh_btn.bind("<Button-1>", lambda e: self.on_refresh_clicked())
```

ドラッグ移動のバインド(`for widget in (root, self.bar_row):` のループ)は変更しない。
root へのバインドは tkinter の bindtags により配下の全ウィジェット(バーCanvas含む)に
伝播するため、バー上でもドラッグは従来どおり機能する。

`__init__` 末尾の `self.refresh_prepaid()` 呼び出しを削除する。

- [ ] **Step 3: 表示更新系メソッドの差し替え**

`apply_snapshot` を以下に置き換え(extra_label への参照を除去し bar_extra を更新):

```python
    def apply_snapshot(self, snap: UsageSnapshot):
        self.snapshot = snap
        self.bar_5h.update(snap.five_hour_pct, self._sev("session"))
        self.bar_week.update(snap.seven_day_pct, self._sev("weekly_all"))
        self.bar_extra.update(extra_percent(snap), None)
        self.set_status("", FG_DIM)
        if self.detail_visible:
            self._rebuild_detail()
```

`_mark_stale` を以下に置き換え:

```python
    def _mark_stale(self):
        if self.snapshot is not None:
            self.bar_5h.update(self.snapshot.five_hour_pct, self._sev("session"), stale=True)
            self.bar_week.update(self.snapshot.seven_day_pct, self._sev("weekly_all"),
                                 stale=True)
            self.bar_extra.update(extra_percent(self.snapshot), None, stale=True)
```

`refresh_prepaid` メソッドを丸ごと削除し(prepaid_label 消滅のため。詳細パネルは `_rebuild_detail` が描画する)、`_edit_prepaid` 内の `self.refresh_prepaid()` の行を削除する(直後の `if self.detail_visible: self._rebuild_detail()` はそのまま)。

`set_refreshing` と `on_refresh_clicked` フックを `_mark_stale` の直後に追加:

```python
    def set_refreshing(self, busy: bool):
        self.refresh_btn.config(fg=BAR_BG if busy else FG_DIM)

    def on_refresh_clicked(self):
        pass  # main() で Poller.poll_now に差し替え
```

- [ ] **Step 4: 既存テストが通ることを確認**

Run: `python -m pytest tests/ -v`
Expected: 全件 PASS(UIは未テスト領域のため回帰なし)

- [ ] **Step 5: スモークスクリプトで折りたたみ高さと描画を確認**

スクラッチパッドに `smoke_ui.py` を作成:

```python
import copy
import tkinter as tk
import claude_usage_widget as w

root = tk.Tk()
widget = w.UsageWidget(root, copy.deepcopy(w.DEFAULT_CONFIG))
snap = w.parse_usage({
    "five_hour": {"utilization": 75.0, "resets_at": None},
    "seven_day": {"utilization": 30.0, "resets_at": None},
    "extra_usage": {"is_enabled": True, "monthly_limit": 5000,
                    "used_credits": 1234.0, "decimal_places": 2},
    "limits": [],
})
widget.apply_snapshot(snap)
root.update_idletasks()
print("collapsed height:", root.winfo_reqheight())
widget.set_refreshing(True)
widget.set_refreshing(False)
widget.toggle_detail()
root.update_idletasks()
print("expanded height:", root.winfo_reqheight())
root.destroy()
```

Run: `python <scratchpad>/smoke_ui.py`
Expected: 例外なく実行され、collapsed height が **20px以下**(現行は約30px)、expanded height はそれより大。

- [ ] **Step 6: コミット**

```bash
git add claude_usage_widget.py
git commit -m "feat: bars-only collapsed view with refresh/expand icons

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Poller の連打対策(_in_flight)と main() 配線

**Files:**
- Modify: `claude_usage_widget.py`(`Poller.__init__` / `poll_now` / `_fetch_bg`、`main()`)
- Create: `tests/test_poller.py`

**Interfaces:**
- Consumes: Task 2 の `UsageWidget.set_refreshing(busy)` / `on_refresh_clicked` フック
- Produces: `Poller._in_flight: bool`(内部状態)、`Poller._fetch_once()`(旧 `_fetch_bg` 本体)

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_poller.py` を新規作成:

```python
import claude_usage_widget as w


class FakeRoot:
    def __init__(self):
        self.after_calls = []

    def after(self, ms, fn=None, *args):
        self.after_calls.append((ms, fn, args))
        return f"id{len(self.after_calls)}"

    def after_cancel(self, after_id):
        pass


class FakeWidget:
    def __init__(self):
        self.config = {"poll_interval_sec": 60}

    def set_refreshing(self, busy):
        pass

    def set_status(self, text, color):
        pass


class FakeThread:
    instances = []

    def __init__(self, target=None, daemon=None):
        self.target = target
        FakeThread.instances.append(self)

    def start(self):
        pass  # 起動しない。テストが target() を同期実行する


def _boom():
    raise OSError("no creds")


def make_poller(monkeypatch):
    FakeThread.instances = []
    monkeypatch.setattr(w.threading, "Thread", FakeThread)
    monkeypatch.setattr(w, "load_credentials", _boom)
    return w.Poller(FakeRoot(), FakeWidget())


def test_poll_now_skips_while_in_flight(monkeypatch):
    p = make_poller(monkeypatch)
    p.poll_now()
    p.poll_now()  # 連打
    p.poll_now()
    assert len(FakeThread.instances) == 1
    assert p._in_flight is True


def test_fetch_bg_clears_flag_even_on_error(monkeypatch):
    p = make_poller(monkeypatch)
    p.poll_now()
    FakeThread.instances[0].target()  # ワーカー本体を同期実行(load_credentialsが例外)
    assert p._in_flight is False


def test_poll_now_allows_next_after_completion(monkeypatch):
    p = make_poller(monkeypatch)
    p.poll_now()
    FakeThread.instances[0].target()
    p.poll_now()
    assert len(FakeThread.instances) == 2


def test_refresh_indicator_signals_start_and_end(monkeypatch):
    p = make_poller(monkeypatch)
    widget = p.widget
    p.poll_now()
    FakeThread.instances[0].target()
    ui_calls = [(fn, args) for ms, fn, args in p.root.after_calls if ms == 0]
    assert (widget.set_refreshing, (True,)) == ui_calls[0]
    assert (widget.set_refreshing, (False,)) == ui_calls[-1]
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_poller.py -v`
Expected: FAIL(`test_poll_now_skips_while_in_flight` で instances が3件、`_in_flight` AttributeError など)

- [ ] **Step 3: Poller を実装**

`Poller.__init__` に `self._in_flight = False` を追加し、`poll_now` を以下に置き換え:

```python
    def poll_now(self):
        self.reschedule(int(self.widget.config.get("poll_interval_sec", 60)))
        if self._in_flight:
            return  # fetch実行中の連打・タイマー発火は無視(タイマーは再設定済み)
        self._in_flight = True
        self._ui(self.widget.set_refreshing, True)
        threading.Thread(target=self._fetch_bg, daemon=True).start()
```

既存 `_fetch_bg` を `_fetch_once` にリネームし(本体は無変更)、新しい `_fetch_bg` を追加:

```python
    def _fetch_bg(self):
        try:
            self._fetch_once()
        finally:
            self._in_flight = False
            self._ui(self.widget.set_refreshing, False)
```

`main()` の `widget.on_interval_changed = poller.reschedule` の直後に追加:

```python
    widget.on_refresh_clicked = poller.poll_now
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/ -v`
Expected: 全件 PASS

- [ ] **Step 5: コミット**

```bash
git add claude_usage_widget.py tests/test_poller.py
git commit -m "feat: manual refresh button with in-flight guard against double-fetch

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: README 更新と実機確認

**Files:**
- Modify: `README.md`(機能一覧の3行)

**Interfaces:**
- Consumes: Task 2/3 の完成したUI
- Produces: なし(ドキュメントと最終確認のみ)

- [ ] **Step 1: README の機能一覧を更新**

`README.md` の機能一覧のうち以下の2行:

```markdown
- 追加使用クレジット(extra usage)の残額を自動取得
- APIプリペイド残高の手動記録欄
- ▼クリックで詳細パネル(モデル別制限の一覧、更新間隔設定)
```

を以下に置き換え:

```markdown
- 追加使用クレジット(extra usage)の使用率バー(月間制限=100%)
- APIプリペイド残高の手動記録欄(詳細パネル内)
- 折りたたみ時はバー3本と⟳(手動更新)▼(展開)のみのスリム表示
- ▼クリックで詳細パネル(モデル別制限の一覧、金額、更新間隔設定)
```

- [ ] **Step 2: 実機確認**

Run: `python claude_usage_widget.py`(手動)
確認項目:
1. 折りたたみ時に文字がなくバー3本+⟳▼のみで、高さが以前より明確に低い
2. ⟳クリックで即時更新され、取得中は⟳がグレー
3. ⟳を素早く連打してもエラーや二重更新が起きない
4. ▼で詳細パネル(文字あり)が開き、APIプリペイドの編集が動く
5. バー部分を含めてドラッグ移動できる
終了はトレイの「終了」。

- [ ] **Step 3: コミット**

```bash
git add README.md
git commit -m "docs: README for bars-only collapsed view and refresh button

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
