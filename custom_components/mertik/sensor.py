from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity

from homeassistant.const import UnitOfTemperature

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    dataservice = hass.data[DOMAIN].get(entry.entry_id)

    async_add_entities([
        MertikAmbientTemperatureSensorEntity(dataservice, entry.entry_id, entry.data["name"]),
    ])


class MertikAmbientTemperatureSensorEntity(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Ambient Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, dataservice, entry_id, device_name):
        super().__init__(dataservice)
        self._dataservice = dataservice
        self._attr_unique_id = entry_id + "-AmbientTemperature"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=device_name,
            manufacturer="Mertik Maxitrol",
        )

    @property
    def native_value(self):
        return self._dataservice.ambient_temperature
