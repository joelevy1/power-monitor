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
if (!source.includes("'logging_handoff'")) {
  failures.push('Log Now handoff state is missing');
}
if (!source.includes('Log handoff complete — BoatMonitor BLE is back')) {
  failures.push('BLE return detection message is missing');
}
if (!source.includes('Battery readings')) {
  failures.push('battery reading freshness row is missing');
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
if (source.includes('BLE stays connected')) {
  failures.push('obsolete Log Now BLE behavior text remains');
}

if (failures.length) {
  console.error(`BLE UI validation failed:\n- ${failures.join('\n- ')}`);
  process.exit(1);
}

console.log('BLE UI metadata and handoff behavior OK');
