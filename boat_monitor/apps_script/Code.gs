/**
 * Boat Monitor — Apps Script Web App receiver for Pico/PC sheet logging
 * (Phase 2 in BOAT_MONITOR_P2_PLAN.md).
 *
 * Why this exists: signing a Google service-account JWT directly on
 * MicroPython (Pico) is possible but heavy. This Web App runs under your
 * own Google account instead, so the Pico only needs to POST plain JSON
 * over HTTPS via the SIM7600 modem -- no crypto/JWT signing on-device.
 *
 * Deploy from the "Boat Monitor Logs" spreadsheet:
 *   1. Extensions -> Apps Script
 *   2. Replace Code.gs with this file's contents
 *   3. Project Settings (gear icon) -> Script properties -> Add property
 *        SHEETS_POST_TOKEN = <a random string>
 *      (put the same string in boat_monitor/secrets.py as SHEETS_POST_TOKEN)
 *   4. Deploy -> New deployment -> type: Web app
 *        Execute as: Me
 *        Who has access: Anyone
 *   5. Deploy -> copy the /exec URL into secrets.py as GOOGLE_APPS_SCRIPT_URL
 *
 * POST body (JSON): { "tab": "GPS_Log", "token": "...", "data": {...} }
 * "data" keys are matched by exact header name in row 1 of that tab
 * (see sheets_bootstrap.py's TABS for the header lists already in use).
 * Unmatched headers are left blank; unmatched data keys are ignored.
 * "timestamp_utc" is filled in automatically if the tab has that header
 * and the caller didn't supply one. Timestamp cells are written as Date
 * values so the spreadsheet can format/display them in Pacific time.
 *
 * After editing this file you MUST publish a new Web App version:
 * Deploy -> Manage deployments -> pencil icon -> Version: New version -> Deploy.
 * Saving Code.gs alone does NOT update the live /exec URL the Pico uses.
 */

var RECEIVER_VERSION = 5;
var TIMESTAMP_DISPLAY_FORMAT = 'mmm d, yyyy h:mm AM/PM';
var CONFIG_TAB = 'Config';

function doPost(e) {
  var result;
  try {
    result = handlePost_(e);
  } catch (err) {
    result = { ok: false, error: String(err) };
  }
  return ContentService
    .createTextOutput(JSON.stringify(result))
    .setMimeType(ContentService.MimeType.JSON);
}

function doGet(e) {
  var params = (e && e.parameter) ? e.parameter : {};
  var action = String(params.action || '').trim().toLowerCase();
  if (action === 'dashboard' || action === 'mobile_dashboard') {
    return jsonOutput_(handleDashboardGet_(params));
  }
  if (action === 'set_config') {
    return jsonOutput_(handleSetConfigGet_(params));
  }

  var body = {
    ok: true,
    receiver_version: RECEIVER_VERSION,
    msg: 'Boat Monitor Sheets receiver is running. POST JSON to log a row. GET ?action=dashboard&token=... for mobile read API.',
  };
  return jsonOutput_(body);
}

function jsonOutput_(body) {
  return ContentService
    .createTextOutput(JSON.stringify(body))
    .setMimeType(ContentService.MimeType.JSON);
}

function handleDashboardGet_(params) {
  var expectedToken = PropertiesService.getScriptProperties().getProperty('SHEETS_POST_TOKEN');
  if (expectedToken && params.token !== expectedToken) {
    return { ok: false, error: 'bad token' };
  }

  var deviceFilter = params.device ? String(params.device).trim() : '';
  var config = readConfigSettingsOnly_(deviceFilter);

  return {
    ok: true,
    receiver_version: RECEIVER_VERSION,
    device: deviceFilter || 'all',
    fetched_at: new Date().toISOString(),
    power: lastRowAsObject_('Power_Log', deviceFilter),
    power_recent: recentRowsAsObjects_('Power_Log', deviceFilter, 72),
    v50_bank: lastRowAsObject_('V50_Bank', deviceFilter),
    gps: lastRowAsObject_('GPS_Log', deviceFilter),
    bilge_recent: recentRowsAsObjects_('Bilge_Log', deviceFilter, 10),
    events_recent: recentRowsAsObjects_('Events', deviceFilter, 10),
    config: config,
  };
}

function sheetHeaders_(sheet) {
  var lastCol = sheet.getLastColumn();
  if (lastCol < 1) {
    return [];
  }
  return sheet.getRange(1, 1, 1, lastCol).getValues()[0];
}

function rowToObject_(headers, row) {
  var out = {};
  for (var i = 0; i < headers.length; i++) {
    var key = String(headers[i] || '').trim();
    if (!key) {
      continue;
    }
    var val = row[i];
    if (val instanceof Date) {
      out[key] = val.toISOString();
    } else {
      out[key] = val;
    }
  }
  return out;
}

function deviceMatches_(rowDevice, deviceFilter) {
  if (!deviceFilter) {
    return true;
  }
  return String(rowDevice || '').trim() === deviceFilter;
}

function lastRowAsObject_(tabName, deviceFilter) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(tabName);
  if (!sheet) {
    return null;
  }
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    return null;
  }
  var headers = sheetHeaders_(sheet);
  var deviceCol = headers.indexOf('device');
  var scanStart = Math.max(2, lastRow - 200);
  var values = sheet.getRange(scanStart, 1, lastRow, headers.length).getValues();
  for (var r = values.length - 1; r >= 0; r--) {
    var row = values[r];
    if (deviceCol !== -1 && !deviceMatches_(row[deviceCol], deviceFilter)) {
      continue;
    }
    return rowToObject_(headers, row);
  }
  return null;
}

function recentRowsAsObjects_(tabName, deviceFilter, limit) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(tabName);
  if (!sheet) {
    return [];
  }
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    return [];
  }
  var headers = sheetHeaders_(sheet);
  var deviceCol = headers.indexOf('device');
  var scanStart = Math.max(2, lastRow - 300);
  var values = sheet.getRange(scanStart, 1, lastRow, headers.length).getValues();
  var out = [];
  for (var r = values.length - 1; r >= 0 && out.length < limit; r--) {
    var row = values[r];
    if (deviceCol !== -1 && !deviceMatches_(row[deviceCol], deviceFilter)) {
      continue;
    }
    out.push(rowToObject_(headers, row));
  }
  return out;
}

/**
 * Mobile: set a Config key (device-scoped). GET ?action=set_config&token=...&device=boat-p2&key=v50_full_at_utc&value=...
 */
function handleSetConfigGet_(params) {
  var expectedToken = PropertiesService.getScriptProperties().getProperty('SHEETS_POST_TOKEN');
  if (expectedToken && params.token !== expectedToken) {
    return { ok: false, error: 'bad token' };
  }
  var deviceId = params.device ? String(params.device).trim() : '';
  var key = params.key ? String(params.key).trim() : '';
  var value = params.value != null ? String(params.value) : '';
  if (!deviceId || !key) {
    return { ok: false, error: 'missing device or key' };
  }
  if (key.indexOf('cmd_') === 0) {
    return { ok: false, error: 'cannot set cmd_* via mobile' };
  }
  upsertConfigKey_(deviceId + ':' + key, value);
  return { ok: true, device: deviceId, key: key, value: value, receiver_version: RECEIVER_VERSION };
}

function upsertConfigKey_(fullKey, value) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var config = ss.getSheetByName(CONFIG_TAB);
  if (!config) {
    throw new Error('missing Config tab');
  }
  var lastRow = config.getLastRow();
  if (lastRow < 1) {
    config.getRange(1, 1, 1, 4).setValues([['key', 'value', 'updated_utc', 'note']]);
    lastRow = 1;
  }
  var searchEnd = Math.max(lastRow, 2);
  var keys = config.getRange(2, 1, searchEnd, 1).getValues();
  for (var i = 0; i < keys.length; i++) {
    if (String(keys[i][0] || '').trim() === fullKey) {
      var rowNum = i + 2;
      config.getRange(rowNum, 2).setValue(value);
      config.getRange(rowNum, 3).setValue(new Date());
      return;
    }
  }
  config.appendRow([fullKey, value, new Date(), 'mobile app']);
}

/**
 * Config read for mobile dashboard — does NOT consume cmd_* one-shots.
 */
function readConfigSettingsOnly_(deviceId) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var config = ss.getSheetByName(CONFIG_TAB);
  if (!config || config.getLastRow() < 2) {
    return {};
  }

  var rows = config.getRange(2, 1, config.getLastRow(), 2).getValues();
  var settings = {};

  for (var i = 0; i < rows.length; i++) {
    var rawKey = String(rows[i][0] || '').trim();
    var value = rows[i][1];
    if (!rawKey) {
      continue;
    }

    var key = rawKey;
    if (rawKey.indexOf(':') !== -1) {
      if (!deviceId || rawKey.indexOf(deviceId + ':') !== 0) {
        continue;
      }
      key = rawKey.substring(deviceId.length + 1);
    }

    if (key.indexOf('cmd_') === 0) {
      continue;
    }

    settings[key] = value;
  }

  return settings;
}

function handlePost_(e) {
  if (!e || !e.postData || !e.postData.contents) {
    return { ok: false, error: 'missing POST body' };
  }

  var body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return { ok: false, error: 'invalid JSON: ' + err };
  }

  var expectedToken = PropertiesService.getScriptProperties().getProperty('SHEETS_POST_TOKEN');
  if (expectedToken && body.token !== expectedToken) {
    return { ok: false, error: 'bad token' };
  }

  var tabName = body.tab;
  if (!tabName) {
    return { ok: false, error: 'missing tab' };
  }

  var data = body.data || {};

  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(tabName);
  if (!sheet) {
    return { ok: false, error: 'unknown tab: ' + tabName };
  }

  var lastCol = sheet.getLastColumn();
  var headers = lastCol > 0 ? sheet.getRange(1, 1, 1, lastCol).getValues()[0] : [];

  var tsIndex = headers.indexOf('timestamp_utc');
  var tsValue = null;
  if (tsIndex !== -1) {
    tsValue = data.timestamp_utc ? parseTimestamp_(data.timestamp_utc) : new Date();
    if (!(tsValue instanceof Date) || isNaN(tsValue.getTime())) {
      tsValue = new Date();
    }
    delete data.timestamp_utc;
  }

  var row = headers.map(function (header) {
    return Object.prototype.hasOwnProperty.call(data, header) ? data[header] : '';
  });

  sheet.appendRow(row);
  var rowNum = sheet.getLastRow();

  if (tsIndex !== -1 && tsValue) {
    var tsCell = sheet.getRange(rowNum, tsIndex + 1);
    tsCell.setValue(tsValue);
    tsCell.setNumberFormat(TIMESTAMP_DISPLAY_FORMAT);
  }

  var deviceId = data.device ? String(data.device) : '';
  var commands = readConfigCommands_(deviceId);

  return {
    ok: true,
    tab: tabName,
    row: rowNum,
    receiver_version: RECEIVER_VERSION,
    commands: commands,
  };
}

function truthy_(value) {
  if (value === true || value === 1) {
    return true;
  }
  var text = String(value || '').trim().toLowerCase();
  return text === '1' || text === 'true' || text === 'yes' || text === 'on';
}

/**
 * Read the Config tab (key | value | updated_utc | note).
 * Persistent keys (interval_*, min_fw_version, ...) are returned in settings.
 * One-shot keys cmd_* (or boat-p2:cmd_ota) clear the value cell when consumed.
 */
function readConfigCommands_(deviceId) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var config = ss.getSheetByName(CONFIG_TAB);
  if (!config || config.getLastRow() < 2) {
    return { settings: {}, one_shots: [] };
  }

  var rows = config.getRange(2, 1, config.getLastRow(), 2).getValues();
  var settings = {};
  var oneShots = [];
  var clearRows = [];

  for (var i = 0; i < rows.length; i++) {
    var rawKey = String(rows[i][0] || '').trim();
    var value = rows[i][1];
    if (!rawKey) {
      continue;
    }

    var key = rawKey;
    if (rawKey.indexOf(':') !== -1) {
      if (!deviceId || rawKey.indexOf(deviceId + ':') !== 0) {
        continue;
      }
      key = rawKey.substring(deviceId.length + 1);
    }

    if (key.indexOf('cmd_') === 0) {
      if (truthy_(value)) {
        oneShots.push(key.substring(4));
        clearRows.push(i + 2);
      }
      continue;
    }

    settings[key] = value;
  }

  for (var c = 0; c < clearRows.length; c++) {
    config.getRange(clearRows[c], 2).setValue('');
  }

  return { settings: settings, one_shots: oneShots };
}

function parseTimestamp_(value) {
  if (Object.prototype.toString.call(value) === '[object Date]') {
    return value;
  }

  if (typeof value === 'string') {
    var parsed = new Date(value);
    if (!isNaN(parsed.getTime())) {
      return parsed;
    }
  }

  return value;
}
