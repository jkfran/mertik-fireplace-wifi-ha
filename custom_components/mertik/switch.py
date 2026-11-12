"""Switches: the fireplace itself and its secondary burner."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import MertikConfigEntry
from .entity import MertikEntity

# Calls are not queued one behind the other here: an off must not wait for a
# turn-on that is still being checked. The coordinator and the protocol layer
# keep what is sent in order.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: MertikConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [MertikOnOffSwitchEntity(coordinator), MertikAuxOnOffSwitchEntity(coordinator)]
    )


class MertikOnOffSwitchEntity(MertikEntity, SwitchEntity):
    """The fireplace: on ignites it, off turns it off completely.

    It reads on whenever the pilot burns, so also in standby and while igniting.

    Unlike the other entities it never becomes unavailable: Home Assistant does
    not pass a command on to an unavailable entity, and turning a fire off must
    not be dropped because the fireplace could not be reached a moment ago.
    While nothing is known about the fireplace it reads unknown.
    """

    _attr_name = None
    _attr_translation_key = "fireplace"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "OnOff")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.available:
            return None
        return self.coordinator.is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_turn_on()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_turn_off()


class MertikAuxOnOffSwitchEntity(MertikEntity, SwitchEntity):
    """Secondary burner on dual-burner fireplaces (the module's aux output).

    Turn off to run on the primary burner only.
    """

    _attr_translation_key = "secondary_burner"

    def __init__(self, coordinator) -> None:
        # The key dates from when this was called "Aux"; it keeps entity IDs stable.
        super().__init__(coordinator, "AuxOnOff")

    @property
    def is_on(self) -> bool:
        return self.coordinator.is_aux_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_aux(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_aux(False)
