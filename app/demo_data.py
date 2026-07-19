"""In-memory data store and live simulator for the AeroTrack demo API.

The simulator mutates the store every few seconds — new shipments arrive,
statuses advance, couriers get freed — so the monitor dashboard always has
live motion, and agent-made changes land in the same store viewers watch.
"""
import asyncio
import random
from collections import deque
from datetime import datetime, timezone
from itertools import count

CITIES = ["Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Pune", "Kolkata", "Jaipur"]
STATUS_FLOW = ["created", "picked_up", "in_transit", "out_for_delivery", "delivered"]
ALL_STATUSES = STATUS_FLOW + ["delayed"]
PRIORITIES = ["standard", "express"]
COURIER_NAMES = ["Arjun", "Meera", "Ravi", "Sana", "Vikram", "Priya", "Farhan", "Divya"]

shipments: dict[str, dict] = {}
couriers: dict[str, dict] = {}
warehouses: dict[str, dict] = {}
events: deque = deque(maxlen=120)
request_log: deque = deque(maxlen=250)

_ship_ids = count(1001)
_rng = random.Random(7)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_event(text: str, kind: str = "simulator") -> None:
    events.appendleft({"time": now_iso(), "kind": kind, "text": text})


def record_request(method: str, path: str, status: int, caller: str) -> None:
    request_log.appendleft(
        {"time": now_iso(), "method": method, "path": path, "status": status, "caller": caller}
    )


def create_shipment(
    origin_city: str,
    dest_city: str,
    weight_kg: float = 2.0,
    priority: str = "standard",
    actor: str = "simulator",
) -> dict:
    sid = f"SHP-{next(_ship_ids)}"
    ts = now_iso()
    shipment = {
        "id": sid,
        "status": "created",
        "origin_city": origin_city,
        "dest_city": dest_city,
        "weight_kg": round(float(weight_kg), 2),
        "priority": priority,
        "courier_id": None,
        "eta_hours": _rng.randint(4, 48),
        "created_at": ts,
        "updated_at": ts,
        "events": [{"time": ts, "status": "created", "note": f"Created by {actor}"}],
    }
    shipments[sid] = shipment
    record_event(f"New {priority} shipment {sid}: {origin_city} → {dest_city}", kind=actor)
    return shipment


def set_status(shipment: dict, status: str, note: str, actor: str = "simulator") -> None:
    shipment["status"] = status
    shipment["updated_at"] = now_iso()
    shipment["events"].append({"time": shipment["updated_at"], "status": status, "note": note})
    record_event(f"{shipment['id']} → {status} ({note})", kind=actor)
    if status == "delivered" and shipment["courier_id"]:
        courier = couriers.get(shipment["courier_id"])
        if courier:
            courier["active_shipments"] = max(0, courier["active_shipments"] - 1)
            if courier["active_shipments"] == 0:
                courier["status"] = "idle"


def assign_courier(shipment: dict, courier: dict, actor: str = "simulator") -> None:
    shipment["courier_id"] = courier["id"]
    shipment["updated_at"] = now_iso()
    courier["status"] = "on_route"
    courier["active_shipments"] += 1
    record_event(f"{courier['name']} ({courier['id']}) assigned to {shipment['id']}", kind=actor)


def _idle_couriers() -> list[dict]:
    return [c for c in couriers.values() if c["status"] == "idle"]


def seed() -> None:
    if warehouses:  # already seeded (e.g. uvicorn --reload)
        return
    for i, city in enumerate(CITIES[:4], start=1):
        warehouses[f"WH-{i}"] = {
            "id": f"WH-{i}",
            "city": city,
            "capacity": 500,
            "packages_held": _rng.randint(120, 420),
        }
    for i, name in enumerate(COURIER_NAMES, start=1):
        couriers[f"CR-{i}"] = {
            "id": f"CR-{i}",
            "name": name,
            "city": _rng.choice(CITIES),
            "vehicle": _rng.choice(["bike", "van", "truck"]),
            "status": "idle",
            "active_shipments": 0,
            "rating": round(_rng.uniform(3.8, 5.0), 1),
        }
    for _ in range(10):
        origin, dest = _rng.sample(CITIES, 2)
        s = create_shipment(origin, dest, _rng.uniform(0.5, 30), _rng.choice(PRIORITIES))
        for _ in range(_rng.randint(0, 3)):
            _advance(s)
    record_event("AeroTrack simulator online — live order flow started", kind="system")


def _advance(shipment: dict) -> None:
    status = shipment["status"]
    if status == "delivered":
        return
    if status == "delayed":
        set_status(shipment, "in_transit", "Delay resolved, back on route")
        return
    if _rng.random() < 0.08 and status == "in_transit":
        set_status(shipment, "delayed", _rng.choice(["Traffic congestion", "Weather hold", "Vehicle breakdown"]))
        return
    next_status = STATUS_FLOW[STATUS_FLOW.index(status) + 1]
    if next_status == "picked_up" and not shipment["courier_id"]:
        idle = _idle_couriers()
        if not idle:
            return
        assign_courier(shipment, _rng.choice(idle))
    set_status(shipment, next_status, f"Scanned at {_rng.choice(CITIES)} hub")


async def simulator_loop() -> None:
    while True:
        await asyncio.sleep(_rng.uniform(3, 7))
        try:
            active = [s for s in shipments.values() if s["status"] != "delivered"]
            # Keep creation slower than delivery throughput so couriers free up
            # and the fleet never deadlocks with zero idle couriers.
            if _rng.random() < 0.22 or not active:
                origin, dest = _rng.sample(CITIES, 2)
                create_shipment(origin, dest, _rng.uniform(0.5, 30), _rng.choice(PRIORITIES))
            else:
                in_progress = [s for s in active if s["courier_id"] or s["status"] == "delayed"]
                pool = in_progress if in_progress and _rng.random() < 0.75 else active
                for shipment in _rng.sample(pool, k=min(2, len(pool))):
                    _advance(shipment)
        except Exception:  # simulator must never die
            pass
