import bluetooth

ble = bluetooth.BLE()
ble.active(True)

print("BLE active:", ble.active())
