"""Model failover: a retired model must not take the app down."""

from unittest.mock import MagicMock

import pytest

from app.llm import NoModelAvailable, candidates, complete

RETIRED = Exception(
    "Error code: 404 - {'error': {'message': 'The model "
    "`llama-3.3-70b-versatile` does not exist or you do not have access to it.'}}"
)
RATE_LIMITED = Exception("Error code: 429 - rate_limit_exceeded: tokens per day")
DAILY_CAP = Exception(
    "Error code: 429 - rate_limit_exceeded: Rate limit reached for model `a` "
    "on tokens per day (TPD): Limit 200000, Used 199641. Please try again in 15m59.9s."
)
MINUTE_CAP = Exception(
    "Error code: 429 - rate_limit_exceeded: Rate limit reached for model `a` "
    "on tokens per minute (TPM): Limit 8000, Used 7200. Please try again in 12.5s."
)


@pytest.fixture(autouse=True)
def fresh_cooldowns():
    from app import llm

    llm._cooldown.clear()
    yield
    llm._cooldown.clear()


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


def test_daily_cap_moves_to_the_next_model_and_skips_it_after():
    """Groq budgets tokens per model, so a spent model says nothing about the next one."""
    client = client_raising(DAILY_CAP)
    assert complete(client, ["a", "b"], messages=[]) == "ok"
    client.chat.completions.create.side_effect = ["ok"]
    complete(client, ["a", "b"], messages=[])
    used = [c.kwargs["model"] for c in client.chat.completions.create.call_args_list]
    assert used == ["a", "b", "b"]  # "a" is not asked again while its budget is spent


def test_per_minute_cap_waits_and_retries_the_same_model(monkeypatch):
    waits = []
    monkeypatch.setattr("app.llm.time.sleep", waits.append)
    client = client_raising(MINUTE_CAP)
    assert complete(client, ["a", "b"], messages=[]) == "ok"
    used = [c.kwargs["model"] for c in client.chat.completions.create.call_args_list]
    assert used == ["a", "a"] and waits == [12.5]


def test_every_model_capped_raises_the_rate_limit_for_the_message():
    client = MagicMock()
    client.chat.completions.create.side_effect = DAILY_CAP
    with pytest.raises(Exception, match="per day"):
        complete(client, ["a", "b"], messages=[])


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


def test_per_minute_limit_says_wait_a_minute_not_come_back_later():
    from app.main import _agent_error_detail

    tpm = Exception(
        "Error code: 429 - rate_limit_exceeded: Rate limit reached for model "
        "`openai/gpt-oss-120b` on tokens per minute (TPM): Limit 8000, Used 7200"
    )
    detail = _agent_error_detail(tpm)
    assert "minute" in detail and "few hours" not in detail
    assert "few hours" in _agent_error_detail(RATE_LIMITED)
