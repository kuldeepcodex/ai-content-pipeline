"""Connects the steps into the full LangGraph."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from src.graph.nodes import (human_review, platform_writer, publish, research,
                             route_after_research, save_drafts)
from src.graph.state import PipelineState


def build_graph(checkpointer):
    g = StateGraph(PipelineState)
    g.add_node("research", research)
    g.add_node("platform_writer", platform_writer)
    g.add_node("save_drafts", save_drafts)
    g.add_node("human_review", human_review)
    g.add_node("publish", publish)

    g.add_edge(START, "research")
    g.add_conditional_edges("research", route_after_research, ["platform_writer", END])
    g.add_edge("platform_writer", "save_drafts")   # waits for all three writers
    g.add_edge("save_drafts", "human_review")
    g.add_edge("human_review", "publish")
    g.add_edge("publish", END)
    return g.compile(checkpointer=checkpointer)
