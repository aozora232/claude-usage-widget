"""claude-usage-widget: Claudeサブスクリプション使用量のデスクトップウィジェット。

Claude Codeの /usage と同じ非公開APIを利用するため、予告なく動かなくなる
可能性がある。トークンのリフレッシュは行わない(Claude Code側に任せる)。
"""
from __future__ import annotations

import copy
import json
import os
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
