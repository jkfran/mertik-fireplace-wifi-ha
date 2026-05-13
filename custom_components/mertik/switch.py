from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MertikConfigEntry
from .const import MODE_THERMO
from .entity import MertikEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MertikConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    dataservice = entry.runtime_data
    async_add_entities(
        [
            MertikOnOffSwitchEntity(dataservice, entry.entry_id, entry.data["name"]),
            MertikAuxOnOffSwitchEntity(dataservice, entry.entry_id, entry.data["name"]),
        ]
    )


class MertikOnOffSwitchEntity(MertikEntity, SwitchEntity):
    _attr_name = None
    _attr_icon = "mdi:fireplace"

    def __init__(self, dataservice, entry_id, device_name):
        super().__init__(dataservice, entry_id, device_name)
        self._attr_unique_id = entry_id + "-OnOff"

    @property
    def is_on(self):
        return bool(self._dataservice.is_on)

    async def async_turn_on(self, **kwargs):
        if self._dataservice.heating_mode == MODE_THERMO:
            # Arm thermostatic control: light pilot only so the switch stays on
            # and the climate loop can ignite the main burner when heat is needed.
            # Never ignite here -- room may already be above setpoint.
            await self.hass.async_add_executor_job(self._dataservice.standby)
        else:
            self._dataservice.mark_optimistic_on()
            await self.hass.async_add_executor_job(self._dataservice.ignite_fireplace)
        self._dataservice.async_set_updated_data(None)

    async def async_turn_off(self, **kwargs):
        await self.hass.async_add_executor_job(self._dataservice.guard_flame_off)
        self._dataservice.mark_optimistic_off()
        self._dataservice.async_set_updated_data(None)


class MertikAuxOnOffSwitchEntity(MertikEntity, SwitchEntity):
    _attr_translation_key = "aux"

    def __init__(self, dataservice, entry_id, device_name):
        super().__init__(dataservice, entry_id, device_name)
        self._attr_unique_id = entry_id + "-AuxOnOff"

    @property
    def is_on(self):
        return bool(self._dataservice.is_aux_on)

    async def async_turn_on(self, **kwargs):
        await self.hass.async_add_executor_job(self._dataservice.aux_on)
        self._dataservice.async_set_updated_data(None)

    async def async_turn_off(self, **kwargs):
        await self.hass.async_add_executor_job(self._dataservice.aux_off)
        self._dataservice.async_set_updated_data(None)
