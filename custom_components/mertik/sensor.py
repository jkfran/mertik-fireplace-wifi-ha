"""Sensors: room temperature, status and a few diagnostics."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import MertikConfigEntry
from .entity import MertikEntity
from .mertik import STATES

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: MertikConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            MertikAmbientTemperatureSensorEntity(coordinator),
            MertikStatusSensorEntity(coordinator),
            MertikFanLevelSensorEntity(coordinator),
            MertikIpAddressSensorEntity(coordinator),
        ]
    )


class MertikAmbientTemperatureSensorEntity(MertikEntity, SensorEntity):
    """Room temperature measured by the handset; unknown without a handset."""

    _attr_translation_key = "ambient_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "AmbientTemperature")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.ambient_temperature


class MertikStatusSensorEntity(MertikEntity, SensorEntity):
    """What the fireplace is doing: off, standby, igniting, on or shutting down."""

    _attr_translation_key = "status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATES

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "Status")

    @property
    def native_value(self) -> str | None:
        return self.coordinator.state


class MertikFanLevelSensorEntity(MertikEntity, SensorEntity):
    """Fan level as reported by the fireplace (it cannot be set from here)."""

    _attr_translation_key = "fan_level"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "FanLevel")

    @property
    def native_value(self) -> int | None:
        return self.coordinator.mertik.fan_level


class MertikIpAddressSensorEntity(MertikEntity, SensorEntity):
    """Address of the WiFi module."""

    _attr_translation_key = "ip_address"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "IPAddress")

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> str:
        return self.coordinator.mertik.ip
