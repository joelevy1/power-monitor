/**
 * V50 USB power bank — watts and rough % from sheet Power_Log history.
 * Capacity (Wh) and "full" anchor live in Config tab (Google Sheet).
 */

function parseTime(value) {
  if (!value) return null;
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return d.getTime();
}

function num(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** Instantaneous power in watts from a Power_Log row (or latest snapshot). */
export function v50WattsFromRow(row) {
  if (!row) return null;
  const v = num(row.v50_v);
  const a = num(row.v50_a);
  if (v == null || a == null) return null;
  return v * a;
}

function capacityWhFromConfig(config) {
  const raw = config?.v50_capacity_wh ?? config?.v50_capacity_Wh;
  const n = num(raw);
  if (n == null || n <= 0) return null;
  return n;
}

function fullAnchorMs(config) {
  return parseTime(config?.v50_full_at_utc);
}

/**
 * Integrate discharge energy (Wh) from power_recent since full anchor.
 * Uses trapezoidal rule between log timestamps; only counts positive v50_a as discharge.
 */
export function integrateV50WhSince(powerRecent, anchorMs) {
  if (!anchorMs || !Array.isArray(powerRecent) || powerRecent.length < 2) {
    return null;
  }
  const rows = powerRecent
    .map((r) => ({
      t: parseTime(r.timestamp_utc),
      v: num(r.v50_v),
      a: num(r.v50_a),
    }))
    .filter((r) => r.t != null && r.t >= anchorMs)
    .sort((a, b) => a.t - b.t);

  if (rows.length < 2) {
    return 0;
  }

  let wh = 0;
  for (let i = 1; i < rows.length; i++) {
    const dtH = (rows[i].t - rows[i - 1].t) / 3600000;
    if (dtH <= 0) continue;
    const a0 = rows[i - 1].a != null ? Math.max(0, rows[i - 1].a) : 0;
    const a1 = rows[i].a != null ? Math.max(0, rows[i].a) : 0;
    const v0 = rows[i - 1].v != null ? rows[i - 1].v : rows[i].v;
    const v1 = rows[i].v != null ? rows[i].v : rows[i - 1].v;
    if (v0 == null || v1 == null) continue;
    const p0 = v0 * a0;
    const p1 = v1 * a1;
    wh += ((p0 + p1) / 2) * dtH;
  }
  return wh;
}

export function estimateV50State({ power, powerRecent, config }) {
  const watts = v50WattsFromRow(power);
  const capacityWh = capacityWhFromConfig(config);
  const anchorMs = fullAnchorMs(config);
  const usedWh = integrateV50WhSince(powerRecent, anchorMs);

  let percent = null;
  if (capacityWh != null && usedWh != null && anchorMs != null) {
    const remaining = Math.max(0, capacityWh - usedWh);
    percent = Math.min(100, Math.max(0, (remaining / capacityWh) * 100));
  }

  return {
    watts,
    capacityWh,
    usedWhSinceFull: usedWh,
    percent,
    needsCapacity: capacityWh == null,
    needsFullAnchor: anchorMs == null,
  };
}
