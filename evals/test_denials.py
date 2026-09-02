"""A denied write must not become a standing ban for the rest of the session."""
import json

from app.agent import DENIAL_MARKER, drop_denied_calls


def denied_turn() -> list[dict]:
    """History after: user asks for a write, human denies it, agent explains."""
    return [
        {"role": "system", "content": "you are an api agent"},
        {"role": "user", "content": "Create a shipment from Delhi to Mumbai."},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "post_shipments_0", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": json.dumps({"error": "Denied...", "marker": DENIAL_MARKER}),
        },
        {"role": "assistant", "content": "That was declined by the operator."},
    ]


def test_denied_pair_is_removed():
    messages = denied_turn()
    drop_denied_calls(messages)
    assert not any(m.get("role") == "tool" for m in messages)
    assert not any(m.get("tool_calls") for m in messages)


def test_narrative_and_system_prompt_survive():
    messages = denied_turn()
    drop_denied_calls(messages)
    assert messages[0]["role"] == "system"
    assert [m["role"] for m in messages] == ["system", "user", "assistant"]


def test_successful_calls_are_untouched():
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_ok",
                    "type": "function",
                    "function": {"name": "get_warehouses_0", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_ok", "content": '{"status": 200}'},
    ]
    before = [dict(m) for m in messages]
    drop_denied_calls(messages)
    assert messages == before


def test_only_the_denied_call_goes():
    messages = denied_turn()
    messages += [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_ok",
                    "type": "function",
                    "function": {"name": "get_warehouses_0", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_ok", "content": '{"status": 200}'},
    ]
    drop_denied_calls(messages)
    tool_ids = [m["tool_call_id"] for m in messages if m.get("role") == "tool"]
    assert tool_ids == ["call_ok"]


def test_no_denials_is_a_no_op():
    messages = [{"role": "user", "content": "hi"}]
    drop_denied_calls(messages)
    assert messages == [{"role": "user", "content": "hi"}]
