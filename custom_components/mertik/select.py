"""Operating mode: manual, the fireplace's own thermostat, or eco."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import MertikConfigEntry
from .entity import MertikEntity
from .mertik import MODE_ECO, MODE_MANUAL, MODE_THERMOSTAT

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: MertikConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([MertikModeSelectEntity(entry.runtime_data)])


class MertikModeSelectEntity(MertikEntity, SelectEntity):
    """The mode the fireplace itself is in, as on the handset and in the app.

    Eco lets the fireplace vary its flame to save gas. Thermostat is the
    fireplace's own thermostat, which needs the handset's temperature.
    """

    _attr_translation_key = "mode"
    _attr_options = [MODE_MANUAL, MODE_THERMOSTAT, MODE_ECO]

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "Mode")

    @property
    def current_option(self) -> str | None:
        return self.coordinator.mode

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_mode(option)
