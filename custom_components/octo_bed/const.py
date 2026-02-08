"""Constants for Octo Bed integration."""

DOMAIN = "octo_bed"

CONF_DEVICE_NAME = "device_name"
CONF_DEVICE_ADDRESS = "device_address"
CONF_DEVICE_NICKNAME = "device_nickname"
CONF_PIN = "pin"
CONF_HEAD_CALIBRATION_SEC = "head_calibration_seconds"
CONF_FEET_CALIBRATION_SEC = "feet_calibration_seconds"

DEFAULT_DEVICE_NAME = "RC2"
DEFAULT_PIN = "0000"
DEFAULT_HEAD_CALIBRATION_SEC = 30.0
DEFAULT_FEET_CALIBRATION_SEC = 30.0

# BLE service and characteristic (same as ESPHome config)
BLE_SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
BLE_CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"

# Command bytes (from your YAML)
CMD_STOP = bytes([0x40, 0x02, 0x73, 0x00, 0x00, 0x0B, 0x40])
CMD_HEAD_UP = bytes([0x40, 0x02, 0x70, 0x00, 0x01, 0x0B, 0x02, 0x40])
CMD_HEAD_DOWN = bytes([0x40, 0x02, 0x71, 0x00, 0x01, 0x0A, 0x02, 0x40])
CMD_FEET_UP = bytes([0x40, 0x02, 0x70, 0x00, 0x01, 0x09, 0x04, 0x40])
CMD_FEET_DOWN = bytes([0x40, 0x02, 0x71, 0x00, 0x01, 0x08, 0x04, 0x40])
CMD_BOTH_UP = bytes([0x40, 0x02, 0x70, 0x00, 0x01, 0x07, 0x06, 0x40])
CMD_BOTH_DOWN = bytes([0x40, 0x02, 0x71, 0x00, 0x01, 0x06, 0x06, 0x40])

# Make device discoverable (same as pressing remote twice after reset). 40 20 72 00 08 d1 ...
CMD_MAKE_DISCOVERABLE = bytes(
    [0x40, 0x20, 0x72, 0x00, 0x08, 0xD1, 0x00, 0x00, 0x10, 0x01, 0x01, 0x01, 0x01, 0x01, 0x40]
)

# Light commands (byte 8: 0x02 = timer/timed, 0x03 = permanent duration per official app)
CMD_LIGHT_ON = bytes(
    [0x40, 0x20, 0x72, 0x00, 0x08, 0xDE, 0x00, 0x01, 0x02, 0x01, 0x01, 0x01, 0x01, 0x01, 0x40]
)
CMD_LIGHT_OFF = bytes(
    [0x40, 0x20, 0x72, 0x00, 0x08, 0xDF, 0x00, 0x01, 0x02, 0x01, 0x01, 0x01, 0x01, 0x00, 0x40]
)
# Permanent duration (from official app: 4020 7200 08DE 0001 0301 0101 0100 40)
CMD_LIGHT_ON_PERMANENT = bytes(
    [0x40, 0x20, 0x72, 0x00, 0x08, 0xDE, 0x00, 0x01, 0x03, 0x01, 0x01, 0x01, 0x01, 0x01, 0x40]
)
CMD_LIGHT_OFF_PERMANENT = bytes(
    [0x40, 0x20, 0x72, 0x00, 0x08, 0xDE, 0x00, 0x01, 0x03, 0x01, 0x01, 0x01, 0x01, 0x00, 0x40]
)

# Keep-alive / validate PIN (4 digits): 40 20 43 00 04 00 + digits + 40
KEEP_ALIVE_PREFIX = bytes([0x40, 0x20, 0x43, 0x00, 0x04, 0x00])
KEEP_ALIVE_SUFFIX = bytes([0x40])

# First-time set PIN (official app / fresh device): 40 20 3c 04 00 04 02 01 + digits + 40
# Bed sends two notifications: first 40 21 3c 04 00 00 1e 40, then 40 21 43 00 01 1a 01 40 (accepted)
SET_PIN_PREFIX = bytes([0x40, 0x20, 0x3C, 0x04, 0x00, 0x04, 0x02, 0x01])

# Bed response on FFE1 after keep-alive: 40 21 ... or 46 21 ... (XX = status)
PIN_RESPONSE_ACCEPTED = 0x1A   # correct PIN
PIN_RESPONSE_REJECTED = 0x18   # wrong PIN
PIN_RESPONSE_REJECTED_ALT = 0x00  # some beds send 46 21 43 80 01 36 00 for wrong PIN
PIN_RESPONSE_STATUS_BYTE_INDEX = 5

# Connection timeout
CONNECT_TIMEOUT = 15.0
WRITE_TIMEOUT = 5.0

# Keep-alive interval (same as YAML keep_connection_alive script)
KEEP_ALIVE_INTERVAL_SEC = 30

# Send movement command this often over a single BLE connection (avoids connect/disconnect stutter)
MOVEMENT_COMMAND_INTERVAL_SEC = 0.25
