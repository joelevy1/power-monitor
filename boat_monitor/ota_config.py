OTA_MANIFEST_URL = (
    "https://raw.githubusercontent.com/joelevy1/power-monitor/"
    "master/boat_monitor/ota_manifest.json"
)

OTA_APN = "iot.t-mobile.com"
OTA_CONTEXT_ID = 1
OTA_SOCKET_PDP_TYPE = 6

# Check GitHub for updates during boot before starting the field console.
# If an update is installed, the Pico reboots once and starts the new files.
AUTO_OTA_ON_BOOT = True
AUTO_OTA_REBOOT_AFTER_UPDATE = True
