"""Tests for sensor entities (temperature and fault code)."""

from unittest.mock import MagicMock

import pytest

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity import EntityCategory

from custom_components.mertik.sensor import (
    MertikAmbientTemperatureSensorEntity,
    MertikFaultCodeSensorEntity,
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

    def test_translation_key(self, sensor):
        assert sensor.translation_key == "handset_temperature"

    def test_has_entity_name(self, sensor):
        assert sensor.has_entity_name is True

    def test_device_class(self, sensor):
        assert sensor.device_class == SensorDeviceClass.TEMPERATURE

    def test_unit(self, sensor):
        assert sensor.native_unit_of_measurement == UnitOfTemperature.CELSIUS

    def test_entity_category(self, sensor):
        assert sensor.entity_category == EntityCategory.DIAGNOSTIC

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


class TestFaultCodeSensor:
    """Test the fault code sensor entity."""

    @pytest.fixture
    def sensor(self, hass, mock_coordinator):
        mock_coordinator.fault_code = 0
        entity = MertikFaultCodeSensorEntity(
            mock_coordinator, "test_entry", "My Fireplace"
        )
        entity.hass = hass
        return entity

    def test_unique_id(self, sensor):
        assert sensor.unique_id == "test_entry-FaultCode"

    def test_translation_key(self, sensor):
        assert sensor.translation_key == "fault_code"

    def test_device_class(self, sensor):
        assert sensor.device_class == SensorDeviceClass.ENUM

    def test_entity_category(self, sensor):
        assert sensor.entity_category == EntityCategory.DIAGNOSTIC

    def test_native_value_no_fault(self, sensor):
        assert sensor.native_value == "none"

    def test_native_value_f04(self, sensor, mock_coordinator):
        mock_coordinator.fault_code = 4
        assert sensor.native_value == "f04"

    def test_native_value_f16(self, sensor, mock_coordinator):
        mock_coordinator.fault_code = 16
        assert sensor.native_value == "f16"

    def test_native_value_f43(self, sensor, mock_coordinator):
        mock_coordinator.fault_code = 43
        assert sensor.native_value == "f43"

    def test_native_value_unknown_code_returns_none(self, sensor, mock_coordinator):
        mock_coordinator.fault_code = 99
        assert sensor.native_value == "none"

    def test_options_includes_all_codes(self, sensor):
        opts = sensor.options
        assert "none" in opts
        for key in ("f02", "f04", "f16", "f41", "f43", "f44"):
            assert key in opts

    def test_options_has_19_entries(self, sensor):
        # none + 18 F-codes
        assert len(sensor.options) == 19


class TestSensorPlatformSetup:
    """Test sensor platform async_setup_entry."""

    async def test_creates_two_entities(self, hass, mock_coordinator, mock_config_entry):
        mock_coordinator.fault_code = 0
        mock_config_entry.runtime_data = mock_coordinator
        added = []
        await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

        assert len(added) == 2
        types = {type(e) for e in added}
        assert MertikAmbientTemperatureSensorEntity in types
        assert MertikFaultCodeSensorEntity in types
