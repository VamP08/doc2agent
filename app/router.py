"""Tool routing for large APIs: cluster endpoints, pick relevant categories.

Tool-schema tokens compete with conversation context, and selection accuracy
degrades past a few dozen tools. For APIs under MAX_TOOLS endpoints we skip
routing entirely. Above that, endpoints are clustered by their first path
segment (deterministic, free) and a cheap LLM call picks the categories
relevant to this question; only those endpoints become tools for the turn.
"""
import json
import os
import re

from groq import Groq

from .models import Endpoint
from .tools import MAX_TOOLS

# Routing is simple classification — a small model keeps the 70B daily
# token budget free for real agent work.
ROUTER_MODEL = os.environ.get("GROQ_ROUTER_MODEL", "llama-3.1-8b-instant")

ROUTER_PROMPT = """You are an API-tool router. A user asked:

"{question}"

The API's endpoints are grouped into these categories:

{catalog}

Return ONLY a JSON object: {{"categories": ["name1", "name2"]}} — the 1 to 3
category names most likely needed to answer the question. No prose.
"""


def categorize(endpoints: list[Endpoint]) -> dict[str, list[Endpoint]]:
    """Group endpoints by first non-parameter path segment."""
    groups: dict[str, list[Endpoint]] = {}
    for ep in endpoints:
        segments = [s for s in ep.path.split("/") if s and not s.startswith("{")]
        key = re.sub(r"[^a-zA-Z0-9_-]", "_", segments[0]) if segments else "root"
        groups.setdefault(key, []).append(ep)
    return groups


def select_endpoints(
    question: str, endpoints: list[Endpoint], client: Groq | None = None
) -> tuple[list[Endpoint], list[str] | None]:
    """Return (endpoints to expose this turn, chosen category names or None).

    None for the category list means routing wasn't needed (small API).
    """
    if len(endpoints) <= MAX_TOOLS:
        return endpoints, None

    groups = categorize(endpoints)
    catalog = "\n".join(
        f"- {name} ({len(eps)} endpoints): "
        + "; ".join(f"{e.method} {e.path}" for e in eps[:3])
        + ("; …" if len(eps) > 3 else "")
        for name, eps in sorted(groups.items())
    )

    chosen_names: list[str] = []
    try:
        completion = (client or Groq()).chat.completions.create(
            model=ROUTER_MODEL,
            response_format={"type": "json_object"},
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": ROUTER_PROMPT.format(question=question, catalog=catalog),
                }
            ],
        )
        data = json.loads(completion.choices[0].message.content)
        chosen_names = [n for n in data.get("categories", []) if n in groups][:3]
    except Exception:
        chosen_names = []

    if not chosen_names:  # router failed — largest categories as fallback
        chosen_names = [
            n for n, _ in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:3]
        ]

    selected: list[Endpoint] = []
    for name in chosen_names:
        selected.extend(groups[name])
    return selected[:MAX_TOOLS], chosen_names
