"""Tests for light entity."""

from unittest.mock import MagicMock

import pytest

from homeassistant.components.light import ColorMode, ATTR_BRIGHTNESS

from custom_components.mertik.light import (
    MertikLightEntity,
    async_setup_entry,
)
from custom_components.mertik.const import DOMAIN


class TestLightEntity:
    """Test the light entity."""

    @pytest.fixture
    def light(self, hass, mock_coordinator):
        entity = MertikLightEntity(
            hass, mock_coordinator, "test_entry", "My Fireplace"
        )
        entity.hass = hass
        return entity

    def test_unique_id(self, light):
        assert light.unique_id == "test_entry-Light"

    def test_name(self, light):
        assert light.name == "My Fireplace Light"

    def test_color_mode(self, light):
        assert light.color_mode == ColorMode.BRIGHTNESS

    def test_supported_color_modes(self, light):
        assert light.supported_color_modes == {ColorMode.BRIGHTNESS}

    def test_device_info(self, light):
        info = light.device_info
        assert info["identifiers"] == {(DOMAIN, "test_entry")}
        assert info["name"] == "My Fireplace"
        assert info["manufacturer"] == "Mertik Maxitrol"

    def test_is_on_false(self, light, mock_coordinator):
        mock_coordinator.is_light_on = False
        assert light.is_on is False

    def test_is_on_true(self, light, mock_coordinator):
        mock_coordinator.is_light_on = True
        assert light.is_on is True

    def test_brightness(self, light, mock_coordinator):
        mock_coordinator.light_brightness = 128
        assert light.brightness == 128

    async def test_turn_on_no_brightness(self, light, mock_coordinator):
        """Turn on without brightness should call light_on."""
        mock_coordinator.is_light_on = False
        await light.async_turn_on()
        mock_coordinator.light_on.assert_called_once()
        mock_coordinator.set_light_brightness.assert_not_called()
        mock_coordinator.async_set_updated_data.assert_called_once_with(None)

    async def test_turn_on_with_brightness(self, light, mock_coordinator):
        """Turn on with brightness should call set_light_brightness."""
        await light.async_turn_on(**{ATTR_BRIGHTNESS: 200})
        mock_coordinator.set_light_brightness.assert_called_once_with(200)
        mock_coordinator.light_on.assert_not_called()
        mock_coordinator.async_set_updated_data.assert_called_once_with(None)

    async def test_turn_on_already_on_no_brightness(self, light, mock_coordinator):
        """Turn on when already on with no brightness should not call light_on."""
        mock_coordinator.is_light_on = True
        await light.async_turn_on()
        mock_coordinator.light_on.assert_not_called()
        mock_coordinator.set_light_brightness.assert_not_called()
        mock_coordinator.async_set_updated_data.assert_called_once_with(None)

    async def test_turn_off(self, light, mock_coordinator):
        await light.async_turn_off()
        mock_coordinator.light_off.assert_called_once()
        mock_coordinator.async_set_updated_data.assert_called_once_with(None)


class TestLightPlatformSetup:
    """Test light platform async_setup_entry."""

    async def test_creates_one_entity(self, hass, mock_coordinator, mock_config_entry):
        hass.data[DOMAIN] = {mock_config_entry.entry_id: mock_coordinator}
        added = []
        await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

        assert len(added) == 1
        assert isinstance(added[0], MertikLightEntity)
        assert added[0].name == "My Fireplace Light"
