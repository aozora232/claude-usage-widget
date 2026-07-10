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

import pystray
import requests
from PIL import Image, ImageDraw

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


class RateLimitError(FetchError):
    """HTTP 429。データ異常ではなく一時的な取得拒否(表示中の値は維持してよい)。"""


def _short_network_error(e: BaseException) -> str:
    """requestsの長い例外詳細を1行の日本語ラベルに畳む(原因はfromで保持)。"""
    if isinstance(e, requests.exceptions.SSLError):
        return "SSLエラー"
    if isinstance(e, requests.exceptions.Timeout):
        return "タイムアウト"
    if isinstance(e, requests.exceptions.ConnectionError):
        return "接続できません"
    return type(e).__name__


def fetch_usage(token: str, timeout: float = 10) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.get(API_URL, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        raise FetchError(_short_network_error(e)) from e
    if resp.status_code == 401:
        raise TokenExpiredError("access token rejected (401)")
    if resp.status_code == 429:
        raise RateLimitError("rate limited (429)")
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


def extra_percent(snap: UsageSnapshot) -> float | None:
    """追加クレジット使用率(月間制限=100%)。表示不能ならNone。"""
    if not snap.extra_enabled:
        return None
    if snap.extra_used is None or snap.extra_limit is None:
        return None
    if snap.extra_limit <= 0:
        return None
    return snap.extra_used / snap.extra_limit * 100


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


BAR_HEIGHT = 8   # スリムバーのCanvas高さ(px)
ICON_SIZE = 12   # ⟳▼アイコンのCanvas一辺(px)。行の高さはこれが上限になる
STATUS_MAX_CHARS = 60  # ステータス行の最大長(超過分は「…」で切り詰め)


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


class UsageWidget:
    def __init__(self, root: tk.Tk, config: dict):
        self.root = root
        self.config = config
        self.detail_visible = False
        self.snapshot: UsageSnapshot | None = None
        self._rate_limited = False

        root.overrideredirect(True)
        root.configure(bg=BG)
        root.attributes("-topmost", bool(config.get("always_on_top", True)))

        # ── スリムバー(バーのみ・文字なし) ─────────────
        self.bar_row = tk.Frame(root, bg=BG)
        self.bar_row.pack(fill="x", padx=8, pady=0)

        self.bar_5h = _Bar(self.bar_row)
        self.bar_5h.canvas.pack(side="left")
        self.bar_week = _Bar(self.bar_row)
        self.bar_week.canvas.pack(side="left", padx=(6, 0))
        self.bar_extra = _Bar(self.bar_row)
        self.bar_extra.canvas.pack(side="left", padx=(6, 0))

        self.toggle_btn = tk.Canvas(self.bar_row, width=ICON_SIZE, height=ICON_SIZE,
                                    bg=BG, highlightthickness=0, cursor="hand2")
        self.toggle_btn.pack(side="right", padx=(6, 0))
        self.toggle_btn.bind("<Button-1>", lambda e: self.toggle_detail())
        self._draw_toggle_icon(expanded=False)

        self.refresh_btn = tk.Canvas(self.bar_row, width=ICON_SIZE, height=ICON_SIZE,
                                     bg=BG, highlightthickness=0, cursor="hand2")
        self.refresh_btn.pack(side="right", padx=(6, 0))
        self.refresh_btn.bind("<Button-1>", lambda e: self.on_refresh_clicked())
        self._draw_refresh_icon(busy=False)

        # ステータス行(エラー時のみ文字が入る)
        # wraplengthは想定外の長文が来た場合のセーフティネット(通常はSTATUS_MAX_CHARSで
        # 1行に収まる)。ここが発動しても縦に折れるだけで、ウィジェット幅は暴走しない。
        self.status_label = tk.Label(root, text="", bg=BG, fg=FG_DIM, font=FONT_SMALL,
                                     anchor="w", justify="left", wraplength=400)

        # ── ドラッグ移動 ─────────────────────────
        for widget in (root, self.bar_row):
            widget.bind("<Button-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._on_drag)
            widget.bind("<ButtonRelease-1>", self._end_drag)
        self._drag_offset = None

        self._place_window()

    def _place_window(self):
        pos = self.config.get("window_pos")
        self.root.update_idletasks()
        try:
            if pos and isinstance(pos, list) and len(pos) == 2:
                self.root.geometry(f"+{int(pos[0])}+{int(pos[1])}")
                return
        except (ValueError, TypeError):
            pass
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
        # ⟳の再描画はPoller側finallyのset_refreshing(False)に任せる(set_statusも同様)
        self._rate_limited = False
        self.bar_5h.update(snap.five_hour_pct, self._sev("session"))
        self.bar_week.update(snap.seven_day_pct, self._sev("weekly_all"))
        self.bar_extra.update(extra_percent(snap), None)
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

    def set_status(self, text: str, color: str):
        if text:
            self._rate_limited = False  # 本物のエラー表示が優先(グレー+文言に切替)
            self.status_label.config(text=text, fg=color)
            self.status_label.pack(fill="x", padx=8, pady=(0, 3))
            self._mark_stale()
        else:
            self.status_label.pack_forget()

    def _mark_stale(self):
        if self.snapshot is not None:
            self.bar_5h.update(self.snapshot.five_hour_pct, self._sev("session"), stale=True)
            self.bar_week.update(self.snapshot.seven_day_pct, self._sev("weekly_all"),
                                 stale=True)
            self.bar_extra.update(extra_percent(self.snapshot), None, stale=True)

    def _draw_toggle_icon(self, expanded: bool):
        c = self.toggle_btn
        c.delete("all")
        pts = (2, 9, 10, 9, 6, 4) if expanded else (2, 4, 10, 4, 6, 9)
        c.create_polygon(*pts, fill=FG_DIM, outline="")

    def _draw_refresh_icon(self, busy: bool):
        c = self.refresh_btn
        c.delete("all")
        if busy:
            color = BAR_BG
        elif self._rate_limited:
            color = COLOR_WARN  # レート制限中はアンバー(データは直前値のまま有効)
        else:
            color = FG_DIM
        c.create_arc(2, 3, 10, 11, start=40, extent=260, style="arc",
                     outline=color, width=2)
        c.create_polygon(8, 0, 12, 3, 8, 6, fill=color, outline="")

    def set_refreshing(self, busy: bool):
        self._draw_refresh_icon(busy)

    def set_rate_limited(self):
        """429: バー・ステータスには触れず、⟳を警告色にするだけ。"""
        self._rate_limited = True
        self._draw_refresh_icon(busy=False)

    def on_refresh_clicked(self):
        pass  # main() で Poller.poll_now に差し替え

    INTERVAL_CHOICES = [30, 60, 120, 300, 600]

    def toggle_detail(self):
        if self.detail_visible:
            self.detail_frame.destroy()
            self.detail_visible = False
            self._draw_toggle_icon(expanded=False)
        else:
            self.detail_frame = tk.Frame(self.root, bg=BG)
            self.detail_frame.pack(fill="x", padx=8, pady=(0, 6))
            self._rebuild_detail()
            self.detail_visible = True
            self._draw_toggle_icon(expanded=True)

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
            if snap.limits:
                for e in snap.limits:
                    color = bar_color(e.percent, e.severity)
                    row(f"{e.label}: {e.percent:.0f}%   リセット {fmt_reset(e.resets_at, now)}",
                        color)
            else:
                if snap.five_hour_pct is not None:
                    color = bar_color(snap.five_hour_pct, None)
                    row(f"5時間: {snap.five_hour_pct:.0f}%   "
                        f"リセット {fmt_reset(snap.five_hour_resets, now)}", color)
                if snap.seven_day_pct is not None:
                    color = bar_color(snap.seven_day_pct, None)
                    row(f"週間: {snap.seven_day_pct:.0f}%   "
                        f"リセット {fmt_reset(snap.seven_day_resets, now)}", color)
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
            if self.detail_visible:
                self._rebuild_detail()


class Poller:
    """背景スレッドでfetchし、結果をtkのafterでUIスレッドに反映する。"""

    def __init__(self, root: tk.Tk, widget: UsageWidget):
        self.root = root
        self.widget = widget
        self._after_id: str | None = None
        self._in_flight = False

    def start(self):
        self.poll_now()

    def reschedule(self, seconds: int):
        if self._after_id:
            self.root.after_cancel(self._after_id)
        self._after_id = self.root.after(seconds * 1000, self.poll_now)

    def poll_now(self):
        self.reschedule(int(self.widget.config.get("poll_interval_sec", 60)))
        if self._in_flight:
            return  # fetch実行中の連打・タイマー発火は無視(タイマーは再設定済み)
        self._in_flight = True
        self._ui(self.widget.set_refreshing, True)
        threading.Thread(target=self._fetch_bg, daemon=True).start()

    def _fetch_bg(self):
        try:
            self._fetch_once()
        finally:
            self._in_flight = False
            self._ui(self.widget.set_refreshing, False)

    def _fetch_once(self):
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
        except RateLimitError:
            self._ui(self.widget.set_rate_limited)
            return
        except FetchError as e:
            stamp = datetime.now().strftime("%H:%M")
            msg = f"更新失敗 {stamp} ({e})"
            if len(msg) > STATUS_MAX_CHARS:
                msg = msg[:STATUS_MAX_CHARS - 1] + "…"
            self._ui(self.widget.set_status, msg, FG_DIM)
            return
        try:
            snap = parse_usage(data)
        except Exception:
            self._ui(self.widget.set_status, "レスポンス解析に失敗", FG_DIM)
            return
        self._ui(self.widget.apply_snapshot, snap)

    def _ui(self, fn, *args):
        try:
            self.root.after(0, fn, *args)
        except (RuntimeError, tk.TclError):
            pass


def worst_severity_color(snap: UsageSnapshot | None) -> str:
    if snap is None:
        return COLOR_NA
    pcts = [e.percent for e in snap.limits]
    if snap.five_hour_pct is not None:
        pcts.append(snap.five_hour_pct)
    if snap.seven_day_pct is not None:
        pcts.append(snap.seven_day_pct)
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
                         checked=lambda item: bool(widget.config.get("always_on_top", True))),
        pystray.MenuItem("今すぐ更新", refresh_now),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("終了", quit_app),
    )
    icon = pystray.Icon(APP_NAME, make_tray_image(COLOR_NA), "Claude Usage", menu)
    threading.Thread(target=icon.run, daemon=True).start()
    return icon


def main():
    config = load_config()
    root = tk.Tk()
    widget = UsageWidget(root, config)
    poller = Poller(root, widget)
    widget.on_interval_changed = poller.reschedule
    widget.on_refresh_clicked = poller.poll_now
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


if __name__ == "__main__":
    main()
