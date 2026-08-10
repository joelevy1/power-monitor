import React, { useState } from 'react';
import AwayErrorBoundary from './AwayErrorBoundary';
import AwayScreen from './AwayScreen';
import BoatBleScreen from './BoatBleScreen';
import HomeScreen from './HomeScreen';

export default function App() {
  const [screen, setScreen] = useState('home');

  if (screen === 'boat') {
    return <BoatBleScreen onBack={() => setScreen('home')} />;
  }
  if (screen === 'away') {
    return (
      <AwayErrorBoundary onBack={() => setScreen('home')}>
        <AwayScreen onBack={() => setScreen('home')} />
      </AwayErrorBoundary>
    );
  }
  return <HomeScreen onOnBoat={() => setScreen('boat')} onAway={() => setScreen('away')} />;
}
