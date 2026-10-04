"""The recorded replay is well-formed and only uses events the page knows how to render."""
import json
from pathlib import Path

REPLAY = Path(__file__).resolve().parent.parent / "static" / "replay.json"
KNOWN = {"routing", "tool_call", "approval_required", "approval_result", "tool_result", "reply", "error"}


def load():
    return json.loads(REPLAY.read_text(encoding="utf-8"))


def test_replay_shape():
    d = load()
    assert d["prompt"] and d["recorded_at"] and d["model"] and d["ingest"]["endpoints"]
    assert d["ingest"]["base_url"] == "/demo"


def test_prefix_stops_at_the_gate():
    prefix = load()["prefix"]
    assert all(e["ev"]["type"] in KNOWN for e in prefix)
    assert prefix[-1]["ev"]["type"] == "approval_required"
    assert [e["t"] for e in prefix] == sorted(e["t"] for e in prefix)


def test_both_branches_resolve_and_answer():
    d = load()
    for name, approved in (("approve", True), ("deny", False)):
        events = d["branches"][name]
        assert all(e["ev"]["type"] in KNOWN for e in events)
        assert events[0]["ev"]["type"] == "approval_result" and events[0]["ev"]["approved"] is approved
        assert events[-1]["ev"]["type"] == "reply"
        # the replay handles one held write; a second one would stall playback
        assert not any(e["ev"]["type"] == "approval_required" for e in events)
