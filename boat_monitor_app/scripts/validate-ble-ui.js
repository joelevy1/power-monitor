const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'BoatBleScreen.js'),
  'utf8',
);

const failures = [];
if (source.includes('Start Wi-Fi') || source.includes('Wi-Fi console (optional)')) {
  failures.push('obsolete Wi-Fi console UI is still visible');
}
if (source.includes('label="Check Signal"')) {
  failures.push('unsafe synchronous signal command is still visible');
}
if (!source.includes("'logging_handoff'")) {
  failures.push('Log Now handoff state is missing');
}
if (!source.includes('Log complete — BoatMonitor is ready to reconnect')) {
  failures.push('BLE return detection message is missing');
}
if (!source.includes('as of {fmtTime(lastUpdated)}')) {
  failures.push('boat status freshness timestamp is missing');
}
if (!source.includes('Engine solar branch') || !source.includes('House solar branch')) {
  failures.push('solar-only current labels are missing');
}
if (!source.includes('Solar current is not total battery load')) {
  failures.push('solar current scope explanation is missing');
}
if (!source.includes("intentionalHandoffRef.current === 'log'")) {
  failures.push('intentional Log Now disconnect suppression is missing');
}
if (!source.includes('label="Refresh Now"')) {
  failures.push('Refresh is not located with service commands');
}
if (!source.includes("return 'Boat Power On'") || !source.includes("return 'Boat Power Off'")) {
  failures.push('friendly boat power mode labels are missing');
}
if (!source.includes('Quick Reboot Pico') || !source.includes('OTA Check (reboot)')) {
  failures.push('firmware reboot choices are incomplete');
}
if (!source.includes('BoatMonitor BLE detected — waiting briefly')) {
  failures.push('BLE handoff stabilization delay is missing');
}
if (source.includes('BLE stays connected')) {
  failures.push('obsolete Log Now BLE behavior text remains');
}

if (failures.length) {
  console.error(`BLE UI validation failed:\n- ${failures.join('\n- ')}`);
  process.exit(1);
}

console.log('BLE UI metadata and handoff behavior OK');
