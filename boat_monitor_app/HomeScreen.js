import React from 'react';
import { Platform, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import Constants from 'expo-constants';

const FW600 = Platform.OS === 'ios' ? {} : { fontWeight: '600' };
const FW500 = Platform.OS === 'ios' ? {} : { fontWeight: '500' };

const APP_VERSION =
  Constants.expoConfig?.version || Constants.manifest2?.extra?.expoClient?.version || '0.0.0';

export default function HomeScreen({ onOnBoat, onAway }) {
  return (
    <View style={styles.container}>
      <View style={styles.hero}>
        <Text style={styles.title}>Boat Monitor</Text>
        <Text style={styles.subtitle}>How are you checking on the boat today?</Text>
      </View>

      <View style={styles.actions}>
        <TouchableOpacity style={styles.onBoatButton} onPress={onOnBoat} accessibilityRole="button">
          <Text style={styles.onBoatTitle}>I'm on the boat</Text>
          <Text style={styles.onBoatHint}>Connect over Bluetooth to the Pico for live status and commands.</Text>
        </TouchableOpacity>

        <TouchableOpacity style={styles.awayButton} onPress={onAway} accessibilityRole="button">
          <Text style={styles.awayTitle}>I'm away from the boat</Text>
          <Text style={styles.awayHint}>View the latest power, mode, bilge, and events from Google Sheets.</Text>
        </TouchableOpacity>
      </View>

      <Text style={styles.footer}>App v{APP_VERSION}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0f172a',
    paddingHorizontal: 20,
    paddingTop: Platform.OS === 'ios' ? 64 : 32,
    paddingBottom: 28,
  },
  hero: {
    marginBottom: 32,
  },
  title: {
    color: '#f8fafc',
    fontSize: 28,
    ...FW600,
    marginBottom: 8,
  },
  subtitle: {
    color: '#94a3b8',
    fontSize: 16,
    lineHeight: 22,
  },
  actions: {
    flex: 1,
    justifyContent: 'center',
    gap: 16,
  },
  onBoatButton: {
    backgroundColor: '#2563eb',
    borderRadius: 16,
    paddingVertical: 22,
    paddingHorizontal: 20,
  },
  onBoatTitle: {
    color: '#fff',
    fontSize: 20,
    ...FW600,
    marginBottom: 8,
  },
  onBoatHint: {
    color: '#dbeafe',
    fontSize: 14,
    lineHeight: 20,
  },
  awayButton: {
    backgroundColor: '#15803d',
    borderRadius: 16,
    paddingVertical: 22,
    paddingHorizontal: 20,
  },
  awayTitle: {
    color: '#fff',
    fontSize: 20,
    ...FW600,
    marginBottom: 8,
  },
  awayHint: {
    color: '#dcfce7',
    fontSize: 14,
    lineHeight: 20,
  },
  footer: {
    color: '#64748b',
    fontSize: 12,
    textAlign: 'center',
    ...FW500,
  },
});
