"""API wiring smoke tests — routing + single-user auth (no DB required)."""

from __future__ import annotations

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from majak.api.main import app

    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_all_routers_are_mounted(client):
    spec = client.get("/openapi.json").json()
    paths = set(spec["paths"])
    for expected in (
        "/api/days",
        "/api/days/current",
        "/api/items/{item_id}",
        "/api/people/{person_id}/brief",
        "/api/inputs",
        "/api/review-queue",
        "/api/rollup",
        "/api/scheduler/fill-overnight",
    ):
        assert expected in paths, f"missing route {expected}"


def test_protected_route_requires_auth(client):
    assert client.get("/api/days").status_code == 401


def test_scheduler_requires_cron_secret(client):
    # Wrong secret is rejected.
    r = client.post("/api/scheduler/fill-overnight", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
