/**
 * Minimal launch screen for isolating native vs JS crashes.
 * Built with EAS profile "smoke" (no react-native-ble-plx native link).
 */
import React from 'react';
import { Platform, Text, View } from 'react-native';

export default function SmokeApp() {
  return (
    <View
      style={{
        flex: 1,
        paddingTop: Platform.OS === 'ios' ? 56 : 24,
        paddingHorizontal: 20,
        backgroundColor: '#0f172a',
        justifyContent: 'center',
      }}
    >
      <Text style={{ color: '#f8fafc', fontSize: 22, marginBottom: 12 }}>Boat Monitor smoke</Text>
      <Text style={{ color: '#94a3b8', fontSize: 15 }}>
        If you see this, the iOS shell opens. Next build adds BLE.
      </Text>
      <Text style={{ color: '#64748b', fontSize: 12, marginTop: 24 }}>variant=smoke</Text>
    </View>
  );
}
