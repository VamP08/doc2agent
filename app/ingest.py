"""Docs ingestion: turn an API documentation URL into structured endpoints.

Two paths:
1. Deterministic — the URL serves an OpenAPI/Swagger spec (JSON or YAML):
   parse it directly, no LLM involved.
2. LLM extraction — the URL is human-readable HTML docs: strip to text and
   have the model extract endpoint definitions as structured JSON.
"""
import json
import os
from urllib.parse import urljoin, urlparse

import httpx
import yaml
from bs4 import BeautifulSoup
from groq import Groq

from .models import Endpoint, Param
from .safety import assert_public_url

USER_AGENT = "Doc2Agent/1.0 (+portfolio demo)"
MAX_DOC_CHARS = 40_000
LLM_CHUNK_CHARS = 14_000

EXTRACTION_MODEL = os.environ.get("GROQ_EXTRACTION_MODEL", "llama-3.3-70b-versatile")

EXTRACTION_PROMPT = """You are an expert API-documentation parser.
From the documentation text below, extract every REST endpoint you can find.

Return ONLY a JSON object of this exact shape:
{
  "base_url": "https://api.example.com",
  "endpoints": [
    {
      "method": "GET",
      "path": "/things/{id}",
      "description": "one-line summary",
      "params": [
        {"name": "id", "location": "path", "type": "string", "required": true,
         "description": "..."}
      ]
    }
  ]
}

Rules:
- "location" must be one of: query, path, body, header.
- Path parameters appear in the path in {curly_braces}.
- If the base URL is not stated in the text, set "base_url" to "".
- Skip endpoints that are deprecated or clearly non-REST (websockets, SDK-only).
- No prose, no markdown fences — raw JSON only.

DOCUMENTATION TEXT:
"""


def fetch(url: str) -> tuple[str, str]:
    """Fetch a URL and return (content_type, text)."""
    assert_public_url(url)
    with httpx.Client(
        follow_redirects=True, timeout=25, headers={"User-Agent": USER_AGENT}
    ) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.headers.get("content-type", ""), resp.text


def try_parse_spec(text: str) -> dict | None:
    """Return a dict if the text is an OpenAPI/Swagger spec, else None."""
    for loader in (json.loads, yaml.safe_load):
        try:
            data = loader(text)
        except Exception:
            continue
        if isinstance(data, dict) and ("openapi" in data or "swagger" in data):
            return data
    return None


def _resolve_ref(node: dict, spec: dict, depth: int = 0) -> dict:
    """Follow local $ref pointers like '#/components/schemas/Pet'."""
    while isinstance(node, dict) and "$ref" in node and depth < 5:
        ref = node["$ref"]
        if not ref.startswith("#/"):
            return {}
        target: dict | None = spec
        for part in ref[2:].split("/"):
            target = target.get(part) if isinstance(target, dict) else None
        if not isinstance(target, dict):
            return {}
        node, depth = target, depth + 1
    return node if isinstance(node, dict) else {}


def _openapi_params(operation: dict, path_item: dict, spec: dict) -> list[Param]:
    params: list[Param] = []
    raw = (path_item.get("parameters") or []) + (operation.get("parameters") or [])
    for p in raw:
        p = _resolve_ref(p, spec) if isinstance(p, dict) else None
        if not p:
            continue
        schema = p.get("schema") or {}
        params.append(
            Param(
                name=p.get("name", ""),
                location=p.get("in", "query") if p.get("in") in ("query", "path", "header") else "query",
                type=schema.get("type") or p.get("type") or "string",
                required=bool(p.get("required", False)),
                description=(p.get("description") or "")[:300],
            )
        )
    body = _resolve_ref(operation.get("requestBody") or {}, spec)
    content = body.get("content") or {}
    json_schema = _resolve_ref((content.get("application/json") or {}).get("schema") or {}, spec)
    for name, prop in (json_schema.get("properties") or {}).items():
        prop = _resolve_ref(prop, spec) if isinstance(prop, dict) else None
        if not prop:
            continue
        params.append(
            Param(
                name=name,
                location="body",
                type=prop.get("type", "string"),
                required=name in (json_schema.get("required") or []),
                description=(prop.get("description") or "")[:300],
            )
        )
    return params


def parse_openapi(spec: dict, spec_url: str) -> tuple[str, list[Endpoint]]:
    """Extract (base_url, endpoints) from an OpenAPI 3.x or Swagger 2.0 spec."""
    if "servers" in spec and spec["servers"]:
        base_url = spec["servers"][0].get("url", "")
        base_url = urljoin(spec_url, base_url)  # resolves relative server URLs
    elif "host" in spec:  # Swagger 2.0
        scheme = (spec.get("schemes") or ["https"])[0]
        base_url = f"{scheme}://{spec['host']}{spec.get('basePath', '')}"
    else:
        parsed = urlparse(spec_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

    endpoints: list[Endpoint] = []
    for path, path_item in (spec.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method in ("get", "post", "put", "patch", "delete"):
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            desc = operation.get("summary") or operation.get("description") or ""
            endpoints.append(
                Endpoint(
                    method=method.upper(),
                    path=path,
                    description=desc.strip()[:300],
                    params=_openapi_params(operation, path_item, spec),
                )
            )
    return base_url.rstrip("/"), endpoints


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)[:MAX_DOC_CHARS]


def llm_extract(text: str, page_url: str) -> tuple[str, list[Endpoint]]:
    """Extract endpoints from free-form docs text via the LLM, chunk by chunk."""
    client = Groq()
    chunks = [text[i : i + LLM_CHUNK_CHARS] for i in range(0, len(text), LLM_CHUNK_CHARS)]

    base_url = ""
    seen: dict[str, Endpoint] = {}
    for chunk in chunks[:3]:
        completion = client.chat.completions.create(
            model=EXTRACTION_MODEL,
            response_format={"type": "json_object"},
            temperature=0,
            messages=[{"role": "user", "content": EXTRACTION_PROMPT + chunk}],
        )
        try:
            data = json.loads(completion.choices[0].message.content)
        except (json.JSONDecodeError, TypeError):
            continue
        if not base_url and data.get("base_url"):
            base_url = str(data["base_url"]).rstrip("/")
        for raw in data.get("endpoints") or []:
            try:
                ep = Endpoint.model_validate(raw)
            except Exception:
                continue
            seen.setdefault(f"{ep.method} {ep.path}", ep)

    if not base_url:
        parsed = urlparse(page_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
    return base_url, list(seen.values())


def ingest(url: str) -> tuple[str, str, list[Endpoint]]:
    """Return (source, base_url, endpoints) for a docs URL."""
    _, text = fetch(url)

    spec = try_parse_spec(text)
    if spec:
        base_url, endpoints = parse_openapi(spec, url)
        return "openapi", base_url, endpoints

    doc_text = html_to_text(text)
    if len(doc_text) < 200:
        raise ValueError(
            "Page had almost no readable text — it may render docs via JavaScript. "
            "Try the API's OpenAPI/Swagger spec URL instead (often /openapi.json)."
        )
    base_url, endpoints = llm_extract(doc_text, url)
    if not endpoints:
        raise ValueError("No REST endpoints could be extracted from this page.")
    return "llm", base_url, endpoints
