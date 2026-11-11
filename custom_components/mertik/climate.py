from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN

DEFAULT_TARGET_TEMPERATURE = 20.0


async def async_setup_entry(hass, entry, async_add_entities):
    dataservice = hass.data[DOMAIN].get(entry.entry_id)

    async_add_entities([
        MertikThermostatEntity(dataservice, entry.entry_id, entry.data["name"]),
    ])


class MertikThermostatEntity(CoordinatorEntity, ClimateEntity):
    """The fireplace's own thermostat mode, as on the handset.

    Heat lets the fireplace regulate its flame towards the target temperature.
    Off returns to manual flame height; it does not put the fire out.
    """

    _attr_has_entity_name = True
    _attr_name = "Thermostat"
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 5
    _attr_max_temp = 36
    _attr_target_temperature_step = 0.5

    def __init__(self, dataservice, entry_id, device_name):
        super().__init__(dataservice)
        self._dataservice = dataservice
        self._attr_unique_id = entry_id + "-Thermostat"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=device_name,
            manufacturer="Mertik Maxitrol",
        )

    @property
    def hvac_mode(self):
        return HVACMode.HEAT if self._dataservice.is_thermostat_on else HVACMode.OFF

    @property
    def hvac_action(self):
        if self._dataservice.is_igniting:
            return HVACAction.PREHEATING
        if self._dataservice.is_burning:
            return HVACAction.HEATING
        if self._dataservice.is_pilot_on:
            return HVACAction.IDLE
        return HVACAction.OFF

    @property
    def current_temperature(self):
        return self._dataservice.ambient_temperature

    @property
    def target_temperature(self):
        target = self._dataservice.target_temperature
        if target is None or not self.min_temp <= target <= self.max_temp:
            return None
        return target

    async def async_set_temperature(self, **kwargs):
        if kwargs.get(ATTR_HVAC_MODE) == HVACMode.OFF:
            await self.async_set_hvac_mode(HVACMode.OFF)
            return
        await self._async_start_thermostat(kwargs[ATTR_TEMPERATURE])

    async def async_set_hvac_mode(self, hvac_mode):
        if hvac_mode == HVACMode.OFF:
            await self.hass.async_add_executor_job(self._dataservice.set_manual)
            self._dataservice.async_set_updated_data(None)
            return
        await self._async_start_thermostat(
            self.target_temperature or DEFAULT_TARGET_TEMPERATURE
        )

    async def _async_start_thermostat(self, temperature):
        if not self._dataservice.is_pilot_on:
            raise ServiceValidationError(
                "Turn on the fireplace before using the thermostat"
            )
        # The handset works in half degrees
        temperature = round(temperature * 2) / 2
        await self.hass.async_add_executor_job(
            self._dataservice.set_thermostat, temperature
        )
        self._dataservice.async_set_updated_data(None)
