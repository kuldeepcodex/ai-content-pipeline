import httpx
import pytest
import requests
from requests_oauthlib import OAuth1

from src import publisher
from src.publisher import PostError

DRAFT = {"id": "11111111-2222-3333-4444-555555555555", "platform": "linkedin",
         "text": "Hello world", "hashtags": ["AI", "Tech"]}


@pytest.fixture(autouse=True)
def fake_db_and_alerts(monkeypatch):
    calls = {"finish": [], "alerts": [], "claimed": set()}

    def claim(draft_id, platform):
        key = (draft_id, platform)
        if key in calls["claimed"]:
            return False
        calls["claimed"].add(key)
        return True

    monkeypatch.setattr(publisher.db, "claim_post", claim)
    monkeypatch.setattr(publisher.db, "finish_post", lambda *a: calls["finish"].append(a))
    monkeypatch.setattr(publisher.alerts, "notify", lambda m: calls["alerts"].append(m))
    for name in ("POST_LIVE", "LINKEDIN_ACCESS_TOKEN", "LINKEDIN_PERSON_ID", "X_API_KEY",
                 "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET", "POST_LIVE_PLATFORMS"):
        monkeypatch.delenv(name, raising=False)
    return calls


def test_dry_run_by_default(fake_db_and_alerts):
    res = publisher.publish_draft(DRAFT, "http://x")
    assert res["status"] == "dry_run" and res["ref"].startswith("dry-run-")


def test_never_posts_twice(fake_db_and_alerts):
    publisher.publish_draft(DRAFT)
    assert publisher.publish_draft(DRAFT)["status"] == "skipped"


def test_linkedin_live_success(monkeypatch, fake_db_and_alerts):
    monkeypatch.setenv("POST_LIVE", "true")
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "tok")
    seen = {}

    def fake_get(url, headers, timeout):
        return httpx.Response(200, json={"sub": "abc123"}, request=httpx.Request("GET", url))

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, body=json)
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:1"}, json={},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(publisher.httpx, "get", fake_get)
    monkeypatch.setattr(publisher.httpx, "post", fake_post)
    res = publisher.publish_draft(DRAFT, "https://example.com/story")
    assert res == {"status": "posted", "ref": "urn:li:share:1", "error": None}
    text = seen["body"]["commentary"]
    assert "\\#AI \\#Tech" in text and "Source: https://example.com/story" in text.replace("\\_", "_")
    assert seen["url"].endswith("/rest/posts")
    assert seen["body"]["author"] == "urn:li:person:abc123"
    assert seen["body"]["lifecycleState"] == "PUBLISHED" and seen["body"]["visibility"] == "PUBLIC"
    assert seen["headers"]["Authorization"] == "Bearer tok"
    assert seen["headers"]["Linkedin-Version"] == publisher.LINKEDIN_VERSION
    assert seen["headers"]["X-Restli-Protocol-Version"] == "2.0.0"


def test_linkedin_expired_token_fails_and_alerts(monkeypatch, fake_db_and_alerts):
    monkeypatch.setenv("POST_LIVE", "true")
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "old")
    monkeypatch.setenv("LINKEDIN_PERSON_ID", "abc")
    monkeypatch.setattr(publisher.httpx, "post", lambda url, headers, json, timeout:
                        httpx.Response(401, text="expired", request=httpx.Request("POST", url)))
    res = publisher.publish_draft(DRAFT)
    assert res["status"] == "failed" and "expired" in res["error"]
    assert fake_db_and_alerts["alerts"] and fake_db_and_alerts["finish"][-1][2] == "failed"


def test_x_live_success_has_no_link(monkeypatch, fake_db_and_alerts):
    monkeypatch.setenv("POST_LIVE", "true")
    for n in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"):
        monkeypatch.setenv(n, "v")
    sent = {}

    def fake_post(url, json, auth, timeout):
        sent.update(url=url, json=json)
        r = requests.Response()
        r.status_code = 201
        r._content = b'{"data": {"id": "999"}}'
        return r

    monkeypatch.setattr(publisher.requests, "post", fake_post)
    res = publisher.publish_draft({**DRAFT, "platform": "twitter"}, "https://example.com/story")
    assert res["status"] == "posted" and res["ref"] == "999"
    assert "http" not in sent["json"]["text"] and sent["json"]["text"].endswith("#AI #Tech")


def test_live_without_credentials_fails_clearly(monkeypatch, fake_db_and_alerts):
    monkeypatch.setenv("POST_LIVE", "true")
    res = publisher.publish_draft({**DRAFT, "platform": "twitter"})
    assert res["status"] == "failed" and "Missing credentials" in res["error"]


def test_too_long_tweet_is_refused_without_network():
    with pytest.raises(PostError):
        publisher.build_tweet({"text": "x" * 300, "hashtags": []})


def test_instagram_stays_dry_run_even_when_live(monkeypatch, fake_db_and_alerts):
    monkeypatch.setenv("POST_LIVE", "true")
    assert publisher.publish_draft({**DRAFT, "platform": "instagram"})["status"] == "dry_run"


def test_oauth1_signs_the_request():
    req = requests.Request("POST", publisher.X_API, json={"text": "hi"},
                           auth=OAuth1("k", "s", "t", "ts")).prepare()
    header = req.headers["Authorization"]
    header = header.decode() if isinstance(header, bytes) else header
    assert header.startswith("OAuth ") and "oauth_signature" in header


def test_linkedin_only_mode_keeps_x_as_dry_run(monkeypatch, fake_db_and_alerts):
    monkeypatch.setenv("POST_LIVE", "true")
    monkeypatch.setenv("POST_LIVE_PLATFORMS", "linkedin")
    res = publisher.publish_draft({**DRAFT, "platform": "twitter"})
    assert res["status"] == "dry_run"


def test_linkedin_escaping_protects_parentheses_and_brackets():
    out = publisher.escape_linkedin("Fix (urgent) [now] @team #1 a_b")
    assert out == "Fix \\(urgent\\) \\[now\\] \\@team \\#1 a\\_b"


def test_linkedin_version_can_be_overridden(monkeypatch, fake_db_and_alerts):
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "t")
    monkeypatch.setenv("LINKEDIN_PERSON_ID", "p")
    monkeypatch.setenv("LINKEDIN_API_VERSION", "202701")
    seen = {}
    monkeypatch.setattr(publisher.httpx, "post", lambda url, headers, json, timeout: (
        seen.update(h=headers) or httpx.Response(201, headers={"x-restli-id": "u"}, json={},
                                                 request=httpx.Request("POST", url))))
    publisher.post_linkedin("hi")
    assert seen["h"]["Linkedin-Version"] == "202701"


def test_linkedin_text_is_not_cut_short_and_never_ends_on_half_an_escape():
    short = publisher.build_linkedin_text({"text": "Hello", "hashtags": []}, None)
    assert short == "Hello"
    long = publisher.build_linkedin_text({"text": "a" * 2999 + "(", "hashtags": []}, None)
    assert len(long) == 2999 and not long.endswith("\\")
