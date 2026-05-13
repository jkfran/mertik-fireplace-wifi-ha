"""Tests for the Mertik hardware communication layer."""

import asyncio
from unittest.mock import MagicMock, AsyncMock, patch, call

import pytest

from custom_components.mertik.mertik import (
    Mertik,
    COMMAND_PREFIX as send_command_prefix,
)
from tests.conftest import _build_status_bytes


class TestMertikInit:
    """Test Mertik class initialization."""

    async def test_connects_to_correct_host_and_port(self, mock_connection):
        await Mertik.async_connect("192.168.1.50")
        mock_connection.assert_called_with("192.168.1.50", 2000)

    async def test_calls_refresh_on_init(self, mock_connection, mock_writer):
        """Startup sends CMD_STATUS as part of the handshake sequence."""
        await Mertik.async_connect("192.168.1.50")
        refresh_cmd = bytearray.fromhex(send_command_prefix + "303303")
        mock_writer.write.assert_any_call(refresh_cmd)


class TestStatusParsing:
    """Test _process_status parsing of status responses."""

    async def test_fireplace_off_when_flame_byte_low(self, mock_connection, mock_reader):
        """Flame byte <= 0x7B means burner off."""
        mock_reader.read.return_value = _build_status_bytes(
            on_flag="00", flame_byte=0x00
        )
        device = await Mertik.async_connect("192.168.1.100")
        assert device.is_on is False
        assert device.flame_on is False

    async def test_fireplace_on_when_flame_byte_high(self, mock_connection, mock_reader):
        """Flame byte > 0x7B and on_flag=FF means fire is on."""
        mock_reader.read.return_value = _build_status_bytes(
            on_flag="FF", flame_byte=0x8F
        )
        device = await Mertik.async_connect("192.168.1.100")
        assert device.is_on is True
        assert device.flame_on is True

    async def test_flame_byte_boundary(self, mock_connection, mock_reader):
        """0x7B=123 is exactly on the boundary — still off."""
        mock_reader.read.return_value = _build_status_bytes(
            on_flag="00", flame_byte=0x7B
        )
        device = await Mertik.async_connect("192.168.1.100")
        assert device.flame_on is False

    async def test_ambient_temperature(self, mock_connection, mock_reader):
        """0xE6=230 -> 230/10 = 23.0°C."""
        mock_reader.read.return_value = _build_status_bytes(ambient_temp=0xE6)
        device = await Mertik.async_connect("192.168.1.100")
        assert device.ambient_temperature == 23.0

    async def test_ambient_temperature_different_value(self, mock_connection, mock_reader):
        """0xC8=200 -> 200/10 = 20.0°C."""
        mock_reader.read.return_value = _build_status_bytes(ambient_temp=0xC8)
        device = await Mertik.async_connect("192.168.1.100")
        assert device.ambient_temperature == 20.0

    async def test_status_bits_shutting_down(self, mock_connection, mock_reader):
        """Bit 7 -> shutting_down. 0x80|0x01=0x81 in high byte -> 0x0100 in 16-bit."""
        mock_reader.read.return_value = _build_status_bytes(
            status_hi="81", flame_byte=0x00
        )
        device = await Mertik.async_connect("192.168.1.100")
        assert device.is_shutting_down is True

    async def test_status_bits_igniting(self, mock_connection, mock_reader):
        """Bit 11 -> igniting. 0x0010 in 16-bit value: carried in flame_byte=0x10."""
        # 16-bit field = (0x80 << 8) | 0x10 = 0x8010; bit[11] = 1
        mock_reader.read.return_value = _build_status_bytes(
            status_hi="80", flame_byte=0x10
        )
        device = await Mertik.async_connect("192.168.1.100")
        assert device.is_igniting is True

    async def test_status_bits_all_clear(self, mock_connection, mock_reader):
        """All status bits clear -> all flags False."""
        mock_reader.read.return_value = _build_status_bytes(
            status_hi="80", flame_byte=0x00
        )
        device = await Mertik.async_connect("192.168.1.100")
        assert device.is_shutting_down is False
        assert device.is_igniting is False

    async def test_second_status_prefix_accepted(self, mock_connection, mock_reader):
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
        mock_reader.read.return_value = raw.encode("ascii")
        device = await Mertik.async_connect("192.168.1.100")
        assert device.is_on is True
        assert device.ambient_temperature == 23.0

    async def test_falling_edge_resets_local_state(self, mock_connection, mock_reader):
        """flame_on True->False (falling edge) resets _local_aux and flameHeight."""
        # Start with fire on
        mock_reader.read.return_value = _build_status_bytes(
            on_flag="FF", flame_byte=0x8F
        )
        device = await Mertik.async_connect("192.168.1.100")
        device._local_aux = True
        device.flameHeight = 8
        device.flame_on = True
        device._prev_flame_on = True
        # Now fire turns off (falling edge)
        mock_reader.read.return_value = _build_status_bytes(
            on_flag="00", flame_byte=0x00
        )
        await device.refresh_status()
        assert device.flame_on is False
        assert device._local_aux is False
        assert device.flameHeight == 0

    async def test_no_reset_during_ignition_transitional(
        self, mock_connection, mock_reader
    ):
        """Transitional low flame during ignition (False->False) preserves local state."""
        mock_reader.read.return_value = _build_status_bytes(
            on_flag="00", flame_byte=0x00
        )
        device = await Mertik.async_connect("192.168.1.100")
        # Simulate ignite having set local state
        device._local_aux = True
        device.flameHeight = 1
        device.flame_on = False
        device._prev_flame_on = False
        # Transitional packet during ignition — flame still below threshold
        mock_reader.read.return_value = _build_status_bytes(
            on_flag="00", flame_byte=0x1F
        )
        await device.refresh_status()
        # Not a falling edge -> local state preserved
        assert device._local_aux is True
        assert device.flameHeight == 1


class TestModeByteAndFaultCodeParsing:
    """Test mode byte parsing from the status packet.

    The fault_code property currently reflects the mode byte at [24:26]
    (0x00=manual, 0x20=thermostatic active). Fault codes proper are not yet
    located — they appear to arrive in a separate packet type.
    """

    async def test_mode_byte_zero_by_default(self, mock_connection, mock_reader):
        mock_reader.read.return_value = _build_status_bytes(fault_code=0x00)
        device = await Mertik.async_connect("192.168.1.100")
        assert device.fault_code == 0

    async def test_mode_byte_thermostatic_active(self, mock_connection, mock_reader):
        mock_reader.read.return_value = _build_status_bytes(fault_code=0x20)
        device = await Mertik.async_connect("192.168.1.100")
        assert device.fault_code == 0x20

    async def test_mode_byte_arbitrary_value(self, mock_connection, mock_reader):
        mock_reader.read.return_value = _build_status_bytes(fault_code=0x04)
        device = await Mertik.async_connect("192.168.1.100")
        assert device.fault_code == 4

    async def test_mode_byte_updates_on_subsequent_packet(
        self, mock_connection, mock_reader
    ):
        mock_reader.read.return_value = _build_status_bytes(fault_code=0x20)
        device = await Mertik.async_connect("192.168.1.100")
        assert device.fault_code == 0x20
        mock_reader.read.return_value = _build_status_bytes(fault_code=0x00)
        await device.refresh_status()
        assert device.fault_code == 0


class TestCommands:
    """Test command sending."""

    async def test_standby_sends_correct_command(self, mertik_device, mock_writer):
        mock_writer.write.reset_mock()
        await mertik_device.standBy()
        expected = bytearray.fromhex(send_command_prefix + "3136303003")
        mock_writer.write.assert_called_with(expected)

    async def test_ignite_sends_ignite_then_aux_on(self, mertik_device, mock_writer):
        """ignite_fireplace sends IGNITE then immediately AUX_ON."""
        mock_writer.write.reset_mock()
        await mertik_device.ignite_fireplace()
        calls = mock_writer.write.call_args_list
        assert calls[0] == call(bytearray.fromhex(send_command_prefix + "314103"))
        assert calls[1] == call(bytearray.fromhex(send_command_prefix + "32303031030a"))

    async def test_ignite_sets_local_aux_and_flame(self, mertik_device):
        """ignite_fireplace sets _local_aux=True and flameHeight=1."""
        await mertik_device.ignite_fireplace()
        assert mertik_device._local_aux is True
        assert mertik_device.flameHeight == 1

    async def test_aux_on_sends_correct_command(self, mertik_device, mock_writer):
        mock_writer.write.reset_mock()
        await mertik_device.aux_on()
        expected = bytearray.fromhex(send_command_prefix + "32303031030a")
        mock_writer.write.assert_called_with(expected)

    async def test_aux_off_sends_correct_command(self, mertik_device, mock_writer):
        mock_writer.write.reset_mock()
        await mertik_device.aux_off()
        expected = bytearray.fromhex(send_command_prefix + "32303030030a")
        mock_writer.write.assert_called_with(expected)

    async def test_light_on_sends_correct_command(self, mertik_device, mock_writer):
        mock_writer.write.reset_mock()
        await mertik_device.light_on()
        expected = bytearray.fromhex(send_command_prefix + "3330303103")
        mock_writer.write.assert_called_with(expected)

    async def test_light_off_sends_correct_command(self, mertik_device, mock_writer):
        mock_writer.write.reset_mock()
        await mertik_device.light_off()
        expected = bytearray.fromhex(send_command_prefix + "3330303003")
        mock_writer.write.assert_called_with(expected)

    async def test_refresh_status_sends_correct_command(self, mertik_device, mock_writer):
        mock_writer.write.reset_mock()
        await mertik_device.refresh_status()
        expected = bytearray.fromhex(send_command_prefix + "303303")
        mock_writer.write.assert_called_with(expected)

    async def test_guard_flame_off_sends_correct_command(
        self, mertik_device, mock_writer
    ):
        mock_writer.write.reset_mock()
        await mertik_device.guard_flame_off()
        expected = bytearray.fromhex(send_command_prefix + "313003")
        mock_writer.write.assert_called_with(expected)

    async def test_set_eco_sends_correct_command(self, mertik_device, mock_writer):
        mock_writer.write.reset_mock()
        await mertik_device.set_eco()
        expected = bytearray.fromhex(send_command_prefix + "4233303103")
        mock_writer.write.assert_called_with(expected)

    async def test_set_manual_sends_correct_command(self, mertik_device, mock_writer):
        mock_writer.write.reset_mock()
        await mertik_device.set_manual()
        expected = bytearray.fromhex(send_command_prefix + "423003")
        mock_writer.write.assert_called_with(expected)


class TestFlameHeight:
    """Test flame height commands and local tracking."""

    async def test_set_flame_height_step_1(self, mertik_device, mock_writer):
        mock_writer.write.reset_mock()
        await mertik_device.set_flame_height(1)
        expected = bytearray.fromhex(send_command_prefix + "3136383003")
        assert mock_writer.write.call_args_list[0] == call(expected)

    async def test_set_flame_height_step_12(self, mertik_device, mock_writer):
        mock_writer.write.reset_mock()
        await mertik_device.set_flame_height(12)
        expected = bytearray.fromhex(send_command_prefix + "3136464603")
        assert mock_writer.write.call_args_list[0] == call(expected)

    async def test_set_flame_height_step_6(self, mertik_device, mock_writer):
        mock_writer.write.reset_mock()
        await mertik_device.set_flame_height(6)
        expected = bytearray.fromhex(send_command_prefix + "3136423903")
        assert mock_writer.write.call_args_list[0] == call(expected)

    async def test_set_flame_height_calls_refresh(self, mertik_device, mock_writer):
        mock_writer.write.reset_mock()
        await mertik_device.set_flame_height(1)
        refresh_cmd = bytearray.fromhex(send_command_prefix + "303303")
        assert mock_writer.write.call_args_list[1] == call(refresh_cmd)

    async def test_flame_height_tracked_locally(self, mertik_device):
        """flameHeight is updated from the command, not the status packet."""
        await mertik_device.set_flame_height(7)
        assert mertik_device.get_flame_height() == 7

    async def test_flame_height_step_13_maps_to_table_max(
        self, mertik_device, mock_writer
    ):
        """Step 13 clamps to table index 11 (code 4646 = 0xFF)."""
        mock_writer.write.reset_mock()
        await mertik_device.set_flame_height(13)
        expected = bytearray.fromhex(send_command_prefix + "3136464603")
        assert mock_writer.write.call_args_list[0] == call(expected)


class TestLightBrightness:
    """Test light brightness commands."""

    async def test_brightness_max(self, mertik_device, mock_writer):
        """Brightness 255 -> device code 4642."""
        mock_writer.write.reset_mock()
        await mertik_device.set_light_brightness(255)
        expected = bytearray.fromhex(send_command_prefix + "33304645464203")
        mock_writer.write.assert_called_with(expected)

    async def test_brightness_min(self, mertik_device, mock_writer):
        """Brightness 1 -> device code 3633."""
        mock_writer.write.reset_mock()
        await mertik_device.set_light_brightness(1)
        expected = bytearray.fromhex(send_command_prefix + "33304645363303")
        mock_writer.write.assert_called_with(expected)

    async def test_brightness_mid(self, mertik_device, mock_writer):
        """brightness=128 -> normalized=50 -> l=40 -> l+=1=41 -> code '4141'."""
        mock_writer.write.reset_mock()
        await mertik_device.set_light_brightness(128)
        expected = bytearray.fromhex(send_command_prefix + "33304645414103")
        mock_writer.write.assert_called_with(expected)

    async def test_brightness_skip_40(self, mertik_device, mock_writer):
        """When l reaches 40 it skips to 41 (device quirk)."""
        mock_writer.write.reset_mock()
        await mertik_device.set_light_brightness(128)
        cmd_bytes = mock_writer.write.call_args[0][0]
        payload = cmd_bytes.hex()[len(send_command_prefix):]
        device_code = payload[8:12]
        assert device_code == "4141"

    async def test_brightness_just_below_skip(self, mertik_device, mock_writer):
        """Brightness where l=39 (below skip threshold)."""
        mock_writer.write.reset_mock()
        await mertik_device.set_light_brightness(96)
        cmd_bytes = mock_writer.write.call_args[0][0]
        payload = cmd_bytes.hex()[len(send_command_prefix):]
        device_code = payload[8:12]
        assert device_code == "3939"


class TestSocketReconnection:
    """Test reconnection on errors."""

    def _make_device(self, mock_reader, mock_writer):
        device = Mertik.__new__(Mertik)
        device.ip = "192.168.1.100"
        device._reader = mock_reader
        device._writer = mock_writer
        device.on = False
        device.flame_on = False
        device._prev_flame_on = False
        device._local_aux = False
        device.flameHeight = 0
        device._shutting_down = False
        device._guard_flame_on = False
        device._igniting = False
        device._ambient_temperature = 0.0
        device._fault_code = 0
        return device

    async def test_reconnects_on_oserror(self, mock_reader, mock_writer):
        """Should reconnect and retry when write raises OSError."""
        call_count = 0

        def write_side_effect(data):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("Connection lost")

        mock_writer.write.side_effect = write_side_effect

        new_reader = AsyncMock()
        new_writer = MagicMock()
        new_writer.drain = AsyncMock()
        new_writer.wait_closed = AsyncMock()
        new_reader.read.return_value = _build_status_bytes()

        with patch(
            "custom_components.mertik.mertik.asyncio.open_connection",
            new_callable=AsyncMock,
            return_value=(new_reader, new_writer),
        ) as mock_open, patch(
            "custom_components.mertik.mertik.asyncio.sleep", new_callable=AsyncMock
        ):
            device = self._make_device(mock_reader, mock_writer)
            await device.refresh_status()
            mock_open.assert_called_with("192.168.1.100", 2000)

    async def test_reconnects_on_empty_recv(self, mock_reader, mock_writer):
        """Should reconnect when read returns empty bytes."""
        recv_count = 0

        async def read_side_effect(size):
            nonlocal recv_count
            recv_count += 1
            if recv_count == 1:
                return b""
            return _build_status_bytes()

        mock_reader.read.side_effect = read_side_effect

        new_reader = AsyncMock()
        new_writer = MagicMock()
        new_writer.drain = AsyncMock()
        new_writer.wait_closed = AsyncMock()
        new_reader.read.return_value = _build_status_bytes()

        with patch(
            "custom_components.mertik.mertik.asyncio.open_connection",
            new_callable=AsyncMock,
            return_value=(new_reader, new_writer),
        ) as mock_open, patch(
            "custom_components.mertik.mertik.asyncio.sleep", new_callable=AsyncMock
        ):
            device = self._make_device(mock_reader, mock_writer)
            await device.refresh_status()
            mock_open.assert_called_with("192.168.1.100", 2000)


class TestProperties:
    async def test_is_flame_on_true_when_flame_on(self, mock_connection, mock_reader):
        mock_reader.read.return_value = _build_status_bytes(
            on_flag="FF", flame_byte=0x8F
        )
        device = await Mertik.async_connect("192.168.1.100")
        assert device.is_flame_on is True

    async def test_is_aux_on_false_when_flame_off(self, mertik_device):
        mertik_device._local_aux = True
        mertik_device.flame_on = False
        assert mertik_device.is_aux_on is False

    async def test_close_success(self, mertik_device, mock_writer):
        await mertik_device.close()
        mock_writer.close.assert_called_once()

    async def test_close_swallows_oserror(self, mertik_device, mock_writer):
        mock_writer.close.side_effect = OSError("Connection reset")
        await mertik_device.close()  # must not raise

    async def test_set_thermostat_sends_command(self, mertik_device, mock_writer):
        mock_writer.write.reset_mock()
        await mertik_device.set_thermostat(20.0)
        # 20.0°C * 2 = 40 half-degrees = 0x28
        assert mock_writer.write.called
        payload = mock_writer.write.call_args[0][0].hex()
        assert "4231" in payload  # CMD_THERMOSTAT_PREFIX
        assert "28" in payload  # 0x28 for 20.0°C

    async def test_set_thermostat_clamps_to_min(self, mertik_device, mock_writer):
        mock_writer.write.reset_mock()
        await mertik_device.set_thermostat(1.0)  # below MIN of 5.0
        assert mock_writer.write.called

    async def test_set_thermostat_clamps_to_max(self, mertik_device, mock_writer):
        mock_writer.write.reset_mock()
        await mertik_device.set_thermostat(40.0)  # above MAX of 36.0
        assert mock_writer.write.called


class TestSendCommandEdgeCases:
    def _make_device(self, mock_reader, mock_writer):
        device = Mertik.__new__(Mertik)
        device.ip = "192.168.1.100"
        device._reader = mock_reader
        device._writer = mock_writer
        device.on = False
        device.flame_on = False
        device._prev_flame_on = False
        device._local_aux = False
        device.flameHeight = 0
        device._shutting_down = False
        device._guard_flame_on = False
        device._igniting = False
        device._ambient_temperature = 0.0
        device._fault_code = 0
        return device

    async def test_timeout_on_recv_returns_gracefully(self, mertik_device, mock_reader):
        mock_reader.read.side_effect = asyncio.TimeoutError
        await mertik_device.refresh_status()  # must not raise
        assert mertik_device.on is False

    async def test_send_fails_after_reconnect_returns_gracefully(
        self, mertik_device, mock_writer
    ):
        mock_writer.write.side_effect = OSError("Connection lost")
        with patch.object(mertik_device, "_reconnect", new_callable=AsyncMock):
            await mertik_device.refresh_status()  # logs error and returns

    async def test_reconnect_close_exception_swallowed(
        self, mertik_device, mock_writer
    ):
        mock_writer.close.side_effect = Exception("Close failed")
        new_reader = AsyncMock()
        new_writer = MagicMock()
        new_writer.drain = AsyncMock()
        new_writer.wait_closed = AsyncMock()
        new_reader.read.return_value = _build_status_bytes()
        with patch(
            "custom_components.mertik.mertik.asyncio.open_connection",
            new_callable=AsyncMock,
            return_value=(new_reader, new_writer),
        ), patch(
            "custom_components.mertik.mertik.asyncio.sleep", new_callable=AsyncMock
        ):
            await mertik_device._reconnect()  # close exception must be swallowed

    async def test_error_during_reconnect_recv_returns_gracefully(
        self, mertik_device, mock_reader
    ):
        recv_count = 0

        async def read_side_effect(size):
            nonlocal recv_count
            recv_count += 1
            if recv_count == 1:
                return b""  # empty recv triggers the reconnect path
            raise asyncio.TimeoutError

        mock_reader.read.side_effect = read_side_effect
        with patch.object(mertik_device, "_reconnect", new_callable=AsyncMock):
            await mertik_device.refresh_status()  # must not raise


class TestStatusParsingEdgeCases:
    async def test_short_status_packet_returns_early(self, mertik_device):
        mertik_device._process_status("SHORT")  # < 32 chars, must not raise
        assert mertik_device.on is False

    async def test_invalid_flame_byte_no_crash(self, mertik_device):
        # "ZZ" at [18:20] is non-hex → ValueError caught
        status_str = "303030300003" + "C6" + "FF" + "80" + "ZZ" + "00" + "04000000" + "E6"
        mertik_device._process_status(status_str)  # must not raise

    async def test_invalid_status_bits_no_crash(self, mertik_device):
        # "ZZ" at [16:18] means status_bits "ZZ8F" is non-hex → ValueError caught
        status_str = "303030300003" + "C6" + "FF" + "ZZ" + "8F" + "00" + "04000000" + "E6"
        mertik_device._process_status(status_str)  # must not raise

    async def test_invalid_temp_no_crash(self, mertik_device):
        # "ZZ" at [30:32] is non-hex → ValueError caught
        status_str = "303030300003" + "C6" + "FF" + "80" + "8F" + "00" + "04000000" + "ZZ"
        mertik_device._process_status(status_str)  # must not raise

    async def test_invalid_fault_code_no_crash(self, mertik_device):
        # "ZZ" at [24:26] is non-hex → ValueError caught
        status_str = (
            "303030300003" + "C6" + "FF" + "80" + "8F" + "00" + "04" + "ZZ" + "00" + "00" + "E6"
        )
        mertik_device._process_status(status_str)  # must not raise


class TestHelperMethods:
    """Test _hex_to_bin and _bit_at helpers."""

    async def test_hex_to_bin(self, mertik_device):
        assert mertik_device._hex_to_bin("FF") == "11111111"
        assert mertik_device._hex_to_bin("00") == "00000000"
        assert mertik_device._hex_to_bin("80") == "10000000"
        assert mertik_device._hex_to_bin("01") == "00000001"

    async def test_bit_at(self, mertik_device):
        assert mertik_device._bit_at("FF", 0) is True
        assert mertik_device._bit_at("FF", 7) is True
        assert mertik_device._bit_at("00", 0) is False
        assert mertik_device._bit_at("80", 0) is True
        assert mertik_device._bit_at("80", 1) is False


class TestNonStatusResponses:
    """Test that non-status responses don't corrupt device state."""

    async def test_non_matching_prefix_ignored(self, mock_connection, mock_reader):
        """Response with unknown prefix leaves state unchanged."""
        mock_reader.read.return_value = _build_status_bytes(
            on_flag="00", flame_byte=0x00
        )
        device = await Mertik.async_connect("192.168.1.100")
        assert device.is_on is False

        mock_reader.read.return_value = b"\x02XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
        await device.refresh_status()
        assert device.is_on is False

    async def test_short_response_no_crash(self, mock_connection, mock_reader):
        """A short response that doesn't match any prefix should not crash."""
        mock_reader.read.return_value = _build_status_bytes()
        device = await Mertik.async_connect("192.168.1.100")

        mock_reader.read.return_value = b"\x02OK"
        await device.refresh_status()  # Must not raise

    async def test_state_preserved_across_non_status(self, mock_connection, mock_reader):
        """Valid state survives a non-status response."""
        mock_reader.read.return_value = _build_status_bytes(
            on_flag="FF", flame_byte=0x8F
        )
        device = await Mertik.async_connect("192.168.1.100")
        assert device.is_on is True

        mock_reader.read.return_value = b"\x02ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ"
        await device.refresh_status()
        assert device.is_on is True


class TestStateTransitions:
    """Test that state updates correctly across multiple status responses."""

    async def test_off_to_on(self, mock_connection, mock_reader):
        mock_reader.read.return_value = _build_status_bytes(
            on_flag="00", flame_byte=0x00
        )
        device = await Mertik.async_connect("192.168.1.100")
        assert device.is_on is False

        mock_reader.read.return_value = _build_status_bytes(
            on_flag="FF", flame_byte=0x8F
        )
        await device.refresh_status()
        assert device.is_on is True
        assert device.flame_on is True

    async def test_on_to_off(self, mock_connection, mock_reader):
        mock_reader.read.return_value = _build_status_bytes(
            on_flag="FF", flame_byte=0x8F
        )
        device = await Mertik.async_connect("192.168.1.100")
        assert device.is_on is True

        mock_reader.read.return_value = _build_status_bytes(
            on_flag="00", flame_byte=0x00
        )
        await device.refresh_status()
        assert device.is_on is False
        assert device.flame_on is False

    async def test_temperature_updates(self, mock_connection, mock_reader):
        mock_reader.read.return_value = _build_status_bytes(ambient_temp=0xC8)
        device = await Mertik.async_connect("192.168.1.100")
        assert device.ambient_temperature == 20.0

        mock_reader.read.return_value = _build_status_bytes(ambient_temp=0xFA)
        await device.refresh_status()
        assert device.ambient_temperature == 25.0


class TestAllFlameHeightSteps:
    """Test every flame height step sends the correct hex code."""

    EXPECTED_STEPS = [
        (1, "3830"),
        (2, "3842"),
        (3, "3937"),
        (4, "4132"),
        (5, "4145"),
        (6, "4239"),
        (7, "4335"),
        (8, "4430"),
        (9, "4443"),
        (10, "4537"),
        (11, "4633"),
        (12, "4646"),
    ]

    @pytest.mark.parametrize("step,hex_code", EXPECTED_STEPS)
    async def test_flame_step(self, mertik_device, mock_writer, step, hex_code):
        mock_writer.write.reset_mock()
        await mertik_device.set_flame_height(step)
        expected = bytearray.fromhex(send_command_prefix + "3136" + hex_code + "03")
        assert mock_writer.write.call_args_list[0] == call(expected)
