import React, { useState, useEffect, useCallback } from "react";
import { api } from "./api.js";

const F = {
  bg: "#0a0e0d", panel: "#111917", edge: "#1e2b28", edge2: "#2a3d38",
  ink: "#d4e6df", dim: "#6f857e", amber: "#ffb627", green: "#3ddc84",
  red: "#ff5964", cyan: "#4fd6e0", grid: "#152420",
};
const TONE = { red: F.red, amber: F.amber, green: F.green };

const label = { fontSize: 10, letterSpacing: 1.5, color: F.dim, textTransform: "uppercase" };
const input = {
  background: F.bg, color: F.ink, border: `1px solid ${F.edge2}`, borderRadius: 4,
  padding: "8px 10px", fontSize: 13, fontFamily: "inherit", outline: "none", width: "100%",
};
const button = (bg, fg) => ({
  background: bg, color: fg, border: "none", borderRadius: 4, padding: "0 14px",
  fontWeight: 700, fontSize: 12, cursor: "pointer", fontFamily: "inherit", height: 34,
});

// `tone` is the alert colour to show ("red" | "amber" | undefined), decided by the
// caller from the value's meaning. The gauge never compares thresholds itself.
function Gauge({ label: text, value, unit, tone, max, fmt }) {
  const v = typeof value === "number" && isFinite(value) ? value : 0;
  const pct = Math.max(0, Math.min(100, (v / max) * 100));
  const color = TONE[tone] || F.green;
  return (
    <div style={{ background: F.panel, border: `1px solid ${F.edge}`, borderRadius: 4, padding: "10px 12px" }}>
      <div style={{ ...label, marginBottom: 6 }}>{text}</div>
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

function Select({ label: text, value, onChange, options }) {
  return (
    <label style={{ display: "block", marginBottom: 10 }}>
      <div style={{ ...label, marginBottom: 4 }}>{text}</div>
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value)} style={input}>
        {options.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
      </select>
    </label>
  );
}

function Num({ label: text, value, onChange, placeholder }) {
  return (
    <label style={{ display: "block", flex: 1, minWidth: 90 }}>
      <div style={{ ...label, marginBottom: 4 }}>{text}</div>
      <input type="number" inputMode="decimal" step="any" value={value} placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)} style={{ ...input, fontSize: 12 }} />
    </label>
  );
}

// Curves with a named prop are selectable; a motor whose only sweep is unnamed
// (the hand-seeded FPV motors) simulates on that sweep and shows no selector.
const curveProps = (motor) => (motor ? motor.curves.map((c) => c.prop).filter(Boolean) : []);

const DEFAULT_SEL = { motor_id: "1404_3000kv", frame_id: "reliant_y6", pack_id: "liion_4s_p1", payload_id: "lr_kit", prop: null };

function voltageNote(r) {
  if (!r.test_volts) return "bench voltage assumed (3.7V/cell)";
  const how = r.test_volts_source === "derived-w-over-a" ? "derived from W/A" : "stated";
  return `bench ${r.test_volts}V, ${how}`;
}

const ERR_LABEL = { auw_g: ["AUW", "g", 0], hover_thr: ["hover", "%", 0], flight_min: ["flight", "min", 1] };

export default function App() {
  const [parts, setParts] = useState(null);
  const [sel, setSel] = useState(DEFAULT_SEL);
  const [r, setR] = useState(null);
  const [saved, setSaved] = useState([]);
  const [cal, setCal] = useState([]);
  const [buildName, setBuildName] = useState("");
  const [fatal, setFatal] = useState(null);    // parts failed to load: nothing works
  const [notice, setNotice] = useState(null);  // a single action failed: show and carry on
  const [logging, setLogging] = useState(null); // build id whose actuals form is open
  const [actual, setActual] = useState({ auw: "", hover: "", flight: "", notes: "" });

  const refreshCal = useCallback(() => api.calibration().then(setCal).catch(() => {}), []);

  useEffect(() => {
    api.parts().then(setParts).catch((e) => setFatal(String(e)));
    api.builds().then(setSaved).catch(() => {});
    refreshCal();
  }, [refreshCal]);

  useEffect(() => {
    if (!parts) return;
    const t = setTimeout(() => {
      api.simulate(sel).then((res) => { setR(res); setNotice(null); }).catch((e) => setNotice(`simulate: ${e.message}`));
    }, 80);
    return () => clearTimeout(t);
  }, [sel, parts]);

  if (fatal) return <div style={{ background: F.bg, color: F.red, minHeight: "100vh", padding: 40, fontFamily: "monospace" }}>API error: {fatal}</div>;
  if (!parts) return <div style={{ background: F.bg, color: F.dim, minHeight: "100vh", padding: 40, fontFamily: "monospace" }}>loading parts…</div>;

  const motor = parts.motors.find((m) => m.id === sel.motor_id);
  const pack = parts.packs.find((p) => p.id === sel.pack_id);
  const frame = parts.frames.find((f) => f.id === sel.frame_id);
  const props = curveProps(motor);
  const set = (k) => (v) => setSel((s) => ({ ...s, [k]: v }));
  const setMotor = (id) => {
    const p = curveProps(parts.motors.find((m) => m.id === id));
    setSel((s) => ({ ...s, motor_id: id, prop: p[0] ?? null }));
  };

  async function save() {
    try {
      const b = await api.saveBuild({ ...sel, name: buildName.trim() });
      setSaved((s) => [b, ...s]);
      setBuildName("");
      setNotice(null);
    } catch (e) { setNotice(`save: ${e.message}`); }
  }
  function load(b) {
    setSel({ motor_id: b.motor_id, frame_id: b.frame_id, pack_id: b.pack_id, payload_id: b.payload_id, prop: b.prop || null });
  }
  async function del(id) {
    try {
      await api.deleteBuild(id);
      setSaved((s) => s.filter((b) => b.id !== id));
      refreshCal();
    } catch (e) { setNotice(`delete: ${e.message}`); }
  }
  function openLog(id) {
    setLogging(logging === id ? null : id);
    setActual({ auw: "", hover: "", flight: "", notes: "" });
  }
  async function submitActual(id) {
    const num = (s) => (s.trim() === "" ? null : Number(s));
    const body = {
      measured_auw_g: num(actual.auw), measured_hover_thr: num(actual.hover),
      measured_flight_min: num(actual.flight), notes: actual.notes.trim(),
    };
    try {
      await api.addActual(id, body);
      setLogging(null);
      refreshCal();
      setNotice(null);
    } catch (e) { setNotice(`log actual: ${e.message}`); }
  }

  // Alert tones, decided here from what each number means.
  const tones = r && {
    auw: r.frame_class === "sub250" && r.auw_g >= 250 ? "red" : undefined,
    twr: !r.can_hover || r.twr < 2 ? "red" : r.twr < 2.5 ? "amber" : undefined,
    hover: !r.can_hover || r.hover_throttle > 65 ? "red" : r.hover_throttle > 50 ? "amber" : undefined,
    current: r.pack_max_a == null ? undefined
      : r.hover_current_a > r.pack_max_a ? "red"
      : r.hover_current_a > 0.8 * r.pack_max_a ? "amber" : undefined,
    punch: r.pack_max_a != null && r.full_current_a > r.pack_max_a ? "red" : undefined,
  };

  return (
    <div style={{ minHeight: "100vh", background: F.bg, color: F.ink,
      fontFamily: "'DM Mono', ui-monospace, 'SF Mono', Menlo, monospace", padding: "20px 16px" }}>
      <style>{`@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Rajdhani:wght@600;700&display=swap');
        select option{background:#0a0e0d} *{box-sizing:border-box} body{margin:0}
        input[type=number]::-webkit-inner-spin-button{opacity:.4}
        @media(max-width:720px){.grid2{grid-template-columns:1fr!important} .g3{grid-template-columns:repeat(2,1fr)!important}}`}</style>

      <div style={{ maxWidth: 940, margin: "0 auto" }}>
        <header style={{ borderBottom: `1px solid ${F.edge2}`, paddingBottom: 12, marginBottom: 18,
          display: "flex", alignItems: "baseline", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
          <div style={{ fontFamily: "'Rajdhani',sans-serif", fontSize: 30, fontWeight: 700, letterSpacing: 3, color: F.ink }}>
            BUILD<span style={{ color: F.amber }}>BENCH</span>
          </div>
          {r && frame && pack && (
            <div style={{ fontSize: 10, color: F.dim, letterSpacing: 1 }}>
              {r.n_motors} MOTOR · {frame.coax ? "COAX" : "FLAT"} · {pack.cells}S · {r.pack_chemistry.toUpperCase()}
            </div>
          )}
        </header>

        {notice && (
          <div style={{ background: "rgba(255,182,39,.08)", border: `1px solid ${F.amber}`, color: F.amber,
            borderRadius: 3, padding: "7px 10px", fontSize: 12, marginBottom: 12 }}>▲ {notice}</div>
        )}

        <div className="grid2" style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: 18 }}>
          <div>
            <Select label="Frame" value={sel.frame_id} onChange={set("frame_id")} options={parts.frames} />
            <Select label="Motor (×n)" value={sel.motor_id} onChange={setMotor} options={parts.motors} />
            {props.length > 0 && (
              <Select label="Prop (bench sweep)" value={sel.prop} onChange={set("prop")}
                options={props.map((p) => ({ id: p, name: p }))} />
            )}
            <Select label="Battery" value={sel.pack_id} onChange={set("pack_id")} options={parts.packs} />
            <Select label="Payload" value={sel.payload_id} onChange={set("payload_id")} options={parts.payloads} />
            <div style={{ marginTop: 4, display: "flex", gap: 6 }}>
              <input value={buildName} onChange={(e) => setBuildName(e.target.value)} placeholder="name this build"
                onKeyDown={(e) => e.key === "Enter" && save()}
                style={{ ...input, flex: 1, minWidth: 0, fontSize: 12 }} />
              <button onClick={save} style={button(F.amber, "#1a1200")}>SAVE</button>
            </div>
          </div>

          {r && (
            <div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2,1fr)", gap: 10, marginBottom: 12 }}>
                <Gauge label="All-up weight" value={r.auw_g} unit="g" tone={tones.auw}
                  max={r.frame_class === "sub250" ? 300 : Math.max(300, r.auw_g * 1.2)} fmt={(v) => v.toFixed(0)} />
                <Gauge label="Thrust : weight" value={r.twr} unit=": 1" max={6} tone={tones.twr} fmt={(v) => v.toFixed(2)} />
                <Gauge label="Hover throttle" value={r.can_hover ? r.hover_throttle : 100} unit="%" max={100} tone={tones.hover} fmt={(v) => v.toFixed(0)} />
                <Gauge label="Flight time" value={r.flight_min} unit="min" max={30} fmt={(v) => v.toFixed(1)} />
              </div>
              <div className="g3" style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10 }}>
                <Gauge label="Max thrust" value={r.max_thrust_g} unit="g" max={r.max_thrust_g * 1.1 || 100} fmt={(v) => v.toFixed(0)} />
                <Gauge label="Hover draw" value={r.hover_power_w} unit="W" max={r.hover_power_w * 1.3 || 100} fmt={(v) => v.toFixed(0)} />
                <Gauge label="Hover current" value={r.hover_current_a} unit={r.pack_max_a != null ? `A of ${r.pack_max_a}` : "A"}
                  max={r.pack_max_a ?? (r.hover_current_a * 1.3 || 10)} tone={tones.current} fmt={(v) => v.toFixed(1)} />
              </div>
              <div className="g3" style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10, marginTop: 10 }}>
                <Gauge label="Spare lift" value={r.carry_g} unit="g" max={Math.max(200, r.carry_g * 1.2)} fmt={(v) => v.toFixed(0)} />
                <Gauge label="Punch-out draw" value={r.full_current_a} unit={r.pack_max_a != null ? `A of ${r.pack_max_a}` : "A"}
                  max={r.pack_max_a ?? (r.full_current_a * 1.2 || 10)} tone={tones.punch} fmt={(v) => v.toFixed(0)} />
                <Gauge label="Sagged V/cell" value={r.hover_v_cell} unit="V" max={4.2} fmt={(v) => v.toFixed(2)} />
              </div>

              <div style={{ marginTop: 10, fontSize: 10, color: F.dim, letterSpacing: .5, lineHeight: 1.6 }}>
                CURVE · {r.prop || "unnamed sweep"} · {r.curve_source} · {voltageNote(r)}
                <br />MASS · rigging {r.rigging_g.toFixed(0)}g · pack {r.pack_wh.toFixed(1)}Wh, {(r.usable_fraction * 100).toFixed(0)}% usable
              </div>

              <div style={{ marginTop: 10, minHeight: 20 }}>
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
            <div style={{ ...label, letterSpacing: 2, marginBottom: 8 }}>Saved builds — tap to load · LOG to record what it really did</div>
            <div style={{ display: "grid", gap: 6 }}>
              {saved.map((b) => (
                <div key={b.id} style={{ background: F.panel, border: `1px solid ${F.edge}`, borderRadius: 4 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 12px", fontSize: 12, flexWrap: "wrap" }}>
                    <button onClick={() => load(b)} style={{ flex: 1, textAlign: "left", background: "none", border: "none",
                      color: F.ink, cursor: "pointer", fontFamily: "inherit", fontSize: 12, minWidth: 120 }}>
                      <span style={{ color: F.amber }}>{b.name}</span>
                      {b.prop && <span style={{ color: F.dim }}> · {b.prop}</span>}
                    </button>
                    <span style={{ color: F.dim, fontVariantNumeric: "tabular-nums" }}>{b.result.auw_g?.toFixed(0)}g</span>
                    <span style={{ color: F.dim, fontVariantNumeric: "tabular-nums" }}>{b.result.twr?.toFixed(1)}:1</span>
                    <span style={{ color: F.dim, fontVariantNumeric: "tabular-nums" }}>{b.result.flight_min?.toFixed(1)}min</span>
                    <span style={{ color: b.result.sub250 ? F.green : F.red }}>{b.result.sub250 ? "sub250" : "over"}</span>
                    <button onClick={() => openLog(b.id)} style={{ background: "none", border: `1px solid ${logging === b.id ? F.cyan : F.edge2}`,
                      color: F.cyan, cursor: "pointer", fontSize: 10, fontFamily: "inherit", borderRadius: 3, padding: "3px 8px", letterSpacing: 1 }}>LOG</button>
                    <button onClick={() => del(b.id)} title="delete build and its logged actuals"
                      style={{ background: "none", border: "none", color: F.dim, cursor: "pointer", fontSize: 14, fontFamily: "inherit" }}>×</button>
                  </div>
                  {logging === b.id && (
                    <div style={{ borderTop: `1px solid ${F.edge}`, padding: "10px 12px", display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
                      <Num label="Measured AUW" value={actual.auw} placeholder={`pred ${b.result.auw_g?.toFixed(0)} g`} onChange={(v) => setActual((a) => ({ ...a, auw: v }))} />
                      <Num label="Hover throttle" value={actual.hover} placeholder={b.result.hover_throttle != null ? `pred ${b.result.hover_throttle.toFixed(0)} %` : "%"} onChange={(v) => setActual((a) => ({ ...a, hover: v }))} />
                      <Num label="Flight time" value={actual.flight} placeholder={`pred ${b.result.flight_min?.toFixed(1)} min`} onChange={(v) => setActual((a) => ({ ...a, flight: v }))} />
                      <label style={{ display: "block", flex: 2, minWidth: 140 }}>
                        <div style={{ ...label, marginBottom: 4 }}>Notes</div>
                        <input value={actual.notes} placeholder="pack, wind, source of the numbers" onChange={(e) => setActual((a) => ({ ...a, notes: e.target.value }))} style={{ ...input, fontSize: 12 }} />
                      </label>
                      <button onClick={() => submitActual(b.id)} style={button(F.cyan, "#02191c")}>RECORD</button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {cal.length > 0 && (
          <div style={{ marginTop: 22, borderTop: `1px solid ${F.edge2}`, paddingTop: 14 }}>
            <div style={{ ...label, letterSpacing: 2, marginBottom: 8 }}>Calibration — predicted minus measured</div>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, fontVariantNumeric: "tabular-nums" }}>
                <thead>
                  <tr style={{ color: F.dim, textAlign: "left" }}>
                    {["build", "metric", "predicted", "measured", "error", "notes"].map((h) => (
                      <th key={h} style={{ ...label, padding: "4px 8px", borderBottom: `1px solid ${F.edge}` }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {cal.flatMap((e) => Object.entries(e.error).map(([k, err]) => {
                    const [name, unit, dp] = ERR_LABEL[k];
                    const pred = k === "auw_g" ? e.predicted.auw_g : k === "hover_thr" ? e.predicted.hover_throttle : e.predicted.flight_min;
                    const meas = k === "auw_g" ? e.actual.measured_auw_g : k === "hover_thr" ? e.actual.measured_hover_thr : e.actual.measured_flight_min;
                    const rel = meas ? Math.abs(err / meas) : 0;
                    return (
                      <tr key={`${e.actual.actual_id}-${k}`} style={{ borderBottom: `1px solid ${F.grid}` }}>
                        <td style={{ padding: "5px 8px", color: F.amber }}>{e.actual.name}{e.actual.prop ? <span style={{ color: F.dim }}> · {e.actual.prop}</span> : null}</td>
                        <td style={{ padding: "5px 8px" }}>{name}</td>
                        <td style={{ padding: "5px 8px" }}>{pred?.toFixed(dp)} {unit}</td>
                        <td style={{ padding: "5px 8px" }}>{meas?.toFixed(dp)} {unit}</td>
                        <td style={{ padding: "5px 8px", color: rel > 0.15 ? F.red : rel > 0.07 ? F.amber : F.green }}>
                          {err > 0 ? "+" : ""}{err.toFixed(dp)} {unit}
                        </td>
                        <td style={{ padding: "5px 8px", color: F.dim }}>{e.actual.notes}</td>
                      </tr>
                    );
                  }))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <div style={{ marginTop: 20, fontSize: 10, color: F.dim, lineHeight: 1.6, borderTop: `1px solid ${F.edge}`, paddingTop: 10 }}>
          Thrust interpolated in throttle² space from the selected bench sweep, scaled by voltage² from that sweep's own bench
          voltage; pack voltage sags with internal resistance under load and the hover point is solved at the sagged voltage.
          Flight time = usable capacity (80% LiPo, 90% Li-ion) ÷ hover current at the sagged operating point. Packs with a known
          rating are checked against hover and punch-out draw. Estimates for comparing builds — log actuals on saved builds to
          calibrate against your real fleet.
        </div>
      </div>
    </div>
  );
}
