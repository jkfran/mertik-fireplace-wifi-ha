from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.components.number import NumberEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    dataservice = hass.data[DOMAIN].get(entry.entry_id)

    async_add_entities([
        MertikFlameHeightEntity(dataservice, entry.entry_id, entry.data["name"]),
    ])


class MertikFlameHeightEntity(CoordinatorEntity, NumberEntity):
    _attr_has_entity_name = True
    _attr_name = "Flame Height"
    _attr_icon = "mdi:fire"
    _attr_native_min_value = 1
    _attr_native_max_value = 12

    def __init__(self, dataservice, entry_id, device_name):
        super().__init__(dataservice)
        self._dataservice = dataservice
        self._attr_unique_id = entry_id + "-FlameHeight"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=device_name,
            manufacturer="Mertik Maxitrol",
        )

    @property
    def native_value(self) -> float:
        return self._dataservice.get_flame_height()

    async def async_set_native_value(self, value: float) -> None:
        await self.hass.async_add_executor_job(self._dataservice.set_flame_height, int(value))
        self._dataservice.async_set_updated_data(None)
