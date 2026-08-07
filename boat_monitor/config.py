# Boat Monitor P2 — pin map (GPIO numbers, not physical header pins)
# Matches AS_BUILT_WIRING.md

# I2C — three separate buses
I2C_ENGINE_SDA, I2C_ENGINE_SCL = 0, 1   # phys 1, 2
I2C_HOUSE_SDA, I2C_HOUSE_SCL = 2, 3     # phys 4, 5
I2C_V50_SDA, I2C_V50_SCL = 4, 5          # phys 6, 7

INA260_ENGINE_ADDR = 0x40
INA260_HOUSE_ADDR = 0x40
INA219_V50_ADDR = 0x40

# TPS2113A
PIN_TPS_STAT = 6    # phys 9
PIN_TPS_VSNS = 11   # phys 15 — drive LOW

# Modem UART1 (crossed: Pico TX→modem RXD)
PIN_UART_TX = 8     # phys 11
PIN_UART_RX = 9     # phys 12
PIN_MODEM_RESET = 10  # phys 14
PIN_MODEM_PWRKEY = 7  # phys 10 — HAT PWR selector pin, active HIGH
MODEM_BAUD = 115200

# Optocoupler outputs — active LOW when boat signal is ON
PIN_BILGE_MID = 26      # phys 31
PIN_BILGE_AFT = 22      # phys 29
PIN_FLOAT_MID = 19      # phys 25
PIN_FLOAT_AFT = 18      # phys 24
PIN_BATTERY_SWITCH = 20  # phys 26
PIN_KEY = 21            # phys 27

# LEDs (active HIGH)
PIN_LED_RED = 13    # phys 17
PIN_LED_GREEN = 15  # phys 20
PIN_LED_BLUE = 14   # phys 19

# Harness wire labels for bench messages (optocoupler INPUT side)
HARNESS_SIGNALS = (
    ("Mid bilge", PIN_BILGE_MID, "Opto Ch1 IN+"),
    ("Aft bilge", PIN_BILGE_AFT, "Opto Ch2 IN+"),
    ("Mid water float", PIN_FLOAT_MID, "Opto Ch3 IN+ (+ house + on float hot)"),
    ("Aft water float", PIN_FLOAT_AFT, "Opto Ch4 IN+ (+ house + on float hot)"),
    ("Battery switch", PIN_BATTERY_SWITCH, "Opto Ch5 IN+ (+ PlusRoc IN+)"),
    ("Key", PIN_KEY, "Opto Ch6 IN+"),
)

# Wi-Fi first; if SSIDs exist but none connect, use SIM7600 when True.
# Empty Wi-Fi list never uses cellular. Set False to fail instead of cell.
ALLOW_CELLULAR_WIFI_FALLBACK = True
