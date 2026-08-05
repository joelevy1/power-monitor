import struct
import time
import bluetooth
import machine
import micropython
from machine import I2C, Pin
from micropython import const

try:
    import ujson as json
except ImportError:
    import json

try:
    import version
except ImportError:
    version = None

import config as cfg


_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)

_FLAG_READ = const(0x0002)
_FLAG_WRITE = const(0x0008)
_FLAG_NOTIFY = const(0x0010)

SERVICE_UUID = bluetooth.UUID("7e400001-b5a3-f393-e0a9-e50e24dcca9e")
STATUS_UUID = bluetooth.UUID("7e400002-b5a3-f393-e0a9-e50e24dcca9e")
COMMAND_UUID = bluetooth.UUID("7e400003-b5a3-f393-e0a9-e50e24dcca9e")


class INA260:
    REG_CURRENT = 0x01
    REG_VOLTAGE = 0x02
    REG_POWER = 0x03

    def __init__(self, i2c, address=0x40):
        self.i2c = i2c
        self.addr = address

    def _read16(self, reg):
        data = self.i2c.readfrom_mem(self.addr, reg, 2)
        raw = (data[0] << 8) | data[1]
        if raw > 32767:
            raw -= 65536
        return raw

    def voltage_v(self):
        return self._read16(self.REG_VOLTAGE) * 1.25 / 1000

    def current_a(self):
        return self._read16(self.REG_CURRENT) * 1.25 / 1000

    def power_w(self):
        raw = self._read16(self.REG_POWER)
        if raw < 0:
            raw = (raw + 65536) % 65536
        return raw * 10 / 1000


class INA219:
    def __init__(self, i2c, address=0x40):
        self.i2c = i2c
        self.addr = address
        self._write(0x00, 0x399F)
        self._write(0x05, 4096)

    def _write(self, reg, value):
        self.i2c.writeto_mem(self.addr, reg, value.to_bytes(2, "big"))

    def _read(self, reg):
        return int.from_bytes(self.i2c.readfrom_mem(self.addr, reg, 2), "big")

    def voltage_v(self):
        return (self._read(0x02) >> 3) * 0.004

    def current_a(self):
        raw = self._read(0x04)
        if raw > 32767:
            raw -= 65536
        return abs(raw * 0.1) / 1000


def i2c_bus(sda, scl, bus_id):
    return I2C(bus_id, sda=Pin(sda), scl=Pin(scl), freq=100000)


def read_ina260(sda, scl, bus_id, addr):
    try:
        sensor = INA260(i2c_bus(sda, scl, bus_id), addr)
        return {
            "v": round(sensor.voltage_v(), 3),
            "a": round(sensor.current_a(), 4),
            "w": round(sensor.power_w(), 3),
            "ok": True,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def read_v50():
    try:
        sensor = INA219(i2c_bus(cfg.I2C_V50_SDA, cfg.I2C_V50_SCL, 0), cfg.INA219_V50_ADDR)
        return {
            "v": round(sensor.voltage_v(), 3),
            "a": round(sensor.current_a(), 4),
            "ok": True,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def input_on(gpio):
    return Pin(gpio, Pin.IN, Pin.PULL_UP).value() == 0


def current_mode(inputs):
    if inputs["key"]:
        return "key_on"
    if inputs["switch"]:
        return "switch_on_key_off"
    if inputs["mid_float"] or inputs["aft_float"]:
        return "float_alert"
    if inputs["mid_bilge"] or inputs["aft_bilge"]:
        return "bilge_active"
    return "docked_off"


def read_status(command_result=None):
    inputs = {
        "switch": input_on(cfg.PIN_BATTERY_SWITCH),
        "key": input_on(cfg.PIN_KEY),
        "mid_bilge": input_on(cfg.PIN_BILGE_MID),
        "aft_bilge": input_on(cfg.PIN_BILGE_AFT),
        "mid_float": input_on(cfg.PIN_FLOAT_MID),
        "aft_float": input_on(cfg.PIN_FLOAT_AFT),
    }

    status = {
        "device": "boat-p2",
        "fw": getattr(version, "VERSION", "unknown") if version else "unknown",
        "mode": current_mode(inputs),
        "engine": read_ina260(cfg.I2C_ENGINE_SDA, cfg.I2C_ENGINE_SCL, 0, cfg.INA260_ENGINE_ADDR),
        "house": read_ina260(cfg.I2C_HOUSE_SDA, cfg.I2C_HOUSE_SCL, 1, cfg.INA260_HOUSE_ADDR),
        "v50": read_v50(),
        "inputs": inputs,
        "note": "negative current means solar charging",
    }

    if command_result:
        status["command_result"] = command_result

    return status


def ensure_wifi_off():
    """Pico W: CYW43439 cannot reliably advertise BLE while WiFi STA/AP is active
    (shared radio). Same fix applied on the Ballast Monitor Pico firmware.

    If WiFi was actually active (e.g. left over from field_console.py in a
    prior session that was only *soft*-rebooted, not power-cycled), give the
    radio a moment to settle before any BLE HCI command runs — otherwise
    ble.active(True) / gatts_register_services can raise OSError ETIMEDOUT
    waiting on a co-processor that's still mid-transition. A soft reboot
    (Ctrl-D in Thonny) does not reset this hardware state; only a real power
    cycle reliably does, which is why this alone is a mitigation, not a fix.
    """
    try:
        import network
    except ImportError:
        return

    disabled_any = False
    for label, iface in (("STA", network.STA_IF), ("AP", network.AP_IF)):
        try:
            wlan = network.WLAN(iface)
            if wlan.active():
                wlan.active(False)
                disabled_any = True
                print("WiFi %s disabled for BLE" % label)
        except Exception as exc:
            print("WiFi %s off: %s" % (label, exc))

    if disabled_any:
        time.sleep_ms(250)


def advertising_payload(name=None, service_uuid=None):
    """Build one AD packet (max 31 bytes). Raises ValueError if too long.

    Legacy BLE advertising PDUs are capped at 31 bytes. Flags (3) + a full
    128-bit service UUID (18) = 21 bytes, leaving no room for the device
    name in the same packet — name (13 bytes) would push the total to 34
    bytes, which silently breaks central-side name/UUID matching (generic
    scanners like LightBlue still show the device since they don't filter
    by name/UUID, which is why they can "see" a device the app can't find).
    Pass name and service_uuid in *separate* calls — one for adv_data
    (service_uuid), one for resp_data (name) — see BoatMonitorBle.__init__.
    """
    payload = bytearray()

    def append(adv_type, value):
        payload.extend(struct.pack("BB", len(value) + 1, adv_type))
        payload.extend(value)

    append(0x01, b"\x06")
    if service_uuid:
        append(0x07, bytes(bluetooth.UUID(service_uuid)))
    if name:
        append(0x09, name.encode())

    if len(payload) > 31:
        raise ValueError("adv payload %d bytes > 31" % len(payload))
    return payload


class BoatMonitorBle:
    def __init__(self):
        ensure_wifi_off()

        self.ble = bluetooth.BLE()
        try:
            self.ble.active(True)
        except OSError as exc:
            print("ERROR: ble.active(True) failed:", exc)
            print("Try a full power cycle (unplug ~10s) -- a soft reboot may not clear radio state.")
            raise

        if not self.ble.active():
            print("ERROR: BLE radio did not activate (ble.active() is False)")
            print("Try a full power cycle (unplug ~10s) -- a soft reboot may not clear radio state.")
            raise OSError("BLE radio did not activate")

        self.ble.irq(self.irq)
        self.connections = set()
        self.command_result = None

        service = (
            SERVICE_UUID,
            (
                (STATUS_UUID, _FLAG_READ | _FLAG_NOTIFY),
                (COMMAND_UUID, _FLAG_WRITE),
            ),
        )

        try:
            ((self.status_handle, self.command_handle),) = self.ble.gatts_register_services((service,))
        except OSError as exc:
            print("ERROR: gatts_register_services failed:", exc)
            print("Try a full power cycle (unplug ~10s) -- a soft reboot may not clear radio state.")
            raise

        try:
            self.payload = advertising_payload(service_uuid="7e400001-b5a3-f393-e0a9-e50e24dcca9e")
            self.scan_resp_payload = advertising_payload(name="BoatMonitor")
        except ValueError as exc:
            print("ERROR: advertising payload:", exc)
            raise

        print(
            "BLE adv payload: %d bytes, scan response: %d bytes (limit 31 each)"
            % (len(self.payload), len(self.scan_resp_payload))
        )
        self.update_status()
        self.advertise()

    def irq(self, event, data):
        # BLE IRQ callbacks must stay quick and must not re-enter the BLE
        # stack or do blocking hardware I/O (I2C reads, JSON work, etc) --
        # doing so can corrupt the stack's internal state and hard-crash the
        # board (seen on-device as Thonny's USB-serial link dying entirely:
        # "ConnectionError: EOF"). micropython.schedule() defers the actual
        # work to run outside the IRQ context, where all of that is safe.
        if event == _IRQ_CENTRAL_CONNECT:
            conn_handle, addr_type, addr = data
            print("BLE connected", conn_handle)
            self.connections.add(conn_handle)
            self._schedule(self._scheduled_update_status, 0)
        elif event == _IRQ_CENTRAL_DISCONNECT:
            conn_handle, addr_type, addr = data
            print("BLE disconnected", conn_handle)
            self.connections.discard(conn_handle)
            self.advertise()
        elif event == _IRQ_GATTS_WRITE:
            conn_handle, value_handle = data
            if value_handle == self.command_handle:
                raw = self.ble.gatts_read(self.command_handle)
                text = raw.decode("utf-8", "ignore").strip()
                self._schedule(self._scheduled_handle_command, text)

    def _schedule(self, fn, arg):
        try:
            micropython.schedule(fn, arg)
        except RuntimeError as exc:
            # Scheduler queue full or nested schedule call -- drop this one
            # rather than crash; the periodic run() loop will still update
            # status on its own 2s cadence.
            print("schedule failed (dropped):", exc)

    def _scheduled_update_status(self, _arg):
        self.update_status()

    def _scheduled_handle_command(self, raw):
        self.handle_command(raw)

    def advertise(self):
        try:
            self.ble.gap_advertise(500000, adv_data=self.payload, resp_data=self.scan_resp_payload)
        except OSError as exc:
            # Don't let a transient radio error crash the whole service — main.py's
            # blanket except would fall back to WiFi mode with no clear diagnostic.
            print("ERROR: gap_advertise failed:", exc)
            return
        print("BLE advertising as BoatMonitor")

    def update_status(self):
        data = json.dumps(read_status(self.command_result)).encode()
        self.ble.gatts_write(self.status_handle, data)
        for conn in self.connections:
            try:
                self.ble.gatts_notify(conn, self.status_handle, data)
            except Exception as exc:
                print("Notify failed:", exc)

    def handle_command(self, raw):
        print("BLE command:", raw)
        try:
            cmd = json.loads(raw).get("cmd", raw)
        except Exception:
            cmd = raw

        if cmd == "refresh":
            self.command_result = "refreshed"
            self.update_status()
        elif cmd == "reboot":
            self.command_result = "rebooting"
            self.update_status()
            time.sleep(0.5)
            machine.reset()
        elif cmd in ("wifi", "start_wifi"):
            with open("wifi_mode.txt", "w") as f:
                f.write("1")
            self.command_result = "starting_wifi"
            self.update_status()
            time.sleep(0.5)
            machine.reset()
        elif cmd in ("ota", "ota_check"):
            self.command_result = "ota_started"
            self.update_status()
            try:
                import ota

                changed = ota.update(reboot=True)
                self.command_result = "ota_updated" if changed else "ota_current"
            except Exception as exc:
                self.command_result = "ota_failed: %s" % exc
            self.update_status()
        else:
            self.command_result = "unknown_command: %s" % cmd
            self.update_status()

    def run(self):
        while True:
            self.update_status()
            time.sleep(2)


def main():
    BoatMonitorBle().run()


if __name__ == "__main__":
    main()
