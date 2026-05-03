"""Tests for sensor entity (ambient temperature)."""

from unittest.mock import MagicMock

import pytest

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfTemperature

from custom_components.mertik.sensor import (
    MertikAmbientTemperatureSensorEntity,
    async_setup_entry,
)
from custom_components.mertik.const import DOMAIN


class TestTemperatureSensor:
    """Test the ambient temperature sensor entity."""

    @pytest.fixture
    def sensor(self, hass, mock_coordinator):
        entity = MertikAmbientTemperatureSensorEntity(
            mock_coordinator, "test_entry", "My Fireplace"
        )
        entity.hass = hass
        return entity

    def test_unique_id(self, sensor):
        assert sensor.unique_id == "test_entry-AmbientTemperature"

    def test_name(self, sensor):
        assert sensor.name == "Ambient Temperature"

    def test_has_entity_name(self, sensor):
        assert sensor.has_entity_name is True

    def test_device_class(self, sensor):
        assert sensor.device_class == SensorDeviceClass.TEMPERATURE

    def test_unit(self, sensor):
        assert sensor.native_unit_of_measurement == UnitOfTemperature.CELSIUS

    def test_device_info(self, sensor):
        info = sensor.device_info
        assert info["identifiers"] == {(DOMAIN, "test_entry")}
        assert info["name"] == "My Fireplace"
        assert info["manufacturer"] == "Mertik Maxitrol"

    def test_native_value(self, sensor, mock_coordinator):
        mock_coordinator.ambient_temperature = 21.5
        assert sensor.native_value == 21.5

    def test_native_value_cold(self, sensor, mock_coordinator):
        mock_coordinator.ambient_temperature = 5.0
        assert sensor.native_value == 5.0


class TestSensorPlatformSetup:
    """Test sensor platform async_setup_entry."""

    async def test_creates_one_entity(self, hass, mock_coordinator, mock_config_entry):
        hass.data[DOMAIN] = {mock_config_entry.entry_id: mock_coordinator}
        added = []
        await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

        assert len(added) == 1
        assert isinstance(added[0], MertikAmbientTemperatureSensorEntity)
