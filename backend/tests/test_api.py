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


SEED_MOTOR_IDS = {
    "0802_19000kv", "1404_4600kv", "1404_3000kv", "1804_2450kv",
    "2004_1800kv", "2207_1750kv", "3115_900kv",
}


def test_parts_seeded(client):
    parts = client.get("/api/parts").json()
    ids = {m["id"] for m in parts["motors"]}
    # The motor library is regenerated from vendor datasheets, so its size moves.
    # What must hold is that the hand-seeded FPV motors survive a re-harvest.
    assert SEED_MOTOR_IDS <= ids
    assert len(parts["motors"]) >= len(SEED_MOTOR_IDS)
    assert len(parts["frames"]) == 6
    assert len(parts["packs"]) == 6
    assert len(parts["payloads"]) == 5


def test_every_motor_has_a_usable_curve(client):
    for m in client.get("/api/parts").json()["motors"]:
        assert m["curves"], f"{m['id']} has no curves"
        assert m["mass_g"] > 0, f"{m['id']} has no mass"
        for c in m["curves"]:
            assert len(c["points"]) >= 3, f"{m['id']}/{c['prop']} too few points"
            thrust = [p[1] for p in c["points"]]
            assert thrust == sorted(thrust), f"{m['id']}/{c['prop']} thrust not monotonic"


def test_harvested_motors_carry_provenance(client):
    harvested = [m for m in client.get("/api/parts").json()["motors"]
                 if m["id"].startswith("tmotor_")]
    assert harvested, "expected harvested T-Motor entries in the library"
    for m in harvested:
        for c in m["curves"]:
            assert c["source"] == "tmotor-html"
            assert c["source_url"].startswith("https://store.tmotor.com/")
            assert c["harvested_at"]
            # Every T-Motor page publishes Power and Current, so a bench voltage
            # is always recoverable; None would mean the harvester regressed.
            assert c["test_volts"] > 0, f"{m['id']}/{c['prop']} lost its bench voltage"
            assert c["test_volts_source"] in ("stated", "derived-w-over-a")
            # W/A must agree with whatever voltage is recorded, stated or derived.
            ratios = [pt[3] / pt[2] for pt in c["points"] if pt[2] > 0]
            med = sorted(ratios)[len(ratios) // 2]
            assert abs(med - c["test_volts"]) / c["test_volts"] < 0.12, \
                f"{m['id']}/{c['prop']}: W/A {med:.1f} vs test_volts {c['test_volts']}"


def test_simulate_reports_voltage_provenance(client):
    parts = client.get("/api/parts").json()
    derived = next((m, c) for m in parts["motors"] for c in m["curves"]
                   if c.get("test_volts_source") == "derived-w-over-a")
    m, c = derived
    body = client.post("/api/simulate", json={
        "motor_id": m["id"], "frame_id": "y6_450", "pack_id": "lipo_6s_5000",
        "payload_id": "none", "prop": c["prop"],
    }).json()
    assert body["test_volts"] == c["test_volts"]
    assert body["test_volts_source"] == "derived-w-over-a"
    assert not any("Bench voltage" in w for w in body["warnings"])


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
