"""claude-usage-widget: Claudeサブスクリプション使用量のデスクトップウィジェット。

Claude Codeの /usage と同じ非公開APIを利用するため、予告なく動かなくなる
可能性がある。トークンのリフレッシュは行わない(Claude Code側に任せる)。
"""
from __future__ import annotations

import copy
import json
import os
import threading
import tkinter as tk
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

APP_NAME = "claude-usage-widget"
API_URL = "https://api.anthropic.com/api/oauth/usage"
CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"

COLOR_OK = "#3fb950"
COLOR_WARN = "#d29922"
COLOR_CRIT = "#f85149"
COLOR_NA = "#8b949e"

_KIND_LABELS = {"session": "5時間", "weekly_all": "週間"}


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
        if self.detail_visible:
            self._rebuild_detail()

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
            if (snap.extra_enabled and snap.extra_limit is not None
                    and snap.extra_used is not None
                    and snap.extra_remaining is not None):
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
