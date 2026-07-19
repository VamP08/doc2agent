"""Live agent evals: scripted tasks against a running Doc2Agent server.

Requires: a server (default http://127.0.0.1:8000) with GROQ_API_KEY set.
Each task asks the agent something with a deterministic, machine-checkable
ground truth, then verifies the outcome against the live store — not just
the agent's own claim. Produces evals/scorecard.md.

Run:  python -m evals.agent_evals
"""
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = os.environ.get("DOC2AGENT_URL", "http://127.0.0.1:8000")
SCORECARD = Path(__file__).parent / "scorecard.md"


def api(method: str, path: str, **kwargs):
    resp = httpx.request(method, BASE + path, timeout=180, **kwargs)
    resp.raise_for_status()
    return resp.json()


def chat(session_id: str, message: str) -> dict:
    return api(
        "POST", "/api/chat",
        json={"session_id": session_id, "message": message, "auto_approve": True},
    )


def extract_shipment_id(text: str) -> str | None:
    match = re.search(r"SHP-\d+", text)
    return match.group(0) if match else None


# ---- tasks: (name, run(session_id) -> (passed, detail)) --------------------

def task_count_warehouses(sid):
    reply = chat(sid, "How many warehouses are there in total? Answer with just the number.")
    truth = api("GET", "/demo/warehouses")["count"]
    passed = str(truth) in reply["reply"]
    return passed, f"expected {truth}, reply: {reply['reply'][:80]!r}"


def task_create_shipment(sid):
    reply = chat(sid, "Create a standard shipment of 3 kg from Delhi to Chennai. Reply with its shipment ID.")
    shipment_id = extract_shipment_id(reply["reply"])
    if not shipment_id:
        return False, f"no SHP id in reply: {reply['reply'][:80]!r}"
    s = api("GET", f"/demo/shipments/{shipment_id}")
    passed = s["origin_city"] == "Delhi" and s["dest_city"] == "Chennai" and s["weight_kg"] == 3
    return passed, f"{shipment_id}: {s['origin_city']}→{s['dest_city']} {s['weight_kg']}kg"


def task_lookup_destination(sid):
    s = api("POST", "/demo/shipments", json={"origin_city": "Kolkata", "dest_city": "Jaipur"})
    reply = chat(sid, f"What is the destination city of shipment {s['id']}?")
    return "Jaipur" in reply["reply"], f"reply: {reply['reply'][:80]!r}"


def task_multi_hop_courier(sid):
    """Requires chaining: find the shipment's courier, then the courier's name."""
    idle = api("GET", "/demo/couriers", params={"status": "idle"})["couriers"]
    if not idle:
        return None, "skipped — no idle courier available"
    s = api("POST", "/demo/shipments", json={"origin_city": "Mumbai", "dest_city": "Delhi"})
    api("POST", f"/demo/shipments/{s['id']}/assign", json={"courier_id": idle[0]["id"]})
    reply = chat(sid, f"What is the NAME of the courier assigned to shipment {s['id']}?")
    return idle[0]["name"] in reply["reply"], f"expected {idle[0]['name']}, reply: {reply['reply'][:80]!r}"


def task_write_with_verification(sid):
    """Check the event history, not current status — the live simulator may
    advance the shipment further between the agent's write and our check."""
    s = api("POST", "/demo/shipments", json={"origin_city": "Pune", "dest_city": "Hyderabad"})
    chat(sid, f"Mark shipment {s['id']} as picked_up with the note 'collected by eval'.")
    events = api("GET", f"/demo/shipments/{s['id']}/events")["events"]
    agent_event = any(
        e["status"] == "picked_up" and "Scanned" not in e["note"] for e in events
    )
    return agent_event, f"events: {[(e['status'], e['note']) for e in events]}"


TASKS = [
    ("count-warehouses (single read)", task_count_warehouses),
    ("create-shipment (write + ID reporting)", task_create_shipment),
    ("lookup-destination (targeted read)", task_lookup_destination),
    ("multi-hop-courier (chained calls)", task_multi_hop_courier),
    ("status-update (write, store-verified)", task_write_with_verification),
]


def main() -> int:
    print(f"Doc2Agent agent evals against {BASE}")
    ingest = api("POST", "/api/ingest", json={"url": f"{BASE}/demo/openapi.json"})
    print(f"ingested demo API: {len(ingest['endpoints'])} endpoints\n")

    rows, passed_count, run_count = [], 0, 0
    for name, task in TASKS:
        sid = api("POST", "/api/ingest", json={"url": f"{BASE}/demo/openapi.json"})["session_id"]
        start = time.time()
        try:
            passed, detail = task(sid)
        except Exception as exc:
            passed, detail = False, f"exception: {exc}"
        elapsed = time.time() - start
        if passed is None:
            status = "SKIP"
        else:
            run_count += 1
            passed_count += passed
            status = "PASS" if passed else "FAIL"
        print(f"[{status}] {name} ({elapsed:.1f}s) — {detail}")
        rows.append((name, status, f"{elapsed:.1f}s", detail))

    score = f"{passed_count}/{run_count}"
    print(f"\nScore: {score}")

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        "# Agent Eval Scorecard",
        "",
        f"**Score: {score}** · model: `{os.environ.get('GROQ_AGENT_MODEL', 'llama-3.3-70b-versatile')}` · {timestamp}",
        "",
        "Each task is verified against the live store, not the agent's claim.",
        "",
        "| Task | Result | Time | Detail |",
        "|---|---|---|---|",
    ]
    for name, status, elapsed, detail in rows:
        lines.append(f"| {name} | {status} | {elapsed} | {detail.replace('|', '/')} |")
    SCORECARD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"scorecard written to {SCORECARD}")
    return 0 if passed_count == run_count else 1


if __name__ == "__main__":
    sys.exit(main())
