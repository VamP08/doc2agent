"""Tool routing for large APIs: cluster endpoints, pick relevant categories.

Tool-schema tokens compete with conversation context, and selection accuracy
degrades past a few dozen tools. For APIs under MAX_TOOLS endpoints we skip
routing entirely. Above that, endpoints are clustered by their first path
segment (deterministic, free) and a cheap LLM call picks the categories
relevant to this question; only those endpoints become tools for the turn.
"""
import json
import re

from groq import Groq

from .llm import ROUTER_MODELS, candidates, complete
from .models import Endpoint
from .tools import MAX_TOOLS

ROUTER_PROMPT = """You are an API-tool router. A user asked:

"{question}"

The API's endpoints are grouped into these categories:

{catalog}

Return ONLY a JSON object: {{"categories": ["name1", "name2"]}} — the 1 to 3
category names most likely needed to answer the question. No prose.
"""


# Segments that carry no topic meaning, so grouping on them buckets a whole
# API into one category. DigitalOcean prefixes all 659 of its paths with /v2.
_NOISE_SEGMENT = re.compile(r"^(?:api|rest|v\d+(?:\.\d+)*|\d{4}-\d{2}-\d{2})$", re.I)


def category_of(path: str) -> str:
    """First path segment that names a resource, skipping version prefixes."""
    segments = [s for s in path.split("/") if s and not s.startswith("{")]
    meaningful = [s for s in segments if not _NOISE_SEGMENT.match(s)]
    chosen = (meaningful or segments or ["root"])[0]
    return re.sub(r"[^a-zA-Z0-9_-]", "_", chosen)


def categorize(endpoints: list[Endpoint]) -> dict[str, list[Endpoint]]:
    """Group endpoints by the first path segment that names a resource."""
    groups: dict[str, list[Endpoint]] = {}
    for ep in endpoints:
        key = category_of(ep.path)
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
        completion = complete(
            client or Groq(),
            candidates("router", ROUTER_MODELS),
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

    # Round-robin, not concatenate-then-truncate: DigitalOcean's gen-ai category
    # alone holds 119 endpoints, which would fill the budget and leave the other
    # chosen categories with no tools at all.
    # ponytail: within a category it is still first-N by spec order; rank by
    # relevance to the question if a measured miss ever justifies the call.
    queues = [list(groups[name]) for name in chosen_names]
    selected: list[Endpoint] = []
    while queues and len(selected) < MAX_TOOLS:
        for queue in queues:
            if queue:
                selected.append(queue.pop(0))
                if len(selected) == MAX_TOOLS:
                    break
        queues = [q for q in queues if q]
    return selected, chosen_names
