import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Platform,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { describeBoatMode } from './boatMode';
import GpsMapView from './GpsMapView';
import LocationActions from './LocationActions';
import { fetchSheetDashboard, getSheetClientConfig, markV50BankFull } from './sheetDashboard';
import { estimateV50State } from './v50Bank';

const FW600 = Platform.OS === 'ios' ? {} : { fontWeight: '600' };
const FW500 = Platform.OS === 'ios' ? {} : { fontWeight: '500' };

function fmtNum(value, digits = 2) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return n.toFixed(digits);
}

function fmtTimestamp(value) {
  if (!value) return '—';
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
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

function Row({ label, value, danger, onPress }) {
  const valueStyle = [styles.rowValue, danger ? styles.danger : null, onPress ? styles.link : null];
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      {onPress ? (
        <TouchableOpacity onPress={onPress}>
          <Text style={valueStyle}>{value}</Text>
        </TouchableOpacity>
      ) : (
        <Text style={valueStyle}>{value}</Text>
      )}
    </View>
  );
}

export default function AwayScreen({ onBack }) {
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [dashboard, setDashboard] = useState(null);
  const [markingFull, setMarkingFull] = useState(false);

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
    } catch (exc) {
      setError(exc?.message || String(exc));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load(false);
  }, [load]);

  const power = dashboard?.power;
  const gps = dashboard?.gps;
  const modeInfo = describeBoatMode(power?.mode);
  const { deviceId } = getSheetClientConfig();
  const lastPowerAt = power?.timestamp_utc;
  const stale = lastPowerAt && Date.now() - new Date(lastPowerAt).getTime() > 6 * 3600 * 1000;
  const v50 = estimateV50State({
    power,
    powerRecent: dashboard?.power_recent,
    config: dashboard?.config,
  });

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
      ? `${fmtNum(power.v50_v)} V · ${fmtNum(power.v50_a, 3)} A`
      : `${fmtNum(power?.v50_v)} V`;
  const v50PowerLine =
    v50.watts != null ? `~${fmtNum(v50.watts, 1)} W now` : null;
  const v50SocLine =
    v50.percent != null
      ? `~${fmtNum(v50.percent, 0)}% left (since “full”)`
      : v50.needsCapacity
        ? 'Add boat-p2:v50_capacity_wh in Config (Wh, e.g. 256 for River 2)'
        : v50.needsFullAnchor
          ? 'Tap “Bank is 100% full” when charged'
          : null;

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
              label="Last log"
              value={`${fmtTimestamp(lastPowerAt)} (${ageLabel(lastPowerAt)})`}
              danger={stale}
            />
            <Row label="Mode" value={modeInfo.label} danger={modeInfo.danger} />
            {modeInfo.detail ? <Text style={styles.modeDetail}>{modeInfo.detail}</Text> : null}
            <Row label="Engine" value={`${fmtNum(power.engine_v)} V · ${fmtNum(power.engine_a, 3)} A`} />
            <Row label="House" value={`${fmtNum(power.house_v)} V · ${fmtNum(power.house_a, 3)} A`} />
            <Row label="V50 bank" value={v50BankLine} />
            {v50PowerLine ? <Row label="V50 load" value={v50PowerLine} /> : null}
            {v50SocLine ? <Row label="V50 estimate" value={v50SocLine} /> : null}
            <TouchableOpacity
              style={styles.v50Button}
              onPress={onMarkV50Full}
              disabled={markingFull || loading}
              accessibilityRole="button"
            >
              <Text style={styles.v50ButtonText}>
                {markingFull ? 'Saving…' : 'Bank is 100% full'}
              </Text>
            </TouchableOpacity>
            <Text style={styles.v50Hint}>
              Uses Power_Log V/A and Config capacity (Wh). Rough estimate — mark full after a charge.
            </Text>
            <Row label="Firmware" value={power.fw || '—'} />
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
    justifyContent: 'space-between',
    paddingVertical: 6,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#334155',
    gap: 8,
  },
  rowLabel: { color: '#cbd5e1', fontSize: 15, flex: 1 },
  rowValue: { color: '#f8fafc', fontSize: 15, textAlign: 'right', flexShrink: 1 },
  danger: { color: '#fca5a5', ...FW600 },
  link: { color: '#7dd3fc', textDecorationLine: 'underline' },
  linkBlock: { color: '#7dd3fc', marginTop: 10, fontSize: 15, ...FW500 },
  modeDetail: { color: '#94a3b8', fontSize: 13, marginBottom: 6 },
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
  footerHint: { color: '#64748b', fontSize: 11, textAlign: 'center', lineHeight: 16, marginTop: 4 },
});
