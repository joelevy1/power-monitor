import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Platform,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { describeBoatMode } from './boatMode';
import { formatDateTime12h } from './dateTimeFormat';
import GpsMapView from './GpsMapView';
import LocationActions from './LocationActions';
import { fetchSheetDashboard, getSheetClientConfig, markV50BankFull } from './sheetDashboard';
import { describeFirmwareStatus, fetchGithubManifestVersion, parseOtaReadiness } from './firmwareStatus';
import { estimateV50State } from './v50Bank';

const EMPTY_V50 = {
  watts: null,
  capacityMah: null,
  mahUsed: null,
  mahRemain: null,
  percent: null,
  needsCapacity: false,
  needsFullAnchor: false,
  source: 'fallback',
};

function safeV50State(args) {
  try {
    return estimateV50State(args);
  } catch (exc) {
    console.warn('estimateV50State failed', exc);
    return EMPTY_V50;
  }
}

function safeOtaReadiness(events, config) {
  try {
    return parseOtaReadiness(events, config);
  } catch (exc) {
    console.warn('parseOtaReadiness failed', exc);
    return { degraded: false, lastOutcome: null, hint: null };
  }
}

const FW600 = Platform.OS === 'ios' ? {} : { fontWeight: '600' };
const FW500 = Platform.OS === 'ios' ? {} : { fontWeight: '500' };

function fmtNum(value, digits = 2) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return n.toFixed(digits);
}

/** Show µA/mA for bench standby loads; full amps when ≥ 10 mA. */
function fmtAmps(amps) {
  const n = Number(amps);
  if (!Number.isFinite(n)) return '—';
  const abs = Math.abs(n);
  if (abs > 0 && abs < 0.01) return `${(n * 1000).toFixed(1)} mA`;
  return `${n.toFixed(3)} A`;
}

function fmtTimestamp(value) {
  return formatDateTime12h(value);
}

function ageLabel(isoOrDate) {
  if (!isoOrDate) return '';
  const d = new Date(isoOrDate);
  if (Number.isNaN(d.getTime())) return '';
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 48) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  return `${days}d ago`;
}

function configIntervalSec(config, mode) {
  const cfg = config || {};
  const onS = Number(cfg.interval_engine_on_s);
  const offS = Number(cfg.interval_engine_off_s);
  const engineOn = mode === 'key_on';
  const chosen = engineOn ? onS : offS;
  if (Number.isFinite(chosen) && chosen >= 60) return chosen;
  return engineOn ? 60 : 300;
}

function fmtIntervalMinutes(sec) {
  if (sec < 60) return `${sec}s`;
  if (sec % 60 === 0) return `${sec / 60} min`;
  return `${Math.round(sec / 60)} min`;
}

function V50RemainBar({ percent, mahRemain, capacityMah }) {
  if (percent == null || !Number.isFinite(percent)) return null;
  const pct = Math.min(100, Math.max(0, percent));
  return (
    <View style={styles.v50BarBlock}>
      <View style={styles.v50BarHeader}>
        <Text style={styles.v50BarLabel}>V50 charge remaining</Text>
        <Text style={styles.v50BarPct}>{fmtNum(pct, 0)}%</Text>
      </View>
      <View style={styles.v50BarTrack} accessibilityRole="progressbar">
        <View style={[styles.v50BarFill, { width: `${pct}%` }]} />
      </View>
      {mahRemain != null && capacityMah != null ? (
        <Text style={styles.v50BarSub}>
          ~{fmtNum(mahRemain, 0)} mAh left · {fmtNum(capacityMah, 0)} mAh rated
        </Text>
      ) : (
        <Text style={styles.v50BarSub}>Estimate from Pico / sheet history</Text>
      )}
    </View>
  );
}

function Row({ label, value, danger, onPress, stacked }) {
  const valueStyle = [
    stacked ? styles.rowValueStacked : styles.rowValue,
    danger ? styles.danger : null,
    onPress ? styles.link : null,
  ];
  const valueWrapStyle = stacked ? styles.rowValueWrapStacked : styles.rowValueWrap;
  const valueNode = onPress ? (
    <TouchableOpacity onPress={onPress} style={valueWrapStyle}>
      <Text style={valueStyle}>{value}</Text>
    </TouchableOpacity>
  ) : (
    <View style={valueWrapStyle}>
      <Text style={valueStyle}>{value}</Text>
    </View>
  );
  if (stacked) {
    return (
      <View style={styles.rowStacked}>
        <Text style={styles.rowLabelStacked}>{label}</Text>
        {valueNode}
      </View>
    );
  }
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      {valueNode}
    </View>
  );
}

export default function AwayScreen({ onBack }) {
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [dashboard, setDashboard] = useState(null);
  const [markingFull, setMarkingFull] = useState(false);
  const [githubFw, setGithubFw] = useState(null);
  const [githubFwError, setGithubFwError] = useState(null);

  const loadGithubFirmware = useCallback(async () => {
    const result = await fetchGithubManifestVersion();
    if (result.ok) {
      setGithubFw(result.version);
      setGithubFwError(null);
    } else {
      setGithubFw(null);
      setGithubFwError(result.error || 'check failed');
    }
  }, []);

  const load = useCallback(async (isRefresh) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      const result = await fetchSheetDashboard();
      if (!result.ok) {
        setError(result.message || result.error || 'Could not load sheet data');
        setDashboard(result.partial || null);
      } else {
        setDashboard(result.data);
      }
      loadGithubFirmware();
    } catch (exc) {
      setError(exc?.message || String(exc));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [loadGithubFirmware]);

  useEffect(() => {
    load(false);
  }, [load]);

  const power = dashboard?.power;
  const gps = dashboard?.gps;
  const modeInfo = describeBoatMode(power?.mode);
  const { deviceId } = getSheetClientConfig();
  const lastPowerAt = power?.timestamp_utc;
  const logAgeMs = lastPowerAt ? Date.now() - new Date(lastPowerAt).getTime() : null;
  const stale = logAgeMs != null && logAgeMs > 6 * 3600 * 1000;
  const expectedIntervalS = power ? configIntervalSec(dashboard?.config, power.mode) : null;
  const logOverdue =
    logAgeMs != null &&
    expectedIntervalS != null &&
    logAgeMs > expectedIntervalS * 1000 * 1.35 + 120000;
  const v50 = safeV50State({
    power,
    powerRecent: dashboard?.power_recent,
    v50Bank: dashboard?.v50_bank,
    config: dashboard?.config,
  });

  const confirmMarkV50Full = () => {
    Alert.alert(
      'Mark V50 bank 100% full?',
      'Writes a new “full” time to sheet Config. The app cannot undo this — only edit Config on the sheet or mark full again after charging.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Mark full',
          style: 'destructive',
          onPress: () => onMarkV50Full(),
        },
      ],
    );
  };

  const onMarkV50Full = async () => {
    setMarkingFull(true);
    try {
      const result = await markV50BankFull();
      if (!result.ok) {
        setError(result.message || result.error || 'Could not save to sheet Config');
      } else {
        await load(true);
      }
    } catch (exc) {
      setError(exc?.message || String(exc));
    } finally {
      setMarkingFull(false);
    }
  };

  const v50BankLine =
    power?.v50_a != null && power.v50_a !== ''
      ? `${fmtNum(power.v50_v)} V · ${fmtAmps(power.v50_a)}`
      : `${fmtNum(power?.v50_v)} V`;
  const v50PowerLine =
    v50.watts != null ? `~${fmtNum(v50.watts, 1)} W now` : null;
  const v50SocLine =
    v50.percent != null
      ? v50.mahRemain != null && v50.capacityMah != null
        ? `${fmtNum(v50.percent, 0)}% · ${fmtNum(v50.mahRemain, 0)} / ${fmtNum(v50.capacityMah, 0)} mAh`
        : `~${fmtNum(v50.percent, 0)}% since full`
      : v50.needsCapacity
        ? 'Set boat-p2:v50_capacity_mah in Config (e.g. 13400)'
        : v50.needsFullAnchor
          ? 'Set “full” anchor after charging (see bottom of screen)'
          : power?.v50_pct_remain == null && power?.v50_mah_used == null
            ? 'Waiting for Pico v50_mah_used on Power_Log (OTA 1.1.37+)'
            : null;

  const minFw = dashboard?.config?.min_fw_version;
  const otaReadiness = safeOtaReadiness(dashboard?.events_recent, dashboard?.config);
  const fwStatus = describeFirmwareStatus(power?.fw, {
    minFw,
    githubFw,
    githubError: githubFwError,
    otaReadiness,
  });

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={onBack} style={styles.backButton} accessibilityRole="button">
          <Text style={styles.backButtonText}>← Home</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Away from boat</Text>
        <Text style={styles.headerSubtitle}>Latest from Google Sheets · {deviceId}</Text>
      </View>

      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => load(true)} tintColor="#7dd3fc" />}
      >
        {loading && !dashboard ? (
          <View style={styles.centered}>
            <ActivityIndicator color="#7dd3fc" size="large" />
            <Text style={styles.loadingText}>Loading sheet data…</Text>
          </View>
        ) : null}

        {error ? (
          <View style={[styles.card, styles.errorCard]}>
            <Text style={styles.errorTitle}>Could not refresh</Text>
            <Text style={styles.errorBody}>{error}</Text>
            <TouchableOpacity style={styles.retryButton} onPress={() => load(false)}>
              <Text style={styles.retryText}>Try again</Text>
            </TouchableOpacity>
          </View>
        ) : null}

        {power ? (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Power snapshot</Text>
            <Row
              label="Last sheet row"
              value={`${fmtTimestamp(lastPowerAt)} (${ageLabel(lastPowerAt)})`}
              danger={stale || logOverdue}
            />
            {expectedIntervalS != null ? (
              <Row
                label="Auto-log target"
                value={`Every ${fmtIntervalMinutes(expectedIntervalS)} (${power.mode || 'mode'})`}
              />
            ) : null}
            {logOverdue ? (
              <Text style={styles.overdueHint}>
                Later than Config suggests — Pico may be stuck (Wi‑Fi/modem), failing uploads, or rebooting.
                Check Events for auto-log / stall lines. Flashing modem LED in standby usually means cellular
                woke (Wi‑Fi miss or hung session); it should go dark after a successful log or watchdog.
              </Text>
            ) : null}
            <Row label="Mode" value={modeInfo.label} danger={modeInfo.danger} />
            {modeInfo.detail ? <Text style={styles.modeDetail}>{modeInfo.detail}</Text> : null}
            <Row label="Engine" value={`${fmtNum(power.engine_v)} V · ${fmtNum(power.engine_a, 3)} A`} />
            <Row label="House" value={`${fmtNum(power.house_v)} V · ${fmtNum(power.house_a, 3)} A`} />
            <Row label="V50 bank" value={v50BankLine} />
            {v50PowerLine ? <Row label="V50 load" value={v50PowerLine} /> : null}
            {v50.percent != null ? (
              <V50RemainBar
                percent={v50.percent}
                mahRemain={v50.mahRemain}
                capacityMah={v50.capacityMah}
              />
            ) : v50SocLine ? (
              <Row label="V50 estimate" value={v50SocLine} stacked />
            ) : null}
            <Text style={styles.v50Hint}>
              Pico tracks cumulative mAh between logs. Charge state updates on each Power_Log row.
            </Text>
            <Row label="Firmware" value={power.fw || '—'} danger={fwStatus.danger} />
            <Row
              label="Firmware status"
              value={
                githubFw == null && !githubFwError && !loading
                  ? `${fwStatus.label} · checking GitHub…`
                  : fwStatus.label
              }
              danger={fwStatus.danger}
            />
            {fwStatus.detail ? <Text style={fwStatus.danger ? styles.overdueHint : styles.modeDetail}>{fwStatus.detail}</Text> : null}
            {minFw ? <Text style={styles.modeDetail}>Sheet min_fw: {String(minFw)}</Text> : null}
            {githubFw ? <Text style={styles.modeDetail}>GitHub manifest: {githubFw}</Text> : null}
            <Row label="Uplink" value={power.uplink || '—'} />
            {power.note ? <Text style={styles.noteText}>{String(power.note)}</Text> : null}
          </View>
        ) : !loading ? (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Power snapshot</Text>
            <Text style={styles.emptyText}>No Power_Log rows yet for this device.</Text>
          </View>
        ) : null}

        {gps ? (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Latest GPS</Text>
            <GpsMapView
              lat={gps.lat}
              lon={gps.lon}
              mapsLink={gps.maps_link}
              label="Boat Monitor"
              timestampLabel={fmtTimestamp(gps.timestamp_utc)}
            />
            <Row label="Time" value={fmtTimestamp(gps.timestamp_utc)} />
            <Row label="Position" value={`${fmtNum(gps.lat, 5)}, ${fmtNum(gps.lon, 5)}`} />
            <Row label="Status" value={gps.status || '—'} />
            <LocationActions
              lat={gps.lat}
              lon={gps.lon}
              mapsLink={gps.maps_link}
              shareTitle="Boat Monitor"
              whenLabel={fmtTimestamp(gps.timestamp_utc)}
            />
          </View>
        ) : null}

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Recent bilge</Text>
          {(dashboard?.bilge_recent || []).length === 0 ? (
            <Text style={styles.emptyText}>No Bilge_Log rows yet.</Text>
          ) : (
            dashboard.bilge_recent.map((row, idx) => (
              <View key={`bilge-${idx}`} style={styles.listItem}>
                <Text style={styles.listPrimary}>
                  {row.channel || 'channel'} · {row.state || '—'}
                </Text>
                <Text style={styles.listSecondary}>{fmtTimestamp(row.timestamp_utc)}</Text>
              </View>
            ))
          )}
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Recent events</Text>
          {(dashboard?.events_recent || []).length === 0 ? (
            <Text style={styles.emptyText}>No Events rows yet.</Text>
          ) : (
            dashboard.events_recent.map((row, idx) => (
              <View key={`event-${idx}`} style={styles.listItem}>
                <Text style={styles.listPrimary}>{row.event || 'event'}</Text>
                <Text style={styles.listSecondary}>{row.detail || ''}</Text>
                <Text style={styles.listMeta}>{fmtTimestamp(row.timestamp_utc)}</Text>
              </View>
            ))
          )}
        </View>

        {dashboard?.config && Object.keys(dashboard.config).length > 0 ? (
          <View style={[styles.card, styles.cardMuted]}>
            <Text style={styles.cardTitle}>Config (sheet)</Text>
            {Object.entries(dashboard.config)
              .slice(0, 8)
              .map(([key, val]) => (
                <Row key={key} label={key} value={String(val ?? '')} />
              ))}
            <TouchableOpacity
              style={styles.v50MarkLink}
              onPress={confirmMarkV50Full}
              disabled={markingFull || loading}
              accessibilityRole="button"
            >
              <Text style={styles.v50MarkLinkText}>
                {markingFull ? 'Saving…' : 'Mark V50 bank 100% full (Config)'}
              </Text>
            </TouchableOpacity>
            <Text style={styles.v50MarkNote}>
              Rare maintenance action — not a live control. Requires confirmation.
            </Text>
          </View>
        ) : null}

        <Text style={styles.footerHint}>
          V50 % needs Apps Script v5, v50_a in Power_Log, and Config keys. Other alerts can be added later.
        </Text>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0f172a' },
  header: {
    backgroundColor: '#14532d',
    paddingTop: Platform.OS === 'ios' ? 50 : 16,
    paddingBottom: 14,
    paddingHorizontal: 16,
    alignItems: 'center',
  },
  backButton: {
    position: 'absolute',
    left: 16,
    top: Platform.OS === 'ios' ? 52 : 18,
  },
  backButtonText: { color: '#bbf7d0', fontSize: 16, ...FW500 },
  headerTitle: { color: '#f8fafc', fontSize: 20, ...FW600 },
  headerSubtitle: { color: '#86efac', fontSize: 12, marginTop: 4 },
  scroll: { padding: 18, paddingBottom: 40 },
  centered: { alignItems: 'center', paddingVertical: 40 },
  loadingText: { color: '#94a3b8', marginTop: 12 },
  card: {
    backgroundColor: '#1e293b',
    borderRadius: 12,
    padding: 14,
    marginBottom: 14,
  },
  cardMuted: { opacity: 0.95 },
  cardTitle: { color: '#f8fafc', fontSize: 18, ...FW600, marginBottom: 8 },
  row: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    paddingVertical: 6,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#334155',
    gap: 10,
  },
  rowLabel: {
    color: '#cbd5e1',
    fontSize: 15,
    width: 118,
    flexShrink: 0,
    paddingTop: 1,
  },
  rowValueWrap: {
    flex: 1,
    minWidth: 0,
    alignItems: 'flex-end',
  },
  rowStacked: {
    paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#334155',
    gap: 4,
  },
  rowLabelStacked: { color: '#cbd5e1', fontSize: 15 },
  rowValueWrapStacked: { width: '100%' },
  rowValueStacked: { color: '#f8fafc', fontSize: 15, lineHeight: 21 },
  rowValue: { color: '#f8fafc', fontSize: 15, textAlign: 'right', flexShrink: 1 },
  danger: { color: '#fca5a5', ...FW600 },
  link: { color: '#7dd3fc', textDecorationLine: 'underline' },
  linkBlock: { color: '#7dd3fc', marginTop: 10, fontSize: 15, ...FW500 },
  modeDetail: { color: '#94a3b8', fontSize: 13, marginBottom: 6 },
  overdueHint: { color: '#fca5a5', fontSize: 12, lineHeight: 17, marginBottom: 6 },
  noteText: { color: '#64748b', fontSize: 12, marginTop: 8, fontStyle: 'italic' },
  emptyText: { color: '#94a3b8', fontSize: 14 },
  listItem: {
    paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#334155',
  },
  listPrimary: { color: '#e2e8f0', fontSize: 15, ...FW500 },
  listSecondary: { color: '#94a3b8', fontSize: 13, marginTop: 2 },
  listMeta: { color: '#64748b', fontSize: 11, marginTop: 2 },
  errorCard: { borderLeftWidth: 3, borderLeftColor: '#f87171' },
  errorTitle: { color: '#fca5a5', fontSize: 16, ...FW600, marginBottom: 6 },
  errorBody: { color: '#cbd5e1', fontSize: 14, lineHeight: 20 },
  retryButton: {
    marginTop: 12,
    alignSelf: 'flex-start',
    backgroundColor: '#334155',
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderRadius: 8,
  },
  retryText: { color: '#fff', ...FW500 },
  v50Hint: { color: '#94a3b8', fontSize: 12, lineHeight: 17, marginTop: 8, marginBottom: 4 },
  v50BarBlock: { marginTop: 8, marginBottom: 4 },
  v50BarHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 6,
  },
  v50BarLabel: { color: '#cbd5e1', fontSize: 15 },
  v50BarPct: { color: '#f8fafc', fontSize: 17, ...FW600 },
  v50BarTrack: {
    height: 12,
    borderRadius: 6,
    backgroundColor: '#334155',
    overflow: 'hidden',
  },
  v50BarFill: {
    height: '100%',
    borderRadius: 6,
    backgroundColor: '#22c55e',
    minWidth: 2,
  },
  v50BarSub: { color: '#94a3b8', fontSize: 12, marginTop: 6 },
  v50MarkLink: {
    marginTop: 12,
    paddingVertical: 8,
    alignSelf: 'flex-start',
  },
  v50MarkLinkText: { color: '#64748b', fontSize: 13, textDecorationLine: 'underline' },
  v50MarkNote: { color: '#475569', fontSize: 11, lineHeight: 15, marginBottom: 4 },
  footerHint: { color: '#64748b', fontSize: 11, textAlign: 'center', lineHeight: 16, marginTop: 4 },
});
