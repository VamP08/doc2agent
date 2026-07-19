"""AeroTrack demo API contract tests — offline, in-process TestClient."""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # context manager runs lifespan (seeds the store)
        yield c


def test_openapi_spec_served(client):
    spec = client.get("/demo/openapi.json").json()
    assert spec["info"]["title"] == "AeroTrack Logistics API"
    assert spec["servers"][0]["url"] == "/demo"
    assert len(spec["paths"]) >= 10


def test_list_and_filter_shipments(client):
    data = client.get("/demo/shipments", params={"limit": 5}).json()
    assert data["count"] <= 5
    for s in data["shipments"]:
        assert s["id"].startswith("SHP-")


def test_create_shipment_and_events(client):
    resp = client.post(
        "/demo/shipments",
        json={"origin_city": "Delhi", "dest_city": "Chennai", "weight_kg": 3, "priority": "express"},
    )
    assert resp.status_code == 201
    shipment = resp.json()
    assert shipment["origin_city"] == "Delhi" and shipment["status"] == "created"
    events = client.get(f"/demo/shipments/{shipment['id']}/events").json()
    assert events["events"][0]["status"] == "created"


def test_same_origin_dest_rejected(client):
    resp = client.post(
        "/demo/shipments", json={"origin_city": "Pune", "dest_city": "Pune"}
    )
    assert resp.status_code == 422


def test_unknown_shipment_404(client):
    assert client.get("/demo/shipments/SHP-99999").status_code == 404


def test_assign_busy_courier_rejected(client):
    couriers = client.get("/demo/couriers", params={"status": "on_route"}).json()
    if not couriers["couriers"]:
        pytest.skip("no busy courier in seed data")
    busy = couriers["couriers"][0]["id"]
    shipment = client.post(
        "/demo/shipments", json={"origin_city": "Mumbai", "dest_city": "Jaipur"}
    ).json()
    resp = client.post(f"/demo/shipments/{shipment['id']}/assign", json={"courier_id": busy})
    assert resp.status_code == 422


def test_stats_and_alerts_shape(client):
    stats = client.get("/demo/stats/overview").json()
    assert {"total_shipments", "by_status", "idle_couriers"} <= set(stats)
    alerts = client.get("/demo/alerts/delayed").json()
    assert "alerts" in alerts


def test_monitor_feed_shape(client):
    feed = client.get("/api/monitor/feed").json()
    assert {"stats", "requests", "events", "shipments"} <= set(feed)
    assert feed["stats"]["total"] >= 10
