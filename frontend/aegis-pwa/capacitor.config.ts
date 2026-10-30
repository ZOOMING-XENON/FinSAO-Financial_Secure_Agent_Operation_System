import type { CapacitorConfig } from '@capacitor/cli';

// Native shells for iOS and Android wrap the same dist/ build.
// In the native app there is no same-origin proxy: point VITE_API_BASE at a
// gateway that adds service credentials server-side (see README).
const config: CapacitorConfig = {
  appId: 'com.anda.aegis',
  appName: 'Aegis',
  webDir: 'dist',
  backgroundColor: '#07080f',
  ios: { contentInset: 'never' },
  android: { allowMixedContent: false },
};

export default config;
