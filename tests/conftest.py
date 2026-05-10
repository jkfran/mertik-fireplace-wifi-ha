"""Fixtures for Mertik tests."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from custom_components.mertik.mertik import Mertik
from custom_components.mertik.const import DOMAIN


@pytest.fixture
def mock_coordinator():
    """Return a mock MertikDataCoordinator for entity tests."""
    coordinator = MagicMock()
    coordinator.is_on = False
    coordinator.is_aux_on = False
    coordinator.ambient_temperature = 21.5
    coordinator.get_flame_height.return_value = 0
    coordinator.async_set_updated_data = MagicMock()
    coordinator.mark_optimistic_on = MagicMock()
    coordinator.mark_optimistic_off = MagicMock()
    coordinator.ignite_fireplace = MagicMock()
    coordinator.guard_flame_off = MagicMock()
    coordinator.aux_on = MagicMock()
    coordinator.aux_off = MagicMock()
    coordinator.light_on = MagicMock()
    coordinator.light_off = MagicMock()
    coordinator.set_light_brightness = MagicMock()
    coordinator.set_flame_height = MagicMock()
    coordinator.fire_just_turned_off = False
    coordinator.async_add_listener = MagicMock(return_value=MagicMock())
    coordinator.data = None
    return coordinator


@pytest.fixture
def mock_config_entry():
    """Return a mock config entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_123"
    entry.data = {"name": "My Fireplace", "host": "192.168.1.100"}
    return entry


@pytest.fixture
def mock_socket():
    """Return a mock socket that doesn't connect anywhere."""
    with patch("custom_components.mertik.mertik.socket.socket") as mock_sock_cls:
        mock_sock = MagicMock()
        mock_sock_cls.return_value = mock_sock
        mock_sock.recv.return_value = _build_status_bytes()
        yield mock_sock


def _build_status_bytes(
    on_flag: str = "00",
    flame_byte: int = 0x00,
    status_hi: str = "80",
    light_level: int = 0x00,
    ambient_temp: int = 0xE6,
) -> bytes:
    """Build a raw status response matching the B6R-H8TV4PB packet layout.

    Our parser reads these fields from the decoded ASCII string (after
    stripping the leading STX byte):

        [0:12]   prefix  "303030300003"
        [12:14]  config byte (e.g. "C6")
        [14:16]  on_flag: "FF"=on, "00"=off
        [16:20]  status bits (4 hex chars); [18:20] is the flame byte
        [20:22]  light level
        [22:30]  filler
        [30:32]  ambient temperature (raw/10 = degrees C)

    Confirmed bit positions within the 16-bit status field [16:20]:
        bit 7  = shutting down  -> set status_hi to include 0x01
        bit 8  = guard flame    -> set status_hi to include 0x80 (default)
        bit 9  = aux on         -> set status_hi to include 0x40
        bit 11 = igniting       -> set flame_byte to 0x10

    flame_byte is the low byte of the 4-char status field [18:20].
    The 16-bit value is: (int(status_hi, 16) << 8) | flame_byte.

    Examples:
        Normal on:    status_hi="80", flame_byte=0x8F  -> bits=0x808F
        Igniting:     status_hi="80", flame_byte=0x10  -> bits=0x8010, bit11=1
        Shutting down:status_hi="81", flame_byte=0x00  -> bits=0x8100, bit7=1
        Aux on:       status_hi="C0", flame_byte=0x8F  -> bits=0xC08F, bit9=1

    Args:
        on_flag:     "FF" when fire is on, "00" when off.
        flame_byte:  Raw flame level. >0x7B means burner running.
                     Also carries igniting flag (0x10) and other low bits.
        status_hi:   High byte of 4-char status field, e.g. "80".
        light_level: Raw light level byte (not parsed by current code).
        ambient_temp: Raw temperature byte; value/10 = degrees C.
    """
    prefix = "303030300003"
    config = "C6"
    status_bits = f"{status_hi}{flame_byte:02X}"
    light = f"{light_level:02X}"
    filler = "04000000"
    temp = f"{ambient_temp:02X}"
    room = "DC" + "4C6976696E6720526F6F6D20" + "FF" * 20 + "043001"

    body = config + on_flag + status_bits + light + filler + temp + room
    raw = "\x02" + prefix + body
    return raw.encode("ascii")


@pytest.fixture
def mertik_device(mock_socket):
    """Return a Mertik instance with a mocked socket."""
    device = Mertik("192.168.1.100")
    return device
