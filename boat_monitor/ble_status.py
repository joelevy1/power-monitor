import time
import bluetooth
from machine import I2C, Pin
from micropython import const
import struct
import config as cfg

_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)

_FLAG_READ = const(0x0002)
_FLAG_NOTIFY = const(0x0010)

_SERVICE_UUID = bluetooth.UUID("7e400001-b5a3-f393-e0a9-e50e24dcca9e")
_STATUS_UUID = bluetooth.UUID("7e400002-b5a3-f393-e0a9-e50e24dcca9e")


class INA260:
    REG_CURRENT = 0x01
    REG_VOLTAGE = 0x02

    def __init__(self, i2c, address=0x40):
        self.i2c = i2c
        self.addr = address

    def _read16(self, reg):
        data = self.i2c.readfrom_mem(self.addr, reg, 2)
        raw = (data[0] << 8) | data[1]
        if raw > 32767:
            raw -= 65536
        return raw

    def read_voltage_v(self):
        return self._read16(self.REG_VOLTAGE) * 1.25 / 1000

    def read_current_a(self):
        return self._read16(self.REG_CURRENT) * 1.25 / 1000


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

    def read_bus_voltage_v(self):
        return (self._read(0x02) >> 3) * 0.004


def i2c_bus(sda, scl, bus_id):
    return I2C(bus_id, sda=Pin(sda), scl=Pin(scl), freq=100000)


def read_ina260(sda, scl, bus_id, addr):
    try:
        sensor = INA260(i2c_bus(sda, scl, bus_id), addr)
        return sensor.read_voltage_v(), sensor.read_current_a()
    except Exception:
        return None, None


def read_v50():
    try:
        sensor = INA219(i2c_bus(cfg.I2C_V50_SDA, cfg.I2C_V50_SCL, 0), cfg.INA219_V50_ADDR)
        return sensor.read_bus_voltage_v()
    except Exception:
        return None


def input_on(gpio):
    return Pin(gpio, Pin.IN, Pin.PULL_UP).value() == 0


def fmt_v(value):
    return "--" if value is None else "%.2fV" % value


def fmt_a(value):
    return "--" if value is None else "%.2fA" % value


def status_text():
    ev, ea = read_ina260(cfg.I2C_ENGINE_SDA, cfg.I2C_ENGINE_SCL, 0, cfg.INA260_ENGINE_ADDR)
    hv, ha = read_ina260(cfg.I2C_HOUSE_SDA, cfg.I2C_HOUSE_SCL, 1, cfg.INA260_HOUSE_ADDR)
    v50 = read_v50()

    return (
        "BoatMonitor\n"
        "Engine: %s %s\n"
        "House:  %s %s\n"
        "V50:    %s\n"
        "Switch: %s\n"
        "Key:    %s\n"
        "Mid bilge: %s\n"
        "Aft bilge: %s\n"
        "Mid float: %s\n"
        "Aft float: %s\n"
        "Note: negative A = solar charge"
        % (
            fmt_v(ev),
            fmt_a(ea),
            fmt_v(hv),
            fmt_a(ha),
            fmt_v(v50),
            "ON" if input_on(cfg.PIN_BATTERY_SWITCH) else "off",
            "ON" if input_on(cfg.PIN_KEY) else "off",
            "ON" if input_on(cfg.PIN_BILGE_MID) else "off",
            "ON" if input_on(cfg.PIN_BILGE_AFT) else "off",
            "ON" if input_on(cfg.PIN_FLOAT_MID) else "off",
            "ON" if input_on(cfg.PIN_FLOAT_AFT) else "off",
        )
    )


def adv_payload(name):
    payload = bytearray()

    def append(adv_type, value):
        payload.extend(struct.pack("BB", len(value) + 1, adv_type))
        payload.extend(value)

    append(0x01, b"\x06")
    append(0x09, name.encode())
    return payload


class BLEStatus:
    def __init__(self):
        self.ble = bluetooth.BLE()
        self.ble.active(True)
        self.ble.irq(self.irq)
        self.connections = set()

        service = (
            _SERVICE_UUID,
            ((_STATUS_UUID, _FLAG_READ | _FLAG_NOTIFY),),
        )

        ((self.status_handle,),) = self.ble.gatts_register_services((service,))
        self.payload = adv_payload("BoatMonitor")
        self.update_status()
        self.advertise()

    def irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            conn_handle, addr_type, addr = data
            print("BLE connected", conn_handle)
            self.connections.add(conn_handle)
        elif event == _IRQ_CENTRAL_DISCONNECT:
            conn_handle, addr_type, addr = data
            print("BLE disconnected", conn_handle)
            self.connections.discard(conn_handle)
            self.advertise()

    def advertise(self):
        print("BLE advertising as BoatMonitor")
        self.ble.gap_advertise(500000, adv_data=self.payload)

    def update_status(self):
        data = status_text().encode()
        self.ble.gatts_write(self.status_handle, data)
        for conn in self.connections:
            try:
                self.ble.gatts_notify(conn, self.status_handle, data)
            except Exception as exc:
                print("Notify failed:", exc)

    def run(self):
        while True:
            self.update_status()
            print(status_text())
            time.sleep(2)


def main():
    BLEStatus().run()


if __name__ == "__main__":
    main()
