import { decode, encode } from 'base64-js';
import { BleManager } from 'react-native-ble-plx';

const DEVICE_NAME = 'BoatMonitor';
const SERVICE_UUID = '7e400001-b5a3-f393-e0a9-e50e24dcca9e';
const STATUS_UUID = '7e400002-b5a3-f393-e0a9-e50e24dcca9e';
const COMMAND_UUID = '7e400003-b5a3-f393-e0a9-e50e24dcca9e';

let managerSingleton = null;

function deviceLabel(device) {
  return String(device?.name || device?.localName || '').trim();
}

export function isBoatMonitor(device) {
  if (!device) return false;
  if (deviceLabel(device) === DEVICE_NAME) return true;
  const uuids = device.serviceUUIDs;
  return Array.isArray(uuids) && uuids.some((id) => String(id).toLowerCase() === SERVICE_UUID);
}

export function decodeBleValue(value) {
  if (!value) return '';
  return new TextDecoder().decode(decode(value));
}

export function encodeBleCommand(cmd) {
  const bytes = new TextEncoder().encode(JSON.stringify({ cmd }));
  return encode(bytes);
}

export async function getBleManager() {
  if (!managerSingleton) {
    managerSingleton = new BleManager();
  }
  return managerSingleton;
}

export async function destroyBleManager() {
  if (managerSingleton) {
    await managerSingleton.destroy();
    managerSingleton = null;
  }
}

export function waitForPoweredOn(manager, timeoutMs = 8000) {
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

export async function scanAndConnect() {
  const manager = await getBleManager();
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

  const connectedDevice = await found.connect();
  await connectedDevice.discoverAllServicesAndCharacteristics();
  return connectedDevice;
}

export {
  SERVICE_UUID,
  STATUS_UUID,
  COMMAND_UUID,
  deviceLabel,
};
