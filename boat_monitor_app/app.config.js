const appJson = require('./app.json');

const variant = process.env.EXPO_PUBLIC_APP_VARIANT || 'full';
const isSmoke = variant === 'smoke';

/** @type {import('@expo/config').ExpoConfig} */
module.exports = ({ config }) => {
  const base = appJson.expo;
  const plugins = isSmoke
    ? base.plugins.filter((p) => {
        const name = Array.isArray(p) ? p[0] : p;
        return name !== 'react-native-ble-plx';
      })
    : base.plugins;

  return {
    ...config,
    ...base,
    name: isSmoke ? 'Boat Monitor Smoke' : base.name,
    plugins,
    extra: {
      ...(base.extra || {}),
      sheetsScriptUrl: process.env.EXPO_PUBLIC_GOOGLE_APPS_SCRIPT_URL || '',
      sheetsPostToken: process.env.EXPO_PUBLIC_SHEETS_POST_TOKEN || '',
      boatDeviceId: process.env.EXPO_PUBLIC_BOAT_DEVICE_ID || 'boat-p2',
      googleMapsConfigured: !!(
        process.env.GOOGLE_MAPS_API_KEY ||
        process.env.EXPO_PUBLIC_GOOGLE_MAPS_API_KEY
      ),
    },
    ios: {
      ...base.ios,
      bundleIdentifier: base.ios.bundleIdentifier,
      config: {
        googleMapsApiKey:
          process.env.GOOGLE_MAPS_API_KEY || process.env.EXPO_PUBLIC_GOOGLE_MAPS_API_KEY || '',
      },
    },
  };
};
