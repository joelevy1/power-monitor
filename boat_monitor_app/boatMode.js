/** Human labels for Power_Log `mode` (from ble_service.current_mode). */

export function describeBoatMode(mode) {
  const m = String(mode || '').trim() || 'unknown';
  switch (m) {
    case 'key_on':
      return { label: 'Key ON (engine / underway)', detail: 'Battery switch and ignition key are on.', danger: false };
    case 'switch_on_key_off':
      return {
        label: 'Switch ON, key OFF',
        detail: 'Master battery switch is on but ignition key is off.',
        danger: true,
      };
    case 'bilge_active':
      return { label: 'Bilge pump running', detail: 'A bilge pump input is active.', danger: true };
    case 'float_alert':
      return { label: 'Water float alert', detail: 'A water float input is active.', danger: true };
    case 'docked_off':
      return { label: 'Docked (switch & key off)', detail: 'Standby logging only.', danger: false };
    default:
      return { label: m, detail: '', danger: false };
  }
}
