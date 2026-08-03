import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { BleManager } from 'react-native-ble-plx';
import { Buffer } from 'buffer';

global.Buffer = Buffer;

const DEVICE_NAME = 'BoatMonitor';
const SERVICE_UUID = '7e400001-b5a3-f393-e0a9-e50e24dcca9e';
const STATUS_UUID = '7e400002-b5a3-f393-e0a9-e50e24dcca9e';
const COMMAND_UUID = '7e400003-b5a3-f393-e0a9-e50e24dcca9e';

function deviceLabel(device) {
  return String(device?.name || device?.localName || '').trim();
}

function isBoatMonitor(device) {
  if (!device) return false;
  if (deviceLabel(device) === DEVICE_NAME) return true;
  const uuids = device.serviceUUIDs;
  return Array.isArray(uuids) && uuids.some((id) => String(id).toLowerCase() === SERVICE_UUID);
}

function waitForPoweredOn(manager, timeoutMs = 8000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      sub.remove();
      reject(new Error('Bluetooth initialization timed out'));
    }, timeoutMs);

    const sub = manager.onStateChange((state) => {
      if (state === 'PoweredOn') {
        clearTimeout(timer);
        sub.remove();
        resolve();
      } else if (state === 'Unsupported' || state === 'Unauthorized') {
        clearTimeout(timer);
        sub.remove();
        reject(new Error(`Bluetooth is ${state}`));
      }
    }, true);
  });
}

function decodeBleValue(value) {
  if (!value) return '';
  return Buffer.from(value, 'base64').toString('utf8');
}

function StatusRow({ label, value, danger }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={[styles.rowValue, danger && styles.danger]}>{value}</Text>
    </View>
  );
}

function fmtMetric(reading, field, digits = 2) {
  if (!reading?.ok || typeof reading[field] !== 'number') return '--';
  return reading[field].toFixed(digits);
}

export default function App() {
  const manager = useMemo(() => new BleManager(), []);
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
      manager.destroy();
    };
  }, [manager]);

  async function connect() {
    if (scanning) return;
    setScanning(true);
    setMessage('Scanning for BoatMonitor...');
    setStatus(null);
    setRawStatus('');

    try {
      await waitForPoweredOn(manager);
      manager.stopDeviceScan();

      const found = await new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          manager.stopDeviceScan();
          reject(new Error('BoatMonitor not found'));
        }, 12000);

        manager.startDeviceScan(null, null, (error, device) => {
          if (error) {
            clearTimeout(timer);
            manager.stopDeviceScan();
            reject(error);
            return;
          }

          if (isBoatMonitor(device)) {
            clearTimeout(timer);
            manager.stopDeviceScan();
            resolve(device);
          }
        });
      });

      setMessage(`Connecting to ${deviceLabel(found) || found.id}...`);
      const connectedDevice = await found.connect();
      deviceRef.current = connectedDevice;
      await connectedDevice.discoverAllServicesAndCharacteristics();

      connectedDevice.onDisconnected(() => {
        setConnected(false);
        setMessage('Disconnected');
        monitorSubRef.current?.remove?.();
        monitorSubRef.current = null;
        deviceRef.current = null;
      });

      monitorSubRef.current = connectedDevice.monitorCharacteristicForService(
        SERVICE_UUID,
        STATUS_UUID,
        (error, characteristic) => {
          if (error) {
            setMessage(`Notify error: ${error.message}`);
            return;
          }
          const text = decodeBleValue(characteristic?.value);
          setRawStatus(text);
          try {
            setStatus(JSON.parse(text));
          } catch {
            setStatus(null);
          }
        },
      );

      const first = await connectedDevice.readCharacteristicForService(SERVICE_UUID, STATUS_UUID);
      const text = decodeBleValue(first.value);
      setRawStatus(text);
      try {
        setStatus(JSON.parse(text));
      } catch {
        setStatus(null);
      }
      setConnected(true);
      setMessage('Connected');
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
      const payload = Buffer.from(JSON.stringify({ cmd }), 'utf8').toString('base64');
      await device.writeCharacteristicWithResponseForService(SERVICE_UUID, COMMAND_UUID, payload);
      setMessage(`Sent command: ${cmd}`);
    } catch (error) {
      Alert.alert('Command failed', error.message || String(error));
    }
  }

  const inputs = status?.inputs || {};
  const mode = status?.mode || '--';

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar style="light" />
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={styles.title}>Boat Monitor</Text>
        <Text style={styles.message}>{message}</Text>

        <View style={styles.buttonRow}>
          <TouchableOpacity style={styles.primaryButton} onPress={connected ? disconnect : connect} disabled={scanning}>
            {scanning ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>{connected ? 'Disconnect' : 'Connect BLE'}</Text>}
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
            <TouchableOpacity style={styles.secondaryButton} onPress={() => sendCommand('ota')} disabled={!connected}>
              <Text style={styles.buttonText}>OTA</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.dangerButton} onPress={() => sendCommand('reboot')} disabled={!connected}>
              <Text style={styles.buttonText}>Reboot</Text>
            </TouchableOpacity>
          </View>
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Raw BLE</Text>
          <Text style={styles.raw}>{rawStatus || 'No status yet'}</Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: '#0f172a',
  },
  container: {
    padding: 18,
    paddingBottom: 40,
  },
  title: {
    color: '#f8fafc',
    fontSize: 32,
    fontWeight: '700',
    marginBottom: 8,
  },
  message: {
    color: '#cbd5e1',
    marginBottom: 16,
  },
  buttonRow: {
    flexDirection: 'row',
    gap: 10,
    marginBottom: 14,
  },
  buttonRowWrap: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  primaryButton: {
    flex: 1,
    backgroundColor: '#2563eb',
    padding: 14,
    borderRadius: 10,
    alignItems: 'center',
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
    fontWeight: '700',
  },
  card: {
    backgroundColor: '#1e293b',
    padding: 14,
    borderRadius: 12,
    marginBottom: 14,
  },
  cardTitle: {
    color: '#f8fafc',
    fontSize: 20,
    fontWeight: '700',
    marginBottom: 10,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    paddingVertical: 6,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#334155',
  },
  rowLabel: {
    color: '#cbd5e1',
    fontSize: 16,
  },
  rowValue: {
    color: '#f8fafc',
    fontSize: 16,
    textAlign: 'right',
    flexShrink: 1,
  },
  danger: {
    color: '#fca5a5',
    fontWeight: '700',
  },
  raw: {
    color: '#cbd5e1',
    fontFamily: 'Courier',
    fontSize: 12,
  },
});
