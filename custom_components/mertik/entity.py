"""Base class of the fireplace's entities."""

from __future__ import annotations

from homeassistant.const import CONF_NAME
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MAC, CONF_MODEL, DOMAIN, MANUFACTURER
from .coordinator import MertikConfigEntry, MertikDataCoordinator


def device_info(entry: MertikConfigEntry) -> DeviceInfo:
    """Describe the fireplace; every entity of an entry belongs to this device."""
    info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data[CONF_NAME],
        manufacturer=MANUFACTURER,
    )
    if model := entry.data.get(CONF_MODEL):
        info["model"] = model
    if mac := entry.data.get(CONF_MAC):
        info["connections"] = {(CONNECTION_NETWORK_MAC, mac)}
    return info


class MertikEntity(CoordinatorEntity[MertikDataCoordinator]):
    """An entity of one fireplace.

    The unique ID is the config entry ID plus a fixed key. The keys of the
    entities that existed before 1.1 must never change.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: MertikDataCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}-{key}"
        self._attr_device_info = device_info(entry)

    @property
    def available(self) -> bool:
        return self.coordinator.available
