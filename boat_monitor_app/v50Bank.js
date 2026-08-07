/**
 * V50 USB power bank — watts and rough % remaining.
 * Prefers on-device cumulative mAh (v50_mah_used) when present; else integrates sheet history.
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

export function v50WattsFromRow(row) {
  if (!row) return null;
  const v = num(row.v50_v);
  const a = num(row.v50_a);
  if (v == null || a == null) return null;
  return v * a;
}

function capacityMahFromConfig(config) {
  const mah = num(config?.v50_capacity_mah);
  if (mah != null && mah > 0) return mah;
  const wh = num(config?.v50_capacity_wh ?? config?.v50_capacity_Wh);
  if (wh != null && wh > 0) return (wh * 1000) / 5;
  return null;
}

function fullAnchorMs(config) {
  return parseTime(config?.v50_full_at_utc);
}

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

export function estimateV50State({ power, powerRecent, v50Bank, config }) {
  const watts = v50WattsFromRow(power);
  const configCapacityMah = capacityMahFromConfig(config);
  const anchorMs = fullAnchorMs(config);

  const deviceMahUsed = num(power?.v50_mah_used);
  const devicePct = num(power?.v50_pct_remain);
  const bankMahUsed = num(v50Bank?.mah_used);
  const bankPct = num(v50Bank?.pct_remain);
  const bankCap = num(v50Bank?.mah_capacity);

  let mahUsed = deviceMahUsed ?? bankMahUsed;
  let percent = devicePct ?? bankPct;
  let capacityMah = bankCap ?? configCapacityMah;

  if (mahUsed == null && capacityMah != null && anchorMs != null) {
    const usedWh = integrateV50WhSince(powerRecent, anchorMs);
    if (usedWh != null) {
      mahUsed = (usedWh * 1000) / 5;
    }
  }

  if (percent == null && capacityMah != null && mahUsed != null) {
    const remaining = Math.max(0, capacityMah - mahUsed);
    percent = Math.min(100, Math.max(0, (remaining / capacityMah) * 100));
  }

  const mahRemain =
    capacityMah != null && mahUsed != null ? Math.max(0, capacityMah - mahUsed) : null;

  return {
    watts,
    capacityMah,
    mahUsed,
    mahRemain,
    percent,
    needsCapacity: capacityMah == null,
    needsFullAnchor: anchorMs == null && mahUsed == null,
    source: deviceMahUsed != null ? 'device' : bankMahUsed != null ? 'v50_bank_tab' : 'sheet_integrate',
  };
}
