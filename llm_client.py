"""Lazily-constructed Groq chat client shared by the RAG agent and /api/interpret.

Nothing here runs at import time, so the rule engine, calculator, partner
locator and admin console all work without a GROQ_API_KEY. Only the
LLM-backed endpoints fail — with LLMUnavailableError, which api.py turns
into a clean 503.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DEFAULT_MODEL = "openai/gpt-oss-20b"

_clients: dict[int, object] = {}


class LLMUnavailableError(RuntimeError):
    """Raised when an LLM-backed feature is used without GROQ_API_KEY configured."""


def get_llm(max_tokens: int):
    """Return a cached ChatGroq client for this max_tokens setting.

    The key is checked on every call (not just the first), so removing it
    from the environment disables LLM features again rather than silently
    reusing a client built earlier.
    """
    if not os.environ.get("GROQ_API_KEY"):
        raise LLMUnavailableError(
            "AI features are unavailable: GROQ_API_KEY is not configured on the server. "
            "Scheme matching, the calculator and the partner locator still work."
        )
    if max_tokens not in _clients:
        from langchain_groq import ChatGroq

        _clients[max_tokens] = ChatGroq(
            model=os.environ.get("GROQ_MODEL", DEFAULT_MODEL),
            temperature=0,
            max_tokens=max_tokens,
        )
    return _clients[max_tokens]
