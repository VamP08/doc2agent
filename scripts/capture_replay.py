"""Record one real AeroTrack agent turn for the console's first-load replay.

Needs the app running locally with a working model key:
    python -m uvicorn app.main:app --port 8010
    python scripts/capture_replay.py --base http://127.0.0.1:8010

The same prompt runs twice, approving the held write once and denying it once. Both runs must hold the
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

PROMPT = "Find a shipment that has no courier yet and assign it an idle courier from its origin city."
DENY_REASON = "Not that one, check with dispatch first."
OUT = Path(__file__).resolve().parent.parent / "static" / "replay.json"


def resolve(base: str, approval_id: str, approve: bool) -> None:
    body = {"approve": approve, "reason": "" if approve else DENY_REASON}
    threading.Thread(target=lambda: httpx.post(f"{base}/api/approvals/{approval_id}", json=body, timeout=30)).start()


def run(base: str, approve: bool) -> tuple[dict, list, list]:
    with httpx.Client(base_url=base, timeout=180) as c:
        ing = c.post("/api/ingest", json={"url": f"{base}/demo/openapi.json"}).json()
        prefix, tail, t0, t_gate = [], [], time.monotonic(), None
        with c.stream("POST", "/api/chat/stream", json={"session_id": ing["session_id"], "message": PROMPT}) as r:
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
                    if ev["type"] == "approval_required":  # a second write: unblock it, reject the run
                        resolve(base, ev["approval_id"], False)
        return ing, prefix, tail


def usable(prefix: list, tail: list, approved: bool) -> bool:
    return bool(
        prefix and prefix[-1]["ev"]["type"] == "approval_required"
        and tail and tail[0]["ev"]["type"] == "approval_result" and tail[0]["ev"]["approved"] is approved
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
    args = ap.parse_args()
    base = args.base.rstrip("/")
    for attempt in range(1, args.tries + 1):
        ing, prefix, yes = run(base, approve=True)
        if not usable(prefix, yes, True):
            print(f"attempt {attempt}: approve run unusable, retrying")
            continue
        _, prefix_no, no = run(base, approve=False)
        if usable(prefix_no, no, False) and held(prefix) == held(prefix_no):
            break
        print(f"attempt {attempt}: deny run unusable or held a different request, retrying")
    else:
        raise SystemExit("could not record two matching runs")
    ingest = {k: ing[k] for k in ("source", "api_title", "api_description", "endpoints")}
    ingest["base_url"] = "/demo"
    OUT.write_text(json.dumps({
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "prompt": PROMPT, "ingest": ingest, "deny_reason": DENY_REASON,
        "prefix": prefix, "branches": {"approve": yes, "deny": no},
    }, indent=1), encoding="utf-8")
    print(f"wrote {OUT} · {len(prefix)} events to the gate, {len(yes)}/{len(no)} after it")


if __name__ == "__main__":
    main()
