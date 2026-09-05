const BASE = "/api";

async function req(path, options = {}) {
  const r = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.status === 204 ? null : r.json();
}

export const api = {
  parts: () => req("/parts"),
  simulate: (sel) => req("/simulate", { method: "POST", body: JSON.stringify(sel) }),
  builds: () => req("/builds"),
  saveBuild: (b) => req("/builds", { method: "POST", body: JSON.stringify(b) }),
  deleteBuild: (id) => req(`/builds/${id}`, { method: "DELETE" }),
  addActual: (buildId, a) => req(`/builds/${buildId}/actuals`, { method: "POST", body: JSON.stringify(a) }),
  calibration: () => req("/calibration"),
};
