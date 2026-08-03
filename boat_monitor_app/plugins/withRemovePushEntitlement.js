/**
 * Removes aps-environment so store builds match provisioning profiles
 * that do not include Push Notifications (this app does not use remote push).
 */
const fs = require('fs');
const path = require('path');

const PROJECT_ROOT = path.join(__dirname, '..');

function loadConfigPlugins() {
  try {
    return require('@expo/config-plugins');
  } catch {
    const tryPaths = [
      path.join(PROJECT_ROOT, 'node_modules', '@expo', 'config-plugins'),
      path.join(
        PROJECT_ROOT,
        'node_modules',
        'expo',
        'node_modules',
        '@expo',
        'config-plugins',
      ),
    ];
    for (const dir of tryPaths) {
      if (fs.existsSync(path.join(dir, 'package.json'))) {
        return require(dir);
      }
    }
    throw new Error(
      '[withRemovePushEntitlement] Could not load @expo/config-plugins. Run: npm install',
    );
  }
}

const { withEntitlementsPlist } = loadConfigPlugins();

module.exports = function withRemovePushEntitlement(config) {
  return withEntitlementsPlist(config, (cfg) => {
    if (cfg.modResults && cfg.modResults['aps-environment'] !== undefined) {
      delete cfg.modResults['aps-environment'];
    }
    return cfg;
  });
};
