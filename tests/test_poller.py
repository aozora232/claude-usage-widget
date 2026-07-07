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

    def set_rate_limited(self):
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


def _raise_rate_limit(token, timeout=10):
    raise w.RateLimitError("rate limited (429)")


def test_rate_limited_signals_icon_not_status(monkeypatch):
    """429ではバーをグレー化するset_statusを呼ばず、set_rate_limitedだけを通知する。"""
    FakeThread.instances = []
    monkeypatch.setattr(w.threading, "Thread", FakeThread)
    monkeypatch.setattr(w, "load_credentials",
                        lambda: {"accessToken": "tok", "expiresAt": 2**62})
    monkeypatch.setattr(w, "fetch_usage", _raise_rate_limit)
    p = w.Poller(FakeRoot(), FakeWidget())
    p.poll_now()
    FakeThread.instances[0].target()
    fns = [fn for ms, fn, args in p.root.after_calls if ms == 0]
    assert p.widget.set_rate_limited in fns
    assert p.widget.set_status not in fns
    assert p._in_flight is False  # 通常どおり解除され、次回ポーリングで再試行できる


def test_refresh_indicator_signals_start_and_end(monkeypatch):
    p = make_poller(monkeypatch)
    widget = p.widget
    p.poll_now()
    FakeThread.instances[0].target()
    ui_calls = [(fn, args) for ms, fn, args in p.root.after_calls if ms == 0]
    assert (widget.set_refreshing, (True,)) == ui_calls[0]
    assert (widget.set_refreshing, (False,)) == ui_calls[-1]


def test_fetch_error_status_text_is_clipped(monkeypatch):
    """FetchErrorの文言が想定外に長くてもset_statusに渡す文字列は上限内に収まる。"""
    FakeThread.instances = []
    monkeypatch.setattr(w.threading, "Thread", FakeThread)
    monkeypatch.setattr(w, "load_credentials",
                        lambda: {"accessToken": "tok", "expiresAt": 2**62})

    def _raise_long(token, timeout=10):
        raise w.FetchError("x" * 500)

    monkeypatch.setattr(w, "fetch_usage", _raise_long)
    p = w.Poller(FakeRoot(), FakeWidget())
    p.poll_now()
    FakeThread.instances[0].target()
    status_args = [args for ms, fn, args in p.root.after_calls
                   if ms == 0 and fn == p.widget.set_status]
    assert status_args, "set_status should have been scheduled"
    text = status_args[0][0]
    assert len(text) <= w.STATUS_MAX_CHARS
    assert text.endswith("…")
