function pad2(n) {
  return String(n).padStart(2, '0');
}

function toDate(value) {
  if (!value) return null;
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return d;
}

/** e.g. 6:51 PM or 6:51:03 PM */
export function formatTime12h(date, { seconds = false } = {}) {
  const d = toDate(date);
  if (!d) return '—';
  let hours = d.getHours();
  const ampm = hours >= 12 ? 'PM' : 'AM';
  hours %= 12;
  if (hours === 0) hours = 12;
  const base = seconds
    ? `${hours}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`
    : `${hours}:${pad2(d.getMinutes())}`;
  return `${base} ${ampm}`;
}

/** e.g. 8/7 6:51 PM */
export function formatDateTime12h(value) {
  const d = toDate(value);
  if (!d) return value ? String(value) : '—';
  return `${d.getMonth() + 1}/${d.getDate()} ${formatTime12h(d)}`;
}
