"""Climate entity -- thermostat setpoint display and thermostatic control logic."""

from __future__ import annotations
import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import MertikConfigEntry
from .const import (
    DOMAIN,
    CONF_LOW_THRESHOLD,
    CONF_HIGH_THRESHOLD,
    CONF_TEMP_SENSOR,
    DEFAULT_LOW_THRESHOLD,
    DEFAULT_HIGH_THRESHOLD,
    DEFAULT_TEMP_SENSOR,
    MODE_STANDBY,
    MODE_FULL,
    MODE_MEDIUM,
    MODE_LOW,
    MODE_THERMO,
)
from .entity import MertikEntity

PARALLEL_UPDATES = 1

_LOGGER = logging.getLogger(__name__)

MIN_TEMP = 5.0
MAX_TEMP_C = 36.0
TEMP_STEP = 0.5
DEFAULT_TARGET = 20.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MertikConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    dataservice = entry.runtime_data
    async_add_entities(
        [
            MertikClimateEntity(dataservice, entry.entry_id, entry.data["name"], entry),
        ]
    )


class MertikClimateEntity(MertikEntity, ClimateEntity, RestoreEntity):
    """Thermostat setpoint + thermostatic control logic.

    Use the Heating Mode select entity to choose Off / Full / Medium / Low /
    Thermostatic. This entity provides the temperature setpoint and current
    temperature readout used in Thermostatic mode.
    """

    _attr_translation_key = "thermostat"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP_C
    _attr_target_temperature_step = TEMP_STEP
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE

    def __init__(self, dataservice, entry_id, device_name, entry):
        super().__init__(dataservice, entry_id, device_name)
        self._entry = entry
        self._attr_unique_id = entry_id + "-Thermostat"
        self._target_temp = DEFAULT_TARGET
        self._last_applied_mode = None  # prevent re-sending same command every poll

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.attributes.get(ATTR_TEMPERATURE) is not None:
            self._target_temp = float(last.attributes[ATTR_TEMPERATURE])

    # ---- Config helpers --------------------------------------------------

    def _get_option(self, key, default):
        return self._entry.options.get(key, self._entry.data.get(key, default))

    @property
    def _low_thresh(self) -> float:
        return float(self._get_option(CONF_LOW_THRESHOLD, DEFAULT_LOW_THRESHOLD))

    @property
    def _high_thresh(self) -> float:
        return float(self._get_option(CONF_HIGH_THRESHOLD, DEFAULT_HIGH_THRESHOLD))

    @property
    def _temp_sensor_entity_id(self) -> str:
        return self._get_option(CONF_TEMP_SENSOR, DEFAULT_TEMP_SENSOR)

    # ---- Temperature reading --------------------------------------------

    def _get_current_temperature(self) -> float | None:
        sensor_id = self._temp_sensor_entity_id
        if sensor_id:
            state = self.hass.states.get(sensor_id)
            if state is not None and state.state not in ("unknown", "unavailable"):
                try:
                    return float(state.state)
                except ValueError:
                    _LOGGER.warning(
                        "Temp sensor %s: non-numeric value %s", sensor_id, state.state
                    )
        t = self._dataservice.ambient_temperature
        return t if t else None

    # ---- State properties -----------------------------------------------

    @property
    def current_temperature(self) -> float | None:
        return self._get_current_temperature()

    @property
    def target_temperature(self) -> float:
        return self._target_temp

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT if self._dataservice.is_on else HVACMode.OFF

    # ---- Commands -------------------------------------------------------

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        self._target_temp = max(MIN_TEMP, min(MAX_TEMP_C, round(float(temp) * 2) / 2.0))
        self._last_applied_mode = None  # force re-evaluation on next poll
        self.async_write_ha_state()
        _LOGGER.debug("Thermostat setpoint -> %.1f C", self._target_temp)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._dataservice.guard_flame_off()
            self._dataservice.mark_optimistic_off()
            self._dataservice.async_set_updated_data(None)

    # ---- Thermostatic logic (runs on every coordinator poll) ------------

    def _handle_coordinator_update(self) -> None:
        self.hass.async_create_task(self._run_thermostatic_logic())
        super()._handle_coordinator_update()

    def _select_entity_id(self) -> str | None:
        from homeassistant.helpers import entity_registry as er

        if self.unique_id is None:
            return None
        registry = er.async_get(self.hass)
        uid = self.unique_id.replace("-Thermostat", "-HeatingMode")
        return registry.async_get_entity_id("select", DOMAIN, uid)

    async def _run_thermostatic_logic(self) -> None:
        # If we are waiting for an ignition to complete, let the
        # coordinator handle it this cycle and skip the temperature
        # comparison -- flame height commands are ignored during ignition.
        if await self._dataservice.check_pending_mode():
            return

        entity_id = self._select_entity_id()
        if entity_id is None:
            return
        select_state = self.hass.states.get(entity_id)
        if select_state is None or select_state.state != MODE_THERMO:
            self._last_applied_mode = None  # reset when leaving thermo mode
            return

        current = self._get_current_temperature()
        if current is None:
            _LOGGER.debug("Thermostatic: no temperature reading, skipping")
            return

        diff = self._target_temp - current
        sensor_id = self._temp_sensor_entity_id or "Mertik handset"

        if diff <= 0:
            target_mode = MODE_STANDBY  # room at/above setpoint -> standby
        elif diff < self._low_thresh:
            target_mode = MODE_LOW
        elif diff < self._high_thresh:
            target_mode = MODE_MEDIUM
        else:
            target_mode = MODE_FULL

        _LOGGER.debug(
            "Thermostatic: sensor=%s current=%.1fC setpoint=%.1fC diff=%.1fC -> %s",
            sensor_id,
            current,
            self._target_temp,
            diff,
            target_mode if target_mode else "Standby",
        )

        # Only act if the required mode has changed -- prevents sending the
        # same command every 10 seconds when the temperature is stable.
        if target_mode == self._last_applied_mode:
            return

        self._last_applied_mode = target_mode

        if target_mode == MODE_STANDBY:
            if self._dataservice.is_on:
                _LOGGER.info(
                    "Thermostatic: standby (%.1fC >= %.1fC setpoint)",
                    current,
                    self._target_temp,
                )
                # Do NOT call mark_optimistic_off here -- _in_standby keeps is_on
                # True so the Fireplace switch stays on while in thermostatic standby.
                await self._dataservice.standby()
        else:
            # apply_heating_mode() itself checks whether the Fireplace
            # switch is off and refuses to ignite if so. Reset _last_applied_mode
            # when fire is off so we re-evaluate as soon as it comes back on.
            if not self._dataservice.is_on and not self._dataservice._in_standby:
                self._last_applied_mode = MODE_STANDBY
            else:
                _LOGGER.info(
                    "Thermostatic: applying %s (diff=%.1fC, sensor=%s)",
                    target_mode,
                    diff,
                    sensor_id,
                )
                await self._dataservice.apply_heating_mode(target_mode)
