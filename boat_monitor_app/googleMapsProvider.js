import { NativeModules, Platform } from 'react-native';
import Constants from 'expo-constants';

function embeddedGoogleMapsKey() {
  return String(Constants.expoConfig?.extra?.googleMapsApiKey || '').trim();
}

function iosGoogleMapsNativeReady() {
  try {
    const mod = NativeModules.BoatMonitorGoogleMaps;
    if (!mod || typeof mod.isReady !== 'function') {
      return false;
    }
    return mod.isReady() === true;
  } catch {
    return false;
  }
}

/**
 * Google map tiles require native setup. On iOS, PROVIDER_GOOGLE without GMSServices aborts.
 */
export function shouldUseGoogleMapProvider() {
  if (Platform.OS === 'android') {
    return embeddedGoogleMapsKey().length >= 20;
  }
  if (Platform.OS === 'ios') {
    return iosGoogleMapsNativeReady();
  }
  return embeddedGoogleMapsKey().length >= 20;
}
