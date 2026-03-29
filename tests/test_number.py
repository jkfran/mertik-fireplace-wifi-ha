"""Tests for number entity (flame height)."""

from unittest.mock import MagicMock

import pytest

from custom_components.mertik.number import (
    MertikFlameHeightEntity,
    async_setup_entry,
)
from custom_components.mertik.const import DOMAIN


class TestFlameHeightEntity:
    """Test the flame height number entity."""

    @pytest.fixture
    def number(self, hass, mock_coordinator):
        entity = MertikFlameHeightEntity(mock_coordinator, "test_entry", "My Fireplace")
        entity.hass = hass
        return entity

    def test_unique_id(self, number):
        assert number.unique_id == "test_entry-FlameHeight"

    def test_name(self, number):
        assert number.name == "Flame Height"

    def test_has_entity_name(self, number):
        assert number.has_entity_name is True

    def test_icon(self, number):
        assert number.icon == "mdi:fire"

    def test_device_info(self, number):
        info = number.device_info
        assert info["identifiers"] == {(DOMAIN, "test_entry")}
        assert info["name"] == "My Fireplace"
        assert info["manufacturer"] == "Mertik Maxitrol"

    def test_min_value(self, number):
        assert number.native_min_value == 1

    def test_max_value(self, number):
        assert number.native_max_value == 12

    def test_native_value(self, number, mock_coordinator):
        mock_coordinator.get_flame_height.return_value = 7
        assert number.native_value == 7

    def test_native_value_zero(self, number, mock_coordinator):
        mock_coordinator.get_flame_height.return_value = 0
        assert number.native_value == 0

    async def test_set_value(self, number, mock_coordinator):
        await number.async_set_native_value(5.0)
        mock_coordinator.set_flame_height.assert_called_once_with(5)
        mock_coordinator.async_set_updated_data.assert_called_once_with(None)

    async def test_set_value_rounds_float(self, number, mock_coordinator):
        await number.async_set_native_value(8.7)
        mock_coordinator.set_flame_height.assert_called_once_with(8)


class TestNumberPlatformSetup:
    """Test number platform async_setup_entry."""

    async def test_creates_one_entity(self, hass, mock_coordinator, mock_config_entry):
        hass.data[DOMAIN] = {mock_config_entry.entry_id: mock_coordinator}
        added = []
        await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

        assert len(added) == 1
        assert isinstance(added[0], MertikFlameHeightEntity)
