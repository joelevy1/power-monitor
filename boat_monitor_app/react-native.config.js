/**
 * When EXPO_PUBLIC_APP_VARIANT=smoke, exclude BLE native module from iOS prebuild
 * so we can test "does the app open at all?" without MultiplatformBleAdapter.
 */
const isSmoke = process.env.EXPO_PUBLIC_APP_VARIANT === 'smoke';

module.exports = {
  dependencies: {
    ...(isSmoke
      ? {
          'react-native-ble-plx': {
            platforms: {
              ios: null,
              android: null,
            },
          },
        }
      : {}),
  },
};
