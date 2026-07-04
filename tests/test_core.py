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
