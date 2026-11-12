"""A scripted WiFi box and clock for tests: no sockets, no waiting."""

from __future__ import annotations

from collections.abc import Callable

from custom_components.mertik.mertik import (
    CMD_DEVICE_INFO,
    CMD_STATUS,
    ETX,
    REPLY_HEADERS,
    REQUEST_HEADER,
    STX,
)

REPLY_HEADER = REPLY_HEADERS[1]  # the header seen on a real box: "0303000000"

# Burner output of the handset's 12 flame steps, written out here on purpose:
# the tests should notice if the table in the code changes.
FLAME_OUTPUTS = (0x80, 0x8B, 0x97, 0xA2, 0xAE, 0xB9, 0xC5, 0xD0, 0xDC, 0xE7, 0xF3, 0xFF)

# A status frame captured from a real fireplace: off, no handset reading.
REAL_FRAME_OFF = "0303000000034700800300000000066600C8" + "0" * 64 + "043E01"


def status_frame(
    *,
    output: int = 0x00,
    word: int = 0x8003,
    light: int = 0x00,
    fan: int = 0x00,
    mode: str = "0",
    flags: int = 0x00,
    room: int | str = 0x00D2,
    target: int | str = 0x00C8,
    name: str = "",
    setup: int = 0x47,
    header: str = REPLY_HEADER,
) -> str:
    """Build the text of a status frame (what sits between STX and ETX)."""
    room_text = room if isinstance(room, str) else f"{room:04X}"
    target_text = target if isinstance(target, str) else f"{target:04X}"
    body = (
        f"{header}03{setup:02X}{output:02X}{word:04X}{light:02X}{fan:02X}"
        f"{mode}0{flags:02X}{room_text}{target_text}"
    )
    body += name.encode("ascii").hex().upper()
    return body + "F" * max(0, 104 - len(body)) + "01"


def framed(*frames: str) -> bytes:
    """Wrap frame texts in STX/ETX as the box sends them."""
    return "".join(STX + frame + ETX for frame in frames).encode("ascii")


def ack(command_id: str, extra: str = "", header: str = REPLY_HEADER) -> str:
    """The acknowledgement frame of a control command."""
    return header + command_id + extra


NO_RECEIVER = REPLY_HEADER + "E101"


class FakeClock:
    """A clock that only moves when told to, or when something sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeConnection:
    def __init__(self, box: FakeBox) -> None:
        self._box = box
        self._chunks: list[bytes] = []
        self.closed = False

    def settimeout(self, timeout: float) -> None:
        self._timeout = timeout

    def sendall(self, data: bytes) -> None:
        if self._box.fail_sends > 0:
            self._box.fail_sends -= 1
            raise OSError("send failed")
        text = data.decode("ascii")
        command = text[1 + len(REQUEST_HEADER) : text.index(ETX)]
        self._box.requests.append(command)
        self._box.raw_requests.append(data)
        self._chunks = list(self._box.reply_to(command))

    def recv(self, size: int) -> bytes:
        if self._chunks:
            return self._chunks.pop(0)
        # Nothing more to say: the read times out, which costs the time waited.
        self._box.clock.advance(self._timeout)
        raise TimeoutError

    def close(self) -> None:
        self.closed = True
        self._box.open_connections -= 1


class FakeBox:
    """Stands in for the WiFi box: answers each request on its own connection."""

    def __init__(self, clock: FakeClock, status: str = REAL_FRAME_OFF) -> None:
        self.clock = clock
        self.status = status
        self.requests: list[str] = []
        self.raw_requests: list[bytes] = []
        self.connections = 0
        self.open_connections = 0
        self.fail_connects = 0
        self.fail_sends = 0
        # False: commands are answered with a status frame only, no acknowledgement.
        self.acknowledge = True
        # True: every request is answered with "no receiver".
        self.no_receiver = False
        # True: requests are not answered at all.
        self.silent = False
        self.device_info = "B6R-H8TV4P" + "0" * 20
        # command text -> chunks to answer with (overrides the default behaviour)
        self.script: dict[str, list[bytes] | Callable[[], list[bytes]]] = {}
        # Called with each control command, to change the status the box reports.
        self.on_command: Callable[[str], None] | None = None

    def connect(self, host: str, port: int, timeout: float) -> FakeConnection:
        if self.fail_connects > 0:
            self.fail_connects -= 1
            raise OSError("connection refused")
        self.connections += 1
        self.open_connections += 1
        return FakeConnection(self)

    def reply_to(self, command: str) -> list[bytes]:
        if command in self.script:
            scripted = self.script[command]
            return scripted() if callable(scripted) else list(scripted)
        if self.silent:
            return []
        if self.no_receiver:
            return [framed(NO_RECEIVER)]
        if command == CMD_STATUS:
            return [framed(self.status)]
        if command == CMD_DEVICE_INFO:
            return [framed(REPLY_HEADER + CMD_DEVICE_INFO + self.device_info)]
        if self.on_command is not None:
            self.on_command(command)
        if self.acknowledge:
            return [framed(ack(command[:2]))]
        return [framed(self.status)]

    @property
    def commands(self) -> list[str]:
        """The control commands received (everything but status and device info)."""
        return [r for r in self.requests if r not in (CMD_STATUS, CMD_DEVICE_INFO)]


class FakeFireplace:
    """Makes a FakeBox report like a fireplace: commands change its status.

    Lighting and shutting down do not finish by themselves; a test moves them
    on with lit(), standby() and off().
    """

    def __init__(self, box: FakeBox) -> None:
        self.box = box
        self.pilot = False
        self.igniting = False
        self.shutting_down = False
        self.output = 0x00
        self.aux = False
        self.light = False
        self.light_level = 0x00
        self.fan = False
        self.fan_level = 0x00
        self.mode = "0"
        self.room: int | str = "0666"  # no handset
        self.target: int | str = 0x00C8
        self.link = True
        self.handset = False
        self.name = ""
        # Whether setting a light level also switches the light on.
        self.level_lights = True
        box.on_command = self._on_command
        self.apply()

    def apply(self) -> None:
        """Put the current state into the frame the box answers with."""
        word = 0x0003
        for bit, is_set in (
            (0x8000, self.link),
            (0x0200, self.handset),
            (0x0100, self.shutting_down),
            (0x0080, self.pilot),
            (0x0040, self.fan),
            (0x0010, self.igniting),
            (0x0008, self.aux),
            (0x0004, self.light),
        ):
            if is_set:
                word |= bit
        self.box.status = status_frame(
            output=self.output,
            word=word,
            light=self.light_level,
            fan=self.fan_level,
            mode=self.mode,
            room=self.room,
            target=self.target,
            name=self.name,
        )

    def set(self, **changes: object) -> None:
        for key, value in changes.items():
            if not hasattr(self, key):
                raise AttributeError(key)
            setattr(self, key, value)
        self.apply()

    def lit(self, flame: int = 12) -> None:
        """The pilot burns; the main burner is at a flame step, or off at 0."""
        output = FLAME_OUTPUTS[flame - 1] if flame else 0x00
        self.set(pilot=True, igniting=False, shutting_down=False, output=output)

    def standby(self) -> None:
        self.lit(0)

    def off(self) -> None:
        self.set(pilot=False, igniting=False, shutting_down=False, output=0x00)

    def _on_command(self, command: str) -> None:
        if command == "1A":
            self.igniting = True
        elif command == "10":
            if self.pilot or self.igniting:
                self.shutting_down = True
            self.igniting = False
        elif command.startswith("30FE"):
            self.light_level = int(command[4:6], 16)
            if self.level_lights:
                self.light = True
        elif command == "3001":
            self.light = True
        elif command == "3000":
            self.light = False
        elif command == "2001":
            self.aux = True
        elif command == "2000":
            self.aux = False
        elif command.startswith("16"):
            self.output = int(command[2:4], 16)
        elif command == "B0":
            self.mode = "0"
        elif command == "B201":
            self.mode = "1"
        elif command.startswith("B2FD"):
            self.target = int(command[4:8], 16)
        elif command == "B301":
            self.mode = "2"
        self.apply()
