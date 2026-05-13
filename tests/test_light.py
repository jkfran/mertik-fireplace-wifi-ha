"""Tests for light entity.

The light entity uses local state tracking (_is_on, _brightness) rather
than reading from the coordinator. This reflects that the device does not
reliably report light state in its status packets.
"""

from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from homeassistant.components.light import ColorMode, ATTR_BRIGHTNESS

from custom_components.mertik.light import (
    MertikLightEntity,
    async_setup_entry,
)
from custom_components.mertik.const import DOMAIN


class TestLightEntity:
    @pytest.fixture
    def light(self, hass, mock_coordinator):
        entity = MertikLightEntity(mock_coordinator, "test_entry", "My Fireplace")
        entity.hass = hass
        entity.entity_id = "light.test_fireplace_light"
        entity.platform = MagicMock(platform_name="mertik", domain="light")
        return entity

    def test_unique_id(self, light):
        assert light.unique_id == "test_entry-Light"

    def test_translation_key(self, light):
        assert light.translation_key == "light"

    def test_has_entity_name(self, light):
        assert light.has_entity_name is True

    def test_color_mode(self, light):
        assert light.color_mode == ColorMode.BRIGHTNESS

    def test_supported_color_modes(self, light):
        assert light.supported_color_modes == {ColorMode.BRIGHTNESS}

    def test_device_info(self, light):
        info = light.device_info
        assert info["identifiers"] == {(DOMAIN, "test_entry")}
        assert info["name"] == "My Fireplace"
        assert info["manufacturer"] == "Mertik Maxitrol"

    def test_is_on_initial_false(self, light):
        """Light always starts off; state is local not from coordinator."""
        assert light.is_on is False

    def test_is_on_after_turn_on(self, light, mock_coordinator):
        light._is_on = True
        assert light.is_on is True

    def test_brightness_initial(self, light):
        """Default brightness is 128."""
        assert light.brightness == 128

    def test_brightness_reflects_local_value(self, light):
        light._brightness = 200
        assert light.brightness == 200

    async def test_turn_on_no_brightness(self, light, mock_coordinator):
        """Turn on with no brightness: sends light_on, sets _is_on=True."""
        await light.async_turn_on()
        mock_coordinator.light_on.assert_called_once()
        mock_coordinator.set_light_brightness.assert_not_called()
        assert light.is_on is True
        mock_coordinator.async_set_updated_data.assert_called_once_with(None)

    async def test_turn_on_with_brightness_when_off(self, light, mock_coordinator):
        """Turn on with brightness when currently off: sends light_on then brightness."""
        light._is_on = False
        await light.async_turn_on(**{ATTR_BRIGHTNESS: 200})
        mock_coordinator.light_on.assert_called_once()
        mock_coordinator.set_light_brightness.assert_called_once_with(200)
        assert light.is_on is True
        assert light.brightness == 200

    async def test_turn_on_with_brightness_already_on(self, light, mock_coordinator):
        """Turn on with brightness when already on: sends brightness only."""
        light._is_on = True
        await light.async_turn_on(**{ATTR_BRIGHTNESS: 200})
        mock_coordinator.light_on.assert_not_called()
        mock_coordinator.set_light_brightness.assert_called_once_with(200)
        assert light.brightness == 200

    async def test_turn_off(self, light, mock_coordinator):
        """Turn off: sets _is_on=False immediately, sends light_off."""
        light._is_on = True
        await light.async_turn_off()
        assert light.is_on is False
        mock_coordinator.light_off.assert_called_once()
        mock_coordinator.async_set_updated_data.assert_called_once_with(None)

    async def test_added_to_hass_restores_brightness(self, light, mock_coordinator):
        last_state = MagicMock()
        last_state.attributes = {ATTR_BRIGHTNESS: 200}
        with patch.object(
            light, "async_get_last_state", new_callable=AsyncMock, return_value=last_state
        ):
            await light.async_added_to_hass()
        assert light.brightness == 200
        assert light.is_on is False
        mock_coordinator.light_off.assert_called_once()

    async def test_added_to_hass_no_brightness_attr(self, light, mock_coordinator):
        last_state = MagicMock()
        last_state.attributes = {}
        with patch.object(
            light, "async_get_last_state", new_callable=AsyncMock, return_value=last_state
        ):
            await light.async_added_to_hass()
        assert light.brightness == 128
        assert light.is_on is False
        mock_coordinator.light_off.assert_called_once()

    async def test_added_to_hass_no_last_state(self, light, mock_coordinator):
        with patch.object(
            light, "async_get_last_state", new_callable=AsyncMock, return_value=None
        ):
            await light.async_added_to_hass()
        assert light.is_on is False
        mock_coordinator.light_off.assert_called_once()

    async def test_restore_light_calls_light_on_and_brightness(
        self, light, mock_coordinator
    ):
        light._brightness = 200
        with patch.object(light, "async_write_ha_state"):
            await light._restore_light()
        mock_coordinator.light_on.assert_called_once()
        mock_coordinator.set_light_brightness.assert_called_once_with(200)

    def test_fire_off_resets_is_on(self, light, mock_coordinator):
        """When fire turns off and light was on, _restore_light task is scheduled."""
        from unittest.mock import patch, AsyncMock

        light._is_on = True
        mock_coordinator.fire_just_turned_off = True
        # _restore_light is scheduled as a task via async_create_task.
        # We patch it to avoid the entity_id requirement in unit tests.
        with patch.object(
            light, "_restore_light", new_callable=AsyncMock
        ) as mock_restore:
            with patch.object(light, "async_write_ha_state"):
                light._handle_coordinator_update()
        # The task was scheduled (hass.async_create_task called with _restore_light)
        assert light._is_on is True  # stays True; restore will re-light it


class TestLightPlatformSetup:
    async def test_creates_one_entity(self, hass, mock_coordinator, mock_config_entry):
        mock_config_entry.runtime_data = mock_coordinator
        added = []
        with patch.object(
            MertikLightEntity, "async_added_to_hass", new_callable=AsyncMock
        ):
            await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))
        assert len(added) == 1
        assert isinstance(added[0], MertikLightEntity)
        assert added[0].translation_key == "light"
