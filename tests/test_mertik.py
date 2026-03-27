"""Tests for the Mertik hardware communication layer."""

from unittest.mock import MagicMock, patch, call

import pytest
import socket

from custom_components.mertik.mertik import (
    Mertik,
    send_command_prefix,
    process_status_prefixes,
)
from tests.conftest import _build_status_bytes


class TestMertikInit:
    """Test Mertik class initialization."""

    def test_connects_to_correct_host_and_port(self, mock_socket):
        device = Mertik("192.168.1.50")
        mock_socket.connect.assert_called_with(("192.168.1.50", 2000))

    def test_sets_timeout(self, mock_socket):
        device = Mertik("192.168.1.50")
        mock_socket.settimeout.assert_called_with(3)

    def test_calls_refresh_on_init(self, mock_socket):
        device = Mertik("192.168.1.50")
        refresh_cmd = bytearray.fromhex(send_command_prefix + "303303")
        mock_socket.send.assert_called_with(refresh_cmd)


class TestStatusParsing:
    """Test __processStatus parsing of status responses."""

    def test_fireplace_off_when_flame_height_low(self, mock_socket):
        """Flame height <= 0x7B means fireplace is off."""
        mock_socket.recv.return_value = _build_status_bytes(flame_height=0x00)
        device = Mertik("192.168.1.100")
        assert device.is_on is False
        assert device.get_flame_height() == 0

    def test_fireplace_on_when_flame_height_high(self, mock_socket):
        """Flame height > 123 means on. 0x80=128 -> height=1."""
        mock_socket.recv.return_value = _build_status_bytes(flame_height=0x80)
        device = Mertik("192.168.1.100")
        assert device.is_on is True
        assert device.get_flame_height() == 1

    def test_flame_height_mid_range(self, mock_socket):
        """0xC0=192 -> round(((192-128)/128)*12)+1 = 7."""
        mock_socket.recv.return_value = _build_status_bytes(flame_height=0xC0)
        device = Mertik("192.168.1.100")
        assert device.is_on is True
        assert device.get_flame_height() == 7

    def test_flame_height_max(self, mock_socket):
        """0xFF=255 -> round(((255-128)/128)*12)+1 = 13."""
        mock_socket.recv.return_value = _build_status_bytes(flame_height=0xFF)
        device = Mertik("192.168.1.100")
        assert device.is_on is True
        # round(((255-128)/128)*12) + 1 = round(11.90625) + 1 = 12 + 1 = 13
        assert device.get_flame_height() == 13

    def test_flame_height_boundary(self, mock_socket):
        """0x7B=123 is the boundary - still off."""
        mock_socket.recv.return_value = _build_status_bytes(flame_height=0x7B)
        device = Mertik("192.168.1.100")
        assert device.is_on is False

    def test_ambient_temperature(self, mock_socket):
        """0xE6=230 -> 230/10 = 23.0 C."""
        mock_socket.recv.return_value = _build_status_bytes(ambient_temp=0xE6)
        device = Mertik("192.168.1.100")
        assert device.ambient_temperature == 23.0

    def test_ambient_temperature_different_value(self, mock_socket):
        """0xC8=200 -> 200/10 = 20.0 C."""
        mock_socket.recv.return_value = _build_status_bytes(ambient_temp=0xC8)
        device = Mertik("192.168.1.100")
        assert device.ambient_temperature == 20.0

    def test_light_brightness_max(self, mock_socket):
        """light_level 0xFB=251 with light on -> round(((251-100)/151)*255) = 255."""
        # Use status_bits with bit 13 set (light_on) — need 16-bit value for stable indexing
        # Bit 13 in 16-bit: 2^(15-13) = 0x0004, plus 0x8000 base for 16-bit length
        mock_socket.recv.return_value = _build_status_bytes(
            light_level=0xFB, status_bits="8004"
        )
        device = Mertik("192.168.1.100")
        assert device.light_brightness == 255

    def test_light_brightness_minimum(self, mock_socket):
        """light_level 0x64=100 -> round(((100-100)/151)*255) = 0."""
        mock_socket.recv.return_value = _build_status_bytes(
            light_level=0x64, status_bits="8004"
        )
        device = Mertik("192.168.1.100")
        assert device.light_brightness == 0

    def test_light_off_brightness_zero(self, mock_socket):
        """When light is off, brightness is forced to 0."""
        mock_socket.recv.return_value = _build_status_bytes(
            light_level=0xFB, status_bits="0000"
        )
        device = Mertik("192.168.1.100")
        assert device.light_brightness == 0

    def test_status_bits_shutting_down(self, mock_socket):
        """Bit 7 -> shutting_down. In 16-bit: 2^(15-7)=0x0100, base 0x8000."""
        mock_socket.recv.return_value = _build_status_bytes(status_bits="8100")
        device = Mertik("192.168.1.100")
        assert device.is_shutting_down is True

    def test_status_bits_igniting(self, mock_socket):
        """Bit 11 -> igniting. In 16-bit: 2^(15-11)=0x0010, base 0x8000."""
        mock_socket.recv.return_value = _build_status_bytes(status_bits="8010")
        device = Mertik("192.168.1.100")
        assert device.is_igniting is True

    def test_status_bits_aux_on(self, mock_socket):
        """Bit 12 -> aux_on. In 16-bit: 2^(15-12)=0x0008, base 0x8000."""
        mock_socket.recv.return_value = _build_status_bytes(status_bits="8008")
        device = Mertik("192.168.1.100")
        assert device.is_aux_on is True

    def test_status_bits_light_on(self, mock_socket):
        """Bit 13 -> light_on. In 16-bit: 2^(15-13)=0x0004, base 0x8000."""
        mock_socket.recv.return_value = _build_status_bytes(status_bits="8004")
        device = Mertik("192.168.1.100")
        assert device.is_light_on is True

    def test_status_bits_all_clear(self, mock_socket):
        """All status bits clear -> all flags False."""
        mock_socket.recv.return_value = _build_status_bytes(status_bits="0000")
        device = Mertik("192.168.1.100")
        assert device.is_shutting_down is False
        assert device.is_igniting is False
        assert device.is_aux_on is False
        assert device.is_light_on is False

    def test_second_status_prefix_accepted(self, mock_socket):
        """The alternate prefix '030300000003' should also be parsed."""
        prefix = "030300000003"
        body = (
            "00"
            f"{0x80:02X}"
            "0000"
            f"{0x64:02X}"
            "00"
            "0"
            "00000"
            f"{0xE6:02X}"
        )
        raw = "\x02" + prefix + body
        mock_socket.recv.return_value = raw.encode("ascii")
        device = Mertik("192.168.1.100")
        assert device.is_on is True
        assert device.ambient_temperature == 23.0


class TestCommands:
    """Test command sending."""

    def test_standby_sends_correct_command(self, mertik_device, mock_socket):
        mock_socket.send.reset_mock()
        mertik_device.standBy()
        expected = bytearray.fromhex(send_command_prefix + "3136303003")
        mock_socket.send.assert_called_with(expected)

    def test_ignite_sends_correct_command(self, mertik_device, mock_socket):
        mock_socket.send.reset_mock()
        mertik_device.ignite_fireplace()
        expected = bytearray.fromhex(send_command_prefix + "314103")
        mock_socket.send.assert_called_with(expected)

    def test_aux_on_sends_correct_command(self, mertik_device, mock_socket):
        mock_socket.send.reset_mock()
        mertik_device.aux_on()
        expected = bytearray.fromhex(send_command_prefix + "32303031030a")
        mock_socket.send.assert_called_with(expected)

    def test_aux_off_sends_correct_command(self, mertik_device, mock_socket):
        mock_socket.send.reset_mock()
        mertik_device.aux_off()
        expected = bytearray.fromhex(send_command_prefix + "32303030030a")
        mock_socket.send.assert_called_with(expected)

    def test_light_on_sends_correct_command(self, mertik_device, mock_socket):
        mock_socket.send.reset_mock()
        mertik_device.light_on()
        expected = bytearray.fromhex(send_command_prefix + "3330303103")
        mock_socket.send.assert_called_with(expected)

    def test_light_off_sends_correct_command(self, mertik_device, mock_socket):
        mock_socket.send.reset_mock()
        mertik_device.light_off()
        expected = bytearray.fromhex(send_command_prefix + "3330303003")
        mock_socket.send.assert_called_with(expected)

    def test_refresh_status_sends_correct_command(self, mertik_device, mock_socket):
        mock_socket.send.reset_mock()
        mertik_device.refresh_status()
        expected = bytearray.fromhex(send_command_prefix + "303303")
        mock_socket.send.assert_called_with(expected)

    def test_guard_flame_off_sends_correct_command(self, mertik_device, mock_socket):
        mock_socket.send.reset_mock()
        mertik_device.guard_flame_off()
        expected = bytearray.fromhex(send_command_prefix + "313003")
        mock_socket.send.assert_called_with(expected)

    def test_set_eco_sends_correct_command(self, mertik_device, mock_socket):
        mock_socket.send.reset_mock()
        mertik_device.set_eco()
        expected = bytearray.fromhex(send_command_prefix + "4233303103")
        mock_socket.send.assert_called_with(expected)

    def test_set_manual_sends_correct_command(self, mertik_device, mock_socket):
        mock_socket.send.reset_mock()
        mertik_device.set_manual()
        expected = bytearray.fromhex(send_command_prefix + "423003")
        mock_socket.send.assert_called_with(expected)


class TestFlameHeight:
    """Test flame height commands."""

    def test_set_flame_height_step_1(self, mertik_device, mock_socket):
        mock_socket.send.reset_mock()
        mertik_device.set_flame_height(1)
        expected = bytearray.fromhex(send_command_prefix + "3136383003")
        assert mock_socket.send.call_args_list[0] == call(expected)

    def test_set_flame_height_step_12(self, mertik_device, mock_socket):
        mock_socket.send.reset_mock()
        mertik_device.set_flame_height(12)
        expected = bytearray.fromhex(send_command_prefix + "3136464603")
        assert mock_socket.send.call_args_list[0] == call(expected)

    def test_set_flame_height_step_6(self, mertik_device, mock_socket):
        mock_socket.send.reset_mock()
        mertik_device.set_flame_height(6)
        expected = bytearray.fromhex(send_command_prefix + "3136423903")
        assert mock_socket.send.call_args_list[0] == call(expected)

    def test_set_flame_height_calls_refresh(self, mertik_device, mock_socket):
        mock_socket.send.reset_mock()
        mertik_device.set_flame_height(1)
        refresh_cmd = bytearray.fromhex(send_command_prefix + "303303")
        assert mock_socket.send.call_args_list[1] == call(refresh_cmd)


class TestLightBrightness:
    """Test light brightness commands."""

    def test_brightness_max(self, mertik_device, mock_socket):
        """Brightness 255 -> device code 4642."""
        mock_socket.send.reset_mock()
        mertik_device.set_light_brightness(255)
        expected = bytearray.fromhex(send_command_prefix + "33304645464203")
        mock_socket.send.assert_called_with(expected)

    def test_brightness_min(self, mertik_device, mock_socket):
        """Brightness 1 -> device code 3633."""
        mock_socket.send.reset_mock()
        mertik_device.set_light_brightness(1)
        expected = bytearray.fromhex(send_command_prefix + "33304645363303")
        mock_socket.send.assert_called_with(expected)

    def test_brightness_mid(self, mertik_device, mock_socket):
        """Mid-range brightness should produce intermediate device code."""
        mock_socket.send.reset_mock()
        mertik_device.set_light_brightness(128)
        # Just verify it sends a command without error
        assert mock_socket.send.called


class TestSocketReconnection:
    """Test socket reconnection on errors."""

    def test_reconnects_on_socket_error(self, mock_socket):
        """Should reconnect and retry when send raises socket.error."""
        call_count = 0

        def side_effect(data):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise socket.error("Connection lost")

        mock_socket.send.side_effect = side_effect

        with patch("custom_components.mertik.mertik.socket.socket") as mock_cls:
            new_sock = MagicMock()
            new_sock.recv.return_value = _build_status_bytes()
            mock_cls.return_value = new_sock

            device = Mertik.__new__(Mertik)
            device.ip = "192.168.1.100"
            device.client = mock_socket
            device.refresh_status()

            new_sock.connect.assert_called_with(("192.168.1.100", 2000))

    def test_reconnects_on_empty_recv(self, mock_socket):
        """Should reconnect when recv returns empty bytes."""
        recv_count = 0

        def recv_side_effect(size):
            nonlocal recv_count
            recv_count += 1
            if recv_count == 1:
                return b""
            return _build_status_bytes()

        mock_socket.recv.side_effect = recv_side_effect

        with patch("custom_components.mertik.mertik.socket.socket") as mock_cls:
            new_sock = MagicMock()
            new_sock.recv.return_value = _build_status_bytes()
            mock_cls.return_value = new_sock

            device = Mertik.__new__(Mertik)
            device.ip = "192.168.1.100"
            device.client = mock_socket
            device.refresh_status()

            new_sock.connect.assert_called_with(("192.168.1.100", 2000))


class TestHelperMethods:
    """Test hex2bin and fromBitStatus helpers."""

    def test_hex2bin(self, mertik_device):
        assert mertik_device._Mertik__hex2bin("FF") == "11111111"
        assert mertik_device._Mertik__hex2bin("00") == "00000000"
        assert mertik_device._Mertik__hex2bin("80") == "10000000"
        assert mertik_device._Mertik__hex2bin("01") == "00000001"

    def test_from_bit_status(self, mertik_device):
        assert mertik_device._Mertik__fromBitStatus("FF", 0) is True
        assert mertik_device._Mertik__fromBitStatus("FF", 7) is True
        assert mertik_device._Mertik__fromBitStatus("00", 0) is False
        assert mertik_device._Mertik__fromBitStatus("80", 0) is True
        assert mertik_device._Mertik__fromBitStatus("80", 1) is False
