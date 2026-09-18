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
| Curves with a stated bench voltage (`test_volts_source: stated`) | 99 / 135 (73%) |
| Curves with a derived bench voltage (`test_volts_source: derived-w-over-a`) | 29 / 135 (21%) |
| Curves with no bench voltage (the 7 `seed` entries) | 7 / 135 (5%) |

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

29 of the 128 T-Motor sweeps (the U8II, U8 Lite and U10II pages) have no Voltage column. They
do have Power and Current for every row, and on the 99 sweeps that publish all three columns,
Power ÷ Current reproduces the stated voltage with 0.0% median error (worst −9.7%), so the
vendor's Power column is V × A. For those 29 the harvester records `test_volts` as the median of
W/A across the sweep and marks it `test_volts_source: "derived-w-over-a"`; sweeps with a real
column are marked `"stated"`. The derivation is refused, leaving `null`, if W/A varies more than
15% across a sweep — a real bench voltage is nearly flat, and a wide spread would mean the
columns are not V × A on that page.

The derived values land where a bench would: 24.0V / 48.0V (4.0V/cell) on the U8 family, and
32.5 / 40.4 / 48.6V on the U10II, which T-Motor sweeps on three pack sizes. Two consequences
worth knowing:

- The U10II's repeated props are now labelled by voltage (`G29*9.5” CF @33V`, `@40V`, `@49V`)
  instead of `#1/#2/#3`.
- `tmotor_u8ii_kv150` and `tmotor_u8lite_kv150` are tagged `rated_cells: 6` from the first sweep
  on the page, but their `P22*6.6” CF` sweep derives to 48V — that one was a 12S bench. The sim
  scales from the curve's own `test_volts`, so this is handled; it would not have been under the
  old `rated_cells × 3.7V` fallback.

Only the 7 hand-seeded FPV curves still carry `test_volts: null`. For those
`PropCurve.rated_volts()` falls back to `rated_cells * NOMINAL_V` and the simulation result warns
that current and flight time are approximate.

## Duplicate sweeps across products ⚠ unverified

Two pairs of T-Motor products publish byte-identical thrust tables on separate product pages
(checked against the cached HTML; the Type column on each page names its own motor):

| Pair | Mass difference | Curves |
|---|---|---|
| `tmotor_u8ii_kv85/100/150/190` ↔ `tmotor_u8lite_kv85/100/150/190` | U8 Lite ~30 g lighter | all 10 identical |
| `tmotor_u8iipro_kv100` ↔ `tmotor_u8iilite_kv100` | Pro 34 g heavier | both identical |

Whether the lite variants were benched separately and happen to match, or the vendor reused the
table, is not knowable from the pages. The sim uses them as published. Treat a Lite-vs-II
comparison as a mass-only comparison.

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
