"""The steps of the graph. Each function takes the state and returns changes to it."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from src import db, publisher
from src.config import get_settings
from src.graph import prompts
from src.graph.state import PipelineState, PlatformState
from src.llm import structured
from src.models import CriticResult, DraftResult, ResearchResult


# ---------- Step 1: research ----------

def research(state: PipelineState) -> dict:
    limits = get_settings()["limits"]
    result = structured(ResearchResult).invoke(
        prompts.research_prompt(state["title"], (state.get("content") or "")[:6000]))
    passed = result.relevance_score >= limits["relevance_min"]
    db.update_article(state["article_id"], summary=result.summary,
                      relevance_score=result.relevance_score,
                      status="researched" if passed else "rejected")
    return {"summary": result.summary, "key_points": result.key_points,
            "relevance_score": result.relevance_score}


def route_after_research(state: PipelineState):
    """Gate 1: drop low-scoring stories, otherwise start one writer per platform."""
    if state["relevance_score"] < get_settings()["limits"]["relevance_min"]:
        return END
    return [
        Send("platform_writer", {
            "platform": p, "title": state["title"], "url": state["url"],
            "summary": state["summary"], "key_points": state["key_points"],
        })
        for p in get_settings()["platforms"]
    ]


# ---------- Steps 2-3: write and review (one small loop per platform) ----------

def _clean_tags(tags: list[str], platform: str) -> list[str]:
    cleaned, seen = [], set()
    for t in tags:
        t = t.strip().lstrip("#").replace(" ", "")
        if t and t.lower() not in seen:
            seen.add(t.lower())
            cleaned.append(t)
    return cleaned[:{"linkedin": 5, "instagram": 10, "twitter": 2}[platform]]


def _full_length(text: str, tags: list[str]) -> int:
    return len(text) + sum(len(t) + 2 for t in tags)


def write(state: PlatformState) -> dict:
    result = structured(DraftResult).invoke(prompts.write_prompt(
        state["platform"], state["title"], state["url"], state["summary"],
        state["key_points"], state.get("text", ""), state.get("feedback", "")))
    rewrites = state.get("rewrites", 0) + (1 if state.get("text") else 0)
    return {"text": result.text.strip(), "hashtags": _clean_tags(result.hashtags, state["platform"]),
            "rewrites": rewrites}


def critic(state: PlatformState) -> dict:
    result = structured(CriticResult).invoke(prompts.critic_prompt(
        state["platform"], state["title"], state["summary"], state["text"], state["hashtags"]))
    score, feedback = result.score, result.feedback
    too_long = (state["platform"] == "twitter"
                and _full_length(state["text"], state["hashtags"]) > prompts.TWITTER_MAX)
    if too_long:   # a hard rule the model cannot argue with
        score = min(score, 5)
        feedback = f"Too long: keep text plus hashtags within {prompts.TWITTER_MAX} characters. {feedback}"
    return {"score": score, "feedback": feedback, "too_long": too_long}


def route_after_critic(state: PlatformState) -> str:
    """Gate 2: good enough, or out of rewrites, finishes. Otherwise write again."""
    limits = get_settings()["limits"]
    if state["score"] >= limits["critic_min"] or state.get("rewrites", 0) >= limits["max_rewrites"]:
        return "finish"
    return "write"


def finish(state: PlatformState) -> dict:
    return {"drafts": [{"platform": state["platform"], "text": state["text"],
                        "hashtags": state["hashtags"], "critic_score": state["score"],
                        "rewrites": state.get("rewrites", 0)}]}


def build_platform_graph():
    g = StateGraph(PlatformState)
    g.add_node("write", write)
    g.add_node("critic", critic)
    g.add_node("finish", finish)
    g.add_edge(START, "write")
    g.add_edge("write", "critic")
    g.add_conditional_edges("critic", route_after_critic, ["write", "finish"])
    g.add_edge("finish", END)
    return g.compile()


_platform_graph = build_platform_graph()


def platform_writer(state: dict) -> dict:
    out = _platform_graph.invoke(state)
    return {"drafts": out["drafts"]}


# ---------- Steps 4-6: save, wait for a human, publish ----------

def save_drafts(state: PipelineState) -> dict:
    for d in state["drafts"]:
        db.save_draft(state["article_id"], d["platform"], d["text"], d["hashtags"],
                      d["critic_score"], d["rewrites"])
    db.update_article(state["article_id"], status="drafted")
    return {}


def human_review(state: PipelineState) -> dict:
    # Gate 3. The run stops here and its state is saved. It continues when
    # run_pipeline resumes it after you decide in the dashboard.
    # Keep this node tiny: on resume it starts again from its first line.
    interrupt({"article_id": state["article_id"], "message": "Review the drafts in the dashboard"})
    return {}


def publish(state: PipelineState) -> dict:
    approved = db.drafts_for_article(state["article_id"], "approved")
    for draft in approved:
        publisher.publish_draft(draft)
        db.set_draft_status(str(draft["id"]), "posted")
    db.update_article(state["article_id"], status="done" if approved else "closed")
    return {}
