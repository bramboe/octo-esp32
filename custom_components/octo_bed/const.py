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
# Handle 0x0011 - kept for import compatibility; use BLE_CHAR_UUID only (handle fails on Bluetooth proxy)
BLE_CHAR_HANDLE = 0x0011

# Command bytes (from YAML; verified against official app BLE capture)
# head_up, head_down, feet_up, feet_down, both_up, both_down, stop - all match app
CMD_STOP = bytes([0x40, 0x02, 0x73, 0x00, 0x00, 0x0B, 0x40])
CMD_HEAD_UP = bytes([0x40, 0x02, 0x70, 0x00, 0x01, 0x0B, 0x02, 0x40])
CMD_HEAD_DOWN = bytes([0x40, 0x02, 0x71, 0x00, 0x01, 0x0A, 0x02, 0x40])
CMD_FEET_UP = bytes([0x40, 0x02, 0x70, 0x00, 0x01, 0x09, 0x04, 0x40])
CMD_FEET_DOWN = bytes([0x40, 0x02, 0x71, 0x00, 0x01, 0x08, 0x04, 0x40])
CMD_BOTH_UP = bytes([0x40, 0x02, 0x70, 0x00, 0x01, 0x07, 0x06, 0x40])
CMD_BOTH_DOWN = bytes([0x40, 0x02, 0x71, 0x00, 0x01, 0x06, 0x06, 0x40])

# Make device discoverable (40 20 72 00 08 d1 ...). Hub: 2× button = teach remote; 10× = hard reset (hub likely sends a different command, not D1×10).
CMD_MAKE_DISCOVERABLE = bytes(
    [0x40, 0x20, 0x72, 0x00, 0x08, 0xD1, 0x00, 0x00, 0x10, 0x01, 0x01, 0x01, 0x01, 0x01, 0x40]
)

# Soft / low reset (40 20 ae 00 00 b2 40). Does not require re-adding the bed.
CMD_SOFT_RESET = bytes([0x40, 0x20, 0xAE, 0x00, 0x00, 0xB2, 0x40])

# System-command patterns (for send_system_command service; see comments below).
# Short form (7 bytes): 40 20 [OP] 00 00 [CK] 40 — checksum CK = (0x160 - OP) & 0xFF.
#   Known OP: 0x70, 0x71, 0x7F (app init), 0xAE (soft reset). Try e.g. 0x6E–0x72, 0x7E, 0x80, 0xAD, 0xAF.
# 72 family (15 bytes): 40 20 72 00 08 [SUB] 00 00 10 01 01 01 01 01 40.
#   Known SUB: 0xD1 (make discoverable), 0xDE (light on), 0xDF (light off). Try e.g. 0xD0, 0xD2–0xDD.

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

# App init (no PIN): 40 20 7f 00 00 e1 40 — use when device has no PIN set (per capture "No pin given.txt")
CMD_APP_INIT = bytes([0x40, 0x20, 0x7F, 0x00, 0x00, 0xE1, 0x40])

# Keep-alive / validate PIN (4 digits): 40 20 43 00 04 00 + digits + 40 — use when device has PIN (per "Pin given.txt")
KEEP_ALIVE_PREFIX = bytes([0x40, 0x20, 0x43, 0x00, 0x04, 0x00])
KEEP_ALIVE_SUFFIX = bytes([0x40])

# First-time set PIN (official app / fresh device): 40 20 3c 04 00 04 02 01 + digits + 40
# Bed sends two notifications: first 40 21 3c 04 00 00 1e 40, then 40 21 43 00 01 1a 01 40 (accepted)
SET_PIN_PREFIX = bytes([0x40, 0x20, 0x3C, 0x04, 0x00, 0x04, 0x02, 0x01])

# Bed response on FFE1 after keep-alive: 40 21 ... or 46 21 ... (XX = status)
PIN_RESPONSE_ACCEPTED = 0x1A   # correct PIN
PIN_RESPONSE_REJECTED = 0x18   # wrong PIN
PIN_RESPONSE_REJECTED_ALT = 0x00  # some beds send 46 21 43 80 01 36 00 for wrong PIN
PIN_RESPONSE_REJECTED_1B = 0x1B   # wrong PIN: bed sends 40 21 43 00 01 1b 00 40
PIN_RESPONSE_NOT_SET = 0x1F   # no PIN set yet (e.g. after hard reset); bed sends 40 21 3c 01 00 00 1f 40 — cannot control until set_pin is used
PIN_RESPONSE_STATUS_BYTE_INDEX = 5

# Connection timeout per attempt (fast when device responds; retries handle transient failures)
CONNECT_TIMEOUT = 15.0
WRITE_TIMEOUT = 5.0
# Delay after connect before first write (YAML on_connect: "ensure service discovery completes")
DELAY_AFTER_CONNECT_SEC = 1.0
# Longer delay for calibration – Bluetooth proxy needs more time for GATT enumeration
DELAY_AFTER_CONNECT_CALIBRATION_SEC = 2.5
# Minimal delay for movement – connect and send immediately (GATT needs ~0.2s)
DELAY_AFTER_CONNECT_MOVEMENT_SEC = 0.2

# Keep-alive interval (same as YAML keep_connection_alive script)
KEEP_ALIVE_INTERVAL_SEC = 30
# Official app does NOT send keep-alive during movement – only movement command

# Send movement command this often (340ms = matches official app capture both_up_continuously)
MOVEMENT_COMMAND_INTERVAL_SEC = 0.34
# Delay after keep-alive before next command (bed needs brief time to process)
KEEP_ALIVE_DELAY_SEC = 0.05
# Delay after stop before movement (same connection)
DELAY_AFTER_STOP_SAME_CONN_SEC = 0.1
# Debounce cover slider: wait for user to release before starting movement (prevents stuttering)
COVER_DEBOUNCE_SEC = 0.35
# Cooldown after movement: skip BLE status check so connection stays "connected" (device needs recovery time)
COOLDOWN_AFTER_MOVEMENT_SEC = 35.0
