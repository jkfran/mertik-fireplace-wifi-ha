"""Thermostat."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity

from .coordinator import MertikConfigEntry
from .entity import MertikEntity
from .mertik import THERMOSTAT_MAX_TEMPERATURE, THERMOSTAT_MIN_TEMPERATURE
from .thermostat import DEFAULT_TARGET_TEMPERATURE

PARALLEL_UPDATES = 1


@dataclass
class ThermostatMemory(ExtraStoredData):
    """What the thermostat keeps across a restart.

    The target is kept in Celsius. The entity's own state would not do: on an
    installation that shows Fahrenheit it holds Fahrenheit, and when the
    fireplace was unreachable at shutdown it holds nothing.
    """

    target: float
    active: bool

    def as_dict(self) -> dict[str, Any]:
        return {"target": self.target, "active": self.active}


async def async_setup_entry(
    hass: HomeAssistant, entry: MertikConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([MertikThermostatEntity(entry.runtime_data)])


class MertikThermostatEntity(MertikEntity, ClimateEntity, RestoreEntity):
    """Keeps the room at a temperature while the fireplace is on.

    Without a temperature sensor in the options this is the fireplace's own
    thermostat mode, which measures with the handset. With one, Home Assistant
    regulates the flame on that sensor. Either way it never ignites the
    fireplace, and off returns to manual flame height without putting the fire
    out.
    """

    _attr_translation_key = "thermostat"
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    # Home Assistant 2026.11 renamed the temperature members of climate entities
    # to native_*. Both sets are defined here: versions before it read the old
    # names, and where both exist the new ones are used, without a warning.
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = THERMOSTAT_MIN_TEMPERATURE
    _attr_max_temp = THERMOSTAT_MAX_TEMPERATURE
    _attr_target_temperature_step = 0.5

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "Thermostat")

    async def async_added_to_hass(self) -> None:
        """Bring back the target, and resume regulating a fire that is burning."""
        await super().async_added_to_hass()
        if (extra := await self.async_get_last_extra_data()) is None:
            return
        memory = extra.as_dict()
        target = memory.get("target")
        if (
            isinstance(target, (int, float))
            and THERMOSTAT_MIN_TEMPERATURE <= target <= THERMOSTAT_MAX_TEMPERATURE
        ):
            self.coordinator.thermostat.target = float(target)
        if (
            memory.get("active") is True
            and self.coordinator.temperature_sensor is not None
            and self.coordinator.is_pilot_on
        ):
            self.coordinator.thermostat.active = True

    @property
    def extra_restore_state_data(self) -> ThermostatMemory:
        thermostat = self.coordinator.thermostat
        return ThermostatMemory(target=thermostat.target, active=thermostat.active)

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT if self.coordinator.is_thermostat_on else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction:
        coordinator = self.coordinator
        if not coordinator.is_thermostat_on:
            return HVACAction.OFF
        if coordinator.is_igniting:
            return HVACAction.PREHEATING
        if coordinator.is_burning:
            return HVACAction.HEATING
        if coordinator.is_pilot_on:
            return HVACAction.IDLE
        return HVACAction.OFF

    @property
    def native_current_temperature(self) -> float | None:
        return self.coordinator.room_temperature

    @property
    def native_target_temperature(self) -> float | None:
        target = self.coordinator.thermostat_target
        if target is None or not self.min_temp <= target <= self.max_temp:
            return None
        return target

    # What the two are called before Home Assistant 2026.11.
    current_temperature = native_current_temperature
    target_temperature = native_target_temperature

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if kwargs.get(ATTR_HVAC_MODE) == HVACMode.OFF:
            await self.async_set_hvac_mode(HVACMode.OFF)
            return
        # The handset works in half degrees.
        temperature = round(kwargs[ATTR_TEMPERATURE] * 2) / 2
        await self.coordinator.async_set_thermostat(
            temperature, must_start=kwargs.get(ATTR_HVAC_MODE) == HVACMode.HEAT
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_stop_thermostat()
            return
        await self.coordinator.async_set_thermostat(
            self.native_target_temperature or DEFAULT_TARGET_TEMPERATURE
        )
