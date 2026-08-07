import React, { useMemo } from 'react';
import { Linking, Platform, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import MapView, { Marker } from 'react-native-maps';

const FW500 = Platform.OS === 'ios' ? {} : { fontWeight: '500' };

export function parseGpsCoord(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  if (n < -180 || n > 180) return null;
  return n;
}

export function googleMapsUrl(lat, lon) {
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${lat},${lon}`)}`;
}

/**
 * Embedded map for the latest sheet GPS fix. On iOS this uses Apple Maps tiles
 * (react-native-maps default). Tap the map or link to open Google Maps app/web.
 */
export default function GpsMapView({ lat, lon, mapsLink, label, timestampLabel }) {
  const latitude = parseGpsCoord(lat);
  const longitude = parseGpsCoord(lon);
  if (latitude == null || longitude == null) {
    return null;
  }

  const region = useMemo(
    () => ({
      latitude,
      longitude,
      latitudeDelta: 0.025,
      longitudeDelta: 0.025,
    }),
    [latitude, longitude],
  );

  const openExternal = () => {
    const url = mapsLink ? String(mapsLink) : googleMapsUrl(latitude, longitude);
    Linking.openURL(url).catch(() => {});
  };

  return (
    <View style={styles.wrap}>
      <TouchableOpacity activeOpacity={0.95} onPress={openExternal} accessibilityRole="button">
        <MapView
          style={styles.map}
          initialRegion={region}
          scrollEnabled={false}
          zoomEnabled={false}
          rotateEnabled={false}
          pitchEnabled={false}
          pointerEvents="none"
        >
          <Marker coordinate={{ latitude, longitude }} title={label || 'Boat'} description={timestampLabel || ''} />
        </MapView>
      </TouchableOpacity>
      <Text style={styles.caption}>
        {Platform.OS === 'ios' ? 'Apple Maps preview' : 'Map preview'} — tap to open in Google Maps
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    marginTop: 4,
    marginBottom: 8,
  },
  map: {
    width: '100%',
    height: 200,
    borderRadius: 10,
    overflow: 'hidden',
  },
  caption: {
    color: '#64748b',
    fontSize: 11,
    marginTop: 8,
    textAlign: 'center',
    ...FW500,
  },
});
