"""Tests for the Mertik Maxitrol integration.

These tests cover the protocol encoding/decoding logic in mertik.py
without requiring a real device connection (socket calls are mocked).
"""
import sys
import types
import socket
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Minimal HA stub so mertik.py can be imported without a full HA install
# ---------------------------------------------------------------------------
for mod in [
    "homeassistant", "homeassistant.core", "homeassistant.helpers",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.restore_state",
    "homeassistant.helpers.entity_registry",
    "homeassistant.components",
    "homeassistant.components.switch",
    "homeassistant.components.number",
    "homeassistant.components.sensor",
    "homeassistant.components.light",
    "homeassistant.components.climate",
    "homeassistant.components.select",
    "homeassistant.const",
    "homeassistant.config_entries",
    "homeassistant.exceptions",
    "homeassistant.util",
    "homeassistant.util.dt",
]:
    if mod not in sys.modules:
        sys.modules[mod] = types.ModuleType(mod)


def _make_mertik():
    """Create a Mertik instance with all socket I/O mocked out."""
    from custom_components.mertik.mertik import Mertik
    m = Mertik.__new__(Mertik)
    m._ambient_temperature = 0.0
    m.flameHeight = 0
    m.on = False
    m.flame_on = False
    m._local_aux = False
    m._shutting_down = False
    m._guard_flame_on = False
    m._igniting = False
    m._prev_flame_on = False
    m.client = MagicMock()
    m.client.recv.side_effect = socket.timeout
    return m


# ---------------------------------------------------------------------------
# Status packet decoding
# ---------------------------------------------------------------------------

class TestStatusPacketDecoding(unittest.TestCase):
    """_process_status correctly decodes real device packets.

    Packets are confirmed captures from a B6R-H8TV4PB receiver,
    verified against known physical states.
    """

    def test_fire_off(self):
        """on_flag=00, flame_raw=0x0B -> off."""
        m = _make_mertik()
        pkt = ("303030300003C6008009BB04000000F500DC"
               "4C6976696E6720526F6F6D20"
               "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF042D00")
        m._process_status(pkt)
        self.assertFalse(m.on)
        self.assertFalse(m.flame_on)
        self.assertEqual(m.flameHeight, 0)

    def test_fire_on(self):
        """on_flag=FF, flame_raw=0x8F -> on."""
        m = _make_mertik()
        pkt = ("303030300003C6FF808F0004000000F500DC"
               "4C6976696E6720526F6F6D20"
               "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF043001")
        m._process_status(pkt)
        self.assertTrue(m.on)
        self.assertTrue(m.flame_on)
        self.assertGreater(m.flameHeight, 0)

    def test_transitional_on_flag_preserves_state(self):
        """on_flag not FF or 00 -> previous on state unchanged."""
        m = _make_mertik()
        m.on = True
        pkt = ("303030300003C697808F0004000000F500DC"
               "4C6976696E6720526F6F6D20"
               "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF043001")
        m._process_status(pkt)
        self.assertTrue(m.on)  # unchanged

    def test_temperature_decoded(self):
        """Temperature at [30:32]: raw/10 = °C. 0xF5=245->24.5°C."""
        m = _make_mertik()
        pkt = ("303030300003C6008009BB04000000F500DC"
               "4C6976696E6720526F6F6D20"
               "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF042D00")
        m._process_status(pkt)
        self.assertAlmostEqual(m._ambient_temperature, 24.5)

    def test_falling_edge_resets_local_state(self):
        """flame_on True->False resets _local_aux and flameHeight."""
        m = _make_mertik()
        m.flame_on = True
        m._prev_flame_on = True
        m._local_aux = True
        m.flameHeight = 8
        pkt = ("303030300003C600800BBB04000000F500DC"
               "4C6976696E6720526F6F6D20"
               "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF042D00")
        m._process_status(pkt)
        self.assertFalse(m.flame_on)
        self.assertFalse(m._local_aux)
        self.assertEqual(m.flameHeight, 0)

    def test_no_reset_during_ignition_transitional(self):
        """flame_on False->False (ignition transitional) preserves local state."""
        m = _make_mertik()
        m.flame_on = False
        m._prev_flame_on = False
        m._local_aux = True    # set by ignite_fireplace()
        m.flameHeight = 1
        # flame_raw=0x1F=31 is below threshold but was also below before
        pkt = ("303030300003C6001F1FBB04000000F500DC"
               "4C6976696E6720526F6F6D20"
               "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF042D00")
        m._process_status(pkt)
        # Not a falling edge -> local state preserved
        self.assertTrue(m._local_aux)
        self.assertEqual(m.flameHeight, 1)


# ---------------------------------------------------------------------------
# Command encoding
# ---------------------------------------------------------------------------

class TestCommandEncoding(unittest.TestCase):
    """Commands produce correctly encoded packets."""

    PREFIX = bytes.fromhex("0233303330333033303830")

    def _sent_bytes(self, m):
        """Concatenate all bytes passed to client.send()."""
        return b"".join(c[0][0] for c in m.client.send.call_args_list)

    def test_guard_flame_off(self):
        m = _make_mertik()
        m.guard_flame_off()
        sent = self._sent_bytes(m)
        self.assertIn(bytes.fromhex("313003"), sent)   # "10\x03"

    def test_ignite_sends_ignite_then_aux_on(self):
        m = _make_mertik()
        m.ignite_fireplace()
        sent = self._sent_bytes(m)
        self.assertIn(bytes.fromhex("314103"), sent)         # IGNITE "1A\x03"
        self.assertIn(bytes.fromhex("32303031030a"), sent)   # AUX_ON "2001\x03\n"

    def test_ignite_sets_local_aux_and_flame(self):
        m = _make_mertik()
        m.ignite_fireplace()
        self.assertTrue(m._local_aux)
        self.assertEqual(m.flameHeight, 1)

    def test_flame_step_1_encoding(self):
        """Step 1 = code '3830' = '80' in payload."""
        m = _make_mertik()
        m.set_flame_height(1)
        sent = self._sent_bytes(m)
        self.assertIn(bytes.fromhex("3136383003"), sent)   # "1680\x03"

    def test_flame_step_13_maps_to_max(self):
        """Step 13 maps to table index 11 -> code '4646' = 'FF'."""
        m = _make_mertik()
        m.set_flame_height(13)
        sent = self._sent_bytes(m)
        self.assertIn(bytes.fromhex("3136464603"), sent)   # "16FF\x03"

    def test_flame_height_tracked_locally(self):
        """flameHeight updated from command, not status packet."""
        m = _make_mertik()
        m.set_flame_height(7)
        self.assertEqual(m.flameHeight, 7)

    def test_aux_on(self):
        m = _make_mertik()
        m.aux_on()
        sent = self._sent_bytes(m)
        self.assertIn(bytes.fromhex("32303031030a"), sent)
        self.assertTrue(m._local_aux)

    def test_aux_off(self):
        m = _make_mertik()
        m._local_aux = True
        m.aux_off()
        sent = self._sent_bytes(m)
        self.assertIn(bytes.fromhex("32303030030a"), sent)
        self.assertFalse(m._local_aux)

    def test_thermostat_encoding_21_5c(self):
        """21.5°C -> round(21.5*2)=43=0x2B -> payload '42 31 32 42 03'."""
        m = _make_mertik()
        m.set_thermostat(21.5)
        sent = self._sent_bytes(m)
        self.assertIn(bytes.fromhex("423132420" + "3"), sent)

    def test_thermostat_encoding_20c(self):
        """20.0°C -> round(20.0*2)=40=0x28 -> payload '42 31 32 38 03'."""
        m = _make_mertik()
        m.set_thermostat(20.0)
        sent = self._sent_bytes(m)
        self.assertIn(bytes.fromhex("4231323803"), sent)

    def test_thermostat_clamped_to_range(self):
        """Temperature clamped to 5.0-36.0°C."""
        m = _make_mertik()
        m.set_thermostat(100.0)  # too high
        sent_high = self._sent_bytes(m)
        m.client.send.reset_mock()
        m.set_thermostat(36.0)   # max
        sent_max = self._sent_bytes(m)
        # Both should produce the same packet
        self.assertEqual(sent_high, sent_max)

    def test_standby(self):
        """standBy sends CMD_STANDBY '1600\x03'."""
        m = _make_mertik()
        m.standBy()
        sent = self._sent_bytes(m)
        self.assertIn(bytes.fromhex("3136303003"), sent)   # "1600\x03"

    def test_light_on(self):
        m = _make_mertik()
        m.light_on()
        sent = self._sent_bytes(m)
        self.assertIn(bytes.fromhex("3330303103"), sent)   # "3001\x03"

    def test_light_off(self):
        m = _make_mertik()
        m.light_off()
        sent = self._sent_bytes(m)
        self.assertIn(bytes.fromhex("3330303003"), sent)   # "3000\x03"

    def test_all_commands_start_with_prefix(self):
        """Every command packet starts with the fixed 11-byte prefix."""
        m = _make_mertik()
        m.guard_flame_off()
        for c in m.client.send.call_args_list:
            pkt = c[0][0]
            self.assertTrue(
                pkt.startswith(self.PREFIX),
                f"Packet does not start with prefix: {pkt.hex()}"
            )


if __name__ == "__main__":
    unittest.main()
