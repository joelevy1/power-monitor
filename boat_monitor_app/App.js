import React, { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Linking,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import Constants from 'expo-constants';

const FW500 = Platform.OS === 'ios' ? {} : { fontWeight: '500' };
const FW600 = Platform.OS === 'ios' ? {} : { fontWeight: '600' };

const APP_VERSION =
  Constants.expoConfig?.version || Constants.manifest2?.extra?.expoClient?.version || '0.0.0';

// Passive BLE scan (home screen, not connected): listen for advertisements
// for PASSIVE_SCAN_WINDOW_MS, then stop -- avoids scanning continuously in
// the background (battery), re-running every PASSIVE_SCAN_REPEAT_MS so the
// "broadcasting nearby" status still stays reasonably fresh while idle.
// Same pattern as the Ballast app's home screen passive RSSI scan.
const PASSIVE_SCAN_WINDOW_MS = 12000;
const PASSIVE_SCAN_REPEAT_MS = 25000;
const LIVE_RSSI_POLL_MS = 2000;

// The Pico's own Wi-Fi AP fallback console (field_console.py's start_ap(),
// see main.py's "wifi"/"start_wifi" boot path). iOS does NOT let
// third-party apps scan for nearby Wi-Fi networks/SSIDs at all -- that's a
// platform restriction, not something this app can work around -- so this
// checks REACHABILITY of the console instead: it only succeeds once your
// phone has actually joined the BoatMonitor Wi-Fi network in iOS Settings,
// at which point a real fetch to it is the practical equivalent of "is the
// AP up and serving".
const WIFI_CONSOLE_URL = 'http://192.168.4.1/';
const WIFI_CHECK_TIMEOUT_MS = 4000;
const OTA_MANIFEST_URL =
  'https://raw.githubusercontent.com/joelevy1/power-monitor/master/boat_monitor/ota_manifest.json';
const FIRMWARE_CHECK_TIMEOUT_MS = 8000;

function fetchWithTimeout(url, options, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  return fetch(url, { ...options, signal: controller.signal }).finally(() => clearTimeout(timer));
}

// Friendly display names + rough expected duration for each command --
// shown up front so "why is this taking so long" has an answer instead of
// silence. Durations are real cellular round-trips (modem reset +
// registration + HTTPS), not app slowness -- see cellular.py/auto_log.py.
const COMMAND_INFO = {
  refresh: { label: 'Refresh', hint: 'instant' },
  log: { label: 'Log Now', hint: '~15-45s over cellular (BLE stays connected)' },
  signal: { label: 'Check Signal', hint: '~5-20s (modem/SIM/network registration, no data session)' },
  gps: { label: 'Check GPS', hint: '~5-30s (GPS fix check, no internet data session)' },
  ota: { label: 'OTA Check', hint: 'reboots, then checks GitHub before BLE starts' },
  wifi: { label: 'Start Wi-Fi', hint: 'reboots immediately -- BLE will disconnect' },
  reboot: { label: 'Reboot', hint: 'reboots immediately -- BLE will disconnect' },
};

// Placeholder command_result values ble_service.py's handle_command() sets
// immediately after receiving a command, before the real (often
// multi-second) work finishes. Anything else is a final result -- used to
// know when a pending command has actually resolved instead of just
// showing "Sent command: X" forever with no further feedback.
const IN_PROGRESS_RESULTS = new Set([
  'logging',
  'logging_modem',
  'logging_power',
  'logging_power_ok',
  'logging_gps',
  'checking_signal',
  'checking_gps',
  'ota_started',
  'ota_rebooting',
  'starting_wifi',
  'rebooting',
]);

function bleAvailabilitySummary({ connected, bleBroadcasting, scanning, inputs }) {
  const switchOn = !!inputs?.switch;
  const keyOn = !!inputs?.key;
  if (connected) {
    if (switchOn || keyOn) {
      return 'BLE active — battery switch or key is ON.';
    }
    return 'Connected, but switch and key read OFF — Pico may leave BLE mode soon.';
  }
  if (scanning) return 'Scanning for BoatMonitor…';
  if (bleBroadcasting) {
    return 'BoatMonitor nearby — tap Connect BLE (keep switch or key ON).';
  }
  return 'No BLE yet — turn battery switch or key ON at the boat and stay within range. USB to a laptop does not start BLE.';
}

function remoteFirmwareHint() {
  return 'Remote firmware update: set Config cmd_ota = 1 on the sheet (one shot). The next automatic upload reboots the Pico for OTA — this does not turn BLE on.';
}

function inProgressStageText(result) {
  switch (result) {
    case 'logging':
      return 'Starting log to Google Sheets...';
    case 'logging_modem':
      return 'Connecting cellular modem to the network (this is usually the slow part)...';
    case 'logging_power':
      return 'Posting Power_Log to Google Sheets...';
    case 'logging_power_ok':
      return 'Power row saved — check the sheet now. Trying a quick GPS fix...';
    case 'logging_gps':
      return 'Trying a quick GPS fix for GPS_Log...';
    case 'checking_signal':
      return 'Checking modem/SIM/network registration...';
    case 'checking_gps':
      return 'Checking GPS fix...';
    case 'ota_rebooting':
      return 'Rebooting to run OTA before BLE starts...';
    case 'ota_started':
      return 'Checking GitHub for firmware updates...';
    case 'starting_wifi':
      return 'Switching to Wi-Fi console mode...';
    case 'rebooting':
      return 'Rebooting Pico...';
    default:
      return result;
  }
}

// These intentionally reboot the Pico -- BLE disconnecting shortly after
// sending them is EXPECTED (a successful outcome), not a failure/hang.
const RESET_COMMANDS = new Set(['reboot', 'wifi', 'ota']);

// Expands the compact command_result strings ble_service.py sends into a
// clearer sentence + icon. Covers every shape handle_command()/
// _maybe_auto_log() actually produce (refreshed, rebooting, starting_wifi,
// ota_current/updated/failed, logged/auto_logged (power: ..., gps: ...),
// log_failed, signal: ...(...), gps: fix/no_fix (...), *_failed,
// unknown_command) -- falls back to showing the raw text with a generic icon
// for anything else.
function friendlyCommandResult(result) {
  if (!result) return { icon: '⚪', text: 'No command sent yet.', danger: false };

  const parsePowerGps = (inner) => {
    const parts = {};
    inner.split(',').forEach((part) => {
      const idx = part.indexOf(':');
      if (idx === -1) return;
      const key = part.slice(0, idx).trim();
      const value = part.slice(idx + 1).trim();
      if (key) parts[key] = value;
    });
    const powerOk = parts.power === 'ok';
    const gpsOk = parts.gps === 'ok';
    const gpsNoFix = parts.gps === 'no_fix';
    const gpsText = gpsOk
      ? 'GPS logged a fix.'
      : gpsNoFix
        ? 'GPS: no fix (normal without a GPS antenna).'
        : `GPS: ${parts.gps || 'unknown'}`;
    const powerText = powerOk
      ? 'Internet and Google Sheets confirmed. Power logged (see Power_Log uplink on sheet).'
      : `Power: ${parts.power || 'unknown'}.`;
    return { icon: powerOk ? '✅' : '⚠️', text: `${powerText} ${gpsText}`, danger: !powerOk };
  };

  let match = result.match(/^logged \((.*)\)$/);
  if (match) return parsePowerGps(match[1]);

  match = result.match(/^auto_logged \((.*)\)$/);
  if (match) {
    const inner = parsePowerGps(match[1]);
    return { ...inner, text: `Automatic log — ${inner.text}` };
  }

  let gpsMatch = result.match(/^gps:\s*fix\s*\(lat:\s*([^,]+),\s*lon:\s*([^,]+),\s*maps:\s*(.*?)\)$/);
  if (gpsMatch) {
    const lat = gpsMatch[1].trim();
    const lon = gpsMatch[2].trim();
    const link = gpsMatch[3].trim();
    return { icon: '✅', text: `GPS fix confirmed: ${lat}, ${lon}.`, link, danger: false };
  }

  gpsMatch = result.match(/^gps:\s*no_fix\s*\((.*)\)$/);
  if (gpsMatch) {
    return { icon: '⚠️', text: `GPS checked, but no fix yet: ${gpsMatch[1]}.`, danger: false };
  }

  if (result.startsWith('signal: ')) {
    const match = result.match(/^signal:\s*(.*?)\s*\((.*?)\)$/);
    const signal = match ? match[1] : result.replace(/^signal:\s*/, '');
    const registration = match ? match[2] : 'unknown registration';
    const registered = registration === 'registered';
    return {
      icon: registered ? '✅' : '⚠️',
      text: registered
        ? `Cell modem and SIM are registered on the network. Signal: ${signal}. This quick check does not test Google Sheets upload.`
        : `Cell modem responded, but network is ${registration}. Signal: ${signal}. Use Log Now to test internet + Sheets after registration works.`,
      danger: !registered,
    };
  }
  if (result === 'refreshed') return { icon: '✅', text: 'Status refreshed.', danger: false };
  if (result === 'ota_current') return { icon: '✅', text: 'Already on the latest firmware.', danger: false };
  if (result === 'ota_updated') {
    return { icon: '✅', text: 'Firmware updated — Pico is rebooting now.', danger: false };
  }
  if (result === 'ota_rebooting') {
    return { icon: '⏳', text: 'Rebooting to run OTA before BLE starts...', danger: false };
  }
  if (result === 'rebooting') return { icon: '⏳', text: 'Rebooting...', danger: false };
  if (result === 'starting_wifi') return { icon: '⏳', text: 'Switching to Wi-Fi mode...', danger: false };

  if (result.startsWith('ota_failed:')) {
    return { icon: '❌', text: result.replace(/^ota_failed:\s*/, 'OTA check failed: '), danger: true };
  }
  if (result.startsWith('log_failed:')) {
    return { icon: '❌', text: result.replace(/^log_failed:\s*/, 'Log failed: '), danger: true };
  }
  if (result.startsWith('signal_failed:')) {
    return { icon: '❌', text: result.replace(/^signal_failed:\s*/, 'Signal check failed: '), danger: true };
  }
  if (result.startsWith('gps_failed:')) {
    return { icon: '❌', text: result.replace(/^gps_failed:\s*/, 'GPS check failed: '), danger: true };
  }
  if (result.startsWith('auto_log_failed:')) {
    return { icon: '❌', text: result.replace(/^auto_log_failed:\s*/, 'Automatic log failed: '), danger: true };
  }
  if (result.startsWith('unknown_command:')) {
    return { icon: '❌', text: result, danger: true };
  }

  const danger = /fail|error/i.test(result);
  return { icon: danger ? '❌' : 'ℹ️', text: result, danger };
}

export default function App() {
  const deviceRef = useRef(null);
  const monitorSubRef = useRef(null);
  const [scanning, setScanning] = useState(false);
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState(null);
  const [rawStatus, setRawStatus] = useState('');
  const [message, setMessage] = useState('Not connected');
  const [lastUpdated, setLastUpdated] = useState(null);
  const [scanRssi, setScanRssi] = useState(null);
  const [signalStrength, setSignalStrength] = useState(null);
  const [wifiConsoleStatus, setWifiConsoleStatus] = useState('idle'); // idle | checking | reachable | unreachable
  const [wifiConsoleError, setWifiConsoleError] = useState(null);
  const [latestFirmware, setLatestFirmware] = useState(null);
  const [firmwareCheckStatus, setFirmwareCheckStatus] = useState('idle'); // idle | checking | ok | error
  const [firmwareCheckError, setFirmwareCheckError] = useState(null);
  const [pendingCommand, setPendingCommand] = useState(null);
  const [pendingSince, setPendingSince] = useState(null);
  const [pendingElapsedS, setPendingElapsedS] = useState(0);
  const [commandResultAt, setCommandResultAt] = useState(null);
  const lastCommandResultRef = useRef(null);
  const lastFirmwareCheckRef = useRef(null);
  const wifiCheckIdRef = useRef(0);
  const commandBaselineRef = useRef(null);

  function resetWifiConsoleStatus() {
    wifiCheckIdRef.current += 1;
    setWifiConsoleStatus('idle');
    setWifiConsoleError(null);
  }

  // Ticking display while a command is pending -- without this, pressing
  // a button that takes 10-90s (a real cellular round-trip) just shows a
  // static "Sent command: X" with zero further feedback, which is exactly
  // what made this feel like nothing was happening.
  useEffect(() => {
    if (!pendingCommand || !pendingSince) {
      setPendingElapsedS(0);
      return undefined;
    }
    const id = setInterval(() => {
      setPendingElapsedS(Math.round((Date.now() - pendingSince) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [pendingCommand, pendingSince]);

  // Clears the pending state once a REAL (non-placeholder) command_result
  // arrives over BLE -- see IN_PROGRESS_RESULTS. This is what actually
  // resolves "Running Log Now... (14s)" back to a normal result, driven
  // by the Pico's own status notifications rather than a fixed timeout.
  useEffect(() => {
    const result = status?.command_result;
    if (!result) return;

    if (pendingCommand) {
      const baseline = commandBaselineRef.current;
      if (result === baseline) return;
      if (IN_PROGRESS_RESULTS.has(result)) return;

      const label = COMMAND_INFO[pendingCommand]?.label || pendingCommand;
      const friendly = friendlyCommandResult(result);
      lastCommandResultRef.current = result;
      setCommandResultAt(new Date());
      setMessage(`${label} ${friendly.danger ? 'failed' : 'finished'} - see Command Status.`);
      setPendingCommand(null);
      setPendingSince(null);
      return;
    }

    if (result !== lastCommandResultRef.current) {
      lastCommandResultRef.current = result;
      setCommandResultAt(new Date());
    }
  }, [status?.command_result, pendingCommand]);

  async function checkFirmwareUpdate() {
    setFirmwareCheckStatus('checking');
    setFirmwareCheckError(null);
    try {
      const res = await fetchWithTimeout(OTA_MANIFEST_URL, { method: 'GET' }, FIRMWARE_CHECK_TIMEOUT_MS);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const manifest = await res.json();
      const version = String(manifest?.version || '').trim();
      if (!version) throw new Error('manifest missing version');
      setLatestFirmware(version);
      setFirmwareCheckStatus('ok');
    } catch (error) {
      setFirmwareCheckStatus('error');
      setFirmwareCheckError(error?.message || String(error));
    }
  }

  useEffect(() => {
    const fw = status?.fw;
    if (!fw || fw === 'unknown' || lastFirmwareCheckRef.current === fw) return;
    lastFirmwareCheckRef.current = fw;
    checkFirmwareUpdate();
  }, [status?.fw]);

  // Passive BLE scan on the home screen: shows whether the Pico is
  // broadcasting nearby and its signal strength before you ever tap
  // Connect. Only runs when idle (not connected, not mid-connect-scan) --
  // stops immediately once either of those becomes true.
  useEffect(() => {
    if (connected || scanning) return undefined;
    let cancelled = false;
    let mgr = null;
    let windowTimer = null;
    let repeatTimer = null;

    const runWindow = async () => {
      if (cancelled) return;
      try {
        const ble = await import('./bleConnection');
        if (cancelled) return;
        mgr = await ble.getBleManager();
        await ble.waitForPoweredOn(mgr, 5000);
        if (cancelled) return;
        setScanRssi(null);
        ble.startPassiveScan(
          mgr,
          (device) => {
            if (!cancelled && Number.isFinite(device?.rssi)) {
              setScanRssi(device.rssi);
            }
          },
          () => {
            // Passive scanning is best-effort -- ignore scan errors (e.g.
            // Bluetooth toggled off mid-scan) rather than alerting the
            // user for a background check they didn't explicitly ask for.
          },
        );
        windowTimer = setTimeout(() => {
          if (mgr) ble.stopScan(mgr);
        }, PASSIVE_SCAN_WINDOW_MS);
      } catch {
        // Bluetooth not ready/available -- leave scanRssi as-is and try
        // again on the next repeat cycle.
      }
    };

    runWindow();
    repeatTimer = setInterval(runWindow, PASSIVE_SCAN_REPEAT_MS);

    return () => {
      cancelled = true;
      if (windowTimer) clearTimeout(windowTimer);
      if (repeatTimer) clearInterval(repeatTimer);
      if (mgr) {
        import('./bleConnection').then((ble) => ble.stopScan(mgr)).catch(() => {});
      }
    };
  }, [connected, scanning]);

  // Live RSSI while actually connected -- same 2s cadence as the Ballast
  // app, using the already-connected device instead of a fresh scan.
  useEffect(() => {
    if (!connected || !deviceRef.current) return undefined;
    const id = setInterval(async () => {
      try {
        const d = await deviceRef.current.readRSSI();
        const r = typeof d === 'number' ? d : d?.rssi;
        if (Number.isFinite(r)) setSignalStrength(r);
      } catch {
        // Device may have just disconnected -- the onDisconnected handler
        // will clean up state; ignore this one failed read.
      }
    }, LIVE_RSSI_POLL_MS);
    return () => clearInterval(id);
  }, [connected]);

  async function checkWifiConsole() {
    const checkId = wifiCheckIdRef.current + 1;
    wifiCheckIdRef.current = checkId;
    setWifiConsoleStatus('checking');
    setWifiConsoleError(null);
    try {
      const res = await fetchWithTimeout(WIFI_CONSOLE_URL, { method: 'GET' }, WIFI_CHECK_TIMEOUT_MS);
      if (wifiCheckIdRef.current !== checkId) return;
      setWifiConsoleStatus(res.ok ? 'reachable' : 'unreachable');
      if (!res.ok) setWifiConsoleError(`HTTP ${res.status}`);
    } catch (error) {
      if (wifiCheckIdRef.current !== checkId) return;
      setWifiConsoleStatus('unreachable');
      setWifiConsoleError(error?.message || String(error));
    }
  }

  async function openWifiConsole() {
    try {
      await Linking.openURL(WIFI_CONSOLE_URL);
    } catch (error) {
      Alert.alert('Could not open Wi-Fi console', error?.message || String(error));
    }
  }

  function confirmRebootForUpdate() {
    if (!firmwareUpdateNeeded) return;
    Alert.alert(
      'Reboot to update Pico?',
      `Pico firmware is ${picoFirmware || 'unknown'} and GitHub has ${latestFirmware}. The Pico will disconnect, reboot, and run OTA before BLE starts.`,
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Reboot to Update', style: 'destructive', onPress: () => sendCommand('reboot') },
      ],
    );
  }

  async function connect() {
    if (scanning) return;
    setScanning(true);
    setMessage('Scanning for BoatMonitor...');
    resetWifiConsoleStatus();
    setStatus(null);
    setRawStatus('');

    try {
      const ble = await import('./bleConnection');
      const connectedDevice = await ble.scanAndConnect();
      deviceRef.current = connectedDevice;

      connectedDevice.onDisconnected(() => {
        setConnected(false);
        setMessage('Disconnected');
        setLastUpdated(null);
        setSignalStrength(null);
        resetWifiConsoleStatus();
        // A pending "reboot"/"wifi" command causes exactly this disconnect
        // as its expected, successful outcome -- but ANY disconnect ends
        // whatever was pending, since there's no more BLE connection left
        // to receive a final result on.
        setPendingCommand(null);
        setPendingSince(null);
        monitorSubRef.current?.remove?.();
        monitorSubRef.current = null;
        deviceRef.current = null;
      });

      monitorSubRef.current = connectedDevice.monitorCharacteristicForService(
        ble.SERVICE_UUID,
        ble.STATUS_UUID,
        (error, characteristic) => {
          // This runs as a native event callback, outside any surrounding
          // try/catch in connect(). An uncaught throw here (e.g. a bad
          // decode) escapes to RN's global exception handler and aborts
          // the app in release builds instead of surfacing as a normal
          // error -- see the BLE decode crash fixed in 0.1.8/0.1.9.
          try {
            if (error) {
              setMessage(`Notify error: ${error.message}`);
              return;
            }
            const text = ble.decodeBleValue(characteristic?.value);
            setRawStatus(text);
            setLastUpdated(new Date());
            try {
              setStatus(JSON.parse(text));
            } catch {
              setStatus(null);
            }
          } catch (exc) {
            setMessage(`Notify handling failed: ${exc?.message || exc}`);
          }
        },
      );

      const first = await connectedDevice.readCharacteristicForService(ble.SERVICE_UUID, ble.STATUS_UUID);
      const text = ble.decodeBleValue(first.value);
      setRawStatus(text);
      setLastUpdated(new Date());
      try {
        setStatus(JSON.parse(text));
      } catch {
        setStatus(null);
      }
      setConnected(true);
      resetWifiConsoleStatus();
      setMessage(`Connected to ${ble.deviceLabel(connectedDevice) || connectedDevice.id}`);
    } catch (error) {
      setMessage(error.message || String(error));
      Alert.alert('Connection failed', error.message || String(error));
    } finally {
      setScanning(false);
    }
  }

  async function disconnect() {
    try {
      monitorSubRef.current?.remove?.();
      monitorSubRef.current = null;
      const device = deviceRef.current;
      if (device) {
        await device.cancelConnection();
      }
    } catch {
      // Ignore disconnect errors.
    } finally {
      deviceRef.current = null;
      setConnected(false);
      setMessage('Disconnected');
      setLastUpdated(null);
      setSignalStrength(null);
      resetWifiConsoleStatus();
      setPendingCommand(null);
      setPendingSince(null);
      import('./bleConnection').then((m) => m.destroyBleManager()).catch(() => {});
    }
  }

  async function sendCommand(cmd) {
    const device = deviceRef.current;
    if (!device) {
      Alert.alert('Not connected', 'Connect to BoatMonitor first.');
      return;
    }
    if (pendingCommand) {
      // Refuse to overlap commands from the app side -- the Pico handles
      // BLE commands one at a time, and stacking a second write while a
      // long cellular round-trip is still in progress would just produce
      // confusing, racy command_result updates.
      return;
    }

    const label = COMMAND_INFO[cmd]?.label || cmd;
    commandBaselineRef.current = status?.command_result ?? null;
    setCommandResultAt(null);
    setPendingCommand(cmd);
    setPendingSince(Date.now());
    if (RESET_COMMANDS.has(cmd)) resetWifiConsoleStatus();

    try {
      const ble = await import('./bleConnection');
      const payload = ble.encodeBleCommand(cmd);
      await device.writeCharacteristicWithResponseForService(ble.SERVICE_UUID, ble.COMMAND_UUID, payload);
      setMessage(
        RESET_COMMANDS.has(cmd)
          ? `${label} sent — Pico will reboot and disconnect shortly (expected).`
          : `${label} command sent to Pico.`,
      );
    } catch (error) {
      setPendingCommand(null);
      setPendingSince(null);
      Alert.alert('Command failed', error.message || String(error));
    }
  }

  const inputs = status?.inputs || {};
  const mode = status?.mode || '--';
  const liveCommandResult = status?.command_result;
  const pendingStage =
    pendingCommand &&
    liveCommandResult &&
    liveCommandResult !== commandBaselineRef.current &&
    IN_PROGRESS_RESULTS.has(liveCommandResult)
      ? inProgressStageText(liveCommandResult)
      : null;
  const friendlyResult = friendlyCommandResult(
    pendingCommand ? null : status?.command_result,
  );

  const activeRssi = connected ? signalStrength : scanRssi;
  const bleQuality = signalQualityFor(activeRssi);
  const bleBroadcasting = connected || Number.isFinite(scanRssi);
  const wifiConsoleText =
    wifiConsoleStatus === 'checking'
      ? 'Checking...'
      : wifiConsoleStatus === 'reachable'
        ? 'Open 192.168.4.1'
        : wifiConsoleStatus === 'unreachable'
          ? `Not reachable${wifiConsoleError ? ` (${wifiConsoleError})` : ''}`
          : 'Not checked yet';
  const picoFirmware = status?.fw || null;
  const firmwareUpdateNeeded = !!latestFirmware && !!picoFirmware && picoFirmware !== 'unknown' && latestFirmware !== picoFirmware;
  const firmwareText =
    firmwareCheckStatus === 'checking'
      ? 'Checking GitHub...'
      : firmwareCheckStatus === 'error'
        ? `Check failed${firmwareCheckError ? ` (${firmwareCheckError})` : ''}`
        : latestFirmware
          ? firmwareUpdateNeeded
            ? `Update available: ${latestFirmware}`
            : `Current (${latestFirmware})`
          : 'Not checked yet';

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Boat Monitor</Text>
      </View>
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.topConnectRow}>
          <View style={styles.buttonRowInner}>
            <TouchableOpacity style={styles.primaryButton} onPress={connected ? disconnect : connect} disabled={scanning}>
              {scanning ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <Text style={styles.buttonText}>{connected ? 'Disconnect' : 'Connect BLE'}</Text>
              )}
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.secondaryButton}
              onPress={() => sendCommand('refresh')}
              disabled={!connected || !!pendingCommand}
            >
              {pendingCommand === 'refresh' ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <Text style={styles.buttonText}>Refresh</Text>
              )}
            </TouchableOpacity>
          </View>
          <View style={styles.topSignalBlock}>
            <Text style={styles.signalBarsCompact}>{bleBroadcasting ? bleQuality.bars : '○○○○○'}</Text>
            <Text style={styles.signalRssiCompact}>
              {Number.isFinite(activeRssi) ? `${activeRssi}` : '—'}
            </Text>
            <Text style={styles.signalCaptionInline}>{bleBroadcasting ? bleQuality.text : 'No BLE'}</Text>
          </View>
        </View>

        <View style={styles.bleBanner}>
          <Text style={styles.bleBannerText}>
            {bleAvailabilitySummary({ connected, bleBroadcasting, scanning, inputs })}
          </Text>
          <Text style={styles.bleBannerHint}>{remoteFirmwareHint()}</Text>
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Command Status</Text>
          <StatusRow label="App" value={message} danger={!connected && !scanning} />
          {pendingCommand ? (
            <View style={styles.pendingRow}>
              <ActivityIndicator color="#7dd3fc" />
              <View style={styles.pendingCopy}>
                <Text style={styles.pendingText}>
                  Waiting for {COMMAND_INFO[pendingCommand]?.label || pendingCommand}... ({pendingElapsedS}s)
                </Text>
                {pendingStage ? <Text style={styles.stageText}>{pendingStage}</Text> : null}
                <Text style={styles.hint}>
                  Expected: {COMMAND_INFO[pendingCommand]?.hint || 'a few seconds'}.
                  {pendingCommand === 'log' ? ' Uses cellular while you stay connected over BLE.' : ''}
                </Text>
              </View>
            </View>
          ) : (
            <View>
              <Text style={[styles.resultText, friendlyResult.danger ? styles.danger : styles.resultOk]}>
                {friendlyResult.icon} {friendlyResult.text}
              </Text>
              {friendlyResult.link ? (
                <TouchableOpacity onPress={() => Linking.openURL(friendlyResult.link)}>
                  <Text style={[styles.resultText, styles.linkValue]}>Open in Google Maps</Text>
                </TouchableOpacity>
              ) : null}
              <Text style={styles.hint}>
                {commandResultAt
                  ? `Last final result received at ${fmtTime(commandResultAt)}.`
                  : 'Send a service command below to see exactly what is running and how it finished.'}
              </Text>
            </View>
          )}
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Service Commands</Text>
          <ServiceButton
            cmd="log"
            label="Log Now"
            style={styles.logNowButton}
            connected={connected}
            pendingCommand={pendingCommand}
            onPress={sendCommand}
          />
          <View style={styles.serviceGrid}>
            <ServiceButton
              cmd="signal"
              label="Check Signal"
              style={styles.serviceGridButton}
              connected={connected}
              pendingCommand={pendingCommand}
              onPress={sendCommand}
            />
            <ServiceButton
              cmd="gps"
              label="Check GPS"
              style={styles.serviceGridButton}
              connected={connected}
              pendingCommand={pendingCommand}
              onPress={sendCommand}
            />
            <ServiceButton
              cmd="wifi"
              label="Start Wi-Fi"
              style={styles.serviceGridButton}
              connected={connected}
              pendingCommand={pendingCommand}
              onPress={sendCommand}
            />
            <ServiceButton
              cmd="reboot"
              label="Reboot"
              style={[styles.serviceGridButton, styles.dangerButton]}
              connected={connected}
              pendingCommand={pendingCommand}
              onPress={sendCommand}
            />
          </View>
          <Text style={styles.hint}>Log Now posts to Google Sheets over cellular. Firmware update: use Reboot to Update below or sheet cmd_ota.</Text>
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Firmware</Text>
          <StatusRow label="Pico firmware" value={status?.fw || '--'} />
          <StatusRow label="GitHub firmware" value={firmwareText} danger={firmwareUpdateNeeded || firmwareCheckStatus === 'error'} />
          <StatusRow label="Last BLE status" value={fmtTime(lastUpdated)} />
          {picoFirmware ? (
            <TouchableOpacity
              style={[styles.secondaryButton, styles.checkWifiButton]}
              onPress={checkFirmwareUpdate}
              disabled={firmwareCheckStatus === 'checking'}
            >
              {firmwareCheckStatus === 'checking' ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <Text style={styles.buttonText}>Check GitHub Version</Text>
              )}
            </TouchableOpacity>
          ) : null}
          {firmwareUpdateNeeded ? (
            <TouchableOpacity
              style={[styles.dangerButton, styles.checkWifiButton]}
              onPress={confirmRebootForUpdate}
              disabled={!connected || !!pendingCommand}
            >
              <Text style={styles.buttonText}>Reboot to Update Pico</Text>
            </TouchableOpacity>
          ) : null}
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Boat Status</Text>
          <StatusRow label="Mode" value={mode} danger={mode === 'switch_on_key_off' || mode === 'float_alert'} />
          <StatusRow label="Engine" value={`${fmtMetric(status?.engine, 'v')} V  ${fmtMetric(status?.engine, 'a', 3)} A`} />
          <StatusRow label="House" value={`${fmtMetric(status?.house, 'v')} V  ${fmtMetric(status?.house, 'a', 3)} A`} />
          <StatusRow label="V50" value={`${fmtMetric(status?.v50, 'v')} V`} />
          <View style={styles.subsectionDivider} />
          <Text style={styles.subsectionTitle}>Inputs</Text>
          <StatusRow label="Switch" value={inputs.switch ? 'ON' : 'off'} danger={inputs.switch && !inputs.key} />
          <StatusRow label="Key" value={inputs.key ? 'ON' : 'off'} />
          <StatusRow label="Mid bilge" value={inputs.mid_bilge ? 'ON' : 'off'} danger={inputs.mid_bilge} />
          <StatusRow label="Aft bilge" value={inputs.aft_bilge ? 'ON' : 'off'} danger={inputs.aft_bilge} />
          <StatusRow label="Mid float" value={inputs.mid_float ? 'ON' : 'off'} danger={inputs.mid_float} />
          <StatusRow label="Aft float" value={inputs.aft_float ? 'ON' : 'off'} danger={inputs.aft_float} />
        </View>

        <View style={[styles.card, styles.cardMuted]}>
          <Text style={styles.cardTitle}>Wi-Fi console (optional)</Text>
          <StatusRow
            label="Console"
            value={wifiConsoleText}
            danger={wifiConsoleStatus === 'unreachable'}
            onPress={wifiConsoleStatus === 'reachable' ? openWifiConsole : null}
          />
          <TouchableOpacity
            style={[styles.secondaryButton, styles.checkWifiButton]}
            onPress={checkWifiConsole}
            disabled={wifiConsoleStatus === 'checking'}
          >
            {wifiConsoleStatus === 'checking' ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <Text style={styles.buttonText}>Check Wi-Fi Console</Text>
            )}
          </TouchableOpacity>
          <Text style={styles.hint}>
            Optional field tool: join the BoatMonitor Wi-Fi AP in iOS Settings, then check console reachability. Normal
            operation uses BLE (app) or automatic Wi-Fi/cellular logging — not this AP.
          </Text>
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Raw BLE</Text>
          <Text style={styles.raw}>{rawStatus || 'No status yet'}</Text>
        </View>

        <Text style={styles.buildLabel}>
          App v{APP_VERSION}
          {status?.fw ? ` · Pico v${status.fw}` : ''} — tap Connect BLE near Pico
        </Text>
      </ScrollView>
    </View>
  );
}

function StatusRow({ label, value, danger, onPress }) {
  const valueStyle = [styles.rowValue, danger ? styles.danger : null, onPress ? styles.linkValue : null];
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      {onPress ? (
        <TouchableOpacity style={styles.rowValueWrap} onPress={onPress}>
          <Text style={valueStyle}>{value}</Text>
        </TouchableOpacity>
      ) : (
        <Text style={valueStyle}>{value}</Text>
      )}
    </View>
  );
}

// Shows a spinner in-place of its own label the moment IT specifically is
// the pending command (immediate feedback right where you tapped), and
// disables every service button while ANY command is pending -- avoids
// stacking overlapping BLE writes while a long cellular round-trip is
// still in progress on the Pico.
function ServiceButton({ cmd, label, style, connected, pendingCommand, onPress }) {
  const isPending = pendingCommand === cmd;
  const disabled = !connected || (!!pendingCommand && !isPending);
  return (
    <TouchableOpacity style={[style, disabled && styles.buttonDisabled]} onPress={() => onPress(cmd)} disabled={disabled}>
      {isPending ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>{label}</Text>}
    </TouchableOpacity>
  );
}

// Pure/no BLE dependency, so this stays a plain local helper instead of
// living in bleConnection.js -- that module is always lazy-loaded here
// (await import('./bleConnection')) to keep app startup crash-safe, and
// this needs to run synchronously during render.
function signalQualityFor(rssi) {
  if (!Number.isFinite(rssi)) return { bars: '○○○○○', text: 'No Signal' };
  if (rssi >= -50) return { bars: '●●●●●', text: 'Excellent' };
  if (rssi >= -60) return { bars: '●●●●○', text: 'Good' };
  if (rssi >= -70) return { bars: '●●●○○', text: 'Fair' };
  if (rssi >= -80) return { bars: '●●○○○', text: 'Weak' };
  return { bars: '●○○○○', text: 'Poor' };
}

function fmtMetric(reading, field, digits = 2) {
  if (!reading?.ok || typeof reading[field] !== 'number') return '--';
  return reading[field].toFixed(digits);
}

// Avoids toLocaleTimeString()/Intl -- Hermes' Intl support has been
// unreliable in this app before (see the base64-js/TextDecoder crashes
// fixed in 0.1.8/0.1.9), so this sticks to plain Date getters.
function fmtTime(date) {
  if (!date) return '--';
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0f172a' },
  header: {
    backgroundColor: '#1e3a5f',
    paddingTop: Platform.OS === 'ios' ? 50 : 16,
    paddingBottom: 14,
    paddingHorizontal: 16,
    alignItems: 'center',
  },
  signalBarsCompact: {
    color: '#7dd3fc',
    fontSize: 11,
    letterSpacing: 0.5,
  },
  signalRssiCompact: {
    color: '#cbd5e1',
    fontSize: 10,
  },
  title: {
    color: '#f8fafc',
    fontSize: 20,
    ...FW600,
  },
  scroll: {
    padding: 18,
    paddingBottom: 40,
  },
  message: {
    color: '#cbd5e1',
    marginBottom: 16,
  },
  buttonRow: {
    flexDirection: 'row',
    marginBottom: 14,
  },
  topConnectRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 14,
  },
  buttonRowInner: {
    flex: 1,
    flexDirection: 'row',
    marginRight: 10,
  },
  topSignalBlock: {
    alignItems: 'center',
    minWidth: 72,
    paddingTop: 2,
  },
  signalCaptionInline: {
    color: '#64748b',
    fontSize: 9,
    marginTop: 2,
    textAlign: 'center',
  },
  buttonRowWrap: {
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  bleBanner: {
    backgroundColor: '#1e293b',
    borderRadius: 10,
    padding: 12,
    marginBottom: 14,
    borderLeftWidth: 3,
    borderLeftColor: '#2563eb',
  },
  bleBannerText: {
    color: '#e2e8f0',
    fontSize: 14,
    lineHeight: 20,
  },
  bleBannerHint: {
    color: '#64748b',
    fontSize: 11,
    lineHeight: 16,
    marginTop: 8,
  },
  logNowButton: {
    backgroundColor: '#2563eb',
    paddingVertical: 14,
    paddingHorizontal: 16,
    borderRadius: 10,
    alignItems: 'center',
    marginBottom: 10,
    width: '100%',
  },
  serviceGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'space-between',
  },
  serviceGridButton: {
    backgroundColor: '#334155',
    paddingVertical: 12,
    paddingHorizontal: 8,
    borderRadius: 10,
    alignItems: 'center',
    width: '48%',
    marginBottom: 10,
  },
  buttonDisabled: {
    opacity: 0.45,
  },
  btnGap: {
    marginLeft: 10,
    marginTop: 10,
  },
  checkWifiButton: {
    marginTop: 10,
  },
  primaryButton: {
    flex: 1,
    backgroundColor: '#2563eb',
    padding: 14,
    borderRadius: 10,
    alignItems: 'center',
    marginRight: 10,
  },
  secondaryButton: {
    backgroundColor: '#334155',
    padding: 14,
    borderRadius: 10,
    alignItems: 'center',
  },
  dangerButton: {
    backgroundColor: '#991b1b',
    padding: 14,
    borderRadius: 10,
    alignItems: 'center',
  },
  buttonText: {
    color: '#fff',
    ...FW500,
  },
  card: {
    backgroundColor: '#1e293b',
    padding: 14,
    borderRadius: 12,
    marginBottom: 14,
  },
  cardMuted: {
    opacity: 0.92,
  },
  subsectionDivider: {
    marginTop: 8,
    marginBottom: 4,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#334155',
  },
  subsectionTitle: {
    color: '#94a3b8',
    fontSize: 14,
    ...FW600,
    marginBottom: 4,
  },
  cardTitle: {
    color: '#f8fafc',
    fontSize: 18,
    ...FW600,
    marginBottom: 10,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 6,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#334155',
  },
  rowLabel: {
    color: '#cbd5e1',
    fontSize: 16,
    flex: 1,
    marginRight: 12,
  },
  rowValue: {
    color: '#f8fafc',
    fontSize: 16,
    textAlign: 'right',
    flexShrink: 1,
  },
  rowValueWrap: {
    flexShrink: 1,
  },
  linkValue: {
    color: '#7dd3fc',
    textDecorationLine: 'underline',
  },
  danger: {
    color: '#fca5a5',
    ...FW600,
  },
  resultText: {
    fontSize: 16,
    ...FW600,
  },
  resultOk: {
    color: '#7dd3fc',
  },
  pendingRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  pendingText: {
    color: '#7dd3fc',
    fontSize: 16,
    ...FW600,
  },
  pendingCopy: {
    flex: 1,
    marginLeft: 10,
  },
  stageText: {
    color: '#cbd5e1',
    fontSize: 14,
    marginTop: 8,
  },
  raw: {
    color: '#cbd5e1',
    fontSize: 12,
  },
  hint: {
    color: '#64748b',
    fontSize: 11,
    marginTop: 10,
  },
  bodyText: {
    color: '#cbd5e1',
    fontSize: 14,
    lineHeight: 20,
  },
  bodyGap: {
    marginTop: 10,
  },
  buildLabel: {
    color: '#64748b',
    fontSize: 11,
    textAlign: 'center',
    marginTop: 8,
    ...FW500,
  },
});
