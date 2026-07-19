"""Golden-spec ingestion tests — offline, run on every CI push."""
import json
from pathlib import Path

import pytest

from app.ingest import parse_openapi, try_parse_spec

FIXTURES = Path(__file__).parent / "fixtures"
PETSTORE_URL = "https://petstore3.swagger.io/api/v3/openapi.json"


@pytest.fixture(scope="module")
def petstore():
    spec = try_parse_spec((FIXTURES / "petstore_openapi.json").read_text(encoding="utf-8"))
    assert spec is not None, "fixture must parse as an OpenAPI spec"
    return parse_openapi(spec, PETSTORE_URL)


def test_petstore_endpoint_count(petstore):
    _, endpoints = petstore
    assert len(endpoints) == 19


def test_petstore_base_url(petstore):
    base_url, _ = petstore
    assert base_url == "https://petstore3.swagger.io/api/v3"


def test_path_params_extracted(petstore):
    _, endpoints = petstore
    get_pet = next(e for e in endpoints if e.method == "GET" and e.path == "/pet/{petId}")
    (param,) = [p for p in get_pet.params if p.name == "petId"]
    assert param.location == "path"
    assert param.required


def test_ref_body_params_resolved(petstore):
    """POST /pet's body is a $ref to components/schemas/Pet — must resolve."""
    _, endpoints = petstore
    post_pet = next(e for e in endpoints if e.method == "POST" and e.path == "/pet")
    body_params = {p.name for p in post_pet.params if p.location == "body"}
    assert {"name", "status", "photoUrls"} <= body_params


def test_query_params_extracted(petstore):
    _, endpoints = petstore
    find = next(e for e in endpoints if e.path == "/pet/findByStatus")
    (status,) = [p for p in find.params if p.name == "status"]
    assert status.location == "query"


def test_swagger_v2_supported():
    spec = {
        "swagger": "2.0",
        "host": "api.example.com",
        "basePath": "/v1",
        "schemes": ["https"],
        "paths": {
            "/things/{id}": {
                "get": {
                    "summary": "Get a thing",
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "type": "integer"}
                    ],
                }
            }
        },
    }
    base_url, endpoints = parse_openapi(spec, "https://api.example.com/swagger.json")
    assert base_url == "https://api.example.com/v1"
    assert endpoints[0].method == "GET"
    assert endpoints[0].params[0].type == "integer"


def test_non_spec_returns_none():
    assert try_parse_spec("<html><body>not a spec</body></html>") is None
    assert try_parse_spec('{"just": "json"}') is None
