import Constants from 'expo-constants';

const DEFAULT_TIMEOUT_MS = 15000;

function extra() {
  return Constants.expoConfig?.extra || Constants.manifest2?.extra?.expoClient?.extra || {};
}

export function getSheetClientConfig() {
  const e = extra();
  const url = String(e.sheetsScriptUrl || process.env.EXPO_PUBLIC_GOOGLE_APPS_SCRIPT_URL || '').trim();
  const token = String(e.sheetsPostToken || process.env.EXPO_PUBLIC_SHEETS_POST_TOKEN || '').trim();
  const deviceId = String(e.boatDeviceId || process.env.EXPO_PUBLIC_BOAT_DEVICE_ID || 'boat-p2').trim();
  return { url, token, deviceId, configured: !!(url && token) };
}

async function fetchWithTimeout(url, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { method: 'GET', signal: controller.signal });
    const text = await res.text();
    let body;
    try {
      body = JSON.parse(text);
    } catch {
      throw new Error(`Invalid JSON (HTTP ${res.status})`);
    }
    if (!res.ok && body?.ok !== true) {
      throw new Error(body?.error || `HTTP ${res.status}`);
    }
    return body;
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchSheetDashboard() {
  const { url, token, deviceId, configured } = getSheetClientConfig();
  if (!configured) {
    return {
      ok: false,
      error: 'missing_config',
      message:
        'Add GOOGLE_APPS_SCRIPT_URL and SHEETS_POST_TOKEN to EAS production (same values as Pico secrets.py), then rebuild. Optional EXPO_PUBLIC_* names also work.',
    };
  }

  const params = new URLSearchParams({
    action: 'dashboard',
    token,
    device: deviceId,
  });
  const requestUrl = `${url}${url.includes('?') ? '&' : '?'}${params.toString()}`;

  const body = await fetchWithTimeout(requestUrl, DEFAULT_TIMEOUT_MS);
  if (!body?.ok) {
    return {
      ok: false,
      error: body?.error || 'request_failed',
      message: body?.error === 'bad token' ? 'Sheet token rejected — check EAS env matches Script property.' : String(body?.error || 'Request failed'),
    };
  }
  if (body.receiver_version != null && Number(body.receiver_version) < 4) {
    return {
      ok: false,
      error: 'old_receiver',
      message:
        'Apps Script deployment is older than v4. Redeploy Code.gs (New version) so GET ?action=dashboard works.',
      partial: body,
    };
  }
  return { ok: true, data: body };
}
