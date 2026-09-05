"""API smoke tests against a temp database."""

import os

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILD_SIM_DB", str(tmp_path / "test.db"))
    # reload db module so DB_PATH picks up the env override
    import importlib

    from app import db
    importlib.reload(db)
    db.init_db()

    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


SIM_REQ = {"motor_id": "1404_3000kv", "frame_id": "reliant_y6",
           "pack_id": "liion_4s_p1", "payload_id": "lr_kit"}


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_parts_seeded(client):
    parts = client.get("/api/parts").json()
    assert len(parts["motors"]) == 7
    assert len(parts["frames"]) == 6
    assert len(parts["packs"]) == 6
    assert len(parts["payloads"]) == 5


def test_simulate(client):
    r = client.post("/api/simulate", json=SIM_REQ)
    assert r.status_code == 200
    body = r.json()
    assert body["can_hover"]
    assert body["auw_g"] > 250  # 6 motors + 21700 pack is heavy — not sub250
    assert not body["sub250"]


def test_simulate_light_combo_is_sub250(client):
    r = client.post("/api/simulate", json={
        "motor_id": "1404_4600kv", "frame_id": "freestyle3",
        "pack_id": "lipo_4s_650", "payload_id": "none",
    })
    body = r.json()
    assert body["can_hover"]
    assert body["sub250"]


def test_simulate_unknown_part_404(client):
    r = client.post("/api/simulate", json={**SIM_REQ, "motor_id": "nope"})
    assert r.status_code == 404


def test_build_roundtrip_and_actuals(client):
    r = client.post("/api/builds", json={**SIM_REQ, "name": "Reliant LR"})
    assert r.status_code == 201
    bid = r.json()["id"]

    builds = client.get("/api/builds").json()
    assert any(b["id"] == bid for b in builds)

    r = client.post(f"/api/builds/{bid}/actuals",
                    json={"measured_auw_g": 240.0, "measured_hover_thr": 42.0})
    assert r.status_code == 201

    cal = client.get("/api/calibration").json()
    assert len(cal) == 1
    assert "auw_g" in cal[0]["error"]
    assert "hover_thr" in cal[0]["error"]

    assert client.delete(f"/api/builds/{bid}").status_code == 204
    assert client.delete(f"/api/builds/{bid}").status_code == 404
