"""Turn extracted endpoints into LLM tool schemas, and execute real HTTP calls."""
import json
import re
from urllib.parse import urlencode

import httpx

from .models import Endpoint, ToolCallTrace
from .safety import assert_public_url

MAX_TOOLS = 40
MAX_RESPONSE_CHARS = 8_000
TYPE_MAP = {"integer": "integer", "number": "number", "boolean": "boolean", "array": "array"}


def tool_name(endpoint: Endpoint, index: int) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", endpoint.path).strip("_") or "root"
    return f"{endpoint.method.lower()}_{slug}"[:58] + f"_{index}"


def endpoint_to_tool(endpoint: Endpoint, index: int) -> dict:
    properties, required = {}, []
    for p in endpoint.params:
        properties[p.name] = {
            "type": TYPE_MAP.get(p.type, "string"),
            "description": f"({p.location}) {p.description}".strip(),
        }
        if p.required:
            required.append(p.name)
    return {
        "type": "function",
        "function": {
            "name": tool_name(endpoint, index),
            "description": f"{endpoint.method} {endpoint.path} — {endpoint.description}"[:1024],
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def build_toolset(endpoints: list[Endpoint]) -> tuple[list[dict], dict[str, Endpoint]]:
    """Return (tool_schemas, name -> endpoint registry), capped at MAX_TOOLS."""
    schemas, registry = [], {}
    for i, ep in enumerate(endpoints[:MAX_TOOLS]):
        schema = endpoint_to_tool(ep, i)
        schemas.append(schema)
        registry[schema["function"]["name"]] = ep
    return schemas, registry


def execute_endpoint(
    endpoint: Endpoint,
    args: dict,
    base_url: str,
    api_key: str | None = None,
    auth_header: str = "Authorization",
    auth_scheme: str = "Bearer",
) -> tuple[str, ToolCallTrace]:
    """Fire the real HTTP request an agent tool call maps to."""
    path = endpoint.path
    query: dict = {}
    body: dict = {}
    headers = {"User-Agent": "Doc2Agent/1.0", "Accept": "application/json"}

    locations = {p.name: p.location for p in endpoint.params}
    for name, value in args.items():
        loc = locations.get(name, "query")
        if loc == "path":
            path = path.replace("{" + name + "}", str(value))
        elif loc == "body":
            body[name] = value
        elif loc == "header":
            headers[name] = str(value)
        else:
            query[name] = value

    if api_key:
        value = f"{auth_scheme} {api_key}".strip() if auth_header == "Authorization" else api_key
        headers[auth_header] = value

    url = base_url.rstrip("/") + "/" + path.lstrip("/")
    display_url = url + ("?" + urlencode(query) if query else "")
    trace = ToolCallTrace(tool="", method=endpoint.method, url=display_url)

    try:
        assert_public_url(url)
        with httpx.Client(follow_redirects=True, timeout=25) as client:
            resp = client.request(
                endpoint.method,
                url,
                params=query or None,
                json=body or None,
                headers=headers,
            )
        trace.status = resp.status_code
        trace.ok = resp.is_success
        text = resp.text[:MAX_RESPONSE_CHARS]
        trace.summary = f"HTTP {resp.status_code}, {len(resp.text)} chars"
        result = {"status": resp.status_code, "body": text}
    except Exception as exc:
        trace.ok = False
        trace.summary = f"{type(exc).__name__}: {exc}"
        result = {"error": trace.summary}

    return json.dumps(result), trace
