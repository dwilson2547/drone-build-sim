---
tier: project
domain: drones
---

# build-sim

Drone build design tool. Pick a frame / motor / pack / payload and get modeled AUW,
thrust-to-weight, hover throttle, flight time, and spare lift — with a calibration loop
that compares predictions against your real fleet's measured numbers.

Successor to the single-file React prototype kept in [`poc/drone-sim.jsx`](poc/drone-sim.jsx).

## Physics model (backend/app/physics.py)

- **Thrust curves** interpolate in throttle² space (amps too; watts in throttle³),
  which is near-exact between sparse bench-test points — the old prototype's linear
  interpolation was its biggest error source.
- **Battery sag:** packs have per-cell internal resistance; pack voltage droops under
  load, thrust scales with V², and the hover point is solved iteratively at the
  sagged voltage. This is why hover estimates now land higher (and more realistic)
  than the old model.
- **Bench voltage:** each curve is scaled from the voltage it was actually measured at
  (`test_volts`), stated on the datasheet or derived from its Power ÷ Current columns —
  see `backend/app/data/SOURCES.md`. Only the hand-seeded FPV curves fall back to 3.7V/cell.
- **Chemistry:** the pack's chemistry sets the mid-discharge voltage the hover point is
  solved at (3.7V LiPo / 3.6V Li-ion), the under-load floor (3.3V / 2.8V) and the usable
  fraction of capacity (80% / 90%). Conventions, refined by the calibration loop.
- **Flight time** = usable capacity ÷ hover current at the sagged operating point.
- **Pack rating:** packs with a known continuous rating (`max_a`) are checked against hover
  draw (warn above 80%, fail above 100%) and full-throttle draw.
- **Rigging** (FC/ESC/wiring/RX) is a per-frame mass by build class, not one constant; a
  measured-AUW actual is the direct check on it.
- Coax frames take a 0.80 stack-efficiency factor.

Frame rigging, pack IR and pack ratings are generic archetype values flagged `⚠ unverified` in
`backend/app/parts_data.py`; replace them with weighed / datasheet numbers as they come in.

## Calibration loop

Save a build, then hit **LOG** on it in the saved-builds list to record what it really did
(measured AUW, hover throttle from OSD/blackbox, real flight time). The calibration table
underneath shows predicted minus measured for every logged number, coloured by relative
error. Same thing over the API: `POST /api/builds`, `POST /api/builds/{id}/actuals`,
`GET /api/calibration`. A saved build records the prop / bench sweep it was simulated on, so
it can be re-simulated when the model changes. Next iteration: fit per-part correction
factors from accumulated error.

## Stack

- `backend/` — FastAPI + SQLite (`/data/build_sim.db` in the container). The parts tables are
  re-synced from `parts_data` on every boot, so a re-harvest or an edited pack shows up on
  restart; saved builds and actuals are the only state the database owns.
- `frontend/` — Vite + React SPA, nginx serves it and proxies `/api` to the backend

## Run locally (dev)

```sh
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --reload          # :8000
cd ../frontend && npm install && npm run dev     # :5173, proxies /api → :8000
```

Tests: `cd backend && .venv/bin/pytest`

## Run with Docker Compose

```sh
docker compose up -d --build   # http://localhost:8087
docker compose down
```

The compose file pins publishable image names
(`dwilson2547/build-sim-{backend,frontend}` on Docker Hub) so the same file is the single
point of contact: `docker compose build && docker compose push` to publish updates.

## Cluster deploy

Runs on the home cluster at http://build-sim.local via ArgoCD
(`infra/cluster-config/argocd/build-sim.yaml`, chart `helm/build-sim/`, namespace `build-sim`).
Images track `:latest` with `pullPolicy: Always`, so publishing an update is:

```sh
docker compose build && docker compose push
kubectl -n build-sim rollout restart deploy/build-sim-backend deploy/build-sim-frontend
```

The SQLite database lives on the `build-sim-data` PVC (`nfs-dataset`); the backend runs one
replica with a `Recreate` strategy so two pods never write it at once.

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/parts` | full parts library |
| POST | `/api/simulate` | simulate a config `{motor_id, frame_id, pack_id, payload_id, prop?}` — `prop` picks the bench sweep, default the motor's first |
| GET/POST | `/api/builds` | list / save builds (same body as simulate plus `name`; the prop is stored) |
| DELETE | `/api/builds/{id}` | delete build (cascades actuals) |
| POST | `/api/builds/{id}/actuals` | log measured AUW / hover throttle (0–100) / flight time; at least one required |
| GET | `/api/calibration` | predicted-vs-measured error report |
