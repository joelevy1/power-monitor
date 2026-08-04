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
import appConfig from './app.json';

const FW500 = Platform.OS === 'ios' ? {} : { fontWeight: '500' };
const FW600 = Platform.OS === 'ios' ? {} : { fontWeight: '600' };

const APP_VERSION = appConfig.expo.version || '0.0.0';

export default function App() {
  const deviceRef = useRef(null);
  const monitorSubRef = useRef(null);
  const [scanning, setScanning] = useState(false);
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState(null);
  const [rawStatus, setRawStatus] = useState('');
  const [message, setMessage] = useState('Not connected');

  useEffect(() => {
    return () => {
      monitorSubRef.current?.remove?.();
      import('./bleConnection').then((m) => m.destroyBleManager()).catch(() => {});
    };
  }, []);

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
        monitorSubRef.current?.remove?.();
        monitorSubRef.current = null;
        deviceRef.current = null;
      });

      monitorSubRef.current = connectedDevice.monitorCharacteristicForService(
        ble.SERVICE_UUID,
        ble.STATUS_UUID,
        (error, characteristic) => {
          if (error) {
            setMessage(`Notify error: ${error.message}`);
            return;
          }
          const text = ble.decodeBleValue(characteristic?.value);
          setRawStatus(text);
          try {
            setStatus(JSON.parse(text));
          } catch {
            setStatus(null);
          }
        },
      );

      const first = await connectedDevice.readCharacteristicForService(ble.SERVICE_UUID, ble.STATUS_UUID);
      const text = ble.decodeBleValue(first.value);
      setRawStatus(text);
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
          <Text style={styles.cardTitle}>Status</Text>
          <StatusRow label="Mode" value={mode} danger={mode === 'switch_on_key_off' || mode === 'float_alert'} />
          <StatusRow label="Firmware" value={status?.fw || '--'} />
          <StatusRow label="Engine" value={`${fmtMetric(status?.engine, 'v')} V  ${fmtMetric(status?.engine, 'a', 3)} A`} />
          <StatusRow label="House" value={`${fmtMetric(status?.house, 'v')} V  ${fmtMetric(status?.house, 'a', 3)} A`} />
          <StatusRow label="V50" value={`${fmtMetric(status?.v50, 'v')} V`} />
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
            <TouchableOpacity style={styles.secondaryButton} onPress={() => sendCommand('wifi')} disabled={!connected}>
              <Text style={styles.buttonText}>Start Wi-Fi</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[styles.secondaryButton, styles.btnGap]} onPress={() => sendCommand('ota')} disabled={!connected}>
              <Text style={styles.buttonText}>OTA</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[styles.dangerButton, styles.btnGap]} onPress={() => sendCommand('reboot')} disabled={!connected}>
              <Text style={styles.buttonText}>Reboot</Text>
            </TouchableOpacity>
          </View>
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Raw BLE</Text>
          <Text style={styles.raw}>{rawStatus || 'No status yet'}</Text>
        </View>

        <Text style={styles.buildLabel}>v0.1.5 full — tap Connect BLE near Pico</Text>
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

function fmtMetric(reading, field, digits = 2) {
  if (!reading?.ok || typeof reading[field] !== 'number') return '--';
  return reading[field].toFixed(digits);
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
  raw: {
    color: '#cbd5e1',
    fontSize: 12,
  },
  buildLabel: {
    color: '#64748b',
    fontSize: 11,
    textAlign: 'center',
    marginTop: 8,
    ...FW500,
  },
});
