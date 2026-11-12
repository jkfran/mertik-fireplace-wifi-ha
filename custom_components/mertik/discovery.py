"""Find Mertik WiFi modules on the local network.

A module answers a 4-byte UDP query on port 30718 with 30 bytes: a 24-byte
field holding its name (for example "mmWiFiBoxV2", with 0xFF filling the bytes
in front of it) followed by its 6-byte MAC address. The answer always goes to
port 30719. The query can be broadcast, or sent to one address.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import logging
import socket
import threading
import time

_LOGGER = logging.getLogger(__name__)

QUERY = bytes.fromhex("000100f6")
QUERY_PORT = 30718
REPLY_PORT = 30719
DEFAULT_TIMEOUT = 3.0
QUERY_INTERVAL = 1.0
BROADCAST = "255.255.255.255"

# Answers come to one fixed port, so two searches at once would take each
# other's answers. Searches wait for each other instead.
_LOCK = threading.Lock()

MIN_NAME_LENGTH = 3
MIN_REPLY_LENGTH = MIN_NAME_LENGTH + 6
MAX_REPLY_LENGTH = 64


@dataclass(frozen=True)
class Module:
    """A WiFi module that answered the query."""

    host: str
    name: str
    mac: str


def format_mac(mac: bytes) -> str:
    """Format a MAC address the way Home Assistant stores it."""
    return ":".join(f"{byte:02x}" for byte in mac)


def parse_reply(data: bytes, host: str) -> Module | None:
    """Return the module described by a discovery reply, or None if it isn't one.

    The length is not insisted on, in case other module versions use another:
    what counts is a readable name, padding around it at most, and a MAC address.
    """
    if not MIN_REPLY_LENGTH <= len(data) <= MAX_REPLY_LENGTH:
        return None
    name = data[:-6].strip(b"\xff\x00")
    if len(name) < MIN_NAME_LENGTH or any(not 0x20 < byte < 0x7F for byte in name):
        return None
    return Module(host=host, name=name.decode("ascii"), mac=format_mac(data[-6:]))


def discover(
    timeout: float = DEFAULT_TIMEOUT,
    targets: Iterable[str] = (BROADCAST,),
    *,
    host: str | None = None,
    socket_factory: Callable[[], socket.socket] | None = None,
) -> list[Module]:
    """Send the query and return the modules that answer, sorted by address.

    With host given, the search ends as soon as that address answers.
    """
    with _LOCK:
        return _discover(timeout, targets, host, socket_factory)


def _discover(
    timeout: float,
    targets: Iterable[str],
    host: str | None,
    socket_factory: Callable[[], socket.socket] | None,
) -> list[Module]:
    found: dict[str, Module] = {}
    try:
        sock = (
            socket_factory()
            if socket_factory
            else socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        )
    except OSError as err:
        _LOGGER.debug("Discovery not possible: %s", err)
        return []
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", REPLY_PORT))
        sock.settimeout(0.3)
        deadline = time.monotonic() + timeout
        next_query = 0.0
        while (now := time.monotonic()) < deadline:
            if now >= next_query:
                for target in targets:
                    try:
                        sock.sendto(QUERY, (target, QUERY_PORT))
                    except (OSError, ValueError) as err:
                        # ValueError: a target that is not an address at all.
                        _LOGGER.debug("Discovery query to %s failed: %s", target, err)
                next_query = now + QUERY_INTERVAL
            try:
                data, (address, _port) = sock.recvfrom(1024)
            except TimeoutError:
                continue
            module = parse_reply(data, address)
            if module is not None:
                found[address] = module
                if host is not None and address == host:
                    break
    except OSError as err:
        # Usually another program holds the reply port.
        _LOGGER.debug("Discovery failed: %s", err)
    finally:
        sock.close()
    return sorted(found.values(), key=lambda module: module.host)


def discover_host(
    host: str,
    timeout: float = 1.5,
    *,
    socket_factory: Callable[[], socket.socket] | None = None,
) -> Module | None:
    """Ask one address for its name and MAC address."""
    for module in discover(timeout, (host,), host=host, socket_factory=socket_factory):
        if module.host == host:
            return module
    return None
