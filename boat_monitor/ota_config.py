_BASE = "https://raw.githubusercontent.com/joelevy1/power-monitor/master/boat_monitor/"
OTA_MANIFEST_URL = _BASE + "ota_manifest.json"
OTA_MANIFEST_RAM_URL = OTA_MANIFEST_URL
OTA_MANIFEST_MICRO_URL = _BASE + "ota_manifest.micro.json"
OTA_MANIFEST_FEATURE_URL = _BASE + "ota_manifest.feature.json"

OTA_APN = "iot.t-mobile.com"
OTA_CONTEXT_ID = 1
OTA_SOCKET_PDP_TYPE = 6

# Check GitHub for updates during boot before starting the field console.
# If an update is installed, the Pico reboots once and starts the new files.
AUTO_OTA_ON_BOOT = True
AUTO_OTA_REBOOT_AFTER_UPDATE = True
# Boot must reach standby even if GitHub/cellular is slow (remote hang recovery).
BOOT_OTA_MAX_SECONDS = 420
