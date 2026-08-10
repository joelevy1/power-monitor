import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import Constants from 'expo-constants';

export default class AwayErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error) {
    console.warn('AwayErrorBoundary', error);
  }

  render() {
    if (this.state.error) {
      const version =
        Constants.expoConfig?.version ||
        Constants.manifest2?.extra?.expoClient?.version ||
        '?';
      const msg = String(this.state.error?.message || this.state.error);
      return (
        <View style={styles.wrap}>
          <Text style={styles.title}>Away screen failed</Text>
          <Text style={styles.version}>App version {version}</Text>
          <Text style={styles.body}>{msg}</Text>
          <Text style={styles.hint}>
            If you see “estimateV50State” or “parseOtaReadiness”, update the app to 0.1.31+ (TestFlight /
            App Store). Build 0.1.32 adds extra hardening.
          </Text>
          <TouchableOpacity style={styles.btn} onPress={() => this.setState({ error: null })}>
            <Text style={styles.btnText}>Try again</Text>
          </TouchableOpacity>
          {this.props.onBack ? (
            <TouchableOpacity style={styles.btnSecondary} onPress={this.props.onBack}>
              <Text style={styles.btnText}>← Home</Text>
            </TouchableOpacity>
          ) : null}
        </View>
      );
    }
    return this.props.children;
  }
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: '#0f172a', padding: 20, justifyContent: 'center' },
  title: { color: '#f87171', fontSize: 20, marginBottom: 8 },
  version: { color: '#94a3b8', fontSize: 13, marginBottom: 12 },
  body: { color: '#e2e8f0', fontSize: 14, lineHeight: 20, marginBottom: 16 },
  hint: { color: '#94a3b8', fontSize: 13, lineHeight: 18, marginBottom: 20 },
  btn: { backgroundColor: '#2563eb', padding: 14, borderRadius: 10, alignItems: 'center', marginBottom: 10 },
  btnSecondary: { backgroundColor: '#334155', padding: 14, borderRadius: 10, alignItems: 'center' },
  btnText: { color: '#fff', fontSize: 16 },
});
