import httpx

from src import alerts


def test_no_telegram_settings_returns_false(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert alerts.notify("hello") is False


def test_sends_to_telegram(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    sent = {}

    def fake_post(url, json, timeout):
        sent.update(url=url, json=json)
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(alerts.httpx, "post", fake_post)
    assert alerts.notify("run failed") is True
    assert sent["json"]["chat_id"] == "42" and "run failed" in sent["json"]["text"]


def test_failure_never_raises_or_leaks_token(monkeypatch, caplog):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:SECRET")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")

    def boom(url, json, timeout):
        raise httpx.ConnectError("cannot reach " + url)

    monkeypatch.setattr(alerts.httpx, "post", boom)
    assert alerts.notify("x") is False
    assert "SECRET" not in caplog.text
