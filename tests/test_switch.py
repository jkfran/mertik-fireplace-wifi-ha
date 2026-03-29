"""Tests for switch entities."""

from unittest.mock import MagicMock

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
        entity = MertikOnOffSwitchEntity(
            hass, mock_coordinator, "test_entry", "My Fireplace"
        )
        entity.hass = hass
        return entity

    def test_unique_id(self, switch):
        assert switch.unique_id == "test_entry-OnOff"

    def test_name(self, switch):
        assert switch.name == "My Fireplace"

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
        await switch.async_turn_on()
        mock_coordinator.ignite_fireplace.assert_called_once()
        mock_coordinator.mark_optimistic_on.assert_called_once()
        mock_coordinator.async_set_updated_data.assert_called_once_with(None)

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
            hass, mock_coordinator, "test_entry", "My Fireplace Aux",
            device_name="My Fireplace",
        )
        entity.hass = hass
        return entity

    def test_unique_id(self, switch):
        assert switch.unique_id == "test_entry-AuxOnOff"

    def test_name(self, switch):
        assert switch.name == "My Fireplace Aux"

    def test_icon(self, switch):
        assert switch.icon == "mdi:light"

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

    async def test_creates_two_entities(self, hass, mock_coordinator, mock_config_entry):
        hass.data[DOMAIN] = {mock_config_entry.entry_id: mock_coordinator}
        added = []
        async_add_entities = lambda entities: added.extend(entities)

        await async_setup_entry(hass, mock_config_entry, async_add_entities)

        assert len(added) == 2
        assert isinstance(added[0], MertikOnOffSwitchEntity)
        assert isinstance(added[1], MertikAuxOnOffSwitchEntity)

    async def test_entity_names(self, hass, mock_coordinator, mock_config_entry):
        hass.data[DOMAIN] = {mock_config_entry.entry_id: mock_coordinator}
        added = []
        await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

        assert added[0].name == "My Fireplace"
        assert added[1].name == "My Fireplace Aux"

    async def test_all_entities_share_device(self, hass, mock_coordinator, mock_config_entry):
        """Both switches should belong to the same device."""
        hass.data[DOMAIN] = {mock_config_entry.entry_id: mock_coordinator}
        added = []
        await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

        assert added[0].device_info["identifiers"] == added[1].device_info["identifiers"]
