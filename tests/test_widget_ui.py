"""UsageWidgetのUI状態フラグのテスト(実tkウィンドウを非表示で使用)。"""
import copy
import tkinter as tk

import pytest

import claude_usage_widget as w


@pytest.fixture()
def widget():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    yield w.UsageWidget(root, copy.deepcopy(w.DEFAULT_CONFIG))
    root.destroy()


def test_rate_limited_cleared_by_next_success(widget):
    widget.set_rate_limited()
    assert widget._rate_limited is True
    widget.apply_snapshot(w.UsageSnapshot())
    assert widget._rate_limited is False


def test_rate_limited_cleared_by_real_error(widget):
    widget.set_rate_limited()
    widget.set_status("更新失敗 00:00 (test)", w.FG_DIM)
    assert widget._rate_limited is False


def test_rate_limited_survives_status_clear(widget):
    # set_status("")(正常時の消灯)ではフラグを解除しない
    widget.set_rate_limited()
    widget.set_status("", w.FG_DIM)
    assert widget._rate_limited is True


def test_status_label_has_wraplength(widget):
    # 万一長文が set_status に渡っても、ラベルが横に無限に伸びないための最終保険。
    wl = int(widget.status_label.cget("wraplength"))
    assert wl > 0
    assert widget.status_label.cget("justify") == "left"
