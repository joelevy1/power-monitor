const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const app = require(path.join(root, 'app.json')).expo;
const plist = fs.readFileSync(
  path.join(root, 'ios', 'BoatMonitor', 'Info.plist'),
  'utf8',
);

function plistString(key) {
  const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = plist.match(
    new RegExp(`<key>${escaped}</key>\\s*<string>([^<]*)</string>`),
  );
  return match ? match[1] : '';
}

const failures = [];
const nativeVersion = plistString('CFBundleShortVersionString');
if (nativeVersion !== app.version) {
  failures.push(
    `native version ${nativeVersion || '(missing)'} does not match app.json ${app.version}`,
  );
}

for (const key of [
  'NSBluetoothAlwaysUsageDescription',
  'NSLocationWhenInUseUsageDescription',
  'NSLocalNetworkUsageDescription',
]) {
  const configured = app.ios?.infoPlist?.[key];
  const native = plistString(key);
  if (!configured || !native) {
    failures.push(`${key} is missing from app.json or native Info.plist`);
  } else if (native !== configured) {
    failures.push(`${key} differs between app.json and native Info.plist`);
  }
}

if (failures.length) {
  console.error(`iOS metadata validation failed:\n- ${failures.join('\n- ')}`);
  process.exit(1);
}

console.log(`iOS metadata OK (version ${nativeVersion})`);
