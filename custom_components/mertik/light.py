from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.components.light import LightEntity, ColorMode, ATTR_BRIGHTNESS

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    dataservice = hass.data[DOMAIN].get(entry.entry_id)

    async_add_entities([
        MertikLightEntity(dataservice, entry.entry_id, entry.data["name"]),
    ])


class MertikLightEntity(CoordinatorEntity, LightEntity):
    _attr_has_entity_name = True
    _attr_name = "Light"
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, dataservice, entry_id, device_name):
        super().__init__(dataservice)
        self._dataservice = dataservice
        self._attr_unique_id = entry_id + "-Light"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=device_name,
            manufacturer="Mertik Maxitrol",
        )

    @property
    def is_on(self):
        return self._dataservice.is_light_on

    @property
    def brightness(self):
        return self._dataservice.light_brightness

    async def async_turn_on(self, **kwargs):
        if ATTR_BRIGHTNESS in kwargs:
            await self.hass.async_add_executor_job(
                self._dataservice.set_light_brightness, kwargs[ATTR_BRIGHTNESS]
            )
        elif not self.is_on:
            await self.hass.async_add_executor_job(self._dataservice.light_on)

        self._dataservice.async_set_updated_data(None)

    async def async_turn_off(self, **kwargs):
        await self.hass.async_add_executor_job(self._dataservice.light_off)
        self._dataservice.async_set_updated_data(None)
