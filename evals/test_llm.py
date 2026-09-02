"""Model failover: a retired model must not take the app down."""
import os
from unittest.mock import MagicMock

import pytest

from app.llm import NoModelAvailable, candidates, complete

RETIRED = Exception(
    "Error code: 404 - {'error': {'message': 'The model "
    "`llama-3.3-70b-versatile` does not exist or you do not have access to it.'}}"
)
RATE_LIMITED = Exception("Error code: 429 - rate_limit_exceeded: tokens per day")


def client_raising(*errors):
    """Client whose calls raise the given errors in order, then succeed."""
    client = MagicMock()
    client.chat.completions.create.side_effect = list(errors) + ["ok"]
    return client


def test_retired_model_falls_through_to_the_next():
    client = client_raising(RETIRED)
    assert complete(client, ["gone-model", "live-model"], messages=[]) == "ok"
    used = [c.kwargs["model"] for c in client.chat.completions.create.call_args_list]
    assert used == ["gone-model", "live-model"]


def test_first_working_model_wins_without_extra_calls():
    client = client_raising()
    complete(client, ["a", "b", "c"], messages=[])
    assert client.chat.completions.create.call_count == 1


def test_rate_limit_is_not_a_model_problem_and_propagates():
    """Retrying a 429 on another model would hide a real account-level limit."""
    client = client_raising(RATE_LIMITED)
    with pytest.raises(Exception, match="429"):
        complete(client, ["a", "b"], messages=[])
    assert client.chat.completions.create.call_count == 1


def test_all_models_gone_raises_a_named_error():
    client = MagicMock()
    client.chat.completions.create.side_effect = RETIRED
    with pytest.raises(NoModelAvailable):
        complete(client, ["a", "b"], messages=[])


def test_env_override_pins_one_model(monkeypatch):
    monkeypatch.setenv("GROQ_AGENT_MODEL", "pinned-model")
    assert candidates("agent", ["default-a", "default-b"]) == ["pinned-model"]


def test_no_override_keeps_the_default_list(monkeypatch):
    monkeypatch.delenv("GROQ_AGENT_MODEL", raising=False)
    assert candidates("agent", ["default-a", "default-b"]) == ["default-a", "default-b"]


def test_no_retired_model_names_remain_in_defaults():
    from app.llm import AGENT_MODELS, EXTRACTION_MODELS, ROUTER_MODELS

    for models in (AGENT_MODELS, EXTRACTION_MODELS, ROUTER_MODELS):
        assert models, "each role needs at least one candidate"
        assert not any("llama-3.3" in m or "llama-3.1" in m for m in models)
