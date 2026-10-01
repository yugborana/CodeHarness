"""Web search via the Exa API.

Gives the agent the ability to search the web for documentation, error
messages, library APIs, and anything else it cannot find in the local
codebase.

Requires:
  pip install exa-py
  EXA_API_KEY in env or ~/.agents/env
"""

import os

from . import history

_client = None


def _exa():
    """Lazy-init the Exa client so we don't crash at import time."""
    global _client
    if _client is None:
        key = os.environ.get("EXA_API_KEY", "")
        if not key:
            raise RuntimeError(
                "EXA_API_KEY is not set. Add it to ~/.agents/env or your environment."
            )
        from exa_py import Exa
        _client = Exa(api_key=key)
    return _client


def web_search(query: str, num_results: int = 5) -> str:
    """Search the web with Exa and return titles, URLs, and highlights.

    Parameters
    ----------
    query : str
        A natural-language search query (e.g. "Python asyncio timeout best practices").
    num_results : int
        How many results to return (default 5, max 10).
    """
    num_results = min(max(num_results, 1), 10)

    results = _exa().search_and_contents(
        query,
        num_results=num_results,
        text={"max_characters": 1500},
        highlights={"num_sentences": 3},
    )

    if not results.results:
        return "No results found."

    parts = []
    for i, r in enumerate(results.results, 1):
        block = f"[{i}] {r.title}\n    {r.url}"
        if getattr(r, "highlights", None):
            for h in r.highlights:
                block += f"\n    > {h}"
        elif getattr(r, "text", None):
            # Trim to a reasonable snippet
            snippet = r.text[:500].strip()
            if len(r.text) > 500:
                snippet += "…"
            block += f"\n    {snippet}"
        parts.append(block)

    return history.cap("\n\n".join(parts))


# ── Tool schema (matches the format in tools.py) ─────────────────────

WEB_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web using Exa. Use this to look up documentation, "
            "error messages, library APIs, or any information not in the "
            "local codebase. Returns titles, URLs, and text snippets."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language search query",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results (1-10, default 5)",
                },
            },
            "required": ["query"],
        },
    },
}
