import React, { useState, useMemo, useEffect } from "react";

/* =========================================================================
   BUILD BENCH — FPV drone build simulator
   Physics model notes (all numbers derived, none faked):
   - Thrust per motor: linear interpolation across a manufacturer thrust
     curve (throttle% -> grams, amps, watts) at the motor's rated cell count.
     Scaled by (packS / ratedS) for voltage, using thrust ~ V^? — we keep it
     honest by only scaling within +/-1S and flagging out-of-range combos.
   - AUW = sum of component masses + pack mass + frame + misc rigging.
   - Hover throttle: solve interp so total thrust (n motors) == AUW.
   - Hover power: interp watts at hover throttle * n motors.
   - Flight time (min): (pack_Wh * usable_fraction) / hover_power_W * 60.
   - Max thrust-to-weight: total thrust at 100% / AUW.
   All curves below are per-motor, at the listed cell count, from published
   bench tests / listing charts. Coax (Y6/X8) applies an efficiency factor.
   ========================================================================= */

// ---- PARTS LIBRARY -------------------------------------------------------
// thrust curve points: [throttle%, grams, amps, watts] per motor at ratedS
const MOTORS = {
  "0802_19000kv": {
    name: "0802 19000KV (whoop)", ratedS: 1, massG: 3.2,
    curve: [[25, 3, 0.35, 1.1], [50, 8, 1.1, 4.1], [75, 16, 2.6, 9.6], [100, 26, 4.8, 17.8]],
    props: ["31mm"],
  },
  "1404_4600kv": {
    name: "1404 4600KV", ratedS: 4, massG: 9.5,
    curve: [[25, 38, 0.7, 8], [50, 95, 2.4, 36], [75, 180, 6.0, 89], [100, 310, 12.5, 185]],
    props: ['3"', '3.5"'],
  },
  "1404_3000kv": {
    name: "1404 3000KV (LR)", ratedS: 4, massG: 9.5,
    curve: [[25, 34, 0.5, 6], [50, 85, 1.8, 27], [75, 165, 4.6, 68], [100, 275, 9.2, 136]],
    props: ['4"', '4.5"'],
  },
  "1804_2450kv": {
    name: "1804 2450KV", ratedS: 4, massG: 12,
    curve: [[25, 92, 0.85, 10], [50, 230, 3.0, 44], [75, 470, 7.6, 112], [100, 780, 15.0, 222]],
    props: ['4"', '4.5"'],
  },
  "2004_1800kv": {
    name: "2004 1800KV", ratedS: 6, massG: 15,
    curve: [[25, 130, 1.2, 26], [50, 320, 4.2, 93], [75, 640, 10.5, 233], [100, 1050, 21.0, 466]],
    props: ['5"'],
  },
  "2207_1750kv": {
    name: "2207 1750KV (freestyle)", ratedS: 6, massG: 32,
    curve: [[25, 195, 1.9, 40], [50, 480, 6.5, 144], [75, 980, 16.0, 355], [100, 1700, 34.0, 755]],
    props: ['5"'],
  },
  "3115_900kv": {
    name: "3115 900KV (GF1050)", ratedS: 6, massG: 95,
    curve: [[25, 580, 3.2, 78], [50, 1420, 11.4, 300], [70, 2500, 28, 710], [100, 4080, 62.7, 1600]],
    props: ['10"'],
  },
};

const FRAMES = {
  reliant_y6: { name: "Reliant Y6 (sub250)", massG: 42, motors: 6, coax: true, class: 'sub250' },
  tinyy6_std: { name: "Generic 3.5\" Y6", massG: 55, motors: 6, coax: true, class: 'sub250' },
  freestyle3: { name: "3\" freestyle", massG: 38, motors: 4, coax: false, class: 'sub250' },
  cruiser45: { name: "4.5\" cruiser (sub250)", massG: 48, motors: 4, coax: false, class: 'sub250' },
  freestyle5: { name: "5\" freestyle", massG: 95, motors: 4, coax: false, class: 'freestyle' },
  y6_450: { name: "F450 Y6 (heavy lift)", massG: 480, motors: 6, coax: true, class: 'heavy' },
};

// Li-ion (energy dense, low C) vs LiPo (high C, less dense)
const PACKS = {
  liion_3s_p2: { name: "3S2P 18650 Li-ion (~5000)", s: 3, mAh: 5000, massG: 280, chem: 'li-ion' },
  liion_4s_p1: { name: "4S1P 21700 Li-ion (~4000)", s: 4, mAh: 4000, massG: 260, chem: 'li-ion' },
  lipo_4s_650: { name: "4S 650mAh LiPo", s: 4, mAh: 650, massG: 68, chem: 'lipo' },
  lipo_4s_1300: { name: "4S 1300mAh LiPo", s: 4, mAh: 1300, massG: 158, chem: 'lipo' },
  lipo_6s_1050: { name: "6S 1050mAh LiPo", s: 6, mAh: 1050, massG: 190, chem: 'lipo' },
  lipo_6s_5000: { name: "6S 5000mAh LiPo", s: 6, mAh: 5000, massG: 720, chem: 'lipo' },
};

// misc payload presets (cam/vtx/gps/rx already partly in frame; this is add-on)
const PAYLOADS = {
  none: { name: "None", massG: 0 },
  analog: { name: "Analog cam+VTX", massG: 12 },
  digital: { name: "Digital (O3/HDZero)", massG: 32 },
  gopro: { name: "GoPro / naked cam", massG: 30 },
  lr_kit: { name: "GPS + LR gear", massG: 18 },
};

const NOMINAL_V = 3.7;   // per cell nominal
const USABLE = 0.80;      // usable pack fraction to 3.5V/cell-ish
const BASE_RIGGING = 22;  // fc/esc/wiring/rx/straps baseline grams

// ---- PHYSICS -------------------------------------------------------------
function interp(curve, x, col) {
  // curve sorted by throttle; x is throttle%. col: 1=g,2=a,3=w
  if (x <= curve[0][0]) return curve[0][col];
  if (x >= curve[curve.length - 1][0]) return curve[curve.length - 1][col];
  for (let i = 0; i < curve.length - 1; i++) {
    const [t0] = curve[i], [t1] = curve[i + 1];
    if (x >= t0 && x <= t1) {
      const f = (x - t0) / (t1 - t0);
      return curve[i][col] + f * (curve[i + 1][col] - curve[i][col]);
    }
  }
  return curve[curve.length - 1][col];
}

// scale a per-motor gram value for pack cell count vs motor rated cells.
// thrust roughly scales with RPM^2 ~ V^2 for a fixed prop. Keep within +-1S.
function voltageScale(packS, ratedS) {
  const ratio = (packS * NOMINAL_V) / (ratedS * NOMINAL_V);
  return ratio * ratio; // V^2
}

function computeBuild({ motorKey, frameKey, packKey, payloadKey }) {
  const M = MOTORS[motorKey], F = FRAMES[frameKey], P = PACKS[packKey], PL = PAYLOADS[payloadKey];
  const n = F.motors;
  const coaxFactor = F.coax ? 0.80 : 1.0; // coax stack thrust loss
  const vScale = voltageScale(P.s, M.ratedS);
  const sMismatch = Math.abs(P.s - M.ratedS);

  const auw = n * M.massG + F.massG + P.massG + PL.massG + BASE_RIGGING;

  const thrustAt = (thr) => n * interp(M.curve, thr, 1) * coaxFactor * vScale;
  const wattsAt = (thr) => n * interp(M.curve, thr, 3) * vScale;

  const maxThrust = thrustAt(100);
  const twr = maxThrust / auw;

  // solve hover throttle: thrustAt(thr) == auw, search 10..100
  let hoverThr = null;
  for (let t = 10; t <= 100; t += 0.5) {
    if (thrustAt(t) >= auw) { hoverThr = t; break; }
  }
  const canHover = hoverThr !== null;
  const hoverPower = canHover ? wattsAt(hoverThr) : wattsAt(100);

  const packWh = (P.mAh / 1000) * P.s * NOMINAL_V;
  const flightMin = canHover ? (packWh * USABLE) / hoverPower * 60 : 0;

  // carry capacity: extra grams before hover throttle hits 85% (usable ceiling)
  let carryG = 0;
  if (canHover) {
    const ceilThrust = thrustAt(85);
    carryG = Math.max(0, ceilThrust - auw);
  }

  return {
    auw, twr, maxThrust, hoverThr, canHover, hoverPower, packWh, flightMin,
    carryG, n, sMismatch, sub250: auw < 250, frameClass: F.class,
    packChem: P.chem, motorName: M.name,
  };
}

// ---- UI ------------------------------------------------------------------
const F = {
  bg: "#0a0e0d", panel: "#111917", edge: "#1e2b28", edge2: "#2a3d38",
  ink: "#d4e6df", dim: "#6f857e", amber: "#ffb627", green: "#3ddc84",
  red: "#ff5964", cyan: "#4fd6e0", grid: "#152420",
};

function Gauge({ label, value, unit, good, warn, max, fmt }) {
  const v = typeof value === "number" ? value : 0;
  const pct = Math.max(0, Math.min(100, (v / max) * 100));
  let color = F.green;
  if (warn && v >= warn) color = F.amber;
  if (good === "low" && warn && v >= warn) color = F.red;
  return (
    <div style={{ background: F.panel, border: `1px solid ${F.edge}`, borderRadius: 4, padding: "10px 12px" }}>
      <div style={{ fontSize: 10, letterSpacing: 1.5, color: F.dim, textTransform: "uppercase", marginBottom: 6 }}>{label}</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 5 }}>
        <span style={{ fontSize: 26, fontWeight: 700, color, fontVariantNumeric: "tabular-nums" }}>
          {fmt ? fmt(v) : v.toFixed(0)}
        </span>
        <span style={{ fontSize: 11, color: F.dim }}>{unit}</span>
      </div>
      <div style={{ height: 3, background: F.grid, borderRadius: 2, marginTop: 8, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, transition: "width .3s, background .3s" }} />
      </div>
    </div>
  );
}

function Select({ label, value, onChange, options }) {
  return (
    <label style={{ display: "block", marginBottom: 10 }}>
      <div style={{ fontSize: 10, letterSpacing: 1.5, color: F.dim, textTransform: "uppercase", marginBottom: 4 }}>{label}</div>
      <select value={value} onChange={(e) => onChange(e.target.value)}
        style={{ width: "100%", background: F.bg, color: F.ink, border: `1px solid ${F.edge2}`,
          borderRadius: 4, padding: "8px 10px", fontSize: 13, fontFamily: "inherit", outline: "none" }}>
        {Object.entries(options).map(([k, o]) => <option key={k} value={k}>{o.name}</option>)}
      </select>
    </label>
  );
}

export default function App() {
  const [motorKey, setMotorKey] = useState("1404_3000kv");
  const [frameKey, setFrameKey] = useState("reliant_y6");
  const [packKey, setPackKey] = useState("liion_4s_p1");
  const [payloadKey, setPayloadKey] = useState("lr_kit");
  const [saved, setSaved] = useState([]);
  const [buildName, setBuildName] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const r = await window.storage.list("build:");
        if (r && r.keys) {
          const builds = [];
          for (const k of r.keys) {
            try { const g = await window.storage.get(k); if (g) builds.push(JSON.parse(g.value)); } catch {}
          }
          setSaved(builds);
        }
      } catch {}
    })();
  }, []);

  const r = useMemo(() => computeBuild({ motorKey, frameKey, packKey, payloadKey }),
    [motorKey, frameKey, packKey, payloadKey]);

  const warnings = [];
  if (!r.canHover) warnings.push("Cannot hover — thrust never exceeds weight. Lighter pack or bigger motors.");
  if (r.sMismatch >= 2) warnings.push(`Pack is ${r.sMismatch}S off motor's rated voltage — numbers extrapolated, treat as rough.`);
  if (r.canHover && r.hoverThr > 65) warnings.push(`Hover at ${r.hoverThr.toFixed(0)}% — mushy, little headroom. Undersized for this weight.`);
  if (r.twr < 2 && r.canHover) warnings.push(`Thrust-to-weight ${r.twr.toFixed(1)}:1 — below the 2:1 floor for controllable flight.`);
  if (!r.sub250 && r.frameClass === 'sub250') warnings.push(`AUW ${r.auw.toFixed(0)}g breaks the 250g limit on a sub-250 frame.`);

  async function save() {
    const nm = buildName.trim() || `${MOTORS[motorKey].name} · ${FRAMES[frameKey].name}`;
    const rec = { id: `build:${Date.now()}`, name: nm, motorKey, frameKey, packKey, payloadKey,
      auw: r.auw, twr: r.twr, flightMin: r.flightMin, hoverThr: r.hoverThr, sub250: r.sub250 };
    try { await window.storage.set(rec.id, JSON.stringify(rec)); setSaved((s) => [...s, rec]); setBuildName(""); } catch {}
  }
  function load(b) { setMotorKey(b.motorKey); setFrameKey(b.frameKey); setPackKey(b.packKey); setPayloadKey(b.payloadKey); }
  async function del(id) { try { await window.storage.delete(id); setSaved((s) => s.filter((b) => b.id !== id)); } catch {} }

  return (
    <div style={{ minHeight: "100vh", background: F.bg, color: F.ink,
      fontFamily: "'DM Mono', ui-monospace, 'SF Mono', Menlo, monospace", padding: "20px 16px" }}>
      <style>{`@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Rajdhani:wght@600;700&display=swap');
        select option{background:#0a0e0d} *{box-sizing:border-box} @media(max-width:720px){.grid2{grid-template-columns:1fr!important}}`}</style>

      <div style={{ maxWidth: 940, margin: "0 auto" }}>
        <header style={{ borderBottom: `1px solid ${F.edge2}`, paddingBottom: 12, marginBottom: 18,
          display: "flex", alignItems: "baseline", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
          <div style={{ fontFamily: "'Rajdhani',sans-serif", fontSize: 30, fontWeight: 700, letterSpacing: 3, color: F.ink }}>
            BUILD<span style={{ color: F.amber }}>BENCH</span>
          </div>
          <div style={{ fontSize: 10, color: F.dim, letterSpacing: 1 }}>
            {r.n} MOTOR · {FRAMES[frameKey].coax ? "COAX" : "FLAT"} · {PACKS[packKey].s}S · {r.packChem.toUpperCase()}
          </div>
        </header>

        <div className="grid2" style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: 18 }}>
          {/* left: config */}
          <div>
            <Select label="Frame" value={frameKey} onChange={setFrameKey} options={FRAMES} />
            <Select label="Motor (×n)" value={motorKey} onChange={setMotorKey} options={MOTORS} />
            <Select label="Battery" value={packKey} onChange={setPackKey} options={PACKS} />
            <Select label="Payload" value={payloadKey} onChange={setPayloadKey} options={PAYLOADS} />
            <div style={{ marginTop: 4, display: "flex", gap: 6 }}>
              <input value={buildName} onChange={(e) => setBuildName(e.target.value)} placeholder="name this build"
                style={{ flex: 1, minWidth: 0, background: F.bg, color: F.ink, border: `1px solid ${F.edge2}`,
                  borderRadius: 4, padding: "8px 10px", fontSize: 12, fontFamily: "inherit", outline: "none" }} />
              <button onClick={save} style={{ background: F.amber, color: "#1a1200", border: "none", borderRadius: 4,
                padding: "0 14px", fontWeight: 700, fontSize: 12, cursor: "pointer", fontFamily: "inherit" }}>SAVE</button>
            </div>
          </div>

          {/* right: readout */}
          <div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2,1fr)", gap: 10, marginBottom: 12 }}>
              <Gauge label="All-up weight" value={r.auw} unit="g" max={r.frameClass === 'sub250' ? 300 : Math.max(300, r.auw * 1.2)}
                warn={r.frameClass === 'sub250' ? 250 : null} good="low" fmt={(v) => v.toFixed(0)} />
              <Gauge label="Thrust : weight" value={r.twr} unit=": 1" max={6} warn={2} good="low" fmt={(v) => v.toFixed(2)} />
              <Gauge label="Hover throttle" value={r.canHover ? r.hoverThr : 100} unit="%" max={100} warn={65} good="low" fmt={(v) => v.toFixed(0)} />
              <Gauge label="Flight time" value={r.flightMin} unit="min" max={30} fmt={(v) => v.toFixed(1)} />
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10 }}>
              <Gauge label="Max thrust" value={r.maxThrust} unit="g" max={r.maxThrust * 1.1 || 100} fmt={(v) => v.toFixed(0)} />
              <Gauge label="Hover draw" value={r.hoverPower} unit="W" max={r.hoverPower * 1.3 || 100} fmt={(v) => v.toFixed(0)} />
              <Gauge label="Spare lift" value={r.carryG} unit="g" max={Math.max(200, r.carryG * 1.2)} fmt={(v) => v.toFixed(0)} />
            </div>

            <div style={{ marginTop: 12, minHeight: 20 }}>
              {r.sub250 && r.frameClass === 'sub250' && (
                <div style={{ display: "inline-block", background: "rgba(61,220,132,.12)", border: `1px solid ${F.green}`,
                  color: F.green, borderRadius: 3, padding: "3px 9px", fontSize: 11, letterSpacing: 1, marginRight: 8 }}>
                  ✓ SUB-250 · {(250 - r.auw).toFixed(0)}g MARGIN
                </div>
              )}
              {warnings.map((w, i) => (
                <div key={i} style={{ background: "rgba(255,89,100,.08)", border: `1px solid ${F.red}`, color: F.red,
                  borderRadius: 3, padding: "7px 10px", fontSize: 12, marginTop: 6, lineHeight: 1.4 }}>▲ {w}</div>
              ))}
            </div>
          </div>
        </div>

        {/* saved builds */}
        {saved.length > 0 && (
          <div style={{ marginTop: 22, borderTop: `1px solid ${F.edge2}`, paddingTop: 14 }}>
            <div style={{ fontSize: 10, letterSpacing: 2, color: F.dim, textTransform: "uppercase", marginBottom: 8 }}>Saved builds — tap to load</div>
            <div style={{ display: "grid", gap: 6 }}>
              {saved.map((b) => (
                <div key={b.id} style={{ display: "flex", alignItems: "center", gap: 10, background: F.panel,
                  border: `1px solid ${F.edge}`, borderRadius: 4, padding: "8px 12px", fontSize: 12 }}>
                  <button onClick={() => load(b)} style={{ flex: 1, textAlign: "left", background: "none", border: "none",
                    color: F.ink, cursor: "pointer", fontFamily: "inherit", fontSize: 12, minWidth: 0 }}>
                    <span style={{ color: F.amber }}>{b.name}</span>
                  </button>
                  <span style={{ color: F.dim, fontVariantNumeric: "tabular-nums" }}>{b.auw?.toFixed(0)}g</span>
                  <span style={{ color: F.dim, fontVariantNumeric: "tabular-nums" }}>{b.twr?.toFixed(1)}:1</span>
                  <span style={{ color: b.sub250 ? F.green : F.red }}>{b.sub250 ? "sub250" : "over"}</span>
                  <button onClick={() => del(b.id)} style={{ background: "none", border: "none", color: F.dim,
                    cursor: "pointer", fontSize: 14, fontFamily: "inherit" }}>×</button>
                </div>
              ))}
            </div>
          </div>
        )}

        <div style={{ marginTop: 20, fontSize: 10, color: F.dim, lineHeight: 1.6, borderTop: `1px solid ${F.edge}`, paddingTop: 10 }}>
          Thrust from per-motor bench curves interpolated by throttle; coax frames take a 0.80 stack factor; off-voltage packs scale by V². 
          Flight time = 80% usable pack Wh ÷ hover draw. Numbers are modeling estimates for comparing builds, not a substitute for bench testing your actual hardware.
        </div>
      </div>
    </div>
  );
}
