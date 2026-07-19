"""AeroTrack Logistics — the bundled demo API Doc2Agent can be pointed at.

A realistic delivery-operations REST API over the live in-memory store in
demo_data.py. FastAPI auto-generates its OpenAPI spec at /demo/openapi.json
and human docs at /demo/docs — so the same app demonstrates both ingestion
paths and every request shows up on the live monitor.
"""
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from . import demo_data as db

demo_app = FastAPI(
    title="AeroTrack Logistics API",
    version="1.0.0",
    description=(
        "Live package-delivery operations API: shipments, couriers, warehouses, "
        "alerts and fleet statistics. Data changes in real time — watch it at /monitor."
    ),
    servers=[{"url": "/demo"}],
)


@demo_app.middleware("http")
async def _log_requests(request: Request, call_next):
    response = await call_next(request)
    caller = "agent" if "Doc2Agent" in request.headers.get("user-agent", "") else "manual"
    db.record_request(request.method, request.url.path, response.status_code, caller)
    return response


class ShipmentCreate(BaseModel):
    origin_city: str = Field(description="City the package ships from, e.g. Mumbai")
    dest_city: str = Field(description="Destination city, e.g. Pune")
    weight_kg: float = Field(default=1.0, gt=0, le=500, description="Package weight in kilograms")
    priority: Literal["standard", "express"] = Field(
        default="standard", description="Delivery priority tier"
    )


class StatusUpdate(BaseModel):
    status: Literal["created", "picked_up", "in_transit", "out_for_delivery", "delivered", "delayed"] = Field(
        description="New shipment status"
    )
    note: str = Field(default="", description="Optional note explaining the change")


class CourierAssign(BaseModel):
    courier_id: str = Field(description="ID of the courier to assign, e.g. CR-3")


def _get_shipment(shipment_id: str) -> dict:
    shipment = db.shipments.get(shipment_id.upper())
    if not shipment:
        raise HTTPException(404, f"Shipment '{shipment_id}' not found")
    return shipment


@demo_app.get("/shipments", summary="List shipments, filterable by status, city and priority")
def list_shipments(
    status: Optional[str] = Query(None, description="Filter by status: created, picked_up, in_transit, out_for_delivery, delivered, delayed"),
    city: Optional[str] = Query(None, description="Match shipments whose origin OR destination is this city"),
    priority: Optional[str] = Query(None, description="Filter by priority: standard or express"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of results"),
):
    result = list(db.shipments.values())
    if status:
        result = [s for s in result if s["status"] == status.lower()]
    if city:
        result = [s for s in result if city.title() in (s["origin_city"], s["dest_city"])]
    if priority:
        result = [s for s in result if s["priority"] == priority.lower()]
    result.sort(key=lambda s: s["updated_at"], reverse=True)
    return {"count": len(result[:limit]), "shipments": [
        {k: v for k, v in s.items() if k != "events"} for s in result[:limit]
    ]}


@demo_app.post("/shipments", status_code=201, summary="Create a new shipment")
def create_shipment(body: ShipmentCreate):
    if body.origin_city.title() == body.dest_city.title():
        raise HTTPException(422, "Origin and destination must differ")
    return db.create_shipment(
        body.origin_city.title(), body.dest_city.title(), body.weight_kg, body.priority, actor="agent"
    )


@demo_app.get("/shipments/{shipment_id}", summary="Get one shipment with full details")
def get_shipment(shipment_id: str):
    return _get_shipment(shipment_id)


@demo_app.get("/shipments/{shipment_id}/events", summary="Get a shipment's full tracking history")
def shipment_events(shipment_id: str):
    shipment = _get_shipment(shipment_id)
    return {"id": shipment["id"], "events": shipment["events"]}


@demo_app.patch("/shipments/{shipment_id}/status", summary="Update a shipment's status")
def update_status(shipment_id: str, body: StatusUpdate):
    shipment = _get_shipment(shipment_id)
    if shipment["status"] == "delivered":
        raise HTTPException(422, "Shipment already delivered; status is final")
    db.set_status(shipment, body.status, body.note or "Status set via API", actor="agent")
    return shipment


@demo_app.post("/shipments/{shipment_id}/assign", summary="Assign a courier to a shipment")
def assign_courier(shipment_id: str, body: CourierAssign):
    shipment = _get_shipment(shipment_id)
    courier = db.couriers.get(body.courier_id.upper())
    if not courier:
        raise HTTPException(404, f"Courier '{body.courier_id}' not found")
    if courier["status"] != "idle":
        raise HTTPException(422, f"Courier {courier['id']} is busy ({courier['active_shipments']} active)")
    db.assign_courier(shipment, courier, actor="agent")
    return shipment


@demo_app.get("/couriers", summary="List couriers, filterable by status")
def list_couriers(
    status: Optional[str] = Query(None, description="Filter by courier status: idle or on_route"),
):
    result = list(db.couriers.values())
    if status:
        result = [c for c in result if c["status"] == status.lower()]
    return {"count": len(result), "couriers": result}


@demo_app.get("/couriers/{courier_id}", summary="Get one courier's details and workload")
def get_courier(courier_id: str):
    courier = db.couriers.get(courier_id.upper())
    if not courier:
        raise HTTPException(404, f"Courier '{courier_id}' not found")
    active = [s["id"] for s in db.shipments.values()
              if s["courier_id"] == courier["id"] and s["status"] != "delivered"]
    return {**courier, "assigned_shipments": active}


@demo_app.get("/warehouses", summary="List all warehouses and their load")
def list_warehouses():
    return {"count": len(db.warehouses), "warehouses": list(db.warehouses.values())}


@demo_app.get("/stats/overview", summary="Fleet-wide operational statistics")
def stats_overview():
    by_status: dict[str, int] = {}
    for s in db.shipments.values():
        by_status[s["status"]] = by_status.get(s["status"], 0) + 1
    return {
        "total_shipments": len(db.shipments),
        "by_status": by_status,
        "express_share": round(
            sum(1 for s in db.shipments.values() if s["priority"] == "express")
            / max(1, len(db.shipments)), 2),
        "idle_couriers": sum(1 for c in db.couriers.values() if c["status"] == "idle"),
        "busiest_courier": max(
            db.couriers.values(), key=lambda c: c["active_shipments"], default=None),
    }


@demo_app.get("/alerts/delayed", summary="All currently delayed shipments — the ops alert feed")
def delayed_alerts():
    delayed = [s for s in db.shipments.values() if s["status"] == "delayed"]
    return {
        "count": len(delayed),
        "alerts": [
            {
                "id": s["id"],
                "route": f"{s['origin_city']} → {s['dest_city']}",
                "priority": s["priority"],
                "courier_id": s["courier_id"],
                "last_note": s["events"][-1]["note"] if s["events"] else "",
            }
            for s in delayed
        ],
    }
