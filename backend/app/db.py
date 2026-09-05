"""SQLite storage layer: parts library, saved builds, and calibration actuals."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

from . import parts_data
from .physics import Frame, Motor, Pack, Payload

DB_PATH = Path(os.environ.get("BUILD_SIM_DB", Path(__file__).resolve().parent.parent / "build_sim.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS motors (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, rated_cells INTEGER NOT NULL,
    mass_g REAL NOT NULL, props TEXT NOT NULL DEFAULT '[]', curve TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS frames (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, mass_g REAL NOT NULL,
    motors INTEGER NOT NULL, coax INTEGER NOT NULL, frame_class TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS packs (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, cells INTEGER NOT NULL,
    mah REAL NOT NULL, mass_g REAL NOT NULL, chemistry TEXT NOT NULL,
    ir_mohm_per_cell REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS payloads (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, mass_g REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS builds (
    id TEXT PRIMARY KEY, name TEXT NOT NULL,
    motor_id TEXT NOT NULL, frame_id TEXT NOT NULL, pack_id TEXT NOT NULL, payload_id TEXT NOT NULL,
    result_json TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS actuals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    build_id TEXT NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
    measured_auw_g REAL, measured_hover_thr REAL, measured_flight_min REAL,
    notes TEXT DEFAULT '', created_at REAL NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        _seed(conn)
        conn.commit()
    finally:
        conn.close()


def _seed(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) FROM motors").fetchone()[0]:
        return
    for m in parts_data.MOTORS:
        conn.execute(
            "INSERT INTO motors VALUES (?,?,?,?,?,?)",
            (m["id"], m["name"], m["rated_cells"], m["mass_g"], json.dumps(m["props"]), json.dumps(m["curve"])),
        )
    for f in parts_data.FRAMES:
        conn.execute(
            "INSERT INTO frames VALUES (?,?,?,?,?,?)",
            (f["id"], f["name"], f["mass_g"], f["motors"], int(f["coax"]), f["frame_class"]),
        )
    for p in parts_data.PACKS:
        conn.execute(
            "INSERT INTO packs VALUES (?,?,?,?,?,?,?)",
            (p["id"], p["name"], p["cells"], p["mah"], p["mass_g"], p["chemistry"], p["ir_mohm_per_cell"]),
        )
    for pl in parts_data.PAYLOADS:
        conn.execute("INSERT INTO payloads VALUES (?,?,?)", (pl["id"], pl["name"], pl["mass_g"]))


def get_motor(conn, mid: str) -> Motor:
    r = conn.execute("SELECT * FROM motors WHERE id=?", (mid,)).fetchone()
    if not r:
        raise KeyError(f"motor '{mid}'")
    curve = [tuple(p) for p in json.loads(r["curve"])]
    return Motor(r["name"], r["rated_cells"], r["mass_g"], curve, json.loads(r["props"]))


def get_frame(conn, fid: str) -> Frame:
    r = conn.execute("SELECT * FROM frames WHERE id=?", (fid,)).fetchone()
    if not r:
        raise KeyError(f"frame '{fid}'")
    return Frame(r["name"], r["mass_g"], r["motors"], bool(r["coax"]), r["frame_class"])


def get_pack(conn, pid: str) -> Pack:
    r = conn.execute("SELECT * FROM packs WHERE id=?", (pid,)).fetchone()
    if not r:
        raise KeyError(f"pack '{pid}'")
    return Pack(r["name"], r["cells"], r["mah"], r["mass_g"], r["chemistry"], r["ir_mohm_per_cell"])


def get_payload(conn, pid: str) -> Payload:
    r = conn.execute("SELECT * FROM payloads WHERE id=?", (pid,)).fetchone()
    if not r:
        raise KeyError(f"payload '{pid}'")
    return Payload(r["name"], r["mass_g"])


def list_parts(conn) -> dict:
    q = lambda t: [dict(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY rowid")]
    motors = q("motors")
    for m in motors:
        m["props"] = json.loads(m["props"])
        m["curve"] = json.loads(m["curve"])
    frames = q("frames")
    for f in frames:
        f["coax"] = bool(f["coax"])
    return {"motors": motors, "frames": frames, "packs": q("packs"), "payloads": q("payloads")}


def save_build(conn, name, motor_id, frame_id, pack_id, payload_id, result: dict) -> dict:
    bid = f"build:{int(time.time() * 1000)}"
    conn.execute(
        "INSERT INTO builds VALUES (?,?,?,?,?,?,?,?)",
        (bid, name, motor_id, frame_id, pack_id, payload_id, json.dumps(result), time.time()),
    )
    conn.commit()
    return {"id": bid, "name": name, "motor_id": motor_id, "frame_id": frame_id,
            "pack_id": pack_id, "payload_id": payload_id, "result": result}


def list_builds(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM builds ORDER BY created_at DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["result"] = json.loads(d.pop("result_json"))
        out.append(d)
    return out


def delete_build(conn, bid: str) -> bool:
    cur = conn.execute("DELETE FROM builds WHERE id=?", (bid,))
    conn.commit()
    return cur.rowcount > 0


def add_actual(conn, build_id: str, auw=None, hover_thr=None, flight_min=None, notes="") -> dict:
    cur = conn.execute(
        "INSERT INTO actuals (build_id, measured_auw_g, measured_hover_thr, measured_flight_min, notes, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (build_id, auw, hover_thr, flight_min, notes, time.time()),
    )
    conn.commit()
    return {"id": cur.lastrowid, "build_id": build_id}


def calibration_report(conn) -> list[dict]:
    """Predicted-vs-measured error per actual — the raw material for fitting
    per-part correction factors in a later iteration."""
    rows = conn.execute(
        """SELECT a.id AS actual_id, a.*, b.name, b.result_json FROM actuals a
           JOIN builds b ON b.id = a.build_id ORDER BY a.created_at DESC"""
    ).fetchall()
    out = []
    for r in rows:
        r = dict(r)
        pred = json.loads(r.pop("result_json"))
        err = {}
        if r["measured_auw_g"] is not None:
            err["auw_g"] = pred["auw_g"] - r["measured_auw_g"]
        if r["measured_hover_thr"] is not None and pred.get("hover_throttle") is not None:
            err["hover_thr"] = pred["hover_throttle"] - r["measured_hover_thr"]
        if r["measured_flight_min"] is not None:
            err["flight_min"] = pred["flight_min"] - r["measured_flight_min"]
        out.append({"actual": r, "predicted": pred, "error": err})
    return out
