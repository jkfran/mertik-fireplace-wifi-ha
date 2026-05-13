"""Tests for the Heating Mode select entity."""

from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from homeassistant.helpers.entity import EntityCategory

from custom_components.mertik.select import (
    MertikHeatingModeSelect,
    async_setup_entry,
)
from custom_components.mertik.const import DOMAIN, HEATING_MODES


class TestHeatingModeSelect:
    @pytest.fixture
    def select(self, hass, mock_coordinator):
        entity = MertikHeatingModeSelect(mock_coordinator, "test_entry", "My Fireplace")
        entity.hass = hass
        return entity

    # --- Identity / metadata --------------------------------------------------

    def test_unique_id(self, select):
        assert select.unique_id == "test_entry-HeatingMode"

    def test_name(self, select):
        assert select.name == "Heating Mode"

    def test_has_entity_name(self, select):
        assert select.has_entity_name is True

    def test_options(self, select):
        assert select.options == HEATING_MODES

    def test_entity_category(self, select):
        assert select.entity_category == EntityCategory.CONFIG

    def test_current_option_default(self, select):
        assert select.current_option == "Standby"

    def test_device_info(self, select):
        info = select.device_info
        assert info["identifiers"] == {(DOMAIN, "test_entry")}
        assert info["name"] == "My Fireplace"
        assert info["manufacturer"] == "Mertik Maxitrol"

    # --- Icon -----------------------------------------------------------------

    def test_icon_standby(self, select):
        select._current_mode = "Standby"
        assert select.icon == "mdi:fire-off"

    def test_icon_full_heat(self, select):
        select._current_mode = "Full Heat"
        assert select.icon == "mdi:fire"

    def test_icon_medium_heat(self, select):
        select._current_mode = "Medium Heat"
        assert select.icon == "mdi:fire-circle"

    def test_icon_low_heat(self, select):
        select._current_mode = "Low Heat"
        assert select.icon == "mdi:flame"

    def test_icon_thermostatic(self, select):
        select._current_mode = "Thermostatic"
        assert select.icon == "mdi:thermostat"

    def test_icon_unknown_falls_back(self, select):
        select._current_mode = "Unknown"
        assert select.icon == "mdi:fire"

    # --- async_added_to_hass --------------------------------------------------

    async def test_added_to_hass_restores_valid_mode(self, select, mock_coordinator):
        last_state = MagicMock()
        last_state.state = "Full Heat"
        with patch.object(
            select, "async_get_last_state", new_callable=AsyncMock, return_value=last_state
        ):
            await select.async_added_to_hass()

        assert select._current_mode == "Full Heat"
        mock_coordinator.set_heating_mode.assert_called_with("Full Heat")

    async def test_added_to_hass_ignores_invalid_state(self, select, mock_coordinator):
        last_state = MagicMock()
        last_state.state = "not_a_mode"
        with patch.object(
            select, "async_get_last_state", new_callable=AsyncMock, return_value=last_state
        ):
            await select.async_added_to_hass()

        assert select._current_mode == "Standby"
        mock_coordinator.set_heating_mode.assert_not_called()

    async def test_added_to_hass_no_last_state(self, select, mock_coordinator):
        with patch.object(
            select, "async_get_last_state", new_callable=AsyncMock, return_value=None
        ):
            await select.async_added_to_hass()

        assert select._current_mode == "Standby"
        mock_coordinator.set_heating_mode.assert_not_called()

    # --- async_select_option --------------------------------------------------

    async def test_select_standby_calls_standby(self, select, mock_coordinator):
        with patch.object(select, "async_write_ha_state"):
            await select.async_select_option("Standby")

        assert select._current_mode == "Standby"
        mock_coordinator.set_heating_mode.assert_called_once_with("Standby")
        mock_coordinator.mark_optimistic_off.assert_called_once()
        mock_coordinator.async_set_updated_data.assert_called_once_with(None)

    async def test_select_thermostatic_no_device_call(self, select, mock_coordinator):
        with patch.object(select, "async_write_ha_state"):
            await select.async_select_option("Thermostatic")

        assert select._current_mode == "Thermostatic"
        mock_coordinator.set_heating_mode.assert_called_once_with("Thermostatic")
        mock_coordinator.mark_optimistic_off.assert_not_called()
        mock_coordinator.apply_heating_mode.assert_not_called()
        mock_coordinator.async_set_updated_data.assert_called_once_with(None)

    async def test_select_full_heat_calls_apply_heating_mode(self, select, mock_coordinator):
        with patch.object(select, "async_write_ha_state"):
            await select.async_select_option("Full Heat")

        assert select._current_mode == "Full Heat"
        mock_coordinator.set_heating_mode.assert_called_once_with("Full Heat")
        mock_coordinator.apply_heating_mode.assert_called_once_with("Full Heat")
        mock_coordinator.async_set_updated_data.assert_called_once_with(None)

    async def test_select_medium_heat(self, select, mock_coordinator):
        with patch.object(select, "async_write_ha_state"):
            await select.async_select_option("Medium Heat")

        assert select._current_mode == "Medium Heat"
        mock_coordinator.apply_heating_mode.assert_called_once_with("Medium Heat")

    async def test_select_low_heat(self, select, mock_coordinator):
        with patch.object(select, "async_write_ha_state"):
            await select.async_select_option("Low Heat")

        assert select._current_mode == "Low Heat"
        mock_coordinator.apply_heating_mode.assert_called_once_with("Low Heat")


class TestSelectPlatformSetup:
    async def test_creates_one_entity(self, hass, mock_coordinator, mock_config_entry):
        mock_config_entry.runtime_data = mock_coordinator
        added = []
        with patch.object(
            MertikHeatingModeSelect, "async_added_to_hass", new_callable=AsyncMock
        ):
            await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))
        assert len(added) == 1
        assert isinstance(added[0], MertikHeatingModeSelect)
        assert added[0].name == "Heating Mode"
