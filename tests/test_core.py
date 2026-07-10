import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import claude_usage_widget as w

SAMPLE = {
    "five_hour": {"utilization": 75.0, "resets_at": "2026-07-04T15:50:00.427157+00:00"},
    "seven_day": {"utilization": 30.0, "resets_at": "2026-07-05T18:00:00.427175+00:00"},
    "extra_usage": {
        "is_enabled": True, "monthly_limit": 5000, "used_credits": 1234.0,
        "currency": "USD", "decimal_places": 2, "disabled_reason": None,
    },
    "limits": [
        {"kind": "session", "group": "session", "percent": 75, "severity": "warning",
         "resets_at": "2026-07-04T15:50:00.427157+00:00", "scope": None, "is_active": True},
        {"kind": "weekly_all", "group": "weekly", "percent": 30, "severity": "normal",
         "resets_at": "2026-07-05T18:00:00.427175+00:00", "scope": None, "is_active": False},
        {"kind": "weekly_scoped", "group": "weekly", "percent": 20, "severity": "normal",
         "resets_at": "2026-07-05T18:00:00.427394+00:00",
         "scope": {"model": {"id": None, "display_name": "Fable"}, "surface": None},
         "is_active": False},
    ],
}


def test_parse_usage_main_bars():
    s = w.parse_usage(SAMPLE)
    assert s.five_hour_pct == 75.0
    assert s.seven_day_pct == 30.0
    assert s.five_hour_resets.hour == 15 and s.five_hour_resets.tzinfo is not None


def test_parse_usage_extra_credits_minor_units():
    s = w.parse_usage(SAMPLE)
    assert s.extra_enabled is True
    assert s.extra_used == 12.34
    assert s.extra_limit == 50.00
    assert s.extra_remaining == 37.66


def test_parse_usage_limits_generic_labels():
    s = w.parse_usage(SAMPLE)
    labels = [e.label for e in s.limits]
    assert labels == ["5時間", "週間", "週間 (Fable)"]
    assert s.limits[2].percent == 20


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
