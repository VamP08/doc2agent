"""Unit tests: tool synthesis, router clustering, MCP export, persistence."""
import ast

from app.agent import AgentSession
from app.mcp_export import generate_mcp_server
from app.models import Endpoint, Param
from app.router import categorize, select_endpoints
from app.tools import MAX_TOOLS, build_toolset, endpoint_to_tool

EP = Endpoint(
    method="GET",
    path="/pets/{petId}",
    description="Get a pet",
    params=[
        Param(name="petId", location="path", type="integer", required=True),
        Param(name="verbose", location="query", type="boolean"),
    ],
)


def test_tool_schema_shape():
    schema = endpoint_to_tool(EP, 0)["function"]
    assert schema["name"].startswith("get_pets_petId")
    assert schema["parameters"]["required"] == ["petId"]
    assert schema["parameters"]["properties"]["petId"]["type"] == "integer"
    assert "(path)" in schema["parameters"]["properties"]["petId"]["description"]


def test_toolset_cap_and_unique_names():
    endpoints = [Endpoint(method="GET", path=f"/x/{i}") for i in range(60)]
    schemas, registry = build_toolset(endpoints)
    assert len(schemas) == MAX_TOOLS
    assert len({s["function"]["name"] for s in schemas}) == MAX_TOOLS
    assert len(registry) == MAX_TOOLS


def test_router_categorize():
    endpoints = [
        Endpoint(method="GET", path="/pets"),
        Endpoint(method="GET", path="/pets/{id}"),
        Endpoint(method="GET", path="/orders"),
        Endpoint(method="GET", path="/{version}/misc"),
    ]
    groups = categorize(endpoints)
    assert len(groups["pets"]) == 2
    assert len(groups["orders"]) == 1
    assert "misc" in groups  # first non-parameter segment


def test_router_skips_small_apis():
    endpoints = [Endpoint(method="GET", path=f"/a/{i}") for i in range(5)]
    selected, categories = select_endpoints("anything", endpoints, client=None)
    assert selected == endpoints
    assert categories is None  # no routing, no LLM call


def test_mcp_export_is_valid_python():
    endpoints = [
        EP,
        Endpoint(
            method="POST",
            path="/pets",
            description="Create",
            params=[
                Param(name="name", location="body", required=True),
                Param(name="filter[status]", location="query"),  # non-identifier name
                Param(name="class", location="query"),  # python keyword
            ],
        ),
    ]
    code = generate_mcp_server("https://api.example.com/v1", endpoints, "example")
    ast.parse(code)  # must be syntactically valid Python
    assert "FastMCP" in code and "https://api.example.com/v1" in code
    assert "filter[status]" in code  # original name preserved in locations map


def test_session_roundtrip():
    session = AgentSession(base_url="https://x.dev", endpoints=[EP], api_key="k")
    session.messages.append({"role": "user", "content": "hi"})
    restored = AgentSession.from_dict(session.to_dict())
    assert restored.base_url == session.base_url
    assert restored.endpoints[0].path == "/pets/{petId}"
    assert restored.messages == session.messages
    assert restored.api_key == "k"
