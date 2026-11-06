"""Data shapes. The LLM must return these, so bad output fails loudly."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Platform = Literal["linkedin", "instagram", "twitter"]


class ResearchResult(BaseModel):
    summary: str = Field(description="Three or four plain sentences about the article")
    key_points: list[str] = Field(description="Two to four facts worth posting")
    relevance_score: int = Field(ge=1, le=10, description="How useful this is to a tech audience")
    reason: str = Field(description="One sentence explaining the score")


class DraftResult(BaseModel):
    text: str
    hashtags: list[str] = Field(default_factory=list)


class CriticResult(BaseModel):
    score: int = Field(ge=1, le=10)
    feedback: str = Field(description="What to fix, in one or two sentences")
