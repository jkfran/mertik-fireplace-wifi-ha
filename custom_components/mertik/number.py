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
    """Flame height control (1-13 steps).

    Step 13 is the maximum (raw 0xFF), matching the device's own reporting.
    The entity is unavailable when the fire is off because the device ignores
    flame height commands when not running.
    """
    _attr_has_entity_name = True
    _attr_name = "Flame Height"
    _attr_icon = "mdi:fire"
    _attr_native_min_value = 1
    _attr_native_max_value = 13
    _attr_native_step = 1

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
    def available(self) -> bool:
        """Only available when the fire is running."""
        return super().available and self._dataservice.is_on

    @property
    def native_value(self) -> float:
        return self._dataservice.get_flame_height()

    async def async_set_native_value(self, value: float) -> None:
        await self.hass.async_add_executor_job(
            self._dataservice.set_flame_height, int(value)
        )
        self._dataservice.async_set_updated_data(None)
