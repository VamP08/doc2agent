"""Router tests against a real large API's path list (DigitalOcean, 659 endpoints)."""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.models import Endpoint
from app.router import categorize, category_of, select_endpoints
from app.tools import MAX_TOOLS

FIXTURE = Path(__file__).parent / "fixtures" / "digitalocean_paths.txt"


@pytest.fixture(scope="module")
def digitalocean() -> list[Endpoint]:
    endpoints = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        method, path = line.split(" ", 1)
        endpoints.append(Endpoint(method=method, path=path))
    return endpoints


def fake_client(categories) -> MagicMock:
    client = MagicMock()
    message = MagicMock()
    message.content = json.dumps({"categories": categories})
    client.chat.completions.create.return_value.choices = [MagicMock(message=message)]
    return client


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/v2/droplets", "droplets"),          # version prefix skipped
        ("/api/v3/pets/{id}", "pets"),         # api + version both skipped
        ("/2026-01-01/messages", "messages"),  # dated version skipped
        ("/rest/V2/orders", "orders"),         # case-insensitive
        ("/pets", "pets"),                     # unprefixed path unaffected
        ("/v2", "v2"),                         # nothing left: keep the segment
        ("/", "root"),
    ],
)
def test_category_of(path, expected):
    assert category_of(path) == expected


def test_version_prefix_does_not_collapse_the_api(digitalocean):
    """Every DigitalOcean path starts with /v2; grouping on it gave 4 buckets."""
    groups = categorize(digitalocean)
    assert len(groups) > 40
    assert "v2" not in groups
    assert {"droplets", "databases", "apps", "kubernetes"} <= set(groups)


def test_no_category_swallows_the_whole_api(digitalocean):
    groups = categorize(digitalocean)
    biggest = max(len(eps) for eps in groups.values())
    assert biggest < len(digitalocean) / 4


def test_every_chosen_category_gets_tools(digitalocean):
    """gen-ai alone has 119 endpoints and would fill the budget on its own."""
    chosen = ["gen-ai", "droplets", "databases"]
    selected, categories = select_endpoints(
        "list my droplets", digitalocean, fake_client(chosen)
    )
    assert categories == chosen
    assert len(selected) == MAX_TOOLS
    represented = {category_of(e.path) for e in selected}
    assert represented == set(chosen)


def test_router_failure_falls_back_to_largest_categories(digitalocean):
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("groq down")
    selected, categories = select_endpoints("anything", digitalocean, client)
    assert len(categories) == 3
    assert 0 < len(selected) <= MAX_TOOLS


def test_hallucinated_category_is_ignored(digitalocean):
    selected, categories = select_endpoints(
        "list my droplets", digitalocean, fake_client(["droplets", "not_a_category"])
    )
    assert categories == ["droplets"]
    assert {category_of(e.path) for e in selected} == {"droplets"}
