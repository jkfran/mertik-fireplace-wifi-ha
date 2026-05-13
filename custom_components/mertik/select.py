"""Heating mode selector for Mertik Maxitrol fireplace."""

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.restore_state import RestoreEntity

from .const import HEATING_MODES
from .entity import MertikEntity

ICON_MAP = {
    "Full Heat": "mdi:fire",
    "Medium Heat": "mdi:fire-circle",
    "Low Heat": "mdi:flame",
    "Standby": "mdi:fire-off",
    "Thermostatic": "mdi:thermostat",
}


async def async_setup_entry(hass, entry, async_add_entities):
    dataservice = entry.runtime_data
    async_add_entities(
        [
            MertikHeatingModeSelect(dataservice, entry.entry_id, entry.data["name"]),
        ]
    )


class MertikHeatingModeSelect(MertikEntity, SelectEntity, RestoreEntity):
    _attr_name = "Heating Mode"
    _attr_options = HEATING_MODES

    def __init__(self, dataservice, entry_id, device_name):
        super().__init__(dataservice, entry_id, device_name)
        self._attr_unique_id = entry_id + "-HeatingMode"
        self._current_mode = "Standby"

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in HEATING_MODES:
            self._current_mode = last_state.state
            self._dataservice.set_heating_mode(last_state.state)

    @property
    def current_option(self) -> str:
        return self._current_mode

    @property
    def icon(self) -> str:
        return ICON_MAP.get(self._current_mode, "mdi:fire")

    async def async_select_option(self, option: str) -> None:
        self._current_mode = option
        self._dataservice.set_heating_mode(option)
        if option == "Standby":
            await self.hass.async_add_executor_job(self._dataservice.standby)
            self._dataservice.mark_optimistic_off()
        elif option != "Thermostatic":
            await self.hass.async_add_executor_job(
                self._dataservice.apply_heating_mode, option
            )
        # Thermostatic: climate entity drives hardware on next poll
        self.async_write_ha_state()
        self._dataservice.async_set_updated_data(None)
