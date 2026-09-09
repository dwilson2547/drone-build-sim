#!/usr/bin/env python3
"""Regenerate the T-Motor half of the parts library from store.tmotor.com.

# Site: T-Motor Official Store
# Strategy: static-html (requests + BS4)
# Discovered endpoint / base URL: https://store.tmotor.com/categorys/<slug>
# Last recon: 2026-09-08
# Selectors / fields: see SELECTORS below

Thrust tables are plain server-rendered <table> markup — no browser, no JS. The
data volume is tiny (~70 pages) and the product lines turn over roughly yearly,
so this is a manual regeneration script, not a service: no cache tier, no permit
server, no scheduler. Responses are cached to disk purely so that iterating on
the parser doesn't re-hit the site.

Run it, read the diff it prints, commit the JSON if the diff looks right:

    python tools/harvest_tmotor.py                 # diff + write
    python tools/harvest_tmotor.py --dry-run       # diff only
    python tools/harvest_tmotor.py --no-cache      # force refetch

Output: backend/app/data/motors.json (merged; `source: "seed"` motors survive).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import statistics
import sys
import time
import unicodedata

import requests
from bs4 import BeautifulSoup

REPO = pathlib.Path(__file__).resolve().parent.parent
DATA = REPO / "backend" / "app" / "data" / "motors.json"
CACHE = REPO / ".harvest-cache"

BASE = "https://store.tmotor.com"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
DELAY_S = 1.5

# robots.txt disallows /api/, /search*, /category-* — these /categorys/ pages
# and the /product/ pages they link to are all permitted.
MOTOR_CATEGORIES = [
    "multi-rotor-drone-motor",
    "uav-motor-u-type",
    "agricultural-uav-motor-p-type",
    "uav-multi-motor-navigator-type",
    "uav-mult-motor-antigravity-type",
    "gimbal-motor",
]

SELECTORS = {
    "product_link": r'href="(?:https://store\.tmotor\.com/)?(product/[a-zA-Z0-9._-]+\.html)"',
    # Thrust sweeps: the one table carrying both a Throttle and a Thrust(g) column.
    "thrust_table_headers": ("Throttle", "Thrust(g)"),
    # Per-KV spec block: a 4-column key|value|key|value table carrying KV + weight.
    "spec_kv": "KV",
    # Bare motor mass, in priority order. Three spellings are in use, one of
    # them a vendor typo ("indl." for "Incl."). Matched EXACTLY and never
    # fuzzily: the same blocks also carry 'PackageWeight' (shipping weight,
    # ~2-4x the motor) and 'Weight(SinglePropeller)', either of which would
    # silently wreck every AUW estimate downstream.
    "spec_mass": ("MotorWeight(Incl.Cable)", "MotorWeight(indl.Cable)", "Weight(Incl.Cable)"),
    "spec_cells": "RatedVoltage(Lipo)",
}

THROTTLE_RE = re.compile(r"^\d+(?:\.\d+)?\s*%$")
KV_RE = re.compile(r"KV\s*(\d+)", re.I)
MASS_RE = re.compile(r"([\d.]+)\s*g")
CELLS_RE = re.compile(r"(\d+)\s*(?:-\s*(\d+))?\s*S", re.I)


# --------------------------------------------------------------------------- fetch

def fetch(url: str, use_cache: bool = True) -> str:
    CACHE.mkdir(exist_ok=True)
    key = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".html")
    if use_cache and key.exists():
        return key.read_text(encoding="utf-8", errors="replace")
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    key.write_text(r.text, encoding="utf-8")
    time.sleep(DELAY_S)
    return r.text


# --------------------------------------------------------------------------- parse

def norm(s: str) -> str:
    """Collapse whitespace and fold fullwidth punctuation for key matching.

    T-Motor mixes ASCII and fullwidth forms across pages — most spec blocks say
    'Motor Weight（Incl. Cable）' with U+FF08/U+FF09, a minority use '('. NFKC
    folds them together so one selector matches both. Applied to keys only;
    values (prop names) are kept verbatim.
    """
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


def grid(table) -> list[list[str]]:
    """Expand a table with rowspan/colspan into a dense list-of-lists.

    T-Motor's sweeps rowspan the Type and Propeller cells across every throttle
    row, so naive cell reads produce ragged rows that silently lose their motor.
    """
    out: list[list[str]] = []
    pending: dict[int, tuple[str, int]] = {}
    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        line: list[str] = []
        ci = cursor = 0
        while cursor < len(cells) or pending:
            if ci in pending:
                text, left = pending[ci]
                line.append(text)
                if left - 1 <= 0:
                    del pending[ci]
                else:
                    pending[ci] = (text, left - 1)
                ci += 1
                continue
            if cursor >= len(cells):
                break
            c = cells[cursor]
            cursor += 1
            text = c.get_text(" ", strip=True)
            rs, cs = int(c.get("rowspan", 1)), int(c.get("colspan", 1))
            for _ in range(cs):
                line.append(text)
                if rs > 1:
                    pending[ci] = (text, rs - 1)
                ci += 1
        out.append(line)
    return out


def parse_specs(soup) -> dict[int, dict]:
    """Per-KV spec blocks, keyed by KV. Each is a 4-column key|value|key|value table."""
    variants: dict[int, dict] = {}
    for t in soup.find_all("table"):
        g = grid(t)
        if not g or len(g[0]) != 4:
            continue
        kv_map: dict[str, str] = {}
        for row in g:
            if len(row) != 4:
                continue
            kv_map[norm(row[0])] = row[1].strip()
            kv_map[norm(row[2])] = row[3].strip()
        if SELECTORS["spec_kv"] not in kv_map:
            continue
        mass_key = next((k for k in SELECTORS["spec_mass"] if k in kv_map), None)
        if mass_key is None:
            continue
        try:
            kv = int(re.sub(r"\D", "", kv_map[SELECTORS["spec_kv"]]))
        except ValueError:
            continue
        m = MASS_RE.search(kv_map[mass_key])
        cells_raw = kv_map.get(SELECTORS["spec_cells"], "")
        cm = CELLS_RE.search(cells_raw)
        variants[kv] = {
            "kv": kv,
            "mass_g": float(m.group(1)) if m else None,
            "cells_min": int(cm.group(1)) if cm else None,
            "cells_max": int(cm.group(2) or cm.group(1)) if cm else None,
        }
    return variants


def parse_sweeps(soup) -> list[tuple[str, str, list[dict]]]:
    """Bench sweeps as (motor type, propeller, points), in document order.

    A single (type, prop) pair can appear more than once on a page — T-Motor
    benches the same combination at several pack voltages and stacks the sweeps
    in one rowspan group. Keying by (type, prop) alone silently concatenates
    them into one impossible curve whose throttle column runs 40..100, 40..100.
    Rows are emitted in document order and each sweep ascends in throttle, so a
    throttle that drops marks the start of the next sweep.
    """
    grouped: dict[tuple[str, str], list[dict]] = {}
    order: list[tuple[str, str]] = []
    for t in soup.find_all("table"):
        g = grid(t)
        if not g:
            continue
        hdr = [norm(h) for h in g[0]]
        if not all(h in hdr for h in SELECTORS["thrust_table_headers"]):
            continue
        idx = {h: i for i, h in enumerate(hdr)}
        for row in g[1:]:
            if len(row) != len(hdr):
                continue
            thr = row[idx["Throttle"]]
            if not THROTTLE_RE.match(thr):
                continue  # drops the trailing "Note: ..." row
            pt = {"throttle_pct": float(thr.rstrip("% "))}
            for col, name in (("Voltage(V)", "volts"), ("Current(A)", "amps"),
                              ("Power(W)", "watts"), ("Thrust(g)", "thrust_g")):
                if col in idx:
                    try:
                        pt[name] = float(row[idx[col]].replace(",", ""))
                    except ValueError:
                        pass
            if "thrust_g" not in pt or "amps" not in pt or "watts" not in pt:
                continue
            key = (row[idx["Type"]].strip(), row[idx["Propeller"]].strip())
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append(pt)

    sweeps: list[tuple[str, str, list[dict]]] = []
    for typ, prop in order:
        run: list[dict] = []
        for pt in grouped[(typ, prop)]:
            if run and pt["throttle_pct"] <= run[-1]["throttle_pct"]:
                sweeps.append((typ, prop, run))
                run = []
            run.append(pt)
        if run:
            sweeps.append((typ, prop, run))
    return sweeps


def pick_cells(test_volts: float | None, lo: int | None, hi: int | None) -> int | None:
    """Which cell count was the sweep actually run at?

    A '6-12S' motor benched at 47.4V was on 12S (3.95V/cell), not 6S. Pick the
    count in range whose per-cell voltage lands in a plausible LiPo band.
    """
    if test_volts is None or lo is None:
        return lo
    best, best_err = None, 1e9
    for c in range(lo, (hi or lo) + 1):
        per_cell = test_volts / c
        if 3.4 <= per_cell <= 4.35:
            err = abs(per_cell - 3.85)
            if err < best_err:
                best, best_err = c, err
    return best or lo


def slug(model: str, kv: int) -> str:
    return "tmotor_" + re.sub(r"[^a-z0-9]+", "_", f"{model} kv{kv}".lower()).strip("_")


def build_motors(url: str, html: str, harvested_at: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    specs = parse_specs(soup)
    sweeps = parse_sweeps(soup)
    if not sweeps:
        return []

    by_variant: dict[int, dict] = {}
    for type_raw, prop_raw, pts in sweeps:
        kvm = KV_RE.search(type_raw)
        if not kvm:
            continue
        kv = int(kvm.group(1))
        model = norm(KV_RE.sub("", type_raw)).strip("-_ ") or "motor"
        pts.sort(key=lambda p: p["throttle_pct"])

        volts = [p["volts"] for p in pts if "volts" in p]
        test_volts = round(statistics.median(volts), 2) if volts else None

        spec = specs.get(kv, {})
        cells = pick_cells(test_volts, spec.get("cells_min"), spec.get("cells_max"))
        if cells is None and test_volts:
            # No rated-voltage row on the page; infer from the bench voltage,
            # which sits near mid-charge (~3.85V/cell) on these sweeps.
            cells = max(1, round(test_volts / 3.85))
        entry = by_variant.setdefault(kv, {
            "id": slug(model, kv),
            "name": f"T-Motor {model} KV{kv}",
            "kv": kv,
            "mass_g": spec.get("mass_g"),
            "rated_cells": cells,
            "curves": [],
        })
        entry["curves"].append({
            "prop": prop_raw,
            "test_volts": test_volts,
            "source": "tmotor-html",
            "source_url": url,
            "harvested_at": harvested_at,
            "points": [[p["throttle_pct"], p["thrust_g"], p["amps"], p["watts"]] for p in pts],
        })

    out = []
    for kv, m in sorted(by_variant.items()):
        # A motor with no mass can't contribute to AUW, and a motor with no cell
        # rating can't be voltage-scaled. Either way the sim can't use it.
        if not m["mass_g"] or not m["rated_cells"]:
            print(f"    skip KV{kv}: missing "
                  f"{'mass' if not m['mass_g'] else 'cell rating'}", file=sys.stderr)
            continue
        # Same prop, several bench voltages -> distinct curves. Keep them all,
        # but make the labels unique so curve_for(prop) stays unambiguous.
        seen: dict[str, int] = {}
        for c in m["curves"]:
            seen[c["prop"]] = seen.get(c["prop"], 0) + 1
        counter: dict[str, int] = {}
        for c in m["curves"]:
            if seen[c["prop"]] > 1:
                counter[c["prop"]] = counter.get(c["prop"], 0) + 1
                suffix = (f"@{c['test_volts']:.0f}V" if c["test_volts"]
                          else f"#{counter[c['prop']]}")
                c["prop"] = f"{c['prop']} {suffix}"
        m["curves"].sort(key=lambda c: c["prop"])
        m["props"] = [c["prop"] for c in m["curves"]]
        out.append(m)
    return out


# --------------------------------------------------------------------------- validate

def validate(motor: dict) -> list[str]:
    """Reject sweeps that can't be real. ~4% of scraped curves fail these."""
    problems = []
    for c in motor["curves"]:
        pts = c["points"]
        label = f"{motor['id']}/{c['prop']}"
        if len(pts) < 3:
            problems.append(f"{label}: only {len(pts)} points")
            continue
        thrust = [p[1] for p in pts]
        amps = [p[2] for p in pts]
        if any(b < a for a, b in zip(thrust, thrust[1:])):
            problems.append(f"{label}: thrust not monotonic in throttle")
        if any(b < a for a, b in zip(amps, amps[1:])):
            problems.append(f"{label}: current not monotonic in throttle")
        if any(t <= 0 for t in thrust):
            problems.append(f"{label}: non-positive thrust")
    return problems


# --------------------------------------------------------------------------- diff

def diff_report(old: list[dict], new: list[dict]) -> list[str]:
    o = {m["id"]: m for m in old}
    n = {m["id"]: m for m in new}
    lines = []
    for mid in sorted(n.keys() - o.keys()):
        lines.append(f"  + new motor   {mid}  ({len(n[mid]['curves'])} curves)")
    for mid in sorted(o.keys() - n.keys()):
        lines.append(f"  - delisted    {mid}")
    for mid in sorted(o.keys() & n.keys()):
        a, b = o[mid], n[mid]
        if a.get("mass_g") != b.get("mass_g"):
            lines.append(f"  ~ {mid}: mass {a.get('mass_g')}g -> {b.get('mass_g')}g")
        ca = {c["prop"]: c["points"] for c in a["curves"]}
        cb = {c["prop"]: c["points"] for c in b["curves"]}
        for p in sorted(cb.keys() - ca.keys()):
            lines.append(f"  + {mid}: new curve for {p}")
        for p in sorted(ca.keys() - cb.keys()):
            lines.append(f"  - {mid}: dropped curve for {p}")
        for p in sorted(ca.keys() & cb.keys()):
            if ca[p] != cb[p]:
                lines.append(f"  ~ {mid}: curve revised for {p}")
    return lines


# --------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report the diff, write nothing")
    ap.add_argument("--no-cache", action="store_true", help="refetch even if cached")
    args = ap.parse_args()

    use_cache = not args.no_cache
    harvested_at = dt.date.today().isoformat()

    print("discovering motor products...")
    link_re = re.compile(SELECTORS["product_link"])
    urls: set[str] = set()
    for cat in MOTOR_CATEGORIES:
        html = fetch(f"{BASE}/categorys/{cat}", use_cache)
        found = set(link_re.findall(html))
        urls |= {f"{BASE}/{p}" for p in found}
        print(f"  {cat}: {len(found)} products")
    print(f"  -> {len(urls)} unique product URLs")

    scraped: list[dict] = []
    problems: list[str] = []
    for i, url in enumerate(sorted(urls), 1):
        try:
            motors = build_motors(url, fetch(url, use_cache), harvested_at)
        except Exception as e:  # one bad page must not lose the whole run
            print(f"[{i:3d}] ERROR {url}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        for m in motors:
            bad = validate(m)
            if bad:
                problems.extend(bad)
                m["curves"] = [c for c in m["curves"]
                               if not any(c["prop"] in b for b in bad)]
            if m["curves"]:
                scraped.append(m)
        if motors:
            print(f"[{i:3d}] {len(motors)} variant(s)  {url.rsplit('/', 1)[-1]}")

    existing = json.loads(DATA.read_text()) if DATA.exists() else []
    seeded = [m for m in existing if all(c.get("source") == "seed" for c in m["curves"])]
    prior_scraped = [m for m in existing if m not in seeded]

    merged = seeded + sorted(scraped, key=lambda m: m["id"])

    print(f"\n=== {len(scraped)} scraped motors, "
          f"{sum(len(m['curves']) for m in scraped)} curves, "
          f"{sum(len(c['points']) for m in scraped for c in m['curves'])} points")
    print(f"=== {len(seeded)} hand-seeded motors preserved")
    if problems:
        print(f"=== {len(problems)} curve(s) rejected by validation:")
        for p in problems:
            print(f"    {p}")

    changes = diff_report(prior_scraped, scraped)
    print(f"\n=== changes since last harvest: {len(changes) or 'none'}")
    for line in changes:
        print(line)

    if args.dry_run:
        print("\n(dry run — nothing written)")
        return 0

    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(merged, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nwrote {DATA.relative_to(REPO)}  ({DATA.stat().st_size // 1024} KB, {len(merged)} motors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
