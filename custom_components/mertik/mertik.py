"""Mertik Maxitrol WiFi fireplace controller."""

import logging
import socket

_LOGGER = logging.getLogger(__name__)

# Protocol framing
COMMAND_PREFIX = "0233303330333033303830"
STATUS_PREFIXES = ("303030300003", "030300000003")
TCP_PORT = 2000
SOCKET_TIMEOUT = 3
RECV_BUFFER = 1024

# Command payloads (appended to COMMAND_PREFIX)
CMD_STANDBY = "3136303003"
CMD_IGNITE = "314103"
CMD_GUARD_FLAME_OFF = "313003"
CMD_REFRESH_STATUS = "303303"
CMD_AUX_ON = "32303031030a"
CMD_AUX_OFF = "32303030030a"
CMD_LIGHT_ON = "3330303103"
CMD_LIGHT_OFF = "3330303003"
CMD_SET_ECO = "4233303103"
CMD_SET_MANUAL = "423003"
CMD_FLAME_PREFIX = "3136"
CMD_FLAME_SUFFIX = "03"
CMD_BRIGHTNESS_PREFIX = "33304645"
CMD_BRIGHTNESS_SUFFIX = "03"

# Brightness device codes for min/max
BRIGHTNESS_CODE_MAX = "4642"
BRIGHTNESS_CODE_MIN = "3633"

# Flame height hex codes for steps 1-12
FLAME_HEIGHT_STEPS = [
    "3830", "3842", "3937", "4132", "4145", "4239",
    "4335", "4430", "4443", "4537", "4633", "4646",
]

# Status response field offsets (indices into the parsed string after prefix)
# The full string layout after stripping the leading byte:
#   [0:12]   prefix
#   [12:14]  padding
#   [14:16]  flame height (2 hex chars)
#   [16:20]  status bits (4 hex chars)
#   [20:22]  light level (2 hex chars)
#   [22:24]  padding
#   [24:25]  mode
#   [25:30]  padding
#   [30:32]  ambient temperature (2 hex chars)
STATUS_FLAME_HEIGHT = slice(14, 16)
STATUS_BITS = slice(16, 20)
STATUS_LIGHT_LEVEL = slice(20, 22)
STATUS_AMBIENT_TEMP = slice(30, 32)

# Status bit indices (within the binary representation of the 4-char hex status)
BIT_SHUTTING_DOWN = 7
BIT_GUARD_FLAME = 8
BIT_IGNITING = 11
BIT_AUX_ON = 12
BIT_LIGHT_ON = 13

# Flame height threshold: values at or below this mean the fireplace is off
FLAME_OFF_THRESHOLD = 123

# Light level range from the device
DEVICE_LIGHT_MIN = 100
DEVICE_LIGHT_MAX = 251


class Mertik:
    def __init__(self, ip):
        self.ip = ip
        self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client.settimeout(SOCKET_TIMEOUT)
        self.client.connect((self.ip, TCP_PORT))
        self.refresh_status()

    @property
    def is_on(self) -> bool:
        return self.on

    @property
    def is_aux_on(self) -> bool:
        return self._aux_on

    @property
    def is_shutting_down(self) -> bool:
        return self._shutting_down

    @property
    def is_igniting(self) -> bool:
        return self._igniting

    @property
    def ambient_temperature(self) -> float:
        return self._ambient_temperature

    @property
    def is_light_on(self) -> bool:
        return self._light_on

    @property
    def light_brightness(self) -> int:
        return self._light_brightness

    def standBy(self):
        self._send_command(CMD_STANDBY)

    def aux_on(self):
        self._send_command(CMD_AUX_ON)

    def aux_off(self):
        self._send_command(CMD_AUX_OFF)

    def ignite_fireplace(self):
        self._send_command(CMD_IGNITE)

    def refresh_status(self):
        self._send_command(CMD_REFRESH_STATUS)

    def guard_flame_off(self):
        self._send_command(CMD_GUARD_FLAME_OFF)

    def light_on(self):
        self._send_command(CMD_LIGHT_ON)

    def light_off(self):
        self._send_command(CMD_LIGHT_OFF)

    def set_light_brightness(self, brightness) -> None:
        normalized = (brightness - 1) / 254 * 100

        if normalized == 100:
            device_code = BRIGHTNESS_CODE_MAX
        elif normalized == 0:
            device_code = BRIGHTNESS_CODE_MIN
        else:
            level = 36 + round(normalized / 100 * 8)
            if level >= 40:
                level += 1  # Device skips code 40
            device_code = f"{level:02d}{level:02d}"

        self._send_command(f"{CMD_BRIGHTNESS_PREFIX}{device_code}{CMD_BRIGHTNESS_SUFFIX}")

    def set_eco(self):
        self._send_command(CMD_SET_ECO)

    def set_manual(self):
        self._send_command(CMD_SET_MANUAL)

    def get_flame_height(self) -> int:
        return self.flameHeight

    def set_flame_height(self, flame_height) -> None:
        step_code = FLAME_HEIGHT_STEPS[flame_height - 1]
        self._send_command(f"{CMD_FLAME_PREFIX}{step_code}{CMD_FLAME_SUFFIX}")
        self.refresh_status()

    def _hex_to_bin(self, hex_str):
        return format(int(hex_str, 16), "b").zfill(8)

    def _bit_at(self, hex_str, index):
        return self._hex_to_bin(hex_str)[index : index + 1] == "1"

    def _reconnect(self):
        """Create a fresh socket connection to the device."""
        _LOGGER.debug("Reconnecting to %s:%s", self.ip, TCP_PORT)
        self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client.settimeout(SOCKET_TIMEOUT)
        self.client.connect((self.ip, TCP_PORT))

    def _send_command(self, msg):
        payload = bytearray.fromhex(COMMAND_PREFIX + msg)

        try:
            self.client.send(payload)
        except socket.error:
            _LOGGER.warning("Send failed, reconnecting to %s", self.ip)
            self._reconnect()
            self.client.send(payload)

        data = self.client.recv(RECV_BUFFER)
        if len(data) == 0:
            _LOGGER.warning("Empty response, reconnecting to %s", self.ip)
            self._reconnect()
            self.client.send(payload)
            data = self.client.recv(RECV_BUFFER)

        response = data.decode("ascii")[1:]
        if response.startswith(STATUS_PREFIXES):
            self._process_status(response)

    def _process_status(self, status_str):
        raw_flame = int(status_str[STATUS_FLAME_HEIGHT], 16)

        if raw_flame <= FLAME_OFF_THRESHOLD:
            self.flameHeight = 0
            self.on = False
        else:
            self.flameHeight = round(((raw_flame - 128) / 128) * 12) + 1
            self.on = True

        status_bits = status_str[STATUS_BITS]
        self._shutting_down = self._bit_at(status_bits, BIT_SHUTTING_DOWN)
        self._guard_flame_on = self._bit_at(status_bits, BIT_GUARD_FLAME)
        self._igniting = self._bit_at(status_bits, BIT_IGNITING)
        self._aux_on = self._bit_at(status_bits, BIT_AUX_ON)
        self._light_on = self._bit_at(status_bits, BIT_LIGHT_ON)

        raw_light = int(status_str[STATUS_LIGHT_LEVEL], 16)
        self._light_brightness = round(
            ((raw_light - DEVICE_LIGHT_MIN) / (DEVICE_LIGHT_MAX - DEVICE_LIGHT_MIN)) * 255
        )
        if self._light_brightness < 0 or not self._light_on:
            self._light_brightness = 0

        self._ambient_temperature = int(status_str[STATUS_AMBIENT_TEMP], 16) / 10
