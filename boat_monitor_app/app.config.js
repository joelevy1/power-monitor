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
    ios: {
      ...base.ios,
      // Same bundle id as production so EAS internal credentials already on file work.
      bundleIdentifier: base.ios.bundleIdentifier,
    },
  };
};
