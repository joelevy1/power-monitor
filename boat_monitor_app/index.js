import React from 'react';
import { registerRootComponent } from 'expo';
import { StyleSheet, Text, View } from 'react-native';
import App from './App';

class RootErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <View style={styles.fallback}>
          <Text style={styles.fallbackTitle}>Boat Monitor crashed</Text>
          <Text style={styles.fallbackBody}>{String(this.state.error?.message || this.state.error)}</Text>
        </View>
      );
    }
    return this.props.children;
  }
}

const styles = StyleSheet.create({
  fallback: {
    flex: 1,
    justifyContent: 'center',
    padding: 24,
    backgroundColor: '#0f172a',
  },
  fallbackTitle: {
    color: '#f8fafc',
    fontSize: 20,
    marginBottom: 12,
  },
  fallbackBody: {
    color: '#fca5a5',
    fontSize: 14,
  },
});

registerRootComponent(() => (
  <RootErrorBoundary>
    <App />
  </RootErrorBoundary>
));
