"""One place that creates the models. Gemini first, Groq if Gemini fails."""
from __future__ import annotations

from typing import Any, Callable

from src.config import get_settings

_fake_factory: Callable[[type], Any] | None = None   # tests plug a fake model in here


def set_fake_factory(factory: Callable[[type], Any] | None) -> None:
    global _fake_factory
    _fake_factory = factory


def structured(schema: type):
    """Return something with .invoke(prompt) that gives back a `schema` object."""
    if _fake_factory is not None:
        return _fake_factory(schema)

    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_groq import ChatGroq

    models = get_settings()["models"]
    primary = ChatGoogleGenerativeAI(model=models["main"], temperature=0.4, max_retries=2)
    backup = ChatGroq(model=models["backup"], temperature=0.4, max_retries=2)
    return primary.with_structured_output(schema).with_fallbacks(
        [backup.with_structured_output(schema)]
    )
