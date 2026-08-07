import { Alert, Platform, Share } from 'react-native';

import { googleMapsUrl, parseGpsCoord } from './GpsMapView';

export function mapsLinkFor(lat, lon, mapsLink) {
  const latitude = parseGpsCoord(lat);
  const longitude = parseGpsCoord(lon);
  if (latitude == null || longitude == null) return null;
  if (mapsLink && String(mapsLink).trim()) return String(mapsLink).trim();
  return googleMapsUrl(latitude, longitude);
}

/**
 * iOS/Android system share sheet — Messages, Mail, AirDrop, copy link, etc.
 */
export async function shareBoatLocation({ lat, lon, mapsLink, title, whenLabel }) {
  const latitude = parseGpsCoord(lat);
  const longitude = parseGpsCoord(lon);
  if (latitude == null || longitude == null) {
    Alert.alert('No location', 'There is no valid GPS coordinate to share yet.');
    return;
  }

  const url = mapsLinkFor(latitude, longitude, mapsLink);
  const coords = `${latitude.toFixed(5)}, ${longitude.toFixed(5)}`;
  const headline = title || 'Boat Monitor';
  const when = whenLabel ? ` (${whenLabel})` : '';
  const message = `${headline} location${when}:\n${coords}\n${url}`;

  try {
    if (Platform.OS === 'ios') {
      await Share.share({ message, url });
    } else {
      await Share.share({ message, title: headline });
    }
  } catch (error) {
    if (error?.message !== 'User did not share') {
      Alert.alert('Share failed', error?.message || String(error));
    }
  }
}
