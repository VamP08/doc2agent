"""Record one real AeroTrack agent turn for the console's first-load replay.

Needs the app running locally with a working model key. Pass the model the server is using,
so the recording says which model produced it:
    GROQ_AGENT_MODEL=openai/gpt-oss-120b python -m uvicorn app.main:app --port 8010
    python scripts/capture_replay.py --base http://127.0.0.1:8010 --model openai/gpt-oss-120b

The same prompt runs twice, denying the held write once and then approving it. Both runs must hold the
same request, so the deny outcome belongs to the request on screen, and neither may ask for a second
approval. Anything else is retried.
"""

import argparse
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

# Warehouses never change, so this has one right answer on every run: one read, then one write.
PROMPT = "Which warehouse has room for the most packages? Create a 5 kg express shipment from its city to Delhi."
DENY_REASON = "Not today, Delhi intake is closed."
OUT = Path(__file__).resolve().parent.parent / "static" / "replay.json"


def resolve(base: str, approval_id: str, approve: bool) -> None:
    body = {"approve": approve, "reason": "" if approve else DENY_REASON}
    threading.Thread(
        target=lambda: httpx.post(f"{base}/api/approvals/{approval_id}", json=body, timeout=30)
    ).start()


def run(base: str, approve: bool) -> tuple[dict, list, list]:
    with httpx.Client(base_url=base, timeout=180) as c:
        ing = c.post("/api/ingest", json={"url": f"{base}/demo/openapi.json"}).json()
        prefix, tail, t0, t_gate = [], [], time.monotonic(), None
        with c.stream(
            "POST", "/api/chat/stream", json={"session_id": ing["session_id"], "message": PROMPT}
        ) as r:
            for line in r.iter_lines():
                if not line.startswith("data: "):
                    continue
                ev = json.loads(line[6:])
                if ev["type"] == "done":
                    break
                now = time.monotonic()
                if t_gate is None:
                    prefix.append({"t": round((now - t0) * 1000), "ev": ev})
                    if ev["type"] == "approval_required":
                        t_gate = now
                        resolve(base, ev["approval_id"], approve)
                else:
                    tail.append({"t": round((now - t_gate) * 1000), "ev": ev})
                    if (
                        ev["type"] == "approval_required"
                    ):  # a second write: unblock it, reject the run
                        resolve(base, ev["approval_id"], False)
        return ing, prefix, tail


def usable(prefix: list, tail: list, approved: bool) -> bool:
    return bool(
        prefix
        and prefix[-1]["ev"]["type"] == "approval_required"
        and tail
        and tail[0]["ev"]["type"] == "approval_result"
        and tail[0]["ev"]["approved"] is approved
        and tail[-1]["ev"]["type"] == "reply"
        and not any(e["ev"]["type"] in ("approval_required", "error") for e in tail)
    )


def held(prefix: list) -> tuple:
    ev = prefix[-1]["ev"]
    return ev["method"], ev["path"], json.dumps(ev["args"], sort_keys=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--tries", type=int, default=5)
    ap.add_argument("--model", required=True, help="the agent model the server is pinned to")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    for attempt in range(1, args.tries + 1):
        # deny first: it changes nothing, so the approve run sees the same data and holds the same request
        _, prefix_no, no = run(base, approve=False)
        if not usable(prefix_no, no, False):
            print(f"attempt {attempt}: deny run unusable, retrying")
            continue
        ing, prefix, yes = run(base, approve=True)
        if usable(prefix, yes, True) and held(prefix) == held(prefix_no):
            break
        print(
            f"attempt {attempt}: approve run unusable or held a different request "
            f"({held(prefix) if prefix and prefix[-1]['ev']['type'] == 'approval_required' else 'no hold'} "
            f"vs {held(prefix_no)}), retrying"
        )
    else:
        raise SystemExit("could not record two matching runs")
    ingest = {k: ing[k] for k in ("source", "api_title", "api_description", "endpoints")}
    ingest["base_url"] = "/demo"
    OUT.write_text(
        json.dumps(
            {
                "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "model": args.model,
                "prompt": PROMPT,
                "ingest": ingest,
                "deny_reason": DENY_REASON,
                "prefix": prefix,
                "branches": {"approve": yes, "deny": no},
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"wrote {OUT} · {len(prefix)} events to the gate, {len(yes)}/{len(no)} after it")


if __name__ == "__main__":
    main()
