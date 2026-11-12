"""Binary sensors: pilot flame, ignition, shutdown, the radio links and faults."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import MertikConfigEntry, MertikDataCoordinator
from .entity import MertikEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class MertikBinarySensorDescription(BinarySensorEntityDescription):
    """A binary sensor and where its value comes from."""

    unique_key: str
    value: Callable[[MertikDataCoordinator], bool | None]
    # Stays available while the receiver link is lost (it reports on that link).
    link_independent: bool = False


DESCRIPTIONS = (
    MertikBinarySensorDescription(
        key="pilot_flame",
        unique_key="PilotFlame",
        translation_key="pilot_flame",
        value=lambda coordinator: coordinator.is_pilot_on,
    ),
    MertikBinarySensorDescription(
        key="igniting",
        unique_key="Igniting",
        translation_key="igniting",
        entity_registry_enabled_default=False,
        value=lambda coordinator: coordinator.is_igniting,
    ),
    MertikBinarySensorDescription(
        key="shutting_down",
        unique_key="ShuttingDown",
        translation_key="shutting_down",
        entity_registry_enabled_default=False,
        value=lambda coordinator: coordinator.is_shutting_down,
    ),
    MertikBinarySensorDescription(
        key="receiver_connection",
        unique_key="ReceiverConnection",
        translation_key="receiver_connection",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        link_independent=True,
        value=lambda coordinator: coordinator.mertik.receiver_connected,
    ),
    MertikBinarySensorDescription(
        key="remote_connection",
        unique_key="RemoteConnection",
        translation_key="remote_connection",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda coordinator: coordinator.mertik.handset_connected,
    ),
    MertikBinarySensorDescription(
        # A fault the fireplace has stored; a fireplace without a handset always has one.
        key="fault",
        unique_key="Fault",
        translation_key="fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value=lambda coordinator: coordinator.mertik.is_faulted,
    ),
    MertikBinarySensorDescription(
        key="fan",
        unique_key="Fan",
        translation_key="fan",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value=lambda coordinator: coordinator.mertik.is_fan_on,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: MertikConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        MertikBinarySensorEntity(coordinator, description) for description in DESCRIPTIONS
    )


class MertikBinarySensorEntity(MertikEntity, BinarySensorEntity):
    entity_description: MertikBinarySensorDescription

    def __init__(self, coordinator, description: MertikBinarySensorDescription) -> None:
        super().__init__(coordinator, description.unique_key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        if self.entity_description.link_independent:
            return self.coordinator.last_update_success
        return super().available

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value(self.coordinator)
