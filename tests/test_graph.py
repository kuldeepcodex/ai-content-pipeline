"""Graph tests with a fake model. They need an EMPTY test database:
set TEST_DATABASE_URL in your shell (do not use your real DATABASE_URL), otherwise they skip.
"""
import os
import uuid

import pytest

from src.models import CriticResult, DraftResult, ResearchResult

TEST_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL not set")


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    from src import db
    db.init_schema()
    from src import llm
    yield db
    llm.set_fake_factory(None)


def fake_model(relevance=8, critic_scores=(9,), long_tweet_first=False):
    scores = list(critic_scores)
    state = {"tweet_calls": 0}

    def factory(schema):
        class Fake:
            def invoke(self, prompt):
                if schema is ResearchResult:
                    return ResearchResult(summary="A summary.", key_points=["fact one"],
                                          relevance_score=relevance, reason="because")
                if schema is DraftResult:
                    long = "x" * 300
                    if long_tweet_first and "twitter" in prompt and state["tweet_calls"] == 0:
                        state["tweet_calls"] += 1
                        return DraftResult(text=long, hashtags=["ai"])
                    return DraftResult(text="A short post.", hashtags=["#AI", "ai", "Tech"])
                score = scores.pop(0) if len(scores) > 1 else scores[0]
                return CriticResult(score=score, feedback="ok")
        return Fake()
    return factory


def run_article(db, graph, title="T"):
    aid = db.insert_article(f"http://t/{uuid.uuid4()}", title, "src", "body")
    cfg = {"configurable": {"thread_id": aid}}
    result = graph.invoke({"article_id": aid, "title": title, "url": "http://t", "content": "body"}, cfg)
    return aid, cfg, result


def test_full_flow_pause_approve_publish(env):
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command
    from src import llm
    from src.graph.pipeline import build_graph
    llm.set_fake_factory(fake_model())
    graph = build_graph(InMemorySaver())
    aid, cfg, result = run_article(env, graph)
    assert "__interrupt__" in result                       # paused for a human
    drafts = env.drafts_for_article(aid)
    assert sorted(d["platform"] for d in drafts) == ["instagram", "linkedin", "twitter"]
    assert all(d["status"] == "pending" for d in drafts)
    assert drafts[0]["hashtags"] == ["AI", "Tech"]          # cleaned and de-duplicated
    assert aid not in env.articles_ready_to_publish()
    for d in drafts[:2]:
        env.set_draft_status(str(d["id"]), "approved")
    env.set_draft_status(str(drafts[2]["id"]), "rejected")
    assert aid in env.articles_ready_to_publish()
    graph.invoke(Command(resume=True), cfg)
    assert len(env.drafts_for_article(aid, "posted")) == 2
    assert env.get_articles("done", 100)[0] is not None


def test_low_relevance_is_rejected(env):
    from langgraph.checkpoint.memory import InMemorySaver
    from src import llm
    from src.graph.pipeline import build_graph
    llm.set_fake_factory(fake_model(relevance=2))
    aid, _, result = run_article(env, build_graph(InMemorySaver()))
    assert "__interrupt__" not in result
    assert env.drafts_for_article(aid) == []


def test_critic_loop_rewrites_a_long_tweet(env):
    from langgraph.checkpoint.memory import InMemorySaver
    from src import llm
    from src.graph.pipeline import build_graph
    llm.set_fake_factory(fake_model(critic_scores=(9,), long_tweet_first=True))
    aid, _, _ = run_article(env, build_graph(InMemorySaver()))
    tweet = [d for d in env.drafts_for_article(aid) if d["platform"] == "twitter"][0]
    assert tweet["rewrites"] == 1
    assert len(tweet["text"]) < 240
