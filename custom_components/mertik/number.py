"""Flame height."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import MertikConfigEntry
from .entity import MertikEntity
from .mertik import FLAME_STEPS

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: MertikConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([MertikFlameHeightEntity(entry.runtime_data)])


class MertikFlameHeightEntity(MertikEntity, NumberEntity):
    """Flame height in the handset's 12 steps; 0 is standby (pilot only)."""

    _attr_translation_key = "flame_height"
    _attr_native_min_value = 0
    _attr_native_max_value = FLAME_STEPS
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "FlameHeight")

    @property
    def native_value(self) -> float:
        return self.coordinator.flame_height

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The raw burner output (0-255), which moves in finer steps."""
        return {"burner_output": self.coordinator.mertik.burner_output}

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_flame_height(int(value))
