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
 */

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
  var body = {
    ok: true,
    msg: 'Boat Monitor Sheets receiver is running. POST JSON to log a row.',
  };
  return ContentService
    .createTextOutput(JSON.stringify(body))
    .setMimeType(ContentService.MimeType.JSON);
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

  if (headers.indexOf('timestamp_utc') !== -1) {
    data.timestamp_utc = data.timestamp_utc ? parseTimestamp_(data.timestamp_utc) : new Date();
  }

  var row = headers.map(function (header) {
    return Object.prototype.hasOwnProperty.call(data, header) ? data[header] : '';
  });

  sheet.appendRow(row);

  return { ok: true, tab: tabName, row: sheet.getLastRow() };
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
