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
