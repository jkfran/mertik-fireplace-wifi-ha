from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MertikConfigEntry
from .entity import MertikEntity

PARALLEL_UPDATES = 0  # read-only coordinator-driven platform


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MertikConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    dataservice = entry.runtime_data
    async_add_entities(
        [
            MertikAmbientTemperatureSensorEntity(
                dataservice, entry.entry_id, entry.data["name"]
            ),
        ]
    )


class MertikAmbientTemperatureSensorEntity(MertikEntity, SensorEntity):
    _attr_translation_key = "ambient_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, dataservice, entry_id, device_name):
        super().__init__(dataservice, entry_id, device_name)
        self._attr_unique_id = entry_id + "-AmbientTemperature"

    @property
    def native_value(self):
        return self._dataservice.ambient_temperature
