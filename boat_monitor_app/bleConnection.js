import { toByteArray, fromByteArray } from 'base64-js';
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

// Hermes (React Native's JS engine) does not implement the Web APIs
// TextDecoder/TextEncoder, so decode/encode UTF-8 manually against the raw
// bytes base64-js already gives us instead of adding a polyfill dependency.
function utf8BytesToString(bytes) {
  let result = '';
  let i = 0;
  while (i < bytes.length) {
    const b1 = bytes[i++];
    if (b1 < 0x80) {
      result += String.fromCharCode(b1);
    } else if (b1 < 0xe0 && i < bytes.length) {
      const b2 = bytes[i++];
      result += String.fromCharCode(((b1 & 0x1f) << 6) | (b2 & 0x3f));
    } else if (b1 < 0xf0 && i + 1 < bytes.length) {
      const b2 = bytes[i++];
      const b3 = bytes[i++];
      result += String.fromCharCode(((b1 & 0x0f) << 12) | ((b2 & 0x3f) << 6) | (b3 & 0x3f));
    } else if (i + 2 < bytes.length) {
      const b2 = bytes[i++];
      const b3 = bytes[i++];
      const b4 = bytes[i++];
      const codepoint =
        ((b1 & 0x07) << 18) | ((b2 & 0x3f) << 12) | ((b3 & 0x3f) << 6) | (b4 & 0x3f);
      result += String.fromCodePoint(codepoint);
    } else {
      // Truncated/invalid sequence at the end of the buffer — skip it rather
      // than throw, so a partial BLE read never crashes the decode step.
      break;
    }
  }
  return result;
}

function stringToUtf8Bytes(str) {
  const bytes = [];
  for (let i = 0; i < str.length; i++) {
    let code = str.codePointAt(i);
    if (code > 0xffff) i++; // consume the low surrogate of the pair
    if (code < 0x80) {
      bytes.push(code);
    } else if (code < 0x800) {
      bytes.push(0xc0 | (code >> 6), 0x80 | (code & 0x3f));
    } else if (code < 0x10000) {
      bytes.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f));
    } else {
      bytes.push(
        0xf0 | (code >> 18),
        0x80 | ((code >> 12) & 0x3f),
        0x80 | ((code >> 6) & 0x3f),
        0x80 | (code & 0x3f),
      );
    }
  }
  return new Uint8Array(bytes);
}

export function decodeBleValue(value) {
  if (!value) return '';
  return utf8BytesToString(toByteArray(value));
}

export function encodeBleCommand(cmd) {
  const bytes = stringToUtf8Bytes(JSON.stringify({ cmd }));
  return fromByteArray(bytes);
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

function safeRemove(sub) {
  try {
    sub?.remove?.();
  } catch (exc) {
    console.warn('subscription remove failed (ignored):', exc?.message || exc);
  }
}

export function waitForPoweredOn(manager, timeoutMs = 8000) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (fn, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      safeRemove(sub);
      fn(value);
    };

    const timer = setTimeout(() => {
      finish(reject, new Error('Bluetooth initialization timed out'));
    }, timeoutMs);

    const sub = manager.onStateChange((state) => {
      try {
        if (state === 'PoweredOn') {
          finish(resolve);
        } else if (state === 'Unsupported' || state === 'Unauthorized') {
          finish(reject, new Error(`Bluetooth is ${state}`));
        }
      } catch (exc) {
        finish(reject, exc);
      }
    }, true);
  });
}

function safeStopScan(manager) {
  // stopDeviceScan can throw synchronously (e.g. BleError if the manager
  // was destroyed or the native bridge is in a bad state). Callbacks below
  // run as their own top-level task (setTimeout / native event callback),
  // so an uncaught throw here has no surrounding try/catch and would crash
  // the app in release builds (RN's ExceptionsManager -> abort()) instead
  // of surfacing as a normal caught rejection.
  try {
    manager.stopDeviceScan();
  } catch (exc) {
    console.warn('stopDeviceScan failed (ignored):', exc?.message || exc);
  }
}

export async function scanAndConnect() {
  const manager = await getBleManager();
  await waitForPoweredOn(manager);
  safeStopScan(manager);

  const found = await new Promise((resolve, reject) => {
    let settled = false;
    const finish = (fn, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      safeStopScan(manager);
      fn(value);
    };

    const timer = setTimeout(() => {
      finish(reject, new Error('BoatMonitor not found'));
    }, 12000);

    try {
      manager.startDeviceScan(null, null, (error, device) => {
        try {
          if (error) {
            finish(reject, error);
            return;
          }
          if (isBoatMonitor(device)) {
            finish(resolve, device);
          }
        } catch (exc) {
          finish(reject, exc);
        }
      });
    } catch (exc) {
      finish(reject, exc);
    }
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
