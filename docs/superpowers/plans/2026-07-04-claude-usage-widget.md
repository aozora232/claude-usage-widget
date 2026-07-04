# claude-usage-widget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claudeサブスクリプションの使用量(5h/週間/追加クレジット)+手動入力のAPIプリペイド残高を表示する、Windowsタスクトレイ常駐の横長デスクトップウィジェットを作る。

**Architecture:** 単一モジュール `claude_usage_widget.py`。純粋関数(パース・計算・設定)はモジュールレベルに置きユニットテスト対象、UI(tkinter枠なしウィンドウ)とトレイ(pystray別スレッド)は手動確認。ネットワークは背景スレッド+queueでUIをブロックしない。

**Tech Stack:** Python 3.12 / tkinter(標準) / requests / pystray / Pillow / pytest(テスト)

## Global Constraints

- 対象OS: Windows 11。パスは `pathlib.Path` を使う
- トークンは `~/.claude/.credentials.json` から毎回読み取り。**自前でOAuthリフレッシュしない**
- 設定は `%APPDATA%\claude-usage-widget\config.json`。リポジトリに個人データを含めない
- 使用API: `GET https://api.anthropic.com/api/oauth/usage`、ヘッダー `Authorization: Bearer <token>` と `anthropic-beta: oauth-2025-04-20`
- 例外でクラッシュさせない。取れないフィールドは `None` → 表示は「—」
- モデル別制限は `limits[]` を汎用列挙(特定モデル名をハードコードしない)
- テスト実行コマンドは常に `python -m pytest tests -v`(作業ディレクトリ: リポジトリルート)
- コミットメッセージ末尾に `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` を付ける

---

### Task 1: プロジェクト骨格

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `LICENSE`
- Create: `README.md`(雛形。完成はTask 8)

**Interfaces:**
- Consumes: なし
- Produces: 依存パッケージのインストール済み環境

- [ ] **Step 1: requirements.txt を作成**

```
requests>=2.31
pystray>=0.19
Pillow>=10.0
```

- [ ] **Step 2: .gitignore を作成**

```
__pycache__/
*.pyc
.pytest_cache/
venv/
.venv/
```

- [ ] **Step 3: LICENSE を作成(MIT)**

```
MIT License

Copyright (c) 2026 claude-usage-widget contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 4: README.md 雛形を作成**

```markdown
# claude-usage-widget

Claudeサブスクリプションの使用量残量をWindowsデスクトップに常時表示するウィジェット。

(セットアップ手順は実装完了後に追記)
```

- [ ] **Step 5: 依存をインストール**

Run: `pip install -r requirements.txt pytest`
Expected: 正常終了(requests / pystray / Pillow / pytest が入る)

- [ ] **Step 6: Commit**

```bash
git add requirements.txt .gitignore LICENSE README.md
git commit -m "chore: project scaffold (deps, license, gitignore)"
```

---

### Task 2: データ層 — パース・認証情報・表示ヘルパー(TDD)

**Files:**
- Create: `claude_usage_widget.py`
- Create: `tests/test_core.py`

**Interfaces:**
- Consumes: なし
- Produces(後続タスクが使う正確なシグネチャ):
  - `@dataclass LimitEntry(kind: str, label: str, percent: float, severity: str, resets_at: datetime | None)`
  - `@dataclass UsageSnapshot(five_hour_pct, five_hour_resets, seven_day_pct, seven_day_resets, limits: list[LimitEntry], extra_enabled: bool, extra_used, extra_limit, extra_remaining, fetched_at: datetime)`(pct/金額は `float | None`、resetsは `datetime | None`)
  - `parse_usage(data: dict) -> UsageSnapshot`
  - `load_credentials(path: Path) -> dict`(`claudeAiOauth` の中身を返す。不在/壊れは `FileNotFoundError`/`ValueError`)
  - `is_token_expired(creds: dict, now_ms: int) -> bool`
  - `bar_color(percent: float | None, severity: str | None) -> str`(`"#3fb950"`緑 / `"#d29922"`黄 / `"#f85149"`赤 / `"#8b949e"`グレー)
  - `fmt_reset(dt: datetime | None, now: datetime) -> str`(同日→`"15:50"`、別日→`"7/5 18:00"`、None→`"—"`)
  - 定数 `API_URL`, `CREDENTIALS_PATH`, `APP_NAME = "claude-usage-widget"`

- [ ] **Step 1: 失敗するテストを書く(`tests/test_core.py`)**

実APIレスポンス(2026-07-04取得)を縮約したサンプルで検証する:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

import claude_usage_widget as w

SAMPLE = {
    "five_hour": {"utilization": 88.0, "resets_at": "2026-07-04T15:50:00.427157+00:00"},
    "seven_day": {"utilization": 43.0, "resets_at": "2026-07-05T18:00:00.427175+00:00"},
    "extra_usage": {
        "is_enabled": True, "monthly_limit": 4000, "used_credits": 471.0,
        "currency": "USD", "decimal_places": 2, "disabled_reason": None,
    },
    "limits": [
        {"kind": "session", "group": "session", "percent": 88, "severity": "warning",
         "resets_at": "2026-07-04T15:50:00.427157+00:00", "scope": None, "is_active": True},
        {"kind": "weekly_all", "group": "weekly", "percent": 43, "severity": "normal",
         "resets_at": "2026-07-05T18:00:00.427175+00:00", "scope": None, "is_active": False},
        {"kind": "weekly_scoped", "group": "weekly", "percent": 12, "severity": "normal",
         "resets_at": "2026-07-05T18:00:00.427394+00:00",
         "scope": {"model": {"id": None, "display_name": "Fable"}, "surface": None},
         "is_active": False},
    ],
}


def test_parse_usage_main_bars():
    s = w.parse_usage(SAMPLE)
    assert s.five_hour_pct == 88.0
    assert s.seven_day_pct == 43.0
    assert s.five_hour_resets.hour == 15 and s.five_hour_resets.tzinfo is not None


def test_parse_usage_extra_credits_minor_units():
    s = w.parse_usage(SAMPLE)
    assert s.extra_enabled is True
    assert s.extra_used == 4.71
    assert s.extra_limit == 40.00
    assert s.extra_remaining == 35.29


def test_parse_usage_limits_generic_labels():
    s = w.parse_usage(SAMPLE)
    labels = [e.label for e in s.limits]
    assert labels == ["5時間", "週間", "週間 (Fable)"]
    assert s.limits[2].percent == 12


def test_parse_usage_missing_fields_dont_crash():
    s = w.parse_usage({})
    assert s.five_hour_pct is None
    assert s.extra_remaining is None
    assert s.limits == []


def test_is_token_expired():
    creds = {"accessToken": "x", "expiresAt": 1000}
    assert w.is_token_expired(creds, now_ms=1001) is True
    assert w.is_token_expired(creds, now_ms=999) is False
    assert w.is_token_expired({}, now_ms=0) is True  # expiresAt欠落は期限切れ扱い


def test_load_credentials(tmp_path: Path):
    p = tmp_path / ".credentials.json"
    p.write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok", "expiresAt": 5}}),
                 encoding="utf-8")
    creds = w.load_credentials(p)
    assert creds["accessToken"] == "tok"


def test_bar_color_thresholds():
    assert w.bar_color(50, "normal") == "#3fb950"
    assert w.bar_color(85, None) == "#d29922"      # 80%以上→黄
    assert w.bar_color(96, None) == "#f85149"      # 95%以上→赤
    assert w.bar_color(10, "warning") == "#d29922"  # severity優先
    assert w.bar_color(None, None) == "#8b949e"


def test_fmt_reset():
    now = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)
    same_day = datetime(2026, 7, 4, 15, 50, tzinfo=timezone.utc)
    other_day = datetime(2026, 7, 5, 18, 0, tzinfo=timezone.utc)
    assert w.fmt_reset(same_day, now) == "15:50"
    assert w.fmt_reset(other_day, now) == "7/5 18:00"
    assert w.fmt_reset(None, now) == "—"
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests -v`
Expected: FAIL(`ModuleNotFoundError: No module named 'claude_usage_widget'`)

- [ ] **Step 3: 実装(`claude_usage_widget.py` 新規作成)**

```python
"""claude-usage-widget: Claudeサブスクリプション使用量のデスクトップウィジェット。

Claude Codeの /usage と同じ非公開APIを利用するため、予告なく動かなくなる
可能性がある。トークンのリフレッシュは行わない(Claude Code側に任せる)。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

APP_NAME = "claude-usage-widget"
API_URL = "https://api.anthropic.com/api/oauth/usage"
CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"

COLOR_OK = "#3fb950"
COLOR_WARN = "#d29922"
COLOR_CRIT = "#f85149"
COLOR_NA = "#8b949e"

_KIND_LABELS = {"session": "5時間", "weekly_all": "週間"}


@dataclass
class LimitEntry:
    kind: str
    label: str
    percent: float
    severity: str
    resets_at: datetime | None


@dataclass
class UsageSnapshot:
    five_hour_pct: float | None = None
    five_hour_resets: datetime | None = None
    seven_day_pct: float | None = None
    seven_day_resets: datetime | None = None
    limits: list[LimitEntry] = field(default_factory=list)
    extra_enabled: bool = False
    extra_used: float | None = None
    extra_limit: float | None = None
    extra_remaining: float | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _limit_label(entry: dict) -> str:
    kind = entry.get("kind", "?")
    scope = entry.get("scope") or {}
    name = ((scope.get("model") or {}).get("display_name")
            or (scope.get("surface") or {}).get("display_name")
            if isinstance(scope.get("surface"), dict) else
            (scope.get("model") or {}).get("display_name"))
    base = _KIND_LABELS.get(kind)
    if base is None:
        base = "週間" if entry.get("group") == "weekly" else kind
    return f"{base} ({name})" if name else base


def parse_usage(data: dict) -> UsageSnapshot:
    snap = UsageSnapshot()
    fh = data.get("five_hour") or {}
    sd = data.get("seven_day") or {}
    snap.five_hour_pct = fh.get("utilization")
    snap.five_hour_resets = _parse_dt(fh.get("resets_at"))
    snap.seven_day_pct = sd.get("utilization")
    snap.seven_day_resets = _parse_dt(sd.get("resets_at"))

    for entry in data.get("limits") or []:
        if not isinstance(entry, dict) or entry.get("percent") is None:
            continue
        snap.limits.append(LimitEntry(
            kind=entry.get("kind", "?"),
            label=_limit_label(entry),
            percent=float(entry["percent"]),
            severity=entry.get("severity") or "normal",
            resets_at=_parse_dt(entry.get("resets_at")),
        ))

    extra = data.get("extra_usage") or {}
    snap.extra_enabled = bool(extra.get("is_enabled"))
    places = extra.get("decimal_places", 2) or 2
    scale = 10 ** places
    used, limit = extra.get("used_credits"), extra.get("monthly_limit")
    if used is not None:
        snap.extra_used = round(used / scale, places)
    if limit is not None:
        snap.extra_limit = round(limit / scale, places)
    if snap.extra_used is not None and snap.extra_limit is not None:
        snap.extra_remaining = round(snap.extra_limit - snap.extra_used, places)
    return snap


def load_credentials(path: Path = CREDENTIALS_PATH) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    oauth = raw.get("claudeAiOauth")
    if not isinstance(oauth, dict):
        raise ValueError("claudeAiOauth section missing")
    return oauth


def is_token_expired(creds: dict, now_ms: int) -> bool:
    expires = creds.get("expiresAt")
    if not isinstance(expires, (int, float)):
        return True
    return now_ms > expires


def bar_color(percent: float | None, severity: str | None) -> str:
    if severity == "critical":
        return COLOR_CRIT
    if severity == "warning":
        return COLOR_WARN
    if percent is None:
        return COLOR_NA
    if percent >= 95:
        return COLOR_CRIT
    if percent >= 80:
        return COLOR_WARN
    return COLOR_OK


def fmt_reset(dt: datetime | None, now: datetime) -> str:
    if dt is None:
        return "—"
    if dt.astimezone(now.tzinfo).date() == now.date():
        return dt.astimezone(now.tzinfo).strftime("%H:%M")
    local = dt.astimezone(now.tzinfo)
    return f"{local.month}/{local.day} {local.strftime('%H:%M')}"
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add claude_usage_widget.py tests/test_core.py
git commit -m "feat: usage parsing, credentials loading, display helpers"
```

---

### Task 3: 設定管理(TDD)

**Files:**
- Modify: `claude_usage_widget.py`(末尾に追記)
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: `APP_NAME`(Task 2)
- Produces:
  - `DEFAULT_CONFIG: dict`
  - `config_path() -> Path`(`%APPDATA%/claude-usage-widget/config.json`)
  - `load_config(path: Path | None = None) -> dict`(不在・壊れ→デフォルト。既知キーへマージ)
  - `save_config(cfg: dict, path: Path | None = None) -> None`(親ディレクトリ自動作成)

- [ ] **Step 1: 失敗するテストを書く(`tests/test_config.py`)**

```python
import json
from pathlib import Path

import claude_usage_widget as w


def test_load_config_missing_returns_defaults(tmp_path: Path):
    cfg = w.load_config(tmp_path / "nope.json")
    assert cfg == w.DEFAULT_CONFIG
    assert cfg is not w.DEFAULT_CONFIG  # コピーであること


def test_load_config_merges_partial_and_ignores_broken(tmp_path: Path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"poll_interval_sec": 300}), encoding="utf-8")
    cfg = w.load_config(p)
    assert cfg["poll_interval_sec"] == 300
    assert cfg["always_on_top"] is True  # デフォルト補完

    p.write_text("{broken json", encoding="utf-8")
    assert w.load_config(p) == w.DEFAULT_CONFIG


def test_save_and_reload_roundtrip(tmp_path: Path):
    p = tmp_path / "sub" / "config.json"  # 親ディレクトリなし
    cfg = w.load_config(p)
    cfg["poll_interval_sec"] = 120
    cfg["prepaid_balance"] = {"amount": 12.34, "currency": "USD", "updated_at": "2026-07-04"}
    w.save_config(cfg, p)
    again = w.load_config(p)
    assert again["poll_interval_sec"] == 120
    assert again["prepaid_balance"]["amount"] == 12.34


def test_config_path_under_appdata(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert w.config_path() == tmp_path / "claude-usage-widget" / "config.json"
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL(`AttributeError: ... has no attribute 'load_config'` 等)

- [ ] **Step 3: 実装(`claude_usage_widget.py` に追記)**

```python
import copy
import os

DEFAULT_CONFIG = {
    "poll_interval_sec": 60,
    "window_pos": None,           # [x, y] or None(None=画面右下に初期配置)
    "always_on_top": True,
    "prepaid_balance": {"amount": None, "currency": "USD", "updated_at": None},
}


def config_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME / "config.json"


def load_config(path: Path | None = None) -> dict:
    path = path or config_path()
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key in cfg:
                if key in data:
                    cfg[key] = data[key]
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg: dict, path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
```

(`import copy` / `import os` はファイル先頭のimport群にまとめる)

- [ ] **Step 4: 全テストが通ることを確認**

Run: `python -m pytest tests -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add claude_usage_widget.py tests/test_config.py
git commit -m "feat: config load/save under APPDATA"
```

---

### Task 4: APIクライアント(TDD、requestsモック)

**Files:**
- Modify: `claude_usage_widget.py`(追記)
- Create: `tests/test_fetch.py`

**Interfaces:**
- Consumes: `API_URL`(Task 2)
- Produces:
  - `class TokenExpiredError(Exception)`
  - `class FetchError(Exception)`(メッセージに状態を含む)
  - `fetch_usage(token: str, timeout: float = 10) -> dict`(200→JSON dict、401→`TokenExpiredError`、その他HTTP/ネットワークエラー→`FetchError`)

- [ ] **Step 1: 失敗するテストを書く(`tests/test_fetch.py`)**

```python
from unittest import mock

import pytest
import requests

import claude_usage_widget as w


def _resp(status: int, payload: dict | None = None):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = payload or {}
    return r


def test_fetch_usage_success():
    with mock.patch.object(w.requests, "get", return_value=_resp(200, {"five_hour": {}})) as g:
        data = w.fetch_usage("tok")
    assert data == {"five_hour": {}}
    _, kwargs = g.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer tok"
    assert kwargs["headers"]["anthropic-beta"] == "oauth-2025-04-20"


def test_fetch_usage_401_raises_token_expired():
    with mock.patch.object(w.requests, "get", return_value=_resp(401)):
        with pytest.raises(w.TokenExpiredError):
            w.fetch_usage("tok")


def test_fetch_usage_500_raises_fetch_error():
    with mock.patch.object(w.requests, "get", return_value=_resp(500)):
        with pytest.raises(w.FetchError):
            w.fetch_usage("tok")


def test_fetch_usage_network_error_raises_fetch_error():
    with mock.patch.object(w.requests, "get", side_effect=requests.ConnectionError("boom")):
        with pytest.raises(w.FetchError):
            w.fetch_usage("tok")
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_fetch.py -v`
Expected: FAIL(`AttributeError: ... no attribute 'fetch_usage'` 等)

- [ ] **Step 3: 実装(`claude_usage_widget.py` に追記)**

```python
import requests


class TokenExpiredError(Exception):
    pass


class FetchError(Exception):
    pass


def fetch_usage(token: str, timeout: float = 10) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.get(API_URL, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        raise FetchError(f"network error: {e}") from e
    if resp.status_code == 401:
        raise TokenExpiredError("access token rejected (401)")
    if resp.status_code != 200:
        raise FetchError(f"HTTP {resp.status_code}")
    try:
        return resp.json()
    except ValueError as e:
        raise FetchError("invalid JSON response") from e
```

(`import requests` はファイル先頭のimport群へ)

- [ ] **Step 4: 全テストが通ることを確認**

Run: `python -m pytest tests -v`
Expected: 16 passed

- [ ] **Step 5: 実APIで動作確認(スモーク)**

Run: `python -c "import claude_usage_widget as w; c=w.load_credentials(); d=w.fetch_usage(c['accessToken']); s=w.parse_usage(d); print(s.five_hour_pct, s.seven_day_pct, s.extra_remaining)"`
Expected: `88.0 43.0 35.29` のような実数値が出力される(値は実行時点の実データ)

- [ ] **Step 6: Commit**

```bash
git add claude_usage_widget.py tests/test_fetch.py
git commit -m "feat: usage API client with 401/network error handling"
```

---

### Task 5: スリムバーUI(枠なしウィンドウ・バー描画・ドラッグ移動)

**Files:**
- Modify: `claude_usage_widget.py`(追記)

**Interfaces:**
- Consumes: `UsageSnapshot`, `bar_color`, `fmt_reset`, `load_config`, `save_config`(Task 2–3)
- Produces:
  - `class UsageWidget`:
    - `__init__(self, root: tk.Tk, config: dict)`
    - `apply_snapshot(self, snap: UsageSnapshot) -> None` — スリムバー表示を更新
    - `set_status(self, text: str, color: str) -> None` — エラー/警告文を表示(空文字で消す)
    - `self.detail_visible: bool`、`self.toggle_detail()`(このタスクでは何もしないプレースホルダではなく、Task 6で本実装するため**このタスクでは▼ボタンとメソッド枠のみ定義し、パネルはTask 6で追加**)
  - `main()` 関数と `if __name__ == "__main__": main()`(この時点では1回fetchして表示するだけ。ポーリングはTask 7)

- [ ] **Step 1: UIコードを実装(`claude_usage_widget.py` に追記)**

```python
import threading
import tkinter as tk
from tkinter import font as tkfont

BG = "#1c2128"
FG = "#e6edf3"
FG_DIM = "#8b949e"
BAR_BG = "#30363d"
FONT = ("Yu Gothic UI", 9)
FONT_SMALL = ("Yu Gothic UI", 8)


class _Bar:
    """ラベル+横バー+%表示のひとかたまり。"""

    def __init__(self, parent: tk.Widget, label: str, width: int = 80):
        self.frame = tk.Frame(parent, bg=BG)
        tk.Label(self.frame, text=label, bg=BG, fg=FG, font=FONT).pack(side="left")
        self.canvas = tk.Canvas(self.frame, width=width, height=12, bg=BAR_BG,
                                highlightthickness=0)
        self.canvas.pack(side="left", padx=(4, 4), pady=2)
        self.pct_label = tk.Label(self.frame, text="—", bg=BG, fg=FG, font=FONT, width=4,
                                  anchor="w")
        self.pct_label.pack(side="left")
        self._width = width

    def update(self, percent: float | None, severity: str | None):
        self.canvas.delete("all")
        color = bar_color(percent, severity)
        if percent is not None:
            fill = max(0, min(self._width, int(self._width * percent / 100)))
            self.canvas.create_rectangle(0, 0, fill, 12, fill=color, width=0)
            self.pct_label.config(text=f"{percent:.0f}%", fg=color)
        else:
            self.pct_label.config(text="—", fg=FG_DIM)


class UsageWidget:
    def __init__(self, root: tk.Tk, config: dict):
        self.root = root
        self.config = config
        self.detail_visible = False
        self.snapshot: UsageSnapshot | None = None

        root.overrideredirect(True)
        root.configure(bg=BG)
        root.attributes("-topmost", bool(config.get("always_on_top", True)))

        # ── スリムバー(1行) ─────────────────────────
        self.bar_row = tk.Frame(root, bg=BG)
        self.bar_row.pack(fill="x", padx=8, pady=4)

        self.bar_5h = _Bar(self.bar_row, "5h")
        self.bar_5h.frame.pack(side="left")
        self._sep()
        self.bar_week = _Bar(self.bar_row, "週")
        self.bar_week.frame.pack(side="left")
        self._sep()
        self.extra_label = tk.Label(self.bar_row, text="残 —", bg=BG, fg=FG, font=FONT)
        self.extra_label.pack(side="left")
        self._sep()
        self.prepaid_label = tk.Label(self.bar_row, text="API —", bg=BG, fg=FG, font=FONT)
        self.prepaid_label.pack(side="left")

        self.toggle_btn = tk.Label(self.bar_row, text="▼", bg=BG, fg=FG_DIM, font=FONT,
                                   cursor="hand2")
        self.toggle_btn.pack(side="right", padx=(6, 0))
        self.toggle_btn.bind("<Button-1>", lambda e: self.toggle_detail())

        # ステータス行(エラー時のみ文字が入る)
        self.status_label = tk.Label(root, text="", bg=BG, fg=FG_DIM, font=FONT_SMALL,
                                     anchor="w")

        # ── ドラッグ移動 ─────────────────────────
        for widget in (root, self.bar_row):
            widget.bind("<Button-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._on_drag)
            widget.bind("<ButtonRelease-1>", self._end_drag)
        self._drag_offset = None

        self._place_window()
        self.refresh_prepaid()

    def _sep(self):
        tk.Label(self.bar_row, text="│", bg=BG, fg=BAR_BG, font=FONT).pack(side="left",
                                                                            padx=4)

    def _place_window(self):
        pos = self.config.get("window_pos")
        self.root.update_idletasks()
        if pos and isinstance(pos, list) and len(pos) == 2:
            self.root.geometry(f"+{int(pos[0])}+{int(pos[1])}")
        else:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            self.root.geometry(f"+{sw - 480}+{sh - 120}")

    # ── ドラッグ ─────────────────────────
    def _start_drag(self, e):
        self._drag_offset = (e.x_root - self.root.winfo_x(),
                             e.y_root - self.root.winfo_y())

    def _on_drag(self, e):
        if self._drag_offset:
            self.root.geometry(f"+{e.x_root - self._drag_offset[0]}"
                               f"+{e.y_root - self._drag_offset[1]}")

    def _end_drag(self, e):
        if self._drag_offset:
            self.config["window_pos"] = [self.root.winfo_x(), self.root.winfo_y()]
            save_config(self.config)
        self._drag_offset = None

    # ── 表示更新 ─────────────────────────
    def apply_snapshot(self, snap: UsageSnapshot):
        self.snapshot = snap
        now = datetime.now().astimezone()
        self.bar_5h.update(snap.five_hour_pct, self._sev("session"))
        self.bar_week.update(snap.seven_day_pct, self._sev("weekly_all"))
        if snap.extra_enabled and snap.extra_remaining is not None:
            self.extra_label.config(text=f"残 ${snap.extra_remaining:.2f}", fg=FG)
        else:
            self.extra_label.config(text="残 —", fg=FG_DIM)
        self.set_status("", FG_DIM)

    def _sev(self, kind: str) -> str | None:
        if not self.snapshot:
            return None
        for e in self.snapshot.limits:
            if e.kind == kind:
                return e.severity
        return None

    def refresh_prepaid(self):
        bal = self.config.get("prepaid_balance") or {}
        amount = bal.get("amount")
        if amount is None:
            self.prepaid_label.config(text="API —", fg=FG_DIM)
        else:
            self.prepaid_label.config(text=f"API ${amount:.2f}", fg=FG)

    def set_status(self, text: str, color: str):
        if text:
            self.status_label.config(text=text, fg=color)
            self.status_label.pack(fill="x", padx=8, pady=(0, 3))
        else:
            self.status_label.pack_forget()

    def toggle_detail(self):
        pass  # Task 6 で実装


def main():
    config = load_config()
    root = tk.Tk()
    widget = UsageWidget(root, config)

    def initial_fetch():
        try:
            creds = load_credentials()
            data = fetch_usage(creds["accessToken"])
            snap = parse_usage(data)
            root.after(0, widget.apply_snapshot, snap)
        except Exception as e:
            root.after(0, widget.set_status, f"取得失敗: {e}", COLOR_WARN)

    threading.Thread(target=initial_fetch, daemon=True).start()
    root.mainloop()


if __name__ == "__main__":
    main()
```

(`import threading`, `import tkinter as tk` 等はファイル先頭へ。`datetime` は既にimport済み)

- [ ] **Step 2: 既存テストが壊れていないことを確認**

Run: `python -m pytest tests -v`
Expected: 16 passed(UIコード追加でimportが失敗しないこと)

- [ ] **Step 3: 手動確認**

Run: `python claude_usage_widget.py`
確認項目:
- 枠なしの横長ウィンドウが画面右下付近に出る
- 数秒以内に 5h/週 のバーと%、「残 $xx.xx」が実データで埋まる
- ドラッグで移動できる。移動後に一度閉じて再起動すると同じ位置に出る
- 終了は一旦タスクマネージャまたはコンソールのCtrl+C(トレイメニューはTask 7)

- [ ] **Step 4: Commit**

```bash
git add claude_usage_widget.py
git commit -m "feat: frameless slim-bar widget with drag & one-shot fetch"
```

---

### Task 6: 詳細パネル(展開/収納・limits列挙・プリペイド編集・ポーリング間隔設定)

**Files:**
- Modify: `claude_usage_widget.py`(`UsageWidget` に追記・`toggle_detail` を本実装)

**Interfaces:**
- Consumes: `UsageWidget`, `LimitEntry`, `fmt_reset`, `save_config`(Task 2–5)
- Produces:
  - `UsageWidget.toggle_detail()` — パネルの表示/非表示
  - `UsageWidget.on_interval_changed(seconds: int)` — Task 7がポーリング再スケジュールに使うフック(このタスクではconfig保存まで)
  - `UsageWidget._rebuild_detail()` — snapshot/configから詳細パネルを再構築

- [ ] **Step 1: 実装(`UsageWidget` クラス内に追加、`toggle_detail` を置換)**

```python
    INTERVAL_CHOICES = [30, 60, 120, 300, 600]

    def toggle_detail(self):
        if self.detail_visible:
            self.detail_frame.destroy()
            self.detail_visible = False
            self.toggle_btn.config(text="▼")
        else:
            self.detail_frame = tk.Frame(self.root, bg=BG)
            self.detail_frame.pack(fill="x", padx=8, pady=(0, 6))
            self._rebuild_detail()
            self.detail_visible = True
            self.toggle_btn.config(text="▲")

    def _rebuild_detail(self):
        for child in self.detail_frame.winfo_children():
            child.destroy()
        now = datetime.now().astimezone()
        snap = self.snapshot

        def row(text: str, fg: str = FG):
            tk.Label(self.detail_frame, text=text, bg=BG, fg=fg, font=FONT,
                     anchor="w").pack(fill="x")

        if snap is None:
            row("データ未取得", FG_DIM)
        else:
            for e in snap.limits:
                color = bar_color(e.percent, e.severity)
                row(f"{e.label}: {e.percent:.0f}%   リセット {fmt_reset(e.resets_at, now)}",
                    color)
            if snap.extra_enabled and snap.extra_limit is not None:
                row(f"追加クレジット: ${snap.extra_used:.2f} 使用 / 上限 "
                    f"${snap.extra_limit:.2f} (残 ${snap.extra_remaining:.2f})")
            else:
                row("追加クレジット: 無効", FG_DIM)

        # ── APIプリペイド(手動) ─────────────
        bal = self.config.get("prepaid_balance") or {}
        prepaid_row = tk.Frame(self.detail_frame, bg=BG)
        prepaid_row.pack(fill="x")
        amount = bal.get("amount")
        text = (f"APIプリペイド: ${amount:.2f}  最終更新 {bal.get('updated_at') or '—'}"
                if amount is not None else "APIプリペイド: 未設定")
        tk.Label(prepaid_row, text=text, bg=BG, fg=FG, font=FONT).pack(side="left")
        edit = tk.Label(prepaid_row, text="[編集]", bg=BG, fg="#58a6ff", font=FONT,
                        cursor="hand2")
        edit.pack(side="left", padx=6)
        edit.bind("<Button-1>", lambda e: self._edit_prepaid())

        # ── ポーリング間隔 ─────────────
        interval_row = tk.Frame(self.detail_frame, bg=BG)
        interval_row.pack(fill="x", pady=(4, 0))
        tk.Label(interval_row, text="更新間隔:", bg=BG, fg=FG, font=FONT).pack(side="left")
        current = int(self.config.get("poll_interval_sec", 60))
        var = tk.StringVar(value=self._interval_text(current))
        menu = tk.OptionMenu(interval_row, var,
                             *[self._interval_text(s) for s in self.INTERVAL_CHOICES],
                             command=lambda v: self._set_interval(v))
        menu.config(bg=BAR_BG, fg=FG, font=FONT_SMALL, highlightthickness=0, bd=0)
        menu["menu"].config(bg=BAR_BG, fg=FG)
        menu.pack(side="left", padx=6)

    @staticmethod
    def _interval_text(seconds: int) -> str:
        return f"{seconds}秒" if seconds < 60 else f"{seconds // 60}分"

    def _set_interval(self, label: str):
        seconds = next(s for s in self.INTERVAL_CHOICES
                       if self._interval_text(s) == label)
        self.config["poll_interval_sec"] = seconds
        save_config(self.config)
        self.on_interval_changed(seconds)

    def on_interval_changed(self, seconds: int):
        pass  # Task 7 でポーリング再スケジュールに差し替え

    def _edit_prepaid(self):
        from tkinter import simpledialog
        bal = self.config.get("prepaid_balance") or {}
        value = simpledialog.askfloat(
            "APIプリペイド残高", "現在の残高 (USD):",
            initialvalue=bal.get("amount"), minvalue=0, parent=self.root)
        if value is not None:
            self.config["prepaid_balance"] = {
                "amount": value, "currency": "USD",
                "updated_at": datetime.now().strftime("%Y-%m-%d"),
            }
            save_config(self.config)
            self.refresh_prepaid()
            if self.detail_visible:
                self._rebuild_detail()
```

さらに `apply_snapshot` の末尾に1行追加(スナップショット更新時にパネルも追随):

```python
        if self.detail_visible:
            self._rebuild_detail()
```

- [ ] **Step 2: 既存テストが壊れていないことを確認**

Run: `python -m pytest tests -v`
Expected: 16 passed

- [ ] **Step 3: 手動確認**

Run: `python claude_usage_widget.py`
確認項目:
- ▼クリックでパネルが下に展開し、▲で閉じる
- パネルに limits 全件(「5時間」「週間」「週間 (Fable)」等)が%・リセット日時つきで出る
- 「追加クレジット: $x.xx 使用 / 上限 $xx.xx (残 $xx.xx)」が出る
- [編集]でプリペイド残高を入力→スリムバーの「API $xx.xx」とパネル表示が即更新
  →再起動しても値が残る(config.json確認)
- 更新間隔のプルダウンを変更→ `%APPDATA%\claude-usage-widget\config.json` の
  `poll_interval_sec` が変わる

- [ ] **Step 4: Commit**

```bash
git add claude_usage_widget.py
git commit -m "feat: expandable detail panel (limits list, prepaid edit, poll interval)"
```

---

### Task 7: ポーリングループ・エラー状態・トークン期限切れ処理

**Files:**
- Modify: `claude_usage_widget.py`(`Poller` クラス追加、`main()` 置換)

**Interfaces:**
- Consumes: `UsageWidget`, `fetch_usage`, `load_credentials`, `is_token_expired`, `parse_usage`, 例外クラス(Task 2–6)
- Produces:
  - `class Poller`: `__init__(self, root, widget: UsageWidget)`, `start()`, `poll_now()`, `reschedule(seconds: int)`
  - `main()` は `Poller` を起動し `widget.on_interval_changed = poller.reschedule` を接続

- [ ] **Step 1: 実装(`claude_usage_widget.py` に追記、既存 `main()` を置換)**

```python
class Poller:
    """背景スレッドでfetchし、結果をtkのafterでUIスレッドに反映する。"""

    def __init__(self, root: tk.Tk, widget: UsageWidget):
        self.root = root
        self.widget = widget
        self._after_id: str | None = None

    def start(self):
        self.poll_now()

    def reschedule(self, seconds: int):
        if self._after_id:
            self.root.after_cancel(self._after_id)
        self._after_id = self.root.after(seconds * 1000, self.poll_now)

    def poll_now(self):
        threading.Thread(target=self._fetch_bg, daemon=True).start()
        self.reschedule(int(self.widget.config.get("poll_interval_sec", 60)))

    def _fetch_bg(self):
        try:
            creds = load_credentials()
        except (OSError, ValueError):
            self._ui(self.widget.set_status,
                     "⚠ Claude Codeの認証情報が見つかりません", COLOR_CRIT)
            return
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        if is_token_expired(creds, now_ms):
            self._ui(self.widget.set_status,
                     "⚠ トークン期限切れ — Claude Codeを起動してください", COLOR_WARN)
            return
        try:
            data = fetch_usage(creds["accessToken"])
        except TokenExpiredError:
            self._ui(self.widget.set_status,
                     "⚠ トークン期限切れ — Claude Codeを起動してください", COLOR_WARN)
            return
        except FetchError as e:
            stamp = datetime.now().strftime("%H:%M")
            self._ui(self.widget.set_status, f"更新失敗 {stamp} ({e})", FG_DIM)
            return
        try:
            snap = parse_usage(data)
        except Exception:
            self._ui(self.widget.set_status, "レスポンス解析に失敗", FG_DIM)
            return
        self._ui(self.widget.apply_snapshot, snap)

    def _ui(self, fn, *args):
        self.root.after(0, fn, *args)


def main():
    config = load_config()
    root = tk.Tk()
    widget = UsageWidget(root, config)
    poller = Poller(root, widget)
    widget.on_interval_changed = poller.reschedule
    poller.start()
    root.mainloop()


if __name__ == "__main__":
    main()
```

(Task 5 の `initial_fetch` 入り `main()` は削除して置き換える)

- [ ] **Step 2: 既存テストが壊れていないことを確認**

Run: `python -m pytest tests -v`
Expected: 16 passed

- [ ] **Step 3: 手動確認**

Run: `python claude_usage_widget.py`
確認項目:
- 起動直後に値が入る。更新間隔を30秒にして待つと再取得される(タスクマネージャ等で
  通信を見るか、%の変化で確認)
- Wi-Fiを一時的に切る→次回ポーリングで「更新失敗 HH:MM」がグレー表示され、
  前回の値は残る。Wi-Fi復帰→次回ポーリングで表示が正常に戻る

- [ ] **Step 4: Commit**

```bash
git add claude_usage_widget.py
git commit -m "feat: polling loop with error and token-expiry states"
```

---

### Task 8: タスクトレイ常駐(pystray)

**Files:**
- Modify: `claude_usage_widget.py`(トレイ関連追加、`main()` 拡張)

**Interfaces:**
- Consumes: `UsageWidget`, `Poller`, 色定数(Task 2–7)
- Produces:
  - `worst_severity_color(snap: UsageSnapshot | None) -> str` — トレイアイコン色
  - `make_tray_image(color: str) -> PIL.Image.Image`
  - `setup_tray(root, widget, poller) -> pystray.Icon`(別スレッドで実行)

- [ ] **Step 1: 実装(`claude_usage_widget.py` に追記、`main()` を拡張)**

```python
import pystray
from PIL import Image, ImageDraw


def worst_severity_color(snap: UsageSnapshot | None) -> str:
    if snap is None:
        return COLOR_NA
    pcts = [e.percent for e in snap.limits]
    sevs = [e.severity for e in snap.limits]
    if "critical" in sevs or any(p >= 95 for p in pcts):
        return COLOR_CRIT
    if "warning" in sevs or any(p >= 80 for p in pcts):
        return COLOR_WARN
    return COLOR_OK


def make_tray_image(color: str) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([8, 8, 56, 56], fill=color)
    return img


def setup_tray(root: tk.Tk, widget: UsageWidget, poller: Poller) -> pystray.Icon:
    def ui(fn, *args):
        root.after(0, fn, *args)

    def toggle_visible(icon, item):
        ui(lambda: root.deiconify() if root.state() == "withdrawn" else root.withdraw())

    def toggle_topmost(icon, item):
        def do():
            new = not widget.config.get("always_on_top", True)
            widget.config["always_on_top"] = new
            root.attributes("-topmost", new)
            save_config(widget.config)
        ui(do)

    def refresh_now(icon, item):
        ui(poller.poll_now)

    def quit_app(icon, item):
        icon.stop()
        ui(root.destroy)

    menu = pystray.Menu(
        pystray.MenuItem("ウィジェット表示/非表示", toggle_visible),
        pystray.MenuItem("最前面に固定",
                         toggle_topmost,
                         checked=lambda item: bool(widget.config.get("always_on_top"))),
        pystray.MenuItem("今すぐ更新", refresh_now),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("終了", quit_app),
    )
    icon = pystray.Icon(APP_NAME, make_tray_image(COLOR_NA), "Claude Usage", menu)
    threading.Thread(target=icon.run, daemon=True).start()
    return icon
```

`main()` を以下に置換し、スナップショット反映時にトレイ色も更新する:

```python
def main():
    config = load_config()
    root = tk.Tk()
    widget = UsageWidget(root, config)
    poller = Poller(root, widget)
    widget.on_interval_changed = poller.reschedule
    icon = setup_tray(root, widget, poller)

    original_apply = widget.apply_snapshot

    def apply_and_recolor(snap: UsageSnapshot):
        original_apply(snap)
        icon.icon = make_tray_image(worst_severity_color(snap))

    widget.apply_snapshot = apply_and_recolor

    original_status = widget.set_status

    def status_and_gray(text: str, color: str):
        original_status(text, color)
        if text:  # エラー/期限切れ表示中はトレイをグレーに(仕様)
            icon.icon = make_tray_image(COLOR_NA)

    widget.set_status = status_and_gray
    poller.start()
    try:
        root.mainloop()
    finally:
        icon.stop()
```

(`import pystray`, `from PIL import Image, ImageDraw` はファイル先頭へ)

- [ ] **Step 2: 既存テストが壊れていないことを確認**

Run: `python -m pytest tests -v`
Expected: 16 passed

- [ ] **Step 3: 手動確認**

Run: `python claude_usage_widget.py`
確認項目:
- タスクトレイ(通知領域)に丸アイコンが出る。データ取得後、使用率に応じた色になる
  (現状88%なら黄)
- 右クリックメニュー: 表示/非表示でウィジェットが消えたり出たりする
- 「最前面に固定」のチェックが切り替わり、再起動後も維持される
- 「今すぐ更新」で即時再取得
- 「終了」でウィジェット・トレイとも消え、プロセスが終了する

- [ ] **Step 4: Commit**

```bash
git add claude_usage_widget.py
git commit -m "feat: system tray icon with severity color and menu"
```

---

### Task 9: README完成・最終確認

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: 完成したアプリ(Task 1–8)
- Produces: GitHub公開可能なREADME

- [ ] **Step 1: README.md を完成させる**

```markdown
# claude-usage-widget

Claudeサブスクリプション(Pro/Max)の使用量残量をWindowsデスクトップに
常時表示する、タスクトレイ常駐ウィジェットです。

- 5時間セッション使用率 / 週間使用率(バー表示、リセット時刻つき)
- 追加使用クレジット(extra usage)の残額を自動取得
- APIプリペイド残高の手動記録欄
- ▼クリックで詳細パネル(モデル別制限の一覧、更新間隔設定)

## 必要条件

- Windows 10/11
- Python 3.10+
- [Claude Code](https://claude.com/claude-code) にログイン済みであること
  (`~/.claude/.credentials.json` の認証情報を読み取ります)

## セットアップ

```
pip install -r requirements.txt
python claude_usage_widget.py
```

コンソールなしで起動する場合は `pythonw claude_usage_widget.py`。

## Windows起動時に自動実行する

1. `Win + R` → `shell:startup` → Enter
2. 開いたフォルダに、以下を対象とするショートカットを作成:
   `pythonw.exe <このリポジトリのパス>\claude_usage_widget.py`

## 設定の保存先

`%APPDATA%\claude-usage-widget\config.json`
(ウィンドウ位置・更新間隔・最前面固定・プリペイド残高)

## 注意事項

- 本ツールは Claude Code の `/usage` コマンドが使う**非公開API**
  (`api.anthropic.com/api/oauth/usage`)を利用しています。仕様変更で
  予告なく動かなくなる可能性があります。
- アクセストークンの読み取りのみ行い、リフレッシュや書き換えは行いません。
  トークンが期限切れの場合はClaude Codeを一度起動してください。
- APIプリペイド残高(console.anthropic.com)には公開APIが存在しないため、
  手動入力です。

## ライセンス

MIT
```

- [ ] **Step 2: 全テスト+起動の最終確認**

Run: `python -m pytest tests -v`
Expected: 16 passed

Run: `python claude_usage_widget.py`
Expected: ウィジェット+トレイが起動し、全機能が動作(Task 5–8の確認項目を一巡)

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: complete README with setup and caveats"
```
