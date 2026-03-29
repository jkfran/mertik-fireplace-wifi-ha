from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.components.switch import SwitchEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    dataservice = hass.data[DOMAIN].get(entry.entry_id)

    entities = [
        MertikOnOffSwitchEntity(dataservice, entry.entry_id, entry.data["name"]),
        MertikAuxOnOffSwitchEntity(dataservice, entry.entry_id, entry.data["name"]),
    ]

    async_add_entities(entities)


class MertikOnOffSwitchEntity(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_icon = "mdi:fireplace"

    def __init__(self, dataservice, entry_id, device_name):
        super().__init__(dataservice)
        self._dataservice = dataservice
        self._attr_unique_id = entry_id + "-OnOff"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=device_name,
            manufacturer="Mertik Maxitrol",
        )

    @property
    def is_on(self):
        return bool(self._dataservice.is_on)

    async def async_turn_on(self, **kwargs):
        await self.hass.async_add_executor_job(self._dataservice.ignite_fireplace)
        self._dataservice.mark_optimistic_on()
        self._dataservice.async_set_updated_data(None)

    async def async_turn_off(self, **kwargs):
        await self.hass.async_add_executor_job(self._dataservice.guard_flame_off)
        self._dataservice.mark_optimistic_off()
        self._dataservice.async_set_updated_data(None)


class MertikAuxOnOffSwitchEntity(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True
    _attr_name = "Aux"
    _attr_icon = "mdi:light"

    def __init__(self, dataservice, entry_id, device_name):
        super().__init__(dataservice)
        self._dataservice = dataservice
        self._attr_unique_id = entry_id + "-AuxOnOff"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=device_name,
            manufacturer="Mertik Maxitrol",
        )

    @property
    def is_on(self):
        return bool(self._dataservice.is_aux_on)

    async def async_turn_on(self, **kwargs):
        await self.hass.async_add_executor_job(self._dataservice.aux_on)
        self._dataservice.async_set_updated_data(None)

    async def async_turn_off(self, **kwargs):
        await self.hass.async_add_executor_job(self._dataservice.aux_off)
        self._dataservice.async_set_updated_data(None)
