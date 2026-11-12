"""Mertik Maxitrol WiFi module: the wire protocol.

Plain Python with no Home Assistant imports, so it can be tested and reused on
its own. PROTOCOL.md describes the protocol and where each fact comes from.

How this module talks to the WiFi box:

* One short TCP connection per request. Some boxes serve a single client at a
  time and push status frames on an open socket; a connection that stays open
  collects stale frames and keeps the vendor app out.
* Replies are split into STX..ETX frames. A read can hold several frames or
  part of one; the newest status frame is the current state.
* Control commands are sent one at a time. Each is acknowledged by the box, and
  the receiver needs a moment before it accepts the next one.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
import socket
import threading
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)

# --- Framing -----------------------------------------------------------------

STX = "\x02"
ETX = "\x03"
TCP_PORT = 2000

# Every request is STX + this header + command id + payload + ETX, all ASCII.
REQUEST_HEADER = "3030303080"
# Replies start with one of these, followed by the id of the command they answer.
REPLY_HEADERS = ("3030303000", "0303000000")
STATUS_PREFIXES = tuple(header + "03" for header in REPLY_HEADERS)

# Kept for code that builds raw frames: STX + REQUEST_HEADER as hex.
COMMAND_PREFIX = "0233303330333033303830"

# --- Command ids and payloads (ASCII, between the header and ETX) -------------

CMD_STATUS = "03"
CMD_DEVICE_INFO = "01"
CMD_IGNITE = "1A"
CMD_OFF = "10"
CMD_BURNER = "16"  # + output as two hex characters; "00" is standby
CMD_STANDBY = CMD_BURNER + "00"
CMD_AUX_ON = "2001"
CMD_AUX_OFF = "2000"
CMD_LIGHT_ON = "3001"
CMD_LIGHT_OFF = "3000"
CMD_LIGHT_LEVEL = "30FE"  # + level as two hex characters
CMD_MANUAL = "B0"
CMD_THERMOSTAT_ON = "B201"
CMD_THERMOSTAT_TEMPERATURE = "B2FD"  # + temperature x10 as four hex characters
CMD_ECO_ON = "B301"

# Reply id sent when the box has no radio link to the fireplace receiver. The
# vendor app shows it as F43.
REPLY_NO_RECEIVER = "E1"

# --- Timing --------------------------------------------------------------------

SOCKET_TIMEOUT = 3.0
# How long to wait for the box to acknowledge a control command.
ACK_TIMEOUT = 3.0
# Pause between two control commands. A command sent while the receiver is still
# busy with the previous one is answered with "no receiver".
COMMAND_GAP = 2.0
# Pause before the single retry of a failed request.
RETRY_DELAY = 1.0
# After the burner output is changed the valve moves for a while; an aux command
# sent meanwhile is refused.
VALVE_SETTLE = 10.0
# A box that answers a command with a status frame but no acknowledgement gets
# this much longer to send one.
ACK_AFTER_STATUS = 1.0
# After an ignite command the fireplace counts as igniting for this long even
# if the box still reports it off; the igniting bit takes a moment to show.
IGNITE_GRACE = 30.0
# After an off command it counts as shutting down for this long even if the box
# still reports it on.
OFF_GRACE = 20.0
# A fresh ignition must hold this long before the fireplace counts as lit. While
# igniting, the box drops its receiver link and reports unreliable values, also
# on attempts where the pilot does not catch.
IGNITION_SETTLE = 60.0
# The receiver link has to be missing for this long before it counts as lost;
# it drops for 20-30 s during every ignition and shutdown.
RECEIVER_LOST_AFTER = 45.0

# --- Status frame --------------------------------------------------------------

# Character offsets in a status frame, after STX.
STATUS_SETUP_STATE = slice(12, 14)
STATUS_BURNER_OUTPUT = slice(14, 16)
STATUS_WORD = slice(16, 20)
STATUS_LIGHT_LEVEL = slice(20, 22)
STATUS_FAN_LEVEL = slice(22, 24)
STATUS_MODE = slice(24, 25)
STATUS_FLAGS = slice(26, 28)
STATUS_ROOM_TEMPERATURE = slice(28, 32)
STATUS_TARGET_TEMPERATURE = slice(32, 36)
STATUS_NAME_START = 36
# Shortest frame that holds every field read here.
STATUS_MIN_LENGTH = 36

# Bits of the 16-bit receiver state word.
WORD_RECEIVER_CONNECTED = 0x8000
WORD_HANDSET_CONNECTED = 0x0200
WORD_SHUTTING_DOWN = 0x0100
WORD_PILOT = 0x0080  # set whenever the pilot burns: fire on and standby
WORD_FAN = 0x0040
WORD_IGNITING = 0x0010
WORD_AUX = 0x0008
WORD_LIGHT = 0x0004
WORD_FAULTED = 0x0002

# System flags.
FLAG_COUNTDOWN = 0x01
FLAG_THERMOSTAT = 0x02
FLAG_CHILD_LOCK = 0x08
FLAG_PROGRAM = 0x10

# Room temperature field while no handset reports one (the app shows F44).
NO_HANDSET_TEMPERATURE = "0666"

MODE_MANUAL = "manual"
MODE_THERMOSTAT = "thermostat"
MODE_ECO = "eco"
MODES = {"0": MODE_MANUAL, "1": MODE_THERMOSTAT, "2": MODE_ECO}

STATE_OFF = "off"
STATE_STANDBY = "standby"
STATE_IGNITING = "igniting"
STATE_ON = "on"
STATE_SHUTTING_DOWN = "shutting_down"
STATES = [STATE_OFF, STATE_STANDBY, STATE_IGNITING, STATE_ON, STATE_SHUTTING_DOWN]

# --- Burner ----------------------------------------------------------------------

# Burner output of the 12 flame steps the handset uses. The output is one byte
# and is reported back in the status frame.
FLAME_STEP_OUTPUTS = (
    0x80, 0x8B, 0x97, 0xA2, 0xAE, 0xB9, 0xC5, 0xD0, 0xDC, 0xE7, 0xF3, 0xFF,
)
FLAME_STEPS = len(FLAME_STEP_OUTPUTS)
# Output above this means the main burner is lit. Standby reports 0x00 or 0x20,
# the lowest real flame seen is 0x69.
BURNER_LIT_ABOVE = 0x40

# --- Light -----------------------------------------------------------------------

# Light levels this module sends. Below 0x77 the light stays dark on some fires.
LIGHT_LEVEL_MIN = 0x77
LIGHT_LEVEL_MAX = 0xFB

# --- Thermostat --------------------------------------------------------------------

THERMOSTAT_MIN_TEMPERATURE = 5.0
THERMOSTAT_MAX_TEMPERATURE = 36.0


class MertikError(Exception):
    """Something went wrong talking to the fireplace."""


class MertikConnectionError(MertikError):
    """The WiFi box cannot be reached or does not answer."""


class MertikReceiverError(MertikError):
    """The WiFi box answers but has no link to the fireplace receiver."""


def build_request(command: str, *, line_feed: bool = False) -> bytes:
    """Return the bytes of a request frame for an ASCII command."""
    frame = (STX + REQUEST_HEADER + command + ETX).encode("ascii")
    return frame + b"\n" if line_feed else frame


def split_frames(buffer: str) -> tuple[list[str], str]:
    """Split received text into complete frames and the unfinished remainder.

    Bytes before an STX are dropped. The remainder starts at the STX of a frame
    whose ETX has not arrived yet.
    """
    frames: list[str] = []
    while True:
        start = buffer.find(STX)
        if start == -1:
            return frames, ""
        end = buffer.find(ETX, start + 1)
        if end == -1:
            return frames, buffer[start:]
        frames.append(buffer[start + 1 : end])
        buffer = buffer[end + 1 :]


def reply_id(frame: str) -> str | None:
    """Return the command id a reply frame answers, or None if it isn't a reply."""
    if frame.startswith(REPLY_HEADERS) and len(frame) >= 12:
        return frame[10:12]
    return None


def flame_step_for_output(output: int) -> int:
    """Return the flame step (1-12) nearest to a burner output, 0 if not lit."""
    if output <= BURNER_LIT_ABOVE:
        return 0
    distances = [abs(output - step) for step in FLAME_STEP_OUTPUTS]
    return distances.index(min(distances)) + 1


def light_level_for_brightness(brightness: int) -> int:
    """Return the light level for a brightness of 1-255."""
    brightness = max(1, min(255, int(brightness)))
    span = LIGHT_LEVEL_MAX - LIGHT_LEVEL_MIN
    return LIGHT_LEVEL_MIN + round((brightness - 1) / 254 * span)


def brightness_for_light_level(level: int) -> int:
    """Return the brightness (1-255) for a reported light level."""
    span = LIGHT_LEVEL_MAX - LIGHT_LEVEL_MIN
    brightness = 1 + round((level - LIGHT_LEVEL_MIN) / span * 254)
    return max(1, min(255, brightness))


def _parse_temperature(text: str) -> float | None:
    try:
        return int(text, 16) / 10
    except ValueError:
        return None


def _parse_name(text: str) -> str | None:
    """Decode the name field: hex-encoded ASCII, padded with FF."""
    characters = []
    for index in range(0, len(text) - 1, 2):
        try:
            value = int(text[index : index + 2], 16)
        except ValueError:
            break
        if not 0x20 <= value < 0x7F:
            break
        characters.append(chr(value))
    name = "".join(characters).strip()
    return name or None


@dataclass(frozen=True)
class Status:
    """One status frame, decoded."""

    raw: str
    setup_state: int
    burner_output: int
    word: int
    light_level: int
    fan_level: int
    mode_character: str
    flags: int
    room_temperature: float | None
    target_temperature: float | None
    name: str | None

    @classmethod
    def parse(cls, frame: str) -> Status | None:
        """Decode a status frame; None if it isn't one or is damaged."""
        if not frame.startswith(STATUS_PREFIXES) or len(frame) < STATUS_MIN_LENGTH:
            return None
        try:
            setup_state = int(frame[STATUS_SETUP_STATE], 16)
            burner_output = int(frame[STATUS_BURNER_OUTPUT], 16)
            word = int(frame[STATUS_WORD], 16)
            light_level = int(frame[STATUS_LIGHT_LEVEL], 16)
            fan_level = int(frame[STATUS_FAN_LEVEL], 16)
            flags = int(frame[STATUS_FLAGS], 16)
        except ValueError:
            return None
        room = frame[STATUS_ROOM_TEMPERATURE]
        return cls(
            raw=frame,
            setup_state=setup_state,
            burner_output=burner_output,
            word=word,
            light_level=light_level,
            fan_level=fan_level,
            mode_character=frame[STATUS_MODE],
            flags=flags,
            room_temperature=(
                None if room.upper() == NO_HANDSET_TEMPERATURE else _parse_temperature(room)
            ),
            target_temperature=_parse_temperature(frame[STATUS_TARGET_TEMPERATURE]),
            name=_parse_name(frame[STATUS_NAME_START:]),
        )

    def _bit(self, mask: int) -> bool:
        return bool(self.word & mask)

    @property
    def receiver_connected(self) -> bool:
        """The box has its radio link to the fireplace receiver."""
        return self._bit(WORD_RECEIVER_CONNECTED)

    @property
    def shutting_down(self) -> bool:
        return self._bit(WORD_SHUTTING_DOWN)

    @property
    def pilot_on(self) -> bool:
        return self._bit(WORD_PILOT)

    @property
    def igniting(self) -> bool:
        return self._bit(WORD_IGNITING)

    @property
    def aux_on(self) -> bool:
        return self._bit(WORD_AUX)

    @property
    def light_on(self) -> bool:
        return self._bit(WORD_LIGHT)

    @property
    def fan_on(self) -> bool:
        return self._bit(WORD_FAN)

    @property
    def faulted(self) -> bool:
        return self._bit(WORD_FAULTED)

    @property
    def handset_bit(self) -> bool:
        return self._bit(WORD_HANDSET_CONNECTED)

    @property
    def burner_lit(self) -> bool:
        """The main burner burns (the output alone does not prove a flame)."""
        return self.pilot_on and self.burner_output > BURNER_LIT_ABOVE

    @property
    def mode(self) -> str | None:
        return MODES.get(self.mode_character)

    @property
    def state(self) -> str:
        """The fireplace state this frame describes."""
        if self.shutting_down:
            return STATE_SHUTTING_DOWN
        if self.igniting:
            return STATE_IGNITING
        if not self.pilot_on:
            return STATE_OFF
        if self.burner_output > BURNER_LIT_ABOVE:
            return STATE_ON
        return STATE_STANDBY


def _default_connect(host: str, port: int, timeout: float) -> Any:
    return socket.create_connection((host, port), timeout=timeout)


class Mertik:
    """A Mertik Maxitrol fireplace behind its WiFi box."""

    def __init__(
        self,
        ip: str,
        *,
        connect: Callable[[str, int, float], Any] = _default_connect,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        refresh: bool = True,
    ) -> None:
        """Set up the fireplace and, unless told otherwise, read its status once.

        Raises MertikConnectionError when that first read fails.
        """
        self.ip = ip
        self._connect = connect
        self._clock = clock
        self._sleep = sleep
        # One exchange at a time: polls and service calls come from different threads.
        self._lock = threading.RLock()

        self._status: Status | None = None
        self._last_frame: str | None = None
        self._device_info: str | None = None
        self._link_seen = False
        self._link_down_since: float | None = None
        self._no_receiver_since: float | None = None
        self._ignition_settles_at: float | None = None
        self._ignite_sent_at: float | None = None
        self._off_sent_at: float | None = None
        self._last_command_done: float | None = None
        self._valve_busy_until: float | None = None

        if refresh:
            self.refresh_status()

    # --- State ---------------------------------------------------------------------

    @property
    def status(self) -> Status | None:
        """The last reliable status frame."""
        return self._status

    @property
    def last_frame(self) -> str | None:
        """The last status frame received, reliable or not (for diagnostics)."""
        return self._last_frame

    @property
    def device_info(self) -> str | None:
        """The raw device info reply (model, versions, serials), if it was read.

        Its layout is not known well enough to decode; it is kept for diagnostics.
        """
        return self._device_info

    def _ignition_pending(self) -> bool:
        return (
            self._ignition_settles_at is not None
            and self._clock() < self._ignition_settles_at
        )

    @property
    def receiver_connected(self) -> bool | None:
        """Whether the box currently reports its link to the receiver."""
        if self._status is None and self._no_receiver_since is None:
            return None
        return self._link_down_since is None and self._no_receiver_since is None

    @property
    def receiver_lost(self) -> bool:
        """The receiver link has been missing for too long to be an ignition."""
        now = self._clock()
        for since in (self._link_down_since, self._no_receiver_since):
            if since is not None and now - since >= RECEIVER_LOST_AFTER:
                return True
        return False

    @property
    def state(self) -> str | None:
        """off, standby, igniting, on or shutting_down; None while unknown."""
        if self._status is None:
            return None
        now = self._clock()
        # The last reliable frame. While the receiver link is down the box sends
        # unreliable values, so that frame stays in force (see receiver_lost).
        state = self._status.state
        if self._off_sent_at is not None and now - self._off_sent_at < OFF_GRACE:
            if state in (STATE_ON, STATE_STANDBY, STATE_IGNITING):
                return STATE_SHUTTING_DOWN
        if state == STATE_SHUTTING_DOWN:
            return state
        if self._ignition_pending():
            if state in (STATE_ON, STATE_STANDBY):
                return STATE_IGNITING
            if self._link_down_since is not None:
                return STATE_IGNITING
            if (
                state == STATE_OFF
                and self._ignite_sent_at is not None
                and now - self._ignite_sent_at < IGNITE_GRACE
            ):
                return STATE_IGNITING
        return state

    @property
    def is_pilot_on(self) -> bool:
        """The pilot burns: the fire is on or in standby."""
        return self.state in (STATE_ON, STATE_STANDBY)

    @property
    def is_on(self) -> bool:
        """The fireplace is on: burning, in standby, or lighting."""
        return self.state in (STATE_ON, STATE_STANDBY, STATE_IGNITING)

    @property
    def is_burning(self) -> bool:
        """The main burner burns."""
        return self.state == STATE_ON

    @property
    def is_igniting(self) -> bool:
        return self.state == STATE_IGNITING

    @property
    def is_shutting_down(self) -> bool:
        return self.state == STATE_SHUTTING_DOWN

    @property
    def is_aux_on(self) -> bool:
        """The secondary burner is enabled (it only burns with the main burner)."""
        return self._status is not None and self._status.aux_on

    @property
    def is_light_on(self) -> bool:
        return self._status is not None and self._status.light_on

    @property
    def light_brightness(self) -> int:
        """Brightness 1-255 of the light, 0 while it is off."""
        if self._status is None or not self._status.light_on:
            return 0
        return brightness_for_light_level(self._status.light_level)

    @property
    def burner_output(self) -> int | None:
        """The raw burner output (0-255) of the last reliable frame."""
        return None if self._status is None else self._status.burner_output

    @property
    def flame_height(self) -> int:
        """Flame step 1-12 while the main burner burns, otherwise 0."""
        if self._status is None or self.state != STATE_ON:
            return 0
        return flame_step_for_output(self._status.burner_output)

    def get_flame_height(self) -> int:
        """Flame step 1-12 while the main burner burns, otherwise 0."""
        return self.flame_height

    @property
    def mode(self) -> str | None:
        """manual, thermostat or eco."""
        return None if self._status is None else self._status.mode

    @property
    def is_thermostat_mode(self) -> bool:
        return self.mode == MODE_THERMOSTAT

    @property
    def ambient_temperature(self) -> float | None:
        """Room temperature from the handset, None while no handset reports one."""
        return None if self._status is None else self._status.room_temperature

    @property
    def target_temperature(self) -> float | None:
        return None if self._status is None else self._status.target_temperature

    @property
    def handset_connected(self) -> bool | None:
        """Whether a handset reports to the fireplace.

        The handset bit is not set on every fireplace, so a room temperature
        counts as well.
        """
        if self._status is None:
            return None
        return self._status.handset_bit or self._status.room_temperature is not None

    @property
    def fan_level(self) -> int | None:
        return None if self._status is None else self._status.fan_level

    @property
    def is_fan_on(self) -> bool:
        return self._status is not None and self._status.fan_on

    @property
    def is_faulted(self) -> bool | None:
        """Whether the fireplace has a fault stored.

        The bit stays set until the fault is cleared in the vendor app, and is
        set for good on a fireplace without a handset (fault F44).
        """
        return None if self._status is None else self._status.faulted

    @property
    def name(self) -> str | None:
        """The name stored in the fireplace, if any."""
        return None if self._status is None else self._status.name

    # --- Commands ------------------------------------------------------------------

    def refresh_status(self) -> None:
        """Read the status. Raises MertikConnectionError if the box does not answer."""
        self._request(CMD_STATUS, control=False)

    def read_device_info(self) -> str | None:
        """Read model, versions and serials. Returns the raw reply, None if unanswered."""
        try:
            self._request(CMD_DEVICE_INFO, control=False)
        except MertikError as err:
            _LOGGER.debug("No device info from %s: %s", self.ip, err)
        return self._device_info

    def ignite_fireplace(self) -> None:
        """Start the ignition. Never sent twice: a second ignite could restart it."""
        self._request(CMD_IGNITE, resend=False)
        now = self._clock()
        self._ignite_sent_at = now
        self._off_sent_at = None
        self._ignition_settles_at = now + IGNITION_SETTLE

    def guard_flame_off(self) -> None:
        """Turn the fireplace off completely, pilot included."""
        self._request(CMD_OFF)
        self._off_sent_at = self._clock()
        self._ignite_sent_at = None
        self._ignition_settles_at = None

    def standBy(self) -> None:  # noqa: N802 (kept: the name older code calls)
        """Turn the main burner down to the pilot. Does not light a cold fire."""
        self.set_flame_height(0)

    def set_flame_height(self, flame_height: int) -> None:
        """Set flame step 1-12, or 0 for standby (pilot only)."""
        flame_height = int(flame_height)
        if not 0 <= flame_height <= FLAME_STEPS:
            raise ValueError(f"Flame height must be 0-{FLAME_STEPS}, got {flame_height}")
        if flame_height == 0:
            self._request(CMD_STANDBY)
        else:
            self._request(f"{CMD_BURNER}{FLAME_STEP_OUTPUTS[flame_height - 1]:02X}")
        self._valve_busy_until = self._clock() + VALVE_SETTLE

    def aux_on(self) -> None:
        """Enable the secondary burner."""
        self._request(CMD_AUX_ON, line_feed=True, wait_for_valve=True)

    def aux_off(self) -> None:
        """Disable the secondary burner, leaving the main burner on its own."""
        self._request(CMD_AUX_OFF, line_feed=True, wait_for_valve=True)

    def light_on(self) -> None:
        self._request(CMD_LIGHT_ON)

    def light_off(self) -> None:
        self._request(CMD_LIGHT_OFF)

    def set_light_brightness(self, brightness: int) -> None:
        """Set the light level from a brightness of 1-255."""
        self._request(f"{CMD_LIGHT_LEVEL}{light_level_for_brightness(brightness):02X}")

    def set_manual(self) -> None:
        """Leave thermostat or eco mode."""
        self._request(CMD_MANUAL)

    def set_eco(self) -> None:
        """Let the fireplace modulate its flame to save gas."""
        self._request(CMD_ECO_ON)

    def set_thermostat(self, temperature: float) -> None:
        """Switch to thermostat mode, regulating towards temperature (C)."""
        temperature = max(
            THERMOSTAT_MIN_TEMPERATURE, min(THERMOSTAT_MAX_TEMPERATURE, float(temperature))
        )
        value = f"{round(temperature * 10):04X}"
        # Held for the whole sequence so a status poll can't land between the two
        # commands; the gap between control commands spaces them.
        with self._lock:
            self._request(CMD_THERMOSTAT_ON)
            self._request(f"{CMD_THERMOSTAT_TEMPERATURE}{value}")

    # --- Transport -----------------------------------------------------------------

    def _wait_before_command(self, wait_for_valve: bool) -> None:
        now = self._clock()
        wait = 0.0
        if self._last_command_done is not None:
            wait = COMMAND_GAP - (now - self._last_command_done)
        if wait_for_valve and self._valve_busy_until is not None:
            wait = max(wait, self._valve_busy_until - now)
        if wait > 0:
            self._sleep(wait)

    def _request(
        self,
        command: str,
        *,
        control: bool = True,
        resend: bool = True,
        line_feed: bool = False,
        wait_for_valve: bool = False,
    ) -> None:
        """Send one request and handle its replies.

        A request that could not be delivered is retried once. One that was sent
        but not answered is only sent again when resend is set: every command
        except ignite sets an absolute state, so twice does no harm.
        """
        payload = build_request(command, line_feed=line_feed)
        attempts = 2
        with self._lock:
            if control:
                self._wait_before_command(wait_for_valve)
            try:
                for attempt in range(1, attempts + 1):
                    last = attempt == attempts
                    sent = False
                    try:
                        try:
                            connection = self._connect(self.ip, TCP_PORT, SOCKET_TIMEOUT)
                        except ValueError as err:
                            # Not an address at all, such as the typo "192.168..1.4":
                            # Python refuses it before anything is looked up.
                            raise MertikConnectionError(
                                f"{self.ip} is not a usable address: {err}"
                            ) from err
                        try:
                            connection.sendall(payload)
                            sent = True
                            outcome = self._read_replies(connection, command[:2], control)
                        finally:
                            _close(connection)
                    except OSError as err:
                        if last or (sent and not resend):
                            raise MertikConnectionError(
                                f"No connection to the fireplace at {self.ip}: {err}"
                            ) from err
                        _LOGGER.debug("Request %s to %s failed (%s), retrying", command, self.ip, err)
                        self._sleep(RETRY_DELAY)
                        continue

                    if outcome == _ANSWERED:
                        return
                    if outcome == _NO_RECEIVER:
                        if not control:
                            # A poll answered with "no receiver" is an answer: the
                            # link state is tracked, nothing more to do.
                            return
                        if last or not resend:
                            raise MertikReceiverError(
                                "The WiFi box has no link to the fireplace receiver"
                            )
                        _LOGGER.debug("Command %s answered with 'no receiver', retrying", command)
                        self._sleep(COMMAND_GAP)
                        continue
                    # No answer at all.
                    if last or not resend:
                        raise MertikConnectionError(
                            f"The fireplace at {self.ip} did not answer"
                        )
                    _LOGGER.debug("Request %s to %s not answered, retrying", command, self.ip)
                    self._sleep(RETRY_DELAY)
            finally:
                if control:
                    self._last_command_done = self._clock()

    def _read_replies(self, connection: Any, command_id: str, control: bool) -> int:
        """Read frames until the request is answered or the time is up.

        A control command is answered by its acknowledgement or, on boxes that
        do not send one, by a status frame. A status or device info request is
        answered by that frame.
        """
        deadline = self._clock() + (ACK_TIMEOUT if control else SOCKET_TIMEOUT)
        buffer = ""
        outcome = _UNANSWERED
        while outcome != _ANSWERED:
            remaining = deadline - self._clock()
            if remaining <= 0:
                break
            connection.settimeout(remaining)
            try:
                data = connection.recv(4096)
            except TimeoutError:
                break
            if not data:
                break
            buffer += data.decode("ascii", errors="replace")
            frames, buffer = split_frames(buffer)
            newest_status: Status | None = None
            for frame in frames:
                answered = reply_id(frame)
                if answered is None:
                    continue
                if answered == REPLY_NO_RECEIVER:
                    self._note_no_receiver()
                    if outcome == _UNANSWERED:
                        outcome = _NO_RECEIVER
                    continue
                if answered == CMD_STATUS:
                    if status := Status.parse(frame):
                        newest_status = status
                        if command_id == CMD_STATUS:
                            outcome = _ANSWERED
                        elif control and outcome != _ANSWERED:
                            if outcome != _STATUS_ONLY:
                                deadline = min(deadline, self._clock() + ACK_AFTER_STATUS)
                            outcome = _STATUS_ONLY
                    continue
                if answered == CMD_DEVICE_INFO and not control:
                    self._device_info = frame[12:]
                    if command_id == CMD_DEVICE_INFO:
                        outcome = _ANSWERED
                    continue
                if control and answered == command_id:
                    outcome = _ANSWERED
            if newest_status is not None:
                self._process_status(newest_status)
            if outcome == _NO_RECEIVER:
                # The box answers "no receiver" instead of the reply asked for.
                break
        if outcome == _STATUS_ONLY:
            # No acknowledgement, but the box answered with its status.
            return _ANSWERED
        return outcome

    def _note_no_receiver(self) -> None:
        if self._no_receiver_since is None:
            self._no_receiver_since = self._clock()

    def _process_status(self, status: Status) -> None:
        """Take over a status frame, unless the receiver link is down in it."""
        self._last_frame = status.raw
        self._no_receiver_since = None
        now = self._clock()

        if status.receiver_connected:
            self._link_seen = True
            self._link_down_since = None
        elif self._link_seen:
            # Only boxes that have shown the link bit are judged on it.
            if self._link_down_since is None:
                self._link_down_since = now
            if self._ignition_pending() or (self._status and self._status.igniting):
                self._ignition_settles_at = now + IGNITION_SETTLE
            return

        self._status = status
        state = status.state
        if state == STATE_IGNITING:
            self._ignition_settles_at = now + IGNITION_SETTLE
        elif state == STATE_SHUTTING_DOWN:
            self._ignition_settles_at = None
            self._ignite_sent_at = None
        elif state == STATE_OFF:
            just_ignited = (
                self._ignite_sent_at is not None
                and now - self._ignite_sent_at < IGNITE_GRACE
            )
            if not just_ignited:
                self._ignition_settles_at = None
                self._ignite_sent_at = None
            self._off_sent_at = None


_UNANSWERED = 0
_ANSWERED = 1
_NO_RECEIVER = 2
_STATUS_ONLY = 3


def _close(connection: Any) -> None:
    try:
        connection.close()
    except OSError:
        pass
