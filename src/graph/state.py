"""The data that flows through the graph."""
from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class PipelineState(TypedDict, total=False):
    article_id: str
    title: str
    url: str
    content: str
    summary: str
    key_points: list[str]
    relevance_score: int
    # each platform writer adds its draft here; operator.add merges the parallel results
    drafts: Annotated[list[dict], operator.add]


class PlatformState(TypedDict, total=False):
    platform: str
    title: str
    url: str
    summary: str
    key_points: list[str]
    text: str
    hashtags: list[str]
    score: int
    feedback: str
    rewrites: int
    too_long: bool
    drafts: list[dict]
