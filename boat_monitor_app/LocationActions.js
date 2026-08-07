import React from 'react';
import { Linking, Platform, StyleSheet, Text, TouchableOpacity, View } from 'react-native';

import { mapsLinkFor, shareBoatLocation } from './shareLocation';

const FW500 = Platform.OS === 'ios' ? {} : { fontWeight: '500' };

export default function LocationActions({ lat, lon, mapsLink, shareTitle, whenLabel }) {
  const url = mapsLinkFor(lat, lon, mapsLink);
  if (!url) return null;

  return (
    <View style={styles.row}>
      <TouchableOpacity
        style={[styles.button, styles.primary]}
        onPress={() => Linking.openURL(url).catch(() => {})}
        accessibilityRole="button"
      >
        <Text style={styles.buttonText}>Open in Google Maps</Text>
      </TouchableOpacity>
      <TouchableOpacity
        style={[styles.button, styles.secondary]}
        onPress={() => shareBoatLocation({ lat, lon, mapsLink, title: shareTitle, whenLabel })}
        accessibilityRole="button"
      >
        <Text style={styles.buttonText}>Share pin</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 10,
  },
  button: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 10,
    alignItems: 'center',
  },
  primary: {
    backgroundColor: '#334155',
  },
  secondary: {
    backgroundColor: '#2563eb',
  },
  buttonText: {
    color: '#fff',
    fontSize: 14,
    ...FW500,
  },
});
