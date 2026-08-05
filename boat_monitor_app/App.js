import React, { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
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

function fetchWithTimeout(url, options, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  return fetch(url, { ...options, signal: controller.signal }).finally(() => clearTimeout(timer));
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
    setWifiConsoleStatus('checking');
    setWifiConsoleError(null);
    try {
      const res = await fetchWithTimeout(WIFI_CONSOLE_URL, { method: 'GET' }, WIFI_CHECK_TIMEOUT_MS);
      setWifiConsoleStatus(res.ok ? 'reachable' : 'unreachable');
      if (!res.ok) setWifiConsoleError(`HTTP ${res.status}`);
    } catch (error) {
      setWifiConsoleStatus('unreachable');
      setWifiConsoleError(error?.message || String(error));
    }
  }

  async function connect() {
    if (scanning) return;
    setScanning(true);
    setMessage('Scanning for BoatMonitor...');
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
      import('./bleConnection').then((m) => m.destroyBleManager()).catch(() => {});
    }
  }

  async function sendCommand(cmd) {
    const device = deviceRef.current;
    if (!device) {
      Alert.alert('Not connected', 'Connect to BoatMonitor first.');
      return;
    }

    try {
      const ble = await import('./bleConnection');
      const payload = ble.encodeBleCommand(cmd);
      await device.writeCharacteristicWithResponseForService(ble.SERVICE_UUID, ble.COMMAND_UUID, payload);
      setMessage(`Sent command: ${cmd}`);
    } catch (error) {
      Alert.alert('Command failed', error.message || String(error));
    }
  }

  const inputs = status?.inputs || {};
  const mode = status?.mode || '--';
  const commandResult = status?.command_result || null;
  const commandResultDanger = /fail|error|unknown_command/i.test(commandResult || '');

  const activeRssi = connected ? signalStrength : scanRssi;
  const bleQuality = signalQualityFor(activeRssi);
  const bleBroadcasting = connected || Number.isFinite(scanRssi);

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Boat Monitor</Text>
      </View>
      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={styles.message}>{message}</Text>

        <View style={styles.buttonRow}>
          <TouchableOpacity style={styles.primaryButton} onPress={connected ? disconnect : connect} disabled={scanning}>
            {scanning ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <Text style={styles.buttonText}>{connected ? 'Disconnect' : 'Connect BLE'}</Text>
            )}
          </TouchableOpacity>
          <TouchableOpacity style={styles.secondaryButton} onPress={() => sendCommand('refresh')} disabled={!connected}>
            <Text style={styles.buttonText}>Refresh</Text>
          </TouchableOpacity>
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Signal</Text>
          <StatusRow
            label="Bluetooth"
            value={bleBroadcasting ? `${bleQuality.bars}  ${bleQuality.text}` : 'Not detected nearby'}
            danger={!bleBroadcasting}
          />
          <StatusRow label="RSSI" value={Number.isFinite(activeRssi) ? `${activeRssi} dBm` : '--'} />
          <StatusRow
            label="Wi-Fi console"
            value={
              wifiConsoleStatus === 'checking'
                ? 'Checking...'
                : wifiConsoleStatus === 'reachable'
                  ? 'Reachable (192.168.4.1)'
                  : wifiConsoleStatus === 'unreachable'
                    ? `Not reachable${wifiConsoleError ? ` (${wifiConsoleError})` : ''}`
                    : 'Not checked yet'
            }
            danger={wifiConsoleStatus === 'unreachable'}
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
            Bluetooth updates automatically -- broadcasting nearby even before you connect, live
            signal once connected. iOS does not let apps scan for nearby Wi-Fi networks, so the
            Wi-Fi console check only works after you have joined the "BoatMonitor" Wi-Fi network
            yourself in iOS Settings (Start Wi-Fi command, or automatic BLE fallback) -- it then
            confirms the console at 192.168.4.1 is actually responding.
          </Text>
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Status</Text>
          <StatusRow label="Mode" value={mode} danger={mode === 'switch_on_key_off' || mode === 'float_alert'} />
          <StatusRow label="Pico firmware" value={status?.fw || '--'} />
          <StatusRow label="Last updated" value={fmtTime(lastUpdated)} />
          <StatusRow label="Engine" value={`${fmtMetric(status?.engine, 'v')} V  ${fmtMetric(status?.engine, 'a', 3)} A`} />
          <StatusRow label="House" value={`${fmtMetric(status?.house, 'v')} V  ${fmtMetric(status?.house, 'a', 3)} A`} />
          <StatusRow label="V50" value={`${fmtMetric(status?.v50, 'v')} V`} />
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Last Result</Text>
          <Text style={[styles.resultText, commandResultDanger ? styles.danger : styles.resultOk]}>
            {commandResult || 'No command sent yet'}
          </Text>
          <Text style={styles.hint}>
            This is the outcome of the last command sent below (e.g. Log Now, OTA, Check Signal) --
            same information Thonny's console would show, surfaced here so a laptop isn't needed.
          </Text>
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Inputs</Text>
          <StatusRow label="Switch" value={inputs.switch ? 'ON' : 'off'} danger={inputs.switch && !inputs.key} />
          <StatusRow label="Key" value={inputs.key ? 'ON' : 'off'} />
          <StatusRow label="Mid bilge" value={inputs.mid_bilge ? 'ON' : 'off'} danger={inputs.mid_bilge} />
          <StatusRow label="Aft bilge" value={inputs.aft_bilge ? 'ON' : 'off'} danger={inputs.aft_bilge} />
          <StatusRow label="Mid float" value={inputs.mid_float ? 'ON' : 'off'} danger={inputs.mid_float} />
          <StatusRow label="Aft float" value={inputs.aft_float ? 'ON' : 'off'} danger={inputs.aft_float} />
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Service Commands</Text>
          <View style={styles.buttonRowWrap}>
            <TouchableOpacity style={styles.secondaryButton} onPress={() => sendCommand('log')} disabled={!connected}>
              <Text style={styles.buttonText}>Log Now</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[styles.secondaryButton, styles.btnGap]} onPress={() => sendCommand('signal')} disabled={!connected}>
              <Text style={styles.buttonText}>Check Signal</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[styles.secondaryButton, styles.btnGap]} onPress={() => sendCommand('wifi')} disabled={!connected}>
              <Text style={styles.buttonText}>Start Wi-Fi</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[styles.secondaryButton, styles.btnGap]} onPress={() => sendCommand('ota')} disabled={!connected}>
              <Text style={styles.buttonText}>OTA</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[styles.dangerButton, styles.btnGap]} onPress={() => sendCommand('reboot')} disabled={!connected}>
              <Text style={styles.buttonText}>Reboot</Text>
            </TouchableOpacity>
          </View>
          <Text style={styles.hint}>
            Log Now posts Power_Log and GPS_Log rows over cellular right now (bypasses Wi-Fi so BLE
            stays connected). Check Signal reports cellular registration + signal strength without
            opening a full data session. See "Last Result" above for the outcome of each.
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

function StatusRow({ label, value, danger }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={[styles.rowValue, danger ? styles.danger : null]}>{value}</Text>
    </View>
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
  buttonRowWrap: {
    flexDirection: 'row',
    flexWrap: 'wrap',
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
  raw: {
    color: '#cbd5e1',
    fontSize: 12,
  },
  hint: {
    color: '#64748b',
    fontSize: 11,
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
