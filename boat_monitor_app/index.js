import { registerRootComponent } from 'expo';

const variant = process.env.EXPO_PUBLIC_APP_VARIANT || 'full';

if (variant === 'smoke') {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  registerRootComponent(require('./SmokeApp').default);
} else {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  registerRootComponent(require('./AppRoot').default);
}
