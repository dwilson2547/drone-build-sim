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


# --- review fixes: chemistry, pack rating, rigging, parts sync, prop persistence

FREESTYLE = {"motor_id": "2207_1750kv", "frame_id": "freestyle5", "payload_id": "digital"}


def test_pack_rating_warns_when_hover_draw_exceeds_it(client):
    # A 6S freestyle motor on a 3S2P 18650 pack hovers near the pack's whole rating.
    body = client.post("/api/simulate", json={**FREESTYLE, "pack_id": "liion_3s_p2"}).json()
    assert body["pack_max_a"] == 20
    assert body["hover_current_a"] > 0.8 * body["pack_max_a"]
    assert any("pack" in w.lower() and "rating" in w.lower() or "cannot sustain" in w for w in body["warnings"])
    # On its own 6S LiPo the hover draw is a fraction of the rating: no hover warning.
    # (Punch-out draw still legitimately exceeds a 1050mAh pack's rating on a 5" quad.)
    ok = client.post("/api/simulate", json={**FREESTYLE, "pack_id": "lipo_6s_1050"}).json()
    assert ok["hover_current_a"] < 0.5 * ok["pack_max_a"]
    assert not any(w.startswith("Hover draws") for w in ok["warnings"])


def test_punch_out_draw_reported(client):
    body = client.post("/api/simulate", json={**FREESTYLE, "pack_id": "lipo_6s_1050"}).json()
    assert body["full_current_a"] > body["hover_current_a"]


def test_chemistry_sets_usable_fraction_and_hover_voltage(client):
    parts = client.get("/api/parts").json()
    liion = client.post("/api/simulate", json={**SIM_REQ, "pack_id": "liion_4s_p1"}).json()
    lipo = client.post("/api/simulate", json={**SIM_REQ, "pack_id": "lipo_4s_1300"}).json()
    assert liion["pack_chemistry"] == "li-ion" and liion["usable_fraction"] == 0.90
    assert lipo["pack_chemistry"] == "lipo" and lipo["usable_fraction"] == 0.80
    # pack_wh uses the chemistry's nominal voltage
    li = next(p for p in parts["packs"] if p["id"] == "liion_4s_p1")
    assert abs(liion["pack_wh"] - li["mah"] / 1000 * li["cells"] * 3.6) < 1e-6


def test_rigging_comes_from_the_frame(client):
    parts = client.get("/api/parts").json()
    heavy = next(f for f in parts["frames"] if f["id"] == "y6_450")
    assert heavy["rigging_g"] == 160
    body = client.post("/api/simulate", json={
        "motor_id": "tmotor_mn5008_kv340", "frame_id": "y6_450", "pack_id": "lipo_6s_5000", "payload_id": "none",
    }).json()
    assert body["rigging_g"] == 160
    motor = next(m for m in parts["motors"] if m["id"] == "tmotor_mn5008_kv340")
    pack = next(p for p in parts["packs"] if p["id"] == "lipo_6s_5000")
    assert abs(body["auw_g"] - (6 * motor["mass_g"] + heavy["mass_g"] + pack["mass_g"] + 160)) < 1e-6


def test_build_persists_prop_and_restores_it(client):
    parts = client.get("/api/parts").json()
    motor = next(m for m in parts["motors"] if len(m["curves"]) > 1)
    prop = motor["curves"][1]["prop"]
    r = client.post("/api/builds", json={
        "motor_id": motor["id"], "frame_id": "y6_450", "pack_id": "lipo_6s_5000",
        "payload_id": "none", "prop": prop, "name": "prop test",
    })
    assert r.status_code == 201
    assert r.json()["prop"] == prop
    listed = next(b for b in client.get("/api/builds").json() if b["id"] == r.json()["id"])
    assert listed["prop"] == prop
    assert listed["result"]["prop"] == prop


def test_seed_motor_rejects_unknown_prop(client):
    r = client.post("/api/simulate", json={**SIM_REQ, "prop": '4"'})
    assert r.status_code == 400


def test_actual_requires_a_measurement_and_sane_ranges(client):
    bid = client.post("/api/builds", json=SIM_REQ).json()["id"]
    assert client.post(f"/api/builds/{bid}/actuals", json={"notes": "nothing measured"}).status_code == 422
    assert client.post(f"/api/builds/{bid}/actuals", json={"measured_hover_thr": 140}).status_code == 422
    assert client.post(f"/api/builds/{bid}/actuals", json={"measured_auw_g": -5}).status_code == 422
    assert client.post(f"/api/builds/{bid}/actuals", json={"measured_flight_min": 12.5}).status_code == 201


def test_parts_resync_on_every_boot(client, monkeypatch):
    """A database seeded once must pick up a changed parts library on the next boot."""
    from app import db, parts_data
    before = client.get("/api/parts").json()["payloads"]
    assert not any(p["id"] == "brick" for p in before)

    monkeypatch.setattr(parts_data, "PAYLOADS", parts_data.PAYLOADS + [{"id": "brick", "name": "Brick", "mass_g": 500}])
    db.init_db()
    after = client.get("/api/parts").json()["payloads"]
    assert any(p["id"] == "brick" for p in after)

    monkeypatch.setattr(parts_data, "PAYLOADS", [p for p in parts_data.PAYLOADS if p["id"] != "brick"])
    db.init_db()
    assert not any(p["id"] == "brick" for p in client.get("/api/parts").json()["payloads"])


def test_migrates_pre_prop_builds_table(tmp_path, monkeypatch):
    """A builds table from before the prop column gains it without losing rows."""
    import importlib
    import json
    import sqlite3
    import time

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE motors (id TEXT PRIMARY KEY, name TEXT, rated_cells INTEGER, mass_g REAL, props TEXT, curves TEXT);
        CREATE TABLE frames (id TEXT PRIMARY KEY, name TEXT, mass_g REAL, motors INTEGER, coax INTEGER, frame_class TEXT);
        CREATE TABLE packs (id TEXT PRIMARY KEY, name TEXT, cells INTEGER, mah REAL, mass_g REAL, chemistry TEXT, ir_mohm_per_cell REAL);
        CREATE TABLE payloads (id TEXT PRIMARY KEY, name TEXT, mass_g REAL);
        CREATE TABLE builds (id TEXT PRIMARY KEY, name TEXT NOT NULL, motor_id TEXT NOT NULL, frame_id TEXT NOT NULL,
            pack_id TEXT NOT NULL, payload_id TEXT NOT NULL, result_json TEXT NOT NULL, created_at REAL NOT NULL);
    """)
    old.execute("INSERT INTO frames VALUES ('stale','Stale',1,4,0,'sub250')")
    old.execute("INSERT INTO builds VALUES ('build:1','old build','1404_3000kv','reliant_y6','liion_4s_p1','lr_kit',?,?)",
                (json.dumps({"auw_g": 1.0}), time.time()))
    old.commit(); old.close()

    monkeypatch.setenv("BUILD_SIM_DB", str(path))
    from app import db
    importlib.reload(db)
    db.init_db()
    conn = db.connect()
    try:
        builds = db.list_builds(conn)
        assert [b["id"] for b in builds] == ["build:1"] and builds[0]["prop"] == ""
        frames = {f["id"] for f in db.list_parts(conn)["frames"]}
        assert "stale" not in frames and "reliant_y6" in frames
        assert db.get_frame(conn, "y6_450").rigging_g == 160
    finally:
        conn.close()
