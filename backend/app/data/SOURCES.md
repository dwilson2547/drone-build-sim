# Parts data sources

`motors.json` is the motor library the sim seeds from. It is **data, not code** — regenerated
from vendor datasheets, reviewed by reading the diff, and committed.

Every curve carries its own `source`, `source_url` and `harvested_at`, because a year from now
the provenance is the only way to tell a benched number from a guessed one.

## Current contents

| | |
|---|---|
| Motors | 62 |
| Curves | 135 |
| Data points | 2,326 |
| Motors with more than one prop curve | 46 |
| Curves with a stated bench voltage | 99 / 135 (73%) |

By source:

| `source` | Curves | Origin | How to regenerate |
|---|---|---|---|
| `tmotor-html` | 128 | `store.tmotor.com` product pages — thrust tables are plain server-rendered HTML | `python tools/harvest_tmotor.py` |
| `seed` | 7 | Hand-entered in the original `drone-sim.jsx` prototype, from published bench tests and listing charts | manual — edit `motors.json` |

## What the seed entries are, and why they stay

The seven `seed` motors are the FPV sizes (0802 through 3115). No vendor publishes those as
scrapable HTML — iFlight, the best FPV source found, ships them as PNG datasheet images
(see below). They are hand-entered, coarse (4 points per curve), and carry
`"test_volts": null`, which makes the sim warn that current and flight time are approximate.

The harvester preserves any motor whose curves are all `source: "seed"`, so re-running it
never destroys hand-entered work.

### Known accuracy of the seed data

`3115_900kv` overlaps a real iFlight datasheet (NIDICI 3115 900KV, HQ 10×4.5×3 @ 24V), which
gives a direct measure of how wrong the hand-entered numbers are:

```
motor mass:  seed 95g   datasheet 77g   +23%  (+108g on a hex)

 thr      thrust seed/real    err      amps seed/real    err     watts seed/real    err
 50%    1420 /   1299g     +9.3%    11.4 / 10.23A   +11.4%     300 /  246.2W  +21.9%
 70%    2500 /   2388g     +4.7%    28.0 / 25.16A   +11.3%     710 /  598.3W  +18.7%
100%    4080 /   4406g     -7.4%    62.7 / 63.28A    -0.9%    1600 / 1479.5W   +8.1%
```

Thrust is within ~9%, but mass is 23% heavy and current runs ~11% high through the hover band.
Both errors push flight-time estimates the same way. Treat seed entries as indicative only.

## Bench voltage

`test_volts` is the pack voltage a sweep was actually measured at. It matters: iFlight benches
6S motors at 24.0V, which is 4.0V/cell, not the 3.7V/cell `physics.NOMINAL_V` assumes. Assuming
22.2V where the sweep ran at 24.0V inflates every current by ~8%, straight through to flight
time.

27% of T-Motor sweeps have no Voltage column on the page. Those keep `test_volts: null`, and
`PropCurve.rated_volts()` falls back to `rated_cells * NOMINAL_V` — with a warning on the
simulation result so the assumption is visible rather than silent.

## Not harvested (and why)

| Source | Status |
|---|---|
| **iFlight** (`shop.iflight.com`) | 141 motor URLs, 78 with a test report, **63 unique PNG datasheets** under `/image/catalog/TEST REPORT/`. Crisp synthetic table renders — readable by a vision pass, not by an HTML parser. This is the FPV-range gap (XING2 1404/2205/2207/2306/2405, NIDICI 2807/2809/3115). Worth doing; not done yet. |
| **BetaFPV** | Shopify with an open `products.json` (501 products, 43 motors), but thrust appears only as marketing prose — *"max thrust can reach more than 230g"*. Useful for mass and price, useless for curves. |
| **BrotherHobby** | Cloudflare interactive challenge. Skipped. |
| **T-Motor FPV line** | Not in `store.tmotor.com` — that store is entirely industrial/UAV (MN, U, P, VTOL, agricultural, manned). |

## Refresh

Monthly is fine and costs nothing (~70 requests). The point of the cadence is that the diff stays
small enough to actually read:

```sh
python tools/harvest_tmotor.py --dry-run    # show the diff, write nothing
python tools/harvest_tmotor.py              # write motors.json
python tools/harvest_tmotor.py --no-cache   # ignore .harvest-cache and refetch
```

Read the printed diff before committing. `+ new motor` and `~ curve revised` lines are the
interesting ones; `- delisted` means a product left the catalogue, and the motor will vanish
from the library unless you move it to a `seed` entry first.
