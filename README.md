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
- **Flight time** = 80% usable capacity ÷ hover current at the sagged operating point.
- Coax frames take a 0.80 stack-efficiency factor.

## Calibration loop

Save a build (`POST /api/builds`), then log measured reality against it
(`POST /api/builds/{id}/actuals` — measured AUW, hover throttle from OSD/blackbox,
real flight time). `GET /api/calibration` returns predicted-vs-measured error per
entry. Next iteration: fit per-part correction factors from accumulated error.

## Stack

- `backend/` — FastAPI + SQLite (`/data/build_sim.db` in the container)
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
(`ghcr.io/dwilson2547/build-sim-{backend,frontend}`) so the same file is the single
point of contact: `docker compose build && docker compose push` to publish updates.

## Promotion path

Local compose first; when stable, promote to the home cluster via ArgoCD —
see `infra/cluster-config/` and the `k8s-argocd` skill (helm chart per
CONVENTIONS.md §6: `<project>/helm/<project>/`).

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/parts` | full parts library |
| POST | `/api/simulate` | simulate a config `{motor_id, frame_id, pack_id, payload_id}` |
| GET/POST | `/api/builds` | list / save builds |
| DELETE | `/api/builds/{id}` | delete build (cascades actuals) |
| POST | `/api/builds/{id}/actuals` | log measured AUW / hover throttle / flight time |
| GET | `/api/calibration` | predicted-vs-measured error report |
