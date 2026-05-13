"""Tests for switch entities."""

import pytest

from custom_components.mertik.switch import (
    MertikOnOffSwitchEntity,
    MertikAuxOnOffSwitchEntity,
    async_setup_entry,
)
from custom_components.mertik.const import DOMAIN


class TestOnOffSwitch:
    """Test the main on/off switch entity."""

    @pytest.fixture
    def switch(self, hass, mock_coordinator):
        entity = MertikOnOffSwitchEntity(mock_coordinator, "test_entry", "My Fireplace")
        entity.hass = hass
        return entity

    def test_unique_id(self, switch):
        assert switch.unique_id == "test_entry-OnOff"

    def test_name(self, switch):
        """Primary entity has name=None (uses device name)."""
        assert switch.name is None

    def test_has_entity_name(self, switch):
        assert switch.has_entity_name is True

    def test_icon(self, switch):
        assert switch.icon == "mdi:fireplace"

    def test_device_info(self, switch):
        info = switch.device_info
        assert info["identifiers"] == {(DOMAIN, "test_entry")}
        assert info["name"] == "My Fireplace"
        assert info["manufacturer"] == "Mertik Maxitrol"

    def test_is_on_false(self, switch, mock_coordinator):
        mock_coordinator.is_on = False
        assert switch.is_on is False

    def test_is_on_true(self, switch, mock_coordinator):
        mock_coordinator.is_on = True
        assert switch.is_on is True

    async def test_turn_on(self, switch, mock_coordinator):
        mock_coordinator.heating_mode = None  # non-thermostatic
        await switch.async_turn_on()
        mock_coordinator.ignite_fireplace.assert_called_once()
        mock_coordinator.mark_optimistic_on.assert_called_once()
        mock_coordinator.async_set_updated_data.assert_called_once_with(None)

    async def test_turn_on_thermostatic_mode_arms_standby(
        self, switch, mock_coordinator
    ):
        """Fireplace switch On in Thermostatic mode arms pilot, never ignites main burner.

        Real-life bug: room=21C, setpoint=19C, Thermostatic mode active.
        Turning on the switch must light the pilot (standby) so the switch stays on
        and the climate loop can decide when to ignite the main burner.
        """
        from custom_components.mertik.const import MODE_THERMO

        mock_coordinator.heating_mode = MODE_THERMO
        await switch.async_turn_on()
        mock_coordinator.standby.assert_called_once()
        mock_coordinator.ignite_fireplace.assert_not_called()
        mock_coordinator.mark_optimistic_on.assert_not_called()
        mock_coordinator.async_set_updated_data.assert_called_once_with(None)

    async def test_turn_on_non_thermostatic_ignites(self, switch, mock_coordinator):
        """Fireplace switch On in any manual mode ignites immediately."""
        from custom_components.mertik.const import MODE_FULL

        mock_coordinator.heating_mode = MODE_FULL
        await switch.async_turn_on()
        mock_coordinator.ignite_fireplace.assert_called_once()
        mock_coordinator.mark_optimistic_on.assert_called_once()

    async def test_turn_off(self, switch, mock_coordinator):
        await switch.async_turn_off()
        mock_coordinator.guard_flame_off.assert_called_once()
        mock_coordinator.mark_optimistic_off.assert_called_once()
        mock_coordinator.async_set_updated_data.assert_called_once_with(None)


class TestAuxSwitch:
    """Test the aux on/off switch entity."""

    @pytest.fixture
    def switch(self, hass, mock_coordinator):
        entity = MertikAuxOnOffSwitchEntity(
            mock_coordinator, "test_entry", "My Fireplace"
        )
        entity.hass = hass
        return entity

    def test_unique_id(self, switch):
        assert switch.unique_id == "test_entry-AuxOnOff"

    def test_translation_key(self, switch):
        assert switch.translation_key == "aux"

    def test_has_entity_name(self, switch):
        assert switch.has_entity_name is True

    def test_icon_in_icons_json(self, switch):
        """Aux icon is defined in icons.json; Python returns None."""
        assert switch.icon is None

    def test_device_info(self, switch):
        info = switch.device_info
        assert info["identifiers"] == {(DOMAIN, "test_entry")}
        assert info["name"] == "My Fireplace"
        assert info["manufacturer"] == "Mertik Maxitrol"

    def test_is_on_false(self, switch, mock_coordinator):
        mock_coordinator.is_aux_on = False
        assert switch.is_on is False

    def test_is_on_true(self, switch, mock_coordinator):
        mock_coordinator.is_aux_on = True
        assert switch.is_on is True

    async def test_turn_on(self, switch, mock_coordinator):
        await switch.async_turn_on()
        mock_coordinator.aux_on.assert_called_once()
        mock_coordinator.async_set_updated_data.assert_called_once_with(None)

    async def test_turn_off(self, switch, mock_coordinator):
        await switch.async_turn_off()
        mock_coordinator.aux_off.assert_called_once()
        mock_coordinator.async_set_updated_data.assert_called_once_with(None)


class TestSwitchPlatformSetup:
    """Test switch platform async_setup_entry."""

    async def test_creates_two_entities(
        self, hass, mock_coordinator, mock_config_entry
    ):
        mock_config_entry.runtime_data = mock_coordinator
        added = []

        await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

        assert len(added) == 2
        assert isinstance(added[0], MertikOnOffSwitchEntity)
        assert isinstance(added[1], MertikAuxOnOffSwitchEntity)

    async def test_entity_names(self, hass, mock_coordinator, mock_config_entry):
        mock_config_entry.runtime_data = mock_coordinator
        added = []
        await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

        assert added[0].name is None
        assert added[1].translation_key == "aux"

    async def test_all_entities_share_device(
        self, hass, mock_coordinator, mock_config_entry
    ):
        mock_config_entry.runtime_data = mock_coordinator
        added = []
        await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

        assert (
            added[0].device_info["identifiers"] == added[1].device_info["identifiers"]
        )
