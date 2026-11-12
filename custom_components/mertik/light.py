"""The fireplace's light."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import MertikConfigEntry
from .entity import MertikEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: MertikConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([MertikLightEntity(entry.runtime_data)])


class MertikLightEntity(MertikEntity, LightEntity):
    """The dimmable light. It works with the fire on or off."""

    _attr_translation_key = "light"
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "Light")

    @property
    def is_on(self) -> bool:
        return self.coordinator.is_light_on

    @property
    def brightness(self) -> int | None:
        return self.coordinator.light_brightness if self.is_on else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_light(True, kwargs.get(ATTR_BRIGHTNESS))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_light(False)
