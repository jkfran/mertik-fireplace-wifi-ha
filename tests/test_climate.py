"""Tests for the climate (thermostat) entity."""

from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from homeassistant.components.climate import HVACMode
from homeassistant.const import ATTR_TEMPERATURE

from custom_components.mertik.climate import (
    MertikClimateEntity,
    async_setup_entry,
    DEFAULT_TARGET,
    MIN_TEMP,
    MAX_TEMP_C,
)
from custom_components.mertik.const import (
    DOMAIN,
    CONF_LOW_THRESHOLD,
    CONF_HIGH_THRESHOLD,
    CONF_TEMP_SENSOR,
    DEFAULT_LOW_THRESHOLD,
    DEFAULT_HIGH_THRESHOLD,
    MODE_STANDBY,
    MODE_FULL,
    MODE_MEDIUM,
    MODE_LOW,
    MODE_THERMO,
)


@pytest.fixture
def mock_entry():
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {
        "name": "My Fireplace",
        "host": "192.168.1.100",
    }
    entry.options = {}
    return entry


@pytest.fixture
def climate(hass, mock_coordinator, mock_entry):
    entity = MertikClimateEntity(
        mock_coordinator, "test_entry", "My Fireplace", mock_entry
    )
    entity.hass = hass
    return entity


class TestClimateEntityProperties:
    def test_unique_id(self, climate):
        assert climate.unique_id == "test_entry-Thermostat"

    def test_translation_key(self, climate):
        assert climate.translation_key == "thermostat"

    def test_has_entity_name(self, climate):
        assert climate.has_entity_name is True

    def test_device_info(self, climate):
        info = climate.device_info
        assert info["identifiers"] == {(DOMAIN, "test_entry")}
        assert info["name"] == "My Fireplace"
        assert info["manufacturer"] == "Mertik Maxitrol"

    def test_target_temperature_default(self, climate):
        assert climate.target_temperature == DEFAULT_TARGET

    def test_hvac_mode_off_when_coordinator_off(self, climate, mock_coordinator):
        mock_coordinator.is_on = False
        assert climate.hvac_mode == HVACMode.OFF

    def test_hvac_mode_heat_when_coordinator_on(self, climate, mock_coordinator):
        mock_coordinator.is_on = True
        assert climate.hvac_mode == HVACMode.HEAT

    def test_min_temp(self, climate):
        assert climate.min_temp == MIN_TEMP

    def test_max_temp(self, climate):
        assert climate.max_temp == MAX_TEMP_C


class TestClimateConfigOptions:
    def test_low_thresh_from_defaults(self, climate):
        assert climate._low_thresh == DEFAULT_LOW_THRESHOLD

    def test_high_thresh_from_defaults(self, climate):
        assert climate._high_thresh == DEFAULT_HIGH_THRESHOLD

    def test_temp_sensor_default_empty(self, climate):
        assert climate._temp_sensor_entity_id == ""

    def test_low_thresh_from_options(self, climate, mock_entry):
        mock_entry.options = {CONF_LOW_THRESHOLD: 2.5}
        assert climate._low_thresh == 2.5

    def test_high_thresh_from_options(self, climate, mock_entry):
        mock_entry.options = {CONF_HIGH_THRESHOLD: 5.0}
        assert climate._high_thresh == 5.0

    def test_temp_sensor_from_options(self, climate, mock_entry):
        mock_entry.options = {CONF_TEMP_SENSOR: "sensor.living_room"}
        assert climate._temp_sensor_entity_id == "sensor.living_room"


class TestClimateTemperatureReading:
    def test_uses_coordinator_when_no_sensor_set(self, climate, mock_coordinator):
        mock_coordinator.ambient_temperature = 19.5
        assert climate.current_temperature == 19.5

    def test_returns_none_when_no_sensor_and_no_ambient(
        self, climate, mock_coordinator
    ):
        mock_coordinator.ambient_temperature = 0
        assert climate.current_temperature is None

    async def test_uses_external_sensor_state(self, climate, mock_entry, hass):
        mock_entry.options = {CONF_TEMP_SENSOR: "sensor.room"}
        hass.states.async_set("sensor.room", "21.5", {})
        assert climate.current_temperature == 21.5

    async def test_skips_unavailable_sensor_state(
        self, climate, mock_entry, hass, mock_coordinator
    ):
        mock_entry.options = {CONF_TEMP_SENSOR: "sensor.room"}
        hass.states.async_set("sensor.room", "unavailable", {})
        mock_coordinator.ambient_temperature = 20.0
        assert climate.current_temperature == 20.0

    async def test_skips_non_numeric_sensor_state(
        self, climate, mock_entry, hass, mock_coordinator
    ):
        mock_entry.options = {CONF_TEMP_SENSOR: "sensor.room"}
        hass.states.async_set("sensor.room", "not_a_number", {})
        mock_coordinator.ambient_temperature = 20.0
        assert climate.current_temperature == 20.0

    def test_returns_none_when_sensor_entity_missing(
        self, climate, mock_entry, mock_coordinator
    ):
        mock_entry.options = {CONF_TEMP_SENSOR: "sensor.nonexistent"}
        mock_coordinator.ambient_temperature = 0
        assert climate.current_temperature is None


class TestClimateCommands:
    async def test_set_temperature_updates_target(self, climate):
        with patch.object(climate, "async_write_ha_state"):
            await climate.async_set_temperature(**{ATTR_TEMPERATURE: 22.0})
        assert climate.target_temperature == 22.0

    async def test_set_temperature_clamps_to_min(self, climate):
        with patch.object(climate, "async_write_ha_state"):
            await climate.async_set_temperature(**{ATTR_TEMPERATURE: 1.0})
        assert climate.target_temperature == MIN_TEMP

    async def test_set_temperature_clamps_to_max(self, climate):
        with patch.object(climate, "async_write_ha_state"):
            await climate.async_set_temperature(**{ATTR_TEMPERATURE: 99.0})
        assert climate.target_temperature == MAX_TEMP_C

    async def test_set_temperature_rounds_to_half_degree(self, climate):
        with patch.object(climate, "async_write_ha_state"):
            await climate.async_set_temperature(**{ATTR_TEMPERATURE: 21.3})
        assert climate.target_temperature == 21.5

    async def test_set_temperature_resets_last_applied_mode(self, climate):
        climate._last_applied_mode = MODE_LOW
        with patch.object(climate, "async_write_ha_state"):
            await climate.async_set_temperature(**{ATTR_TEMPERATURE: 22.0})
        assert climate._last_applied_mode is None

    async def test_set_temperature_ignores_none(self, climate):
        with patch.object(climate, "async_write_ha_state"):
            await climate.async_set_temperature(**{})
        assert climate.target_temperature == DEFAULT_TARGET

    async def test_set_hvac_mode_off_calls_guard_flame_off(self, climate, mock_coordinator):
        await climate.async_set_hvac_mode(HVACMode.OFF)
        mock_coordinator.guard_flame_off.assert_called_once()
        mock_coordinator.mark_optimistic_off.assert_called_once()
        mock_coordinator.async_set_updated_data.assert_called_once_with(None)

    async def test_set_hvac_mode_heat_is_noop(self, climate, mock_coordinator):
        await climate.async_set_hvac_mode(HVACMode.HEAT)
        mock_coordinator.guard_flame_off.assert_not_called()


class TestClimateAddedToHass:
    async def test_restores_target_temperature(self, climate):
        last_state = MagicMock()
        last_state.attributes = {ATTR_TEMPERATURE: 23.5}
        with patch.object(
            climate, "async_get_last_state", new_callable=AsyncMock, return_value=last_state
        ):
            await climate.async_added_to_hass()
        assert climate.target_temperature == 23.5

    async def test_no_restore_when_no_last_state(self, climate):
        with patch.object(
            climate, "async_get_last_state", new_callable=AsyncMock, return_value=None
        ):
            await climate.async_added_to_hass()
        assert climate.target_temperature == DEFAULT_TARGET

    async def test_no_restore_when_no_temperature_attr(self, climate):
        last_state = MagicMock()
        last_state.attributes = {}
        with patch.object(
            climate,
            "async_get_last_state",
            new_callable=AsyncMock,
            return_value=last_state,
        ):
            await climate.async_added_to_hass()
        assert climate.target_temperature == DEFAULT_TARGET


class TestThermostaticLogic:
    """Tests for _run_thermostatic_logic."""

    def _make_climate(self, hass, mock_coordinator, mock_entry, target=22.0):
        entity = MertikClimateEntity(
            mock_coordinator, "test_entry", "My Fireplace", mock_entry
        )
        entity.hass = hass
        entity._target_temp = target
        return entity

    def test_skips_when_pending_mode(self, hass, mock_coordinator, mock_entry):
        mock_coordinator.check_pending_mode.return_value = True
        climate = self._make_climate(hass, mock_coordinator, mock_entry)
        with patch.object(climate, "_select_entity_id", return_value="select.mode"):
            climate._run_thermostatic_logic()
        mock_coordinator.check_pending_mode.assert_called_once()

    def test_skips_when_no_select_entity(self, hass, mock_coordinator, mock_entry):
        mock_coordinator.check_pending_mode.return_value = False
        climate = self._make_climate(hass, mock_coordinator, mock_entry)
        with patch.object(climate, "_select_entity_id", return_value=None):
            climate._run_thermostatic_logic()  # should not raise

    def test_skips_when_select_state_none(self, hass, mock_coordinator, mock_entry):
        # "select.mode" is not in the state machine → get() returns None
        mock_coordinator.check_pending_mode.return_value = False
        climate = self._make_climate(hass, mock_coordinator, mock_entry)
        with patch.object(climate, "_select_entity_id", return_value="select.mode"):
            climate._run_thermostatic_logic()

    def test_skips_when_not_in_thermo_mode(self, hass, mock_coordinator, mock_entry):
        mock_coordinator.check_pending_mode.return_value = False
        climate = self._make_climate(hass, mock_coordinator, mock_entry)
        hass.states.async_set("select.mode", "Full Heat")
        climate._last_applied_mode = MODE_LOW
        with patch.object(climate, "_select_entity_id", return_value="select.mode"):
            climate._run_thermostatic_logic()
        assert climate._last_applied_mode is None  # reset when leaving thermo mode

    def test_skips_when_no_temperature(self, hass, mock_coordinator, mock_entry):
        mock_coordinator.check_pending_mode.return_value = False
        climate = self._make_climate(hass, mock_coordinator, mock_entry)
        hass.states.async_set("select.mode", MODE_THERMO)
        with patch.object(climate, "_select_entity_id", return_value="select.mode"), patch.object(
            climate, "_get_current_temperature", return_value=None
        ):
            climate._run_thermostatic_logic()

    def test_same_mode_not_resent(self, hass, mock_coordinator, mock_entry):
        mock_coordinator.check_pending_mode.return_value = False
        climate = self._make_climate(hass, mock_coordinator, mock_entry, target=22.0)
        climate._last_applied_mode = MODE_FULL
        hass.states.async_set("select.mode", MODE_THERMO)
        with patch.object(climate, "_select_entity_id", return_value="select.mode"), patch.object(
            climate, "_get_current_temperature", return_value=18.0
        ):
            climate._run_thermostatic_logic()
        # diff=4 > high_thresh=2 → MODE_FULL, same as last → no task scheduled
        assert climate._last_applied_mode == MODE_FULL

    def test_standby_when_at_setpoint(self, hass, mock_coordinator, mock_entry):
        mock_coordinator.check_pending_mode.return_value = False
        mock_coordinator.is_on = True
        climate = self._make_climate(hass, mock_coordinator, mock_entry, target=20.0)
        hass.states.async_set("select.mode", MODE_THERMO)
        tasks = []
        hass.async_create_task = MagicMock(side_effect=tasks.append)
        with patch.object(climate, "_select_entity_id", return_value="select.mode"), patch.object(
            climate, "_get_current_temperature", return_value=20.0
        ):
            climate._run_thermostatic_logic()
        assert climate._last_applied_mode == MODE_STANDBY
        assert len(tasks) == 1  # standby task scheduled

    def test_standby_not_scheduled_when_fire_already_off(
        self, hass, mock_coordinator, mock_entry
    ):
        mock_coordinator.check_pending_mode.return_value = False
        mock_coordinator.is_on = False
        climate = self._make_climate(hass, mock_coordinator, mock_entry, target=20.0)
        hass.states.async_set("select.mode", MODE_THERMO)
        hass.async_create_task = MagicMock()
        with patch.object(climate, "_select_entity_id", return_value="select.mode"), patch.object(
            climate, "_get_current_temperature", return_value=20.0
        ):
            climate._run_thermostatic_logic()
        hass.async_create_task.assert_not_called()

    def test_low_heat_when_within_low_thresh(self, hass, mock_coordinator, mock_entry):
        mock_coordinator.check_pending_mode.return_value = False
        mock_coordinator.is_on = True
        climate = self._make_climate(hass, mock_coordinator, mock_entry, target=20.0)
        hass.states.async_set("select.mode", MODE_THERMO)
        tasks = []
        hass.async_create_task = MagicMock(side_effect=tasks.append)
        # diff = 0.5, low_thresh = 1.0 → LOW
        with patch.object(climate, "_select_entity_id", return_value="select.mode"), patch.object(
            climate, "_get_current_temperature", return_value=19.5
        ):
            climate._run_thermostatic_logic()
        assert climate._last_applied_mode == MODE_LOW
        assert len(tasks) == 1

    def test_medium_heat_within_high_thresh(self, hass, mock_coordinator, mock_entry):
        mock_coordinator.check_pending_mode.return_value = False
        mock_coordinator.is_on = True
        climate = self._make_climate(hass, mock_coordinator, mock_entry, target=20.0)
        hass.states.async_set("select.mode", MODE_THERMO)
        tasks = []
        hass.async_create_task = MagicMock(side_effect=tasks.append)
        # diff = 1.5, low_thresh=1.0, high_thresh=2.0 → MEDIUM
        with patch.object(climate, "_select_entity_id", return_value="select.mode"), patch.object(
            climate, "_get_current_temperature", return_value=18.5
        ):
            climate._run_thermostatic_logic()
        assert climate._last_applied_mode == MODE_MEDIUM
        assert len(tasks) == 1

    def test_full_heat_beyond_high_thresh(self, hass, mock_coordinator, mock_entry):
        mock_coordinator.check_pending_mode.return_value = False
        mock_coordinator.is_on = True
        climate = self._make_climate(hass, mock_coordinator, mock_entry, target=20.0)
        hass.states.async_set("select.mode", MODE_THERMO)
        tasks = []
        hass.async_create_task = MagicMock(side_effect=tasks.append)
        # diff = 5.0, high_thresh=2.0 → FULL
        with patch.object(climate, "_select_entity_id", return_value="select.mode"), patch.object(
            climate, "_get_current_temperature", return_value=15.0
        ):
            climate._run_thermostatic_logic()
        assert climate._last_applied_mode == MODE_FULL
        assert len(tasks) == 1

    async def test_standby_task_body_calls_dataservice_standby(
        self, hass, mock_coordinator, mock_entry
    ):
        mock_coordinator.check_pending_mode.return_value = False
        mock_coordinator.is_on = True
        climate = self._make_climate(hass, mock_coordinator, mock_entry, target=20.0)
        hass.states.async_set("select.mode", MODE_THERMO)
        tasks = []
        hass.async_create_task = MagicMock(side_effect=tasks.append)
        with patch.object(climate, "_select_entity_id", return_value="select.mode"), \
             patch.object(climate, "_get_current_temperature", return_value=20.0):
            climate._run_thermostatic_logic()
        assert len(tasks) == 1
        await tasks[0]
        mock_coordinator.standby.assert_called_once()

    async def test_apply_task_body_calls_apply_heating_mode(
        self, hass, mock_coordinator, mock_entry
    ):
        mock_coordinator.check_pending_mode.return_value = False
        mock_coordinator.is_on = True
        climate = self._make_climate(hass, mock_coordinator, mock_entry, target=20.0)
        hass.states.async_set("select.mode", MODE_THERMO)
        tasks = []
        hass.async_create_task = MagicMock(side_effect=tasks.append)
        with patch.object(climate, "_select_entity_id", return_value="select.mode"), \
             patch.object(climate, "_get_current_temperature", return_value=15.0):
            climate._run_thermostatic_logic()
        assert len(tasks) == 1
        await tasks[0]
        mock_coordinator.apply_heating_mode.assert_called_once_with(MODE_FULL)

    def test_fire_off_resets_last_mode_to_standby(self, hass, mock_coordinator, mock_entry):
        mock_coordinator.check_pending_mode.return_value = False
        mock_coordinator.is_on = False
        mock_coordinator._in_standby = False
        climate = self._make_climate(hass, mock_coordinator, mock_entry, target=20.0)
        climate._last_applied_mode = MODE_STANDBY
        hass.states.async_set("select.mode", MODE_THERMO)
        hass.async_create_task = MagicMock()
        # diff=5 → FULL, but fire is off → resets _last_applied_mode to STANDBY
        with patch.object(climate, "_select_entity_id", return_value="select.mode"), patch.object(
            climate, "_get_current_temperature", return_value=15.0
        ):
            climate._run_thermostatic_logic()
        assert climate._last_applied_mode == MODE_STANDBY


class TestHandleCoordinatorUpdate:
    def test_calls_thermostatic_logic(self, climate):
        with patch.object(climate, "_run_thermostatic_logic") as mock_thermo, \
             patch.object(climate, "async_write_ha_state"):
            climate._handle_coordinator_update()
        mock_thermo.assert_called_once()


class TestSelectEntityId:
    def test_returns_none_when_unique_id_is_none(self, climate):
        climate._attr_unique_id = None
        assert climate._select_entity_id() is None

    def test_returns_none_when_entity_not_registered(self, climate):
        result = climate._select_entity_id()
        assert result is None


class TestClimatePlatformSetup:
    async def test_creates_one_entity(self, hass, mock_coordinator, mock_config_entry):
        mock_config_entry.runtime_data = mock_coordinator
        added = []
        with patch.object(
            MertikClimateEntity, "async_added_to_hass", new_callable=AsyncMock
        ):
            await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))
        assert len(added) == 1
        assert isinstance(added[0], MertikClimateEntity)
        assert added[0].translation_key == "thermostat"
