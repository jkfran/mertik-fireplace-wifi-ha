"""Tests for the Mertik hardware communication layer."""

from unittest.mock import MagicMock, patch, call

import pytest
import socket

from custom_components.mertik.mertik import (
    Mertik,
    COMMAND_PREFIX as send_command_prefix,
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
        """brightness=128 -> normalized=50 -> l=40 -> l+=1=41 -> code '4141'."""
        mock_socket.send.reset_mock()
        mertik_device.set_light_brightness(128)
        expected = bytearray.fromhex(send_command_prefix + "33304645414103")
        mock_socket.send.assert_called_with(expected)

    def test_brightness_skip_40(self, mertik_device, mock_socket):
        """When l reaches 40, it skips to 41 (the skip-40 quirk)."""
        # brightness where normalized=50 -> l=36+round(4.0)=40 -> 40>=40 -> l=41
        mock_socket.send.reset_mock()
        mertik_device.set_light_brightness(128)
        cmd_bytes = mock_socket.send.call_args[0][0]
        cmd_hex = cmd_bytes.hex()
        # The device code is after "33304645" prefix, extract it
        payload = cmd_hex[len(send_command_prefix):]
        # payload = "33304645XXYY03", device_code = payload[8:12]
        device_code = payload[8:12]
        assert device_code == "4141"  # 41 (skipped 40)

    def test_brightness_just_below_skip(self, mertik_device, mock_socket):
        """Brightness where l=39 (below skip threshold)."""
        # normalized = (b-1)/254*100, l = 36 + round(normalized/100*8)
        # l=39 -> round(normalized/100*8)=3 -> normalized=37.5 -> b=1+37.5*254/100=96.25
        # b=96: normalized=(95/254)*100=37.40, l=36+round(2.99)=36+3=39
        mock_socket.send.reset_mock()
        mertik_device.set_light_brightness(96)
        cmd_bytes = mock_socket.send.call_args[0][0]
        payload = cmd_bytes.hex()[len(send_command_prefix):]
        device_code = payload[8:12]
        assert device_code == "3939"  # 39 (no skip applied)

    def test_brightness_near_max(self, mertik_device, mock_socket):
        """Brightness 254 (just below max)."""
        # normalized=(253/254)*100=99.6, l=36+round(7.97)=36+8=44, >=40 so l=45
        mock_socket.send.reset_mock()
        mertik_device.set_light_brightness(254)
        cmd_bytes = mock_socket.send.call_args[0][0]
        payload = cmd_bytes.hex()[len(send_command_prefix):]
        device_code = payload[8:12]
        assert device_code == "4545"  # 45

    def test_brightness_low(self, mertik_device, mock_socket):
        """Brightness 2 -> very low normalized value."""
        # normalized=(1/254)*100=0.394, l=36+round(0.031)=36+0=36
        mock_socket.send.reset_mock()
        mertik_device.set_light_brightness(2)
        cmd_bytes = mock_socket.send.call_args[0][0]
        payload = cmd_bytes.hex()[len(send_command_prefix):]
        device_code = payload[8:12]
        assert device_code == "3636"  # 36 (no skip)


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

    def test_hex_to_bin(self, mertik_device):
        assert mertik_device._hex_to_bin("FF") == "11111111"
        assert mertik_device._hex_to_bin("00") == "00000000"
        assert mertik_device._hex_to_bin("80") == "10000000"
        assert mertik_device._hex_to_bin("01") == "00000001"

    def test_bit_at(self, mertik_device):
        assert mertik_device._bit_at("FF", 0) is True
        assert mertik_device._bit_at("FF", 7) is True
        assert mertik_device._bit_at("00", 0) is False
        assert mertik_device._bit_at("80", 0) is True
        assert mertik_device._bit_at("80", 1) is False


class TestNonStatusResponses:
    """Test that non-status responses don't alter device state."""

    def test_non_matching_prefix_ignored(self, mock_socket):
        """Response with unknown prefix should not update state."""
        # First init with known-good status (off)
        mock_socket.recv.return_value = _build_status_bytes(flame_height=0x00)
        device = Mertik("192.168.1.100")
        assert device.is_on is False

        # Now send a command that returns a non-status response
        mock_socket.recv.return_value = b"\x02XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
        device.refresh_status()

        # State should remain unchanged
        assert device.is_on is False
        assert device.get_flame_height() == 0

    def test_short_response_no_crash(self, mock_socket):
        """A short response that doesn't match prefix should not crash."""
        mock_socket.recv.return_value = _build_status_bytes()
        device = Mertik("192.168.1.100")

        # Short response - won't match any prefix
        mock_socket.recv.return_value = b"\x02OK"
        device.refresh_status()  # Should not raise

    def test_state_preserved_across_non_status(self, mock_socket):
        """State from a valid status should survive non-status responses."""
        # Set up with fireplace on, flame=7
        mock_socket.recv.return_value = _build_status_bytes(flame_height=0xC0)
        device = Mertik("192.168.1.100")
        assert device.is_on is True
        assert device.get_flame_height() == 7

        # Non-status response
        mock_socket.recv.return_value = b"\x02ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ"
        device.refresh_status()

        # Previous state preserved
        assert device.is_on is True
        assert device.get_flame_height() == 7


class TestAllFlameHeightSteps:
    """Test every flame height step sends the correct hex code."""

    EXPECTED_STEPS = [
        (1, "3830"), (2, "3842"), (3, "3937"), (4, "4132"),
        (5, "4145"), (6, "4239"), (7, "4335"), (8, "4430"),
        (9, "4443"), (10, "4537"), (11, "4633"), (12, "4646"),
    ]

    @pytest.mark.parametrize("step,hex_code", EXPECTED_STEPS)
    def test_flame_step(self, mertik_device, mock_socket, step, hex_code):
        mock_socket.send.reset_mock()
        mertik_device.set_flame_height(step)
        expected = bytearray.fromhex(send_command_prefix + "3136" + hex_code + "03")
        assert mock_socket.send.call_args_list[0] == call(expected)


class TestBrightnessEdgeCases:
    """Test light brightness edge cases for safe refactoring."""

    def test_light_level_below_100_clamps_to_zero(self, mock_socket):
        """Light level below 100 with light on should clamp brightness to 0."""
        # 0x50 = 80, brightness = round(((80-100)/151)*255) = -34, clamped to 0
        mock_socket.recv.return_value = _build_status_bytes(
            light_level=0x50, status_bits="8004"  # light on
        )
        device = Mertik("192.168.1.100")
        assert device.light_brightness == 0

    def test_light_level_mid_range(self, mock_socket):
        """Light level in mid range with light on."""
        # 0xAF = 175, brightness = round(((175-100)/151)*255) = round(126.6) = 127
        mock_socket.recv.return_value = _build_status_bytes(
            light_level=0xAF, status_bits="8004"
        )
        device = Mertik("192.168.1.100")
        assert device.light_brightness == 127


class TestGuardFlame:
    """Test the guard flame internal attribute."""

    def test_guard_flame_on(self, mock_socket):
        """Bit 8 -> _guard_flame_on. In 16-bit: 2^(15-8)=0x0080, base 0x8000."""
        mock_socket.recv.return_value = _build_status_bytes(status_bits="8080")
        device = Mertik("192.168.1.100")
        assert device._guard_flame_on is True

    def test_guard_flame_off(self, mock_socket):
        mock_socket.recv.return_value = _build_status_bytes(status_bits="8000")
        device = Mertik("192.168.1.100")
        assert device._guard_flame_on is False


class TestStateTransitions:
    """Test that state updates correctly across multiple status responses."""

    def test_off_to_on(self, mock_socket):
        """State should transition from off to on."""
        mock_socket.recv.return_value = _build_status_bytes(flame_height=0x00)
        device = Mertik("192.168.1.100")
        assert device.is_on is False

        mock_socket.recv.return_value = _build_status_bytes(flame_height=0xC0)
        device.refresh_status()
        assert device.is_on is True
        assert device.get_flame_height() == 7

    def test_on_to_off(self, mock_socket):
        """State should transition from on to off."""
        mock_socket.recv.return_value = _build_status_bytes(flame_height=0xC0)
        device = Mertik("192.168.1.100")
        assert device.is_on is True

        mock_socket.recv.return_value = _build_status_bytes(flame_height=0x00)
        device.refresh_status()
        assert device.is_on is False
        assert device.get_flame_height() == 0

    def test_temperature_updates(self, mock_socket):
        """Temperature should update on each status response."""
        mock_socket.recv.return_value = _build_status_bytes(ambient_temp=0xC8)
        device = Mertik("192.168.1.100")
        assert device.ambient_temperature == 20.0

        mock_socket.recv.return_value = _build_status_bytes(ambient_temp=0xFA)
        device.refresh_status()
        assert device.ambient_temperature == 25.0

    def test_all_properties_update_together(self, mock_socket):
        """All parsed properties should update from a single status response."""
        mock_socket.recv.return_value = _build_status_bytes(
            flame_height=0xC0,
            status_bits="801C",  # igniting + aux + light on
            light_level=0xFB,
            ambient_temp=0xE6,
        )
        device = Mertik("192.168.1.100")

        assert device.is_on is True
        assert device.get_flame_height() == 7
        assert device.is_igniting is True
        assert device.is_aux_on is True
        assert device.is_light_on is True
        assert device.light_brightness == 255
        assert device.ambient_temperature == 23.0

        # Now update everything at once
        mock_socket.recv.return_value = _build_status_bytes(
            flame_height=0x00,
            status_bits="8000",  # all off
            light_level=0x64,
            ambient_temp=0xC8,
        )
        device.refresh_status()

        assert device.is_on is False
        assert device.get_flame_height() == 0
        assert device.is_igniting is False
        assert device.is_aux_on is False
        assert device.is_light_on is False
        assert device.light_brightness == 0
        assert device.ambient_temperature == 20.0
