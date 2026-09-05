import React, { useState, useEffect } from "react";
import { api } from "./api.js";

const F = {
  bg: "#0a0e0d", panel: "#111917", edge: "#1e2b28", edge2: "#2a3d38",
  ink: "#d4e6df", dim: "#6f857e", amber: "#ffb627", green: "#3ddc84",
  red: "#ff5964", cyan: "#4fd6e0", grid: "#152420",
};

function Gauge({ label, value, unit, warn, max, fmt }) {
  const v = typeof value === "number" && isFinite(value) ? value : 0;
  const pct = Math.max(0, Math.min(100, (v / max) * 100));
  let color = F.green;
  if (warn && v >= warn) color = warn >= 100 ? F.red : F.amber;
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
        {options.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
      </select>
    </label>
  );
}

export default function App() {
  const [parts, setParts] = useState(null);
  const [sel, setSel] = useState({ motor_id: "1404_3000kv", frame_id: "reliant_y6", pack_id: "liion_4s_p1", payload_id: "lr_kit" });
  const [r, setR] = useState(null);
  const [saved, setSaved] = useState([]);
  const [buildName, setBuildName] = useState("");
  const [error, setError] = useState(null);

  useEffect(() => {
    api.parts().then(setParts).catch((e) => setError(String(e)));
    api.builds().then(setSaved).catch(() => {});
  }, []);

  useEffect(() => {
    if (!parts) return;
    const t = setTimeout(() => {
      api.simulate(sel).then(setR).catch((e) => setError(String(e)));
    }, 80);
    return () => clearTimeout(t);
  }, [sel, parts]);

  if (error) return <div style={{ background: F.bg, color: F.red, minHeight: "100vh", padding: 40, fontFamily: "monospace" }}>API error: {error}</div>;
  if (!parts) return <div style={{ background: F.bg, color: F.dim, minHeight: "100vh", padding: 40, fontFamily: "monospace" }}>loading parts…</div>;

  const pack = parts.packs.find((p) => p.id === sel.pack_id);
  const frame = parts.frames.find((f) => f.id === sel.frame_id);
  const set = (k) => (v) => setSel((s) => ({ ...s, [k]: v }));

  async function save() {
    const b = await api.saveBuild({ ...sel, name: buildName.trim() });
    setSaved((s) => [b, ...s]);
    setBuildName("");
  }
  function load(b) {
    setSel({ motor_id: b.motor_id, frame_id: b.frame_id, pack_id: b.pack_id, payload_id: b.payload_id });
  }
  async function del(id) {
    await api.deleteBuild(id);
    setSaved((s) => s.filter((b) => b.id !== id));
  }

  return (
    <div style={{ minHeight: "100vh", background: F.bg, color: F.ink,
      fontFamily: "'DM Mono', ui-monospace, 'SF Mono', Menlo, monospace", padding: "20px 16px" }}>
      <style>{`@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Rajdhani:wght@600;700&display=swap');
        select option{background:#0a0e0d} *{box-sizing:border-box} body{margin:0} @media(max-width:720px){.grid2{grid-template-columns:1fr!important}}`}</style>

      <div style={{ maxWidth: 940, margin: "0 auto" }}>
        <header style={{ borderBottom: `1px solid ${F.edge2}`, paddingBottom: 12, marginBottom: 18,
          display: "flex", alignItems: "baseline", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
          <div style={{ fontFamily: "'Rajdhani',sans-serif", fontSize: 30, fontWeight: 700, letterSpacing: 3, color: F.ink }}>
            BUILD<span style={{ color: F.amber }}>BENCH</span>
          </div>
          {r && (
            <div style={{ fontSize: 10, color: F.dim, letterSpacing: 1 }}>
              {r.n_motors} MOTOR · {frame.coax ? "COAX" : "FLAT"} · {pack.cells}S · {r.pack_chemistry.toUpperCase()}
            </div>
          )}
        </header>

        <div className="grid2" style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: 18 }}>
          <div>
            <Select label="Frame" value={sel.frame_id} onChange={set("frame_id")} options={parts.frames} />
            <Select label="Motor (×n)" value={sel.motor_id} onChange={set("motor_id")} options={parts.motors} />
            <Select label="Battery" value={sel.pack_id} onChange={set("pack_id")} options={parts.packs} />
            <Select label="Payload" value={sel.payload_id} onChange={set("payload_id")} options={parts.payloads} />
            <div style={{ marginTop: 4, display: "flex", gap: 6 }}>
              <input value={buildName} onChange={(e) => setBuildName(e.target.value)} placeholder="name this build"
                style={{ flex: 1, minWidth: 0, background: F.bg, color: F.ink, border: `1px solid ${F.edge2}`,
                  borderRadius: 4, padding: "8px 10px", fontSize: 12, fontFamily: "inherit", outline: "none" }} />
              <button onClick={save} style={{ background: F.amber, color: "#1a1200", border: "none", borderRadius: 4,
                padding: "0 14px", fontWeight: 700, fontSize: 12, cursor: "pointer", fontFamily: "inherit" }}>SAVE</button>
            </div>
          </div>

          {r && (
            <div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2,1fr)", gap: 10, marginBottom: 12 }}>
                <Gauge label="All-up weight" value={r.auw_g} unit="g" max={r.frame_class === "sub250" ? 300 : Math.max(300, r.auw_g * 1.2)}
                  warn={r.frame_class === "sub250" ? 250 : null} fmt={(v) => v.toFixed(0)} />
                <Gauge label="Thrust : weight" value={r.twr} unit=": 1" max={6} warn={r.twr < 2 ? 100 : null} fmt={(v) => v.toFixed(2)} />
                <Gauge label="Hover throttle" value={r.can_hover ? r.hover_throttle : 100} unit="%" max={100} warn={r.can_hover && r.hover_throttle > 65 ? 100 : null} fmt={(v) => v.toFixed(0)} />
                <Gauge label="Flight time" value={r.flight_min} unit="min" max={30} fmt={(v) => v.toFixed(1)} />
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10 }}>
                <Gauge label="Max thrust" value={r.max_thrust_g} unit="g" max={r.max_thrust_g * 1.1 || 100} fmt={(v) => v.toFixed(0)} />
                <Gauge label="Hover draw" value={r.hover_power_w} unit="W" max={r.hover_power_w * 1.3 || 100} fmt={(v) => v.toFixed(0)} />
                <Gauge label="Hover current" value={r.hover_current_a} unit="A" max={r.hover_current_a * 1.3 || 10} fmt={(v) => v.toFixed(1)} />
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10, marginTop: 10 }}>
                <Gauge label="Spare lift" value={r.carry_g} unit="g" max={Math.max(200, r.carry_g * 1.2)} fmt={(v) => v.toFixed(0)} />
                <Gauge label="Pack energy" value={r.pack_wh} unit="Wh" max={Math.max(100, r.pack_wh * 1.2)} fmt={(v) => v.toFixed(1)} />
                <Gauge label="Sagged V/cell" value={r.hover_v_cell} unit="V" max={4.2} fmt={(v) => v.toFixed(2)} />
              </div>

              <div style={{ marginTop: 12, minHeight: 20 }}>
                {r.sub250 && r.frame_class === "sub250" && (
                  <div style={{ display: "inline-block", background: "rgba(61,220,132,.12)", border: `1px solid ${F.green}`,
                    color: F.green, borderRadius: 3, padding: "3px 9px", fontSize: 11, letterSpacing: 1, marginRight: 8 }}>
                    ✓ SUB-250 · {(250 - r.auw_g).toFixed(0)}g MARGIN
                  </div>
                )}
                {r.warnings.map((w, i) => (
                  <div key={i} style={{ background: "rgba(255,89,100,.08)", border: `1px solid ${F.red}`, color: F.red,
                    borderRadius: 3, padding: "7px 10px", fontSize: 12, marginTop: 6, lineHeight: 1.4 }}>▲ {w}</div>
                ))}
              </div>
            </div>
          )}
        </div>

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
                  <span style={{ color: F.dim, fontVariantNumeric: "tabular-nums" }}>{b.result.auw_g?.toFixed(0)}g</span>
                  <span style={{ color: F.dim, fontVariantNumeric: "tabular-nums" }}>{b.result.twr?.toFixed(1)}:1</span>
                  <span style={{ color: b.result.sub250 ? F.green : F.red }}>{b.result.sub250 ? "sub250" : "over"}</span>
                  <button onClick={() => del(b.id)} style={{ background: "none", border: "none", color: F.dim,
                    cursor: "pointer", fontSize: 14, fontFamily: "inherit" }}>×</button>
                </div>
              ))}
            </div>
          </div>
        )}

        <div style={{ marginTop: 20, fontSize: 10, color: F.dim, lineHeight: 1.6, borderTop: `1px solid ${F.edge}`, paddingTop: 10 }}>
          Thrust interpolated in throttle² space from per-motor bench curves; pack voltage sags with internal resistance under load,
          and the hover point is solved at the sagged voltage. Flight time = 80% usable capacity ÷ hover current at the sagged operating point.
          Estimates for comparing builds — log actuals on saved builds to calibrate against your real fleet.
        </div>
      </div>
    </div>
  );
}
