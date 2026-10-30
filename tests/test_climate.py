"""Tests for the thermostat climate entity."""

import pytest

from homeassistant.components.climate import (
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.exceptions import ServiceValidationError

from custom_components.mertik.climate import (
    MertikThermostatEntity,
    async_setup_entry,
)
from custom_components.mertik.const import DOMAIN


class TestThermostat:
    """Test the thermostat climate entity."""

    @pytest.fixture
    def thermostat(self, hass, mock_coordinator):
        entity = MertikThermostatEntity(mock_coordinator, "test_entry", "My Fireplace")
        entity.hass = hass
        return entity

    def test_unique_id(self, thermostat):
        assert thermostat.unique_id == "test_entry-Thermostat"

    def test_name(self, thermostat):
        assert thermostat.name == "Thermostat"

    def test_has_entity_name(self, thermostat):
        assert thermostat.has_entity_name is True

    def test_device_info(self, thermostat):
        info = thermostat.device_info
        assert info["identifiers"] == {(DOMAIN, "test_entry")}
        assert info["name"] == "My Fireplace"
        assert info["manufacturer"] == "Mertik Maxitrol"

    def test_hvac_modes(self, thermostat):
        assert thermostat.hvac_modes == [HVACMode.OFF, HVACMode.HEAT]

    def test_supported_features(self, thermostat):
        assert thermostat.supported_features == (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

    def test_temperature_range(self, thermostat):
        assert thermostat.temperature_unit == UnitOfTemperature.CELSIUS
        assert thermostat.min_temp == 5
        assert thermostat.max_temp == 36
        assert thermostat.target_temperature_step == 0.5

    def test_hvac_mode_heat(self, thermostat, mock_coordinator):
        mock_coordinator.is_thermostat_on = True
        assert thermostat.hvac_mode == HVACMode.HEAT

    def test_hvac_mode_off(self, thermostat, mock_coordinator):
        mock_coordinator.is_thermostat_on = False
        assert thermostat.hvac_mode == HVACMode.OFF

    def test_hvac_action_preheating(self, thermostat, mock_coordinator):
        mock_coordinator.is_igniting = True
        assert thermostat.hvac_action == HVACAction.PREHEATING

    def test_hvac_action_heating(self, thermostat, mock_coordinator):
        mock_coordinator.is_burning = True
        mock_coordinator.is_pilot_on = True
        assert thermostat.hvac_action == HVACAction.HEATING

    def test_hvac_action_idle_on_pilot(self, thermostat, mock_coordinator):
        """Room warm enough: the fireplace drops to its pilot flame."""
        mock_coordinator.is_pilot_on = True
        assert thermostat.hvac_action == HVACAction.IDLE

    def test_hvac_action_off(self, thermostat):
        assert thermostat.hvac_action == HVACAction.OFF

    def test_current_temperature(self, thermostat, mock_coordinator):
        mock_coordinator.ambient_temperature = 21.5
        assert thermostat.current_temperature == 21.5

    def test_target_temperature(self, thermostat, mock_coordinator):
        mock_coordinator.target_temperature = 22.0
        assert thermostat.target_temperature == 22.0

    def test_target_temperature_unset(self, thermostat, mock_coordinator):
        """The device reports 0 when no target has been set."""
        mock_coordinator.target_temperature = 0.0
        assert thermostat.target_temperature is None

    def test_target_temperature_unknown(self, thermostat, mock_coordinator):
        mock_coordinator.target_temperature = None
        assert thermostat.target_temperature is None

    async def test_set_temperature(self, thermostat, mock_coordinator):
        mock_coordinator.is_pilot_on = True
        await thermostat.async_set_temperature(temperature=21.5)
        mock_coordinator.set_thermostat.assert_called_once_with(21.5)
        mock_coordinator.async_set_updated_data.assert_called_once_with(None)

    async def test_set_temperature_rounds_to_half_degrees(self, thermostat, mock_coordinator):
        mock_coordinator.is_pilot_on = True
        await thermostat.async_set_temperature(temperature=21.3)
        mock_coordinator.set_thermostat.assert_called_once_with(21.5)

    async def test_set_temperature_with_hvac_mode_off(self, thermostat, mock_coordinator):
        mock_coordinator.is_pilot_on = True
        await thermostat.async_set_temperature(temperature=21.5, hvac_mode=HVACMode.OFF)
        mock_coordinator.set_manual.assert_called_once()
        mock_coordinator.set_thermostat.assert_not_called()

    async def test_set_temperature_requires_lit_fireplace(self, thermostat, mock_coordinator):
        mock_coordinator.is_pilot_on = False
        with pytest.raises(ServiceValidationError):
            await thermostat.async_set_temperature(temperature=21.5)
        mock_coordinator.set_thermostat.assert_not_called()

    async def test_set_hvac_mode_heat_uses_current_target(self, thermostat, mock_coordinator):
        mock_coordinator.is_pilot_on = True
        mock_coordinator.target_temperature = 22.5
        await thermostat.async_set_hvac_mode(HVACMode.HEAT)
        mock_coordinator.set_thermostat.assert_called_once_with(22.5)
        mock_coordinator.async_set_updated_data.assert_called_once_with(None)

    async def test_set_hvac_mode_heat_defaults_target(self, thermostat, mock_coordinator):
        """Without a stored target, start the thermostat at 20 C."""
        mock_coordinator.is_pilot_on = True
        mock_coordinator.target_temperature = 0.0
        await thermostat.async_set_hvac_mode(HVACMode.HEAT)
        mock_coordinator.set_thermostat.assert_called_once_with(20.0)

    async def test_set_hvac_mode_heat_requires_lit_fireplace(self, thermostat, mock_coordinator):
        mock_coordinator.is_pilot_on = False
        with pytest.raises(ServiceValidationError):
            await thermostat.async_set_hvac_mode(HVACMode.HEAT)
        mock_coordinator.set_thermostat.assert_not_called()

    async def test_set_hvac_mode_off_returns_to_manual(self, thermostat, mock_coordinator):
        await thermostat.async_set_hvac_mode(HVACMode.OFF)
        mock_coordinator.set_manual.assert_called_once()
        mock_coordinator.async_set_updated_data.assert_called_once_with(None)

    async def test_turn_on(self, thermostat, mock_coordinator):
        mock_coordinator.is_pilot_on = True
        mock_coordinator.target_temperature = 21.0
        await thermostat.async_turn_on()
        mock_coordinator.set_thermostat.assert_called_once_with(21.0)

    async def test_turn_off(self, thermostat, mock_coordinator):
        await thermostat.async_turn_off()
        mock_coordinator.set_manual.assert_called_once()


class TestClimatePlatformSetup:
    """Test climate platform async_setup_entry."""

    async def test_creates_thermostat(self, hass, mock_coordinator, mock_config_entry):
        hass.data[DOMAIN] = {mock_config_entry.entry_id: mock_coordinator}
        added = []

        await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

        assert len(added) == 1
        assert isinstance(added[0], MertikThermostatEntity)
        assert added[0].unique_id == "test_entry_123-Thermostat"
