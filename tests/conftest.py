"""Fixtures for Mertik tests."""

import pytest

from unittest.mock import MagicMock, patch

from custom_components.mertik.mertik import Mertik


@pytest.fixture
def mock_socket():
    """Return a mock socket that doesn't connect anywhere."""
    with patch("custom_components.mertik.mertik.socket.socket") as mock_sock_cls:
        mock_sock = MagicMock()
        mock_sock_cls.return_value = mock_sock
        mock_sock.recv.return_value = _build_status_bytes()
        yield mock_sock


def _build_status_bytes(
    flame_height: int = 0x00,
    status_bits: str = "0000",
    light_level: int = 0x64,
    mode: str = "0",
    ambient_temp: int = 0xE6,
) -> bytes:
    """Build a raw status response matching the Mertik protocol.

    After __sendCommand strips the first byte and the regex no-op, __processStatus
    receives a string parsed at these indices:

        [0:12]   prefix (e.g. "303030300003")
        [12:14]  padding
        [14:16]  flame height (2 hex chars)
        [16:20]  status bits (4 hex chars)
        [20:22]  light level (2 hex chars)
        [22:24]  padding
        [24:25]  mode (1 char)
        [25:30]  padding
        [30:32]  ambient temperature (2 hex chars)
    """
    prefix = "303030300003"
    body = (
        "00"                        # [12:14] padding
        f"{flame_height:02X}"       # [14:16] flame height
        f"{status_bits}"            # [16:20] status bits (4 hex chars)
        f"{light_level:02X}"        # [20:22] light level
        "00"                        # [22:24] padding
        f"{mode}"                   # [24:25] mode
        "00000"                     # [25:30] padding
        f"{ambient_temp:02X}"       # [30:32] ambient temp
    )
    # __sendCommand strips the first byte, so prepend a dummy
    raw = "\x02" + prefix + body
    return raw.encode("ascii")


@pytest.fixture
def mertik_device(mock_socket):
    """Return a Mertik instance with a mocked socket."""
    device = Mertik("192.168.1.100")
    return device
