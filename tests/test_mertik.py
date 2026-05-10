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
        """Startup sends CMD_STATUS as part of the handshake sequence."""
        device = Mertik("192.168.1.50")
        refresh_cmd = bytearray.fromhex(send_command_prefix + "303303")
        # Startup sends multiple commands; STATUS is one of them
        mock_socket.send.assert_any_call(refresh_cmd)


class TestStatusParsing:
    """Test _process_status parsing of status responses."""

    def test_fireplace_off_when_flame_byte_low(self, mock_socket):
        """Flame byte <= 0x7B means burner off."""
        mock_socket.recv.return_value = _build_status_bytes(on_flag="00", flame_byte=0x00)
        device = Mertik("192.168.1.100")
        assert device.is_on is False
        assert device.flame_on is False

    def test_fireplace_on_when_flame_byte_high(self, mock_socket):
        """Flame byte > 0x7B and on_flag=FF means fire is on."""
        mock_socket.recv.return_value = _build_status_bytes(on_flag="FF", flame_byte=0x8F)
        device = Mertik("192.168.1.100")
        assert device.is_on is True
        assert device.flame_on is True

    def test_flame_byte_boundary(self, mock_socket):
        """0x7B=123 is exactly on the boundary — still off."""
        mock_socket.recv.return_value = _build_status_bytes(on_flag="00", flame_byte=0x7B)
        device = Mertik("192.168.1.100")
        assert device.flame_on is False

    def test_ambient_temperature(self, mock_socket):
        """0xE6=230 -> 230/10 = 23.0°C."""
        mock_socket.recv.return_value = _build_status_bytes(ambient_temp=0xE6)
        device = Mertik("192.168.1.100")
        assert device.ambient_temperature == 23.0

    def test_ambient_temperature_different_value(self, mock_socket):
        """0xC8=200 -> 200/10 = 20.0°C."""
        mock_socket.recv.return_value = _build_status_bytes(ambient_temp=0xC8)
        device = Mertik("192.168.1.100")
        assert device.ambient_temperature == 20.0

    def test_status_bits_shutting_down(self, mock_socket):
        """Bit 7 -> shutting_down. 0x80|0x01=0x81 in high byte -> 0x0100 in 16-bit."""
        mock_socket.recv.return_value = _build_status_bytes(status_hi="81", flame_byte=0x00)
        device = Mertik("192.168.1.100")
        assert device.is_shutting_down is True

    def test_status_bits_igniting(self, mock_socket):
        """Bit 11 -> igniting. 0x0010 in 16-bit value: carried in flame_byte=0x10."""
        # 16-bit field = (0x80 << 8) | 0x10 = 0x8010; bit[11] = 1
        mock_socket.recv.return_value = _build_status_bytes(status_hi="80", flame_byte=0x10)
        device = Mertik("192.168.1.100")
        assert device.is_igniting is True

    def test_status_bits_all_clear(self, mock_socket):
        """All status bits clear -> all flags False."""
        mock_socket.recv.return_value = _build_status_bytes(status_hi="80", flame_byte=0x00)
        device = Mertik("192.168.1.100")
        assert device.is_shutting_down is False
        assert device.is_igniting is False

    def test_second_status_prefix_accepted(self, mock_socket):
        """The alternate prefix '030300000003' should also be parsed."""
        prefix = "030300000003"
        config = "C6"
        on_flag = "FF"
        status_bits = "808F"
        light = "00"
        filler = "04000000"
        temp = "E6"
        room = "DC" + "4C6976696E6720526F6F6D20" + "FF" * 20 + "043001"
        body = config + on_flag + status_bits + light + filler + temp + room
        raw = "\x02" + prefix + body
        mock_socket.recv.return_value = raw.encode("ascii")
        device = Mertik("192.168.1.100")
        assert device.is_on is True
        assert device.ambient_temperature == 23.0

    def test_falling_edge_resets_local_state(self, mock_socket):
        """flame_on True->False (falling edge) resets _local_aux and flameHeight."""
        # Start with fire on
        mock_socket.recv.return_value = _build_status_bytes(on_flag="FF", flame_byte=0x8F)
        device = Mertik("192.168.1.100")
        device._local_aux = True
        device.flameHeight = 8
        device.flame_on = True
        device._prev_flame_on = True
        # Now fire turns off (falling edge)
        mock_socket.recv.return_value = _build_status_bytes(on_flag="00", flame_byte=0x00)
        device.refresh_status()
        assert device.flame_on is False
        assert device._local_aux is False
        assert device.flameHeight == 0

    def test_no_reset_during_ignition_transitional(self, mock_socket):
        """Transitional low flame during ignition (False->False) preserves local state."""
        mock_socket.recv.return_value = _build_status_bytes(on_flag="00", flame_byte=0x00)
        device = Mertik("192.168.1.100")
        # Simulate ignite having set local state
        device._local_aux = True
        device.flameHeight = 1
        device.flame_on = False
        device._prev_flame_on = False
        # Transitional packet during ignition — flame still below threshold
        mock_socket.recv.return_value = _build_status_bytes(on_flag="00", flame_byte=0x1F)
        device.refresh_status()
        # Not a falling edge -> local state preserved
        assert device._local_aux is True
        assert device.flameHeight == 1


class TestCommands:
    """Test command sending."""

    def test_standby_sends_correct_command(self, mertik_device, mock_socket):
        mock_socket.send.reset_mock()
        mertik_device.standBy()
        expected = bytearray.fromhex(send_command_prefix + "3136303003")
        mock_socket.send.assert_called_with(expected)

    def test_ignite_sends_ignite_then_aux_on(self, mertik_device, mock_socket):
        """ignite_fireplace sends IGNITE then immediately AUX_ON."""
        mock_socket.send.reset_mock()
        mertik_device.ignite_fireplace()
        calls = mock_socket.send.call_args_list
        assert calls[0] == call(bytearray.fromhex(send_command_prefix + "314103"))
        assert calls[1] == call(bytearray.fromhex(send_command_prefix + "32303031030a"))

    def test_ignite_sets_local_aux_and_flame(self, mertik_device, mock_socket):
        """ignite_fireplace sets _local_aux=True and flameHeight=1."""
        mertik_device.ignite_fireplace()
        assert mertik_device._local_aux is True
        assert mertik_device.flameHeight == 1

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
    """Test flame height commands and local tracking."""

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

    def test_flame_height_tracked_locally(self, mertik_device, mock_socket):
        """flameHeight is updated from the command, not the status packet."""
        mertik_device.set_flame_height(7)
        assert mertik_device.get_flame_height() == 7

    def test_flame_height_step_13_maps_to_table_max(self, mertik_device, mock_socket):
        """Step 13 clamps to table index 11 (code 4646 = 0xFF)."""
        mock_socket.send.reset_mock()
        mertik_device.set_flame_height(13)
        expected = bytearray.fromhex(send_command_prefix + "3136464603")
        assert mock_socket.send.call_args_list[0] == call(expected)


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
        """When l reaches 40 it skips to 41 (device quirk)."""
        mock_socket.send.reset_mock()
        mertik_device.set_light_brightness(128)
        cmd_bytes = mock_socket.send.call_args[0][0]
        payload = cmd_bytes.hex()[len(send_command_prefix):]
        device_code = payload[8:12]
        assert device_code == "4141"

    def test_brightness_just_below_skip(self, mertik_device, mock_socket):
        """Brightness where l=39 (below skip threshold)."""
        mock_socket.send.reset_mock()
        mertik_device.set_light_brightness(96)
        cmd_bytes = mock_socket.send.call_args[0][0]
        payload = cmd_bytes.hex()[len(send_command_prefix):]
        device_code = payload[8:12]
        assert device_code == "3939"


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
            # Initialise all attributes that _process_status needs
            device.on = False
            device.flame_on = False
            device._prev_flame_on = False
            device._local_aux = False
            device.flameHeight = 0
            device._shutting_down = False
            device._guard_flame_on = False
            device._igniting = False
            device._ambient_temperature = 0.0
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
            # Initialise all attributes that _process_status needs
            device.on = False
            device.flame_on = False
            device._prev_flame_on = False
            device._local_aux = False
            device.flameHeight = 0
            device._shutting_down = False
            device._guard_flame_on = False
            device._igniting = False
            device._ambient_temperature = 0.0
            device.refresh_status()

            new_sock.connect.assert_called_with(("192.168.1.100", 2000))


class TestHelperMethods:
    """Test _hex_to_bin and _bit_at helpers."""

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
    """Test that non-status responses don't corrupt device state."""

    def test_non_matching_prefix_ignored(self, mock_socket):
        """Response with unknown prefix leaves state unchanged."""
        mock_socket.recv.return_value = _build_status_bytes(on_flag="00", flame_byte=0x00)
        device = Mertik("192.168.1.100")
        assert device.is_on is False

        mock_socket.recv.return_value = b"\x02XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
        device.refresh_status()
        assert device.is_on is False

    def test_short_response_no_crash(self, mock_socket):
        """A short response that doesn't match any prefix should not crash."""
        mock_socket.recv.return_value = _build_status_bytes()
        device = Mertik("192.168.1.100")

        mock_socket.recv.return_value = b"\x02OK"
        device.refresh_status()  # Must not raise

    def test_state_preserved_across_non_status(self, mock_socket):
        """Valid state survives a non-status response."""
        mock_socket.recv.return_value = _build_status_bytes(on_flag="FF", flame_byte=0x8F)
        device = Mertik("192.168.1.100")
        assert device.is_on is True

        mock_socket.recv.return_value = b"\x02ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ"
        device.refresh_status()
        assert device.is_on is True


class TestStateTransitions:
    """Test that state updates correctly across multiple status responses."""

    def test_off_to_on(self, mock_socket):
        mock_socket.recv.return_value = _build_status_bytes(on_flag="00", flame_byte=0x00)
        device = Mertik("192.168.1.100")
        assert device.is_on is False

        mock_socket.recv.return_value = _build_status_bytes(on_flag="FF", flame_byte=0x8F)
        device.refresh_status()
        assert device.is_on is True
        assert device.flame_on is True

    def test_on_to_off(self, mock_socket):
        mock_socket.recv.return_value = _build_status_bytes(on_flag="FF", flame_byte=0x8F)
        device = Mertik("192.168.1.100")
        assert device.is_on is True

        mock_socket.recv.return_value = _build_status_bytes(on_flag="00", flame_byte=0x00)
        device.refresh_status()
        assert device.is_on is False
        assert device.flame_on is False

    def test_temperature_updates(self, mock_socket):
        mock_socket.recv.return_value = _build_status_bytes(ambient_temp=0xC8)
        device = Mertik("192.168.1.100")
        assert device.ambient_temperature == 20.0

        mock_socket.recv.return_value = _build_status_bytes(ambient_temp=0xFA)
        device.refresh_status()
        assert device.ambient_temperature == 25.0


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
