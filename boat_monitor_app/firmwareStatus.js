const OTA_MANIFEST_URL =
  'https://raw.githubusercontent.com/joelevy1/power-monitor/master/boat_monitor/ota_manifest.json';
const MANIFEST_TIMEOUT_MS = 8000;

function parseFwParts(text) {
  const parts = [];
  for (const piece of String(text || '').trim().split('.')) {
    const n = parseInt(piece, 10);
    parts.push(Number.isFinite(n) ? n : 0);
  }
  return parts;
}

export function compareFirmware(a, b) {
  const pa = parseFwParts(a);
  const pb = parseFwParts(b);
  const len = Math.max(pa.length, pb.length);
  for (let i = 0; i < len; i += 1) {
    const da = pa[i] || 0;
    const db = pb[i] || 0;
    if (da < db) return -1;
    if (da > db) return 1;
  }
  return 0;
}

export function firmwareLt(a, b) {
  return compareFirmware(a, b) < 0;
}

export async function fetchGithubManifestVersion() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), MANIFEST_TIMEOUT_MS);
  try {
    const res = await fetch(OTA_MANIFEST_URL, { signal: controller.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const manifest = await res.json();
    const version = String(manifest?.version || '').trim();
    if (!version) throw new Error('manifest missing version');
    return { ok: true, version };
  } catch (exc) {
    return { ok: false, error: exc?.message || String(exc) };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Infer OTA health from sheet Config + recent Events rows (dashboard v4+).
 */
export function parseOtaReadiness(eventsRecent, config) {
  const cfg = config || {};
  const degraded =
    String(cfg.ota_degraded || '').trim() === '1' ||
    String(cfg.ota_degraded || '').toLowerCase() === 'true';

  let lastOutcome = null;
  const rows = Array.isArray(eventsRecent) ? eventsRecent : [];
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    const row = rows[i];
    if (!row || typeof row !== 'object') continue;
    const ev = String(row.event || row.name || '').trim();
    const detail = String(row.detail || row.message || '');
    if (ev === 'boot_ota') {
      const m = detail.match(/outcome=([^\s;]+)/);
      lastOutcome = m ? m[1] : detail.slice(0, 40) || 'boot_ota';
      break;
    }
    if (ev === 'ota_lifecycle' && detail.includes('boot_end')) {
      const m = detail.match(/outcome=([^\s;]+)/);
      if (m) {
        lastOutcome = m[1];
        break;
      }
    }
    if (detail.includes('ota_health') && detail.includes('preflight_fail')) {
      lastOutcome = 'preflight_fail';
      break;
    }
  }

  let hint = null;
  if (degraded) {
    hint =
      'Boot OTA is in a protected state (repeated failures). Use home Wi‑Fi, USB recovery, or sheet cmd_ota_force once.';
  } else if (lastOutcome && /fail|preflight|degraded/i.test(lastOutcome)) {
    hint = `Last boot OTA: ${lastOutcome}. Dock on Wi‑Fi or USB-push recovery if this repeats.`;
  }

  return { degraded, lastOutcome, hint };
}

/**
 * @returns {{ label: string, detail: string|null, danger: boolean, ok: boolean }}
 */
export function describeFirmwareStatus(deviceFw, { minFw, githubFw, githubError, otaReadiness } = {}) {
  const fw = String(deviceFw || '').trim();
  if (!fw || fw === '—') {
    return { label: '—', detail: null, danger: false, ok: true };
  }

  const min = minFw ? String(minFw).trim() : '';
  const gh = githubFw ? String(githubFw).trim() : '';

  const behindMin = min && firmwareLt(fw, min);
  const behindGithub = gh && firmwareLt(fw, gh);
  const meetsMin = !min || !behindMin;
  const meetsGithub = !gh || !behindGithub;
  const ota = otaReadiness || {};

  if (ota.degraded) {
    return {
      label: 'OTA degraded',
      detail:
        ota.hint ||
        'Repeated boot OTA failures — use USB recovery or home Wi‑Fi before forcing another OTA.',
      danger: true,
      ok: false,
    };
  }

  if (behindMin) {
    return {
      label: 'Update pending',
      detail: min
        ? `Sheet requires ${min} · Pico is ${fw}. Boot OTA or cmd_ota should apply when the boat is on.${
            ota.hint ? ` ${ota.hint}` : ''
          }`
        : `Pico is ${fw} — sheet min_fw not set.`,
      danger: true,
      ok: false,
    };
  }

  if (behindGithub) {
    return {
      label: 'Newer on GitHub',
      detail: `GitHub manifest is ${gh}. Sheet min_fw is satisfied (${min || 'n/a'}).`,
      danger: true,
      ok: false,
    };
  }

  if (meetsMin && meetsGithub) {
    const target = gh || min || fw;
    return {
      label: 'Latest',
      detail: gh && min ? `Matches GitHub ${gh} and sheet min ${min}.` : gh ? `Matches GitHub ${gh}.` : `At sheet min ${min}.`,
      danger: false,
      ok: true,
    };
  }

  if (githubError && !gh) {
    return {
      label: meetsMin ? 'OK (sheet)' : 'Unknown',
      detail: min
        ? `At or above sheet min ${min}. Could not check GitHub (${githubError}).`
        : `Could not check GitHub (${githubError}).`,
      danger: false,
      ok: meetsMin,
    };
  }

  return { label: 'OK', detail: null, danger: false, ok: true };
}
