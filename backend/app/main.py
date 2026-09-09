"""build-sim API: parts library, simulation, saved builds, calibration actuals."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import db
from .physics import simulate


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="build-sim", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


class SimulateRequest(BaseModel):
    motor_id: str
    frame_id: str
    pack_id: str
    payload_id: str
    prop: str | None = None   # which bench sweep to use; None = the motor's first


class BuildRequest(SimulateRequest):
    name: str = ""


class ActualRequest(BaseModel):
    measured_auw_g: float | None = None
    measured_hover_thr: float | None = None
    measured_flight_min: float | None = None
    notes: str = ""


def run_sim(conn, req: SimulateRequest) -> dict:
    try:
        motor = db.get_motor(conn, req.motor_id)
        frame = db.get_frame(conn, req.frame_id)
        pack = db.get_pack(conn, req.pack_id)
        payload = db.get_payload(conn, req.payload_id)
    except KeyError as e:
        raise HTTPException(404, f"unknown part: {e}")
    try:
        return asdict(simulate(motor, frame, pack, payload, prop=req.prop))
    except KeyError as e:
        raise HTTPException(400, f"unknown prop: {e}")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/parts")
def parts(conn=Depends(get_conn)):
    return db.list_parts(conn)


@app.post("/api/simulate")
def simulate_endpoint(req: SimulateRequest, conn=Depends(get_conn)):
    return run_sim(conn, req)


@app.get("/api/builds")
def builds(conn=Depends(get_conn)):
    return db.list_builds(conn)


@app.post("/api/builds", status_code=201)
def create_build(req: BuildRequest, conn=Depends(get_conn)):
    result = run_sim(conn, req)
    name = req.name.strip() or f"{req.motor_id} · {req.frame_id}"
    return db.save_build(conn, name, req.motor_id, req.frame_id, req.pack_id, req.payload_id, result)


@app.delete("/api/builds/{build_id}", status_code=204)
def remove_build(build_id: str, conn=Depends(get_conn)):
    if not db.delete_build(conn, build_id):
        raise HTTPException(404, "build not found")


@app.post("/api/builds/{build_id}/actuals", status_code=201)
def add_actual(build_id: str, req: ActualRequest, conn=Depends(get_conn)):
    if not conn.execute("SELECT 1 FROM builds WHERE id=?", (build_id,)).fetchone():
        raise HTTPException(404, "build not found")
    return db.add_actual(conn, build_id, req.measured_auw_g, req.measured_hover_thr,
                         req.measured_flight_min, req.notes)


@app.get("/api/calibration")
def calibration(conn=Depends(get_conn)):
    return db.calibration_report(conn)
