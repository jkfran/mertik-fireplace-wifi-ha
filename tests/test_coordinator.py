"""Tests for the MertikDataCoordinator."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from homeassistant.util import dt as dt_util

from custom_components.mertik.mertikdatacoordinator import (
    MertikDataCoordinator,
    OPTIMISTIC_ON_SECONDS,
    OPTIMISTIC_OFF_SECONDS,
)


@pytest.fixture
def mock_mertik():
    """Return a mock Mertik device."""
    mertik = MagicMock()
    mertik.is_on = False
    mertik.is_igniting = False
    mertik.is_aux_on = False
    mertik.is_light_on = False
    mertik.light_brightness = 0
    mertik.ambient_temperature = 20.0
    return mertik


@pytest.fixture
def coordinator(hass, mock_mertik):
    """Return a MertikDataCoordinator with mocked Mertik."""
    return MertikDataCoordinator(hass, mock_mertik)


class TestOptimisticState:
    """Test optimistic on/off state logic."""

    def test_is_on_false_by_default(self, coordinator, mock_mertik):
        """When device is off and no optimistic state, is_on should be False."""
        mock_mertik.is_on = False
        mock_mertik.is_igniting = False
        assert coordinator.is_on is False

    def test_is_on_true_when_device_on(self, coordinator, mock_mertik):
        """When device reports on, is_on should be True."""
        mock_mertik.is_on = True
        assert coordinator.is_on is True

    def test_is_on_true_when_igniting(self, coordinator, mock_mertik):
        """When device is igniting, is_on should be True."""
        mock_mertik.is_igniting = True
        assert coordinator.is_on is True

    def test_optimistic_on(self, coordinator, mock_mertik):
        """After mark_optimistic_on, is_on should be True even if device says off."""
        mock_mertik.is_on = False
        mock_mertik.is_igniting = False
        coordinator.mark_optimistic_on()
        assert coordinator.is_on is True

    def test_optimistic_on_expires(self, coordinator, mock_mertik):
        """Optimistic on should expire after OPTIMISTIC_ON_SECONDS."""
        mock_mertik.is_on = False
        mock_mertik.is_igniting = False
        coordinator.mark_optimistic_on()

        future = dt_util.utcnow() + timedelta(seconds=OPTIMISTIC_ON_SECONDS + 1)
        with patch.object(dt_util, "utcnow", return_value=future):
            assert coordinator.is_on is False

    def test_optimistic_off(self, coordinator, mock_mertik):
        """After mark_optimistic_off, is_on should be False even if device says on."""
        mock_mertik.is_on = True
        coordinator.mark_optimistic_off()
        assert coordinator.is_on is False

    def test_optimistic_off_expires(self, coordinator, mock_mertik):
        """Optimistic off should expire after OPTIMISTIC_OFF_SECONDS."""
        mock_mertik.is_on = True
        coordinator.mark_optimistic_off()

        future = dt_util.utcnow() + timedelta(seconds=OPTIMISTIC_OFF_SECONDS + 1)
        with patch.object(dt_util, "utcnow", return_value=future):
            assert coordinator.is_on is True

    def test_optimistic_on_clears_optimistic_off(self, coordinator, mock_mertik):
        """mark_optimistic_on should clear any pending optimistic_off."""
        mock_mertik.is_on = True
        coordinator.mark_optimistic_off()
        assert coordinator.is_on is False

        coordinator.mark_optimistic_on()
        assert coordinator.is_on is True

    def test_optimistic_off_clears_optimistic_on(self, coordinator, mock_mertik):
        """mark_optimistic_off should clear any pending optimistic_on."""
        mock_mertik.is_on = False
        mock_mertik.is_igniting = False
        coordinator.mark_optimistic_on()
        assert coordinator.is_on is True

        coordinator.mark_optimistic_off()
        assert coordinator.is_on is False


class TestCoordinatorDelegation:
    """Test that coordinator properly delegates to Mertik device."""

    def test_ignite_fireplace(self, coordinator, mock_mertik):
        coordinator.ignite_fireplace()
        mock_mertik.ignite_fireplace.assert_called_once()

    def test_guard_flame_off_clears_optimistic(self, coordinator, mock_mertik):
        """guard_flame_off should clear optimistic state and delegate."""
        coordinator.mark_optimistic_on()
        coordinator.guard_flame_off()
        mock_mertik.guard_flame_off.assert_called_once()
        # Optimistic should be cleared
        assert coordinator._optimistic_on_until is None
        assert coordinator._optimistic_off_until is None

    def test_aux_on(self, coordinator, mock_mertik):
        coordinator.aux_on()
        mock_mertik.aux_on.assert_called_once()

    def test_aux_off(self, coordinator, mock_mertik):
        coordinator.aux_off()
        mock_mertik.aux_off.assert_called_once()

    def test_get_flame_height(self, coordinator, mock_mertik):
        mock_mertik.get_flame_height.return_value = 5
        assert coordinator.get_flame_height() == 5

    def test_set_flame_height(self, coordinator, mock_mertik):
        coordinator.set_flame_height(7)
        mock_mertik.set_flame_height.assert_called_once_with(7)

    def test_light_on(self, coordinator, mock_mertik):
        coordinator.light_on()
        mock_mertik.light_on.assert_called_once()

    def test_light_off(self, coordinator, mock_mertik):
        coordinator.light_off()
        mock_mertik.light_off.assert_called_once()

    def test_set_light_brightness(self, coordinator, mock_mertik):
        coordinator.set_light_brightness(128)
        mock_mertik.set_light_brightness.assert_called_once_with(128)

    def test_ambient_temperature(self, coordinator, mock_mertik):
        mock_mertik.ambient_temperature = 22.5
        assert coordinator.ambient_temperature == 22.5

    def test_is_aux_on_requires_device_on(self, coordinator, mock_mertik):
        """is_aux_on should only be True if device is on AND aux is on."""
        mock_mertik.is_on = False
        mock_mertik.is_aux_on = True
        assert coordinator.is_aux_on is False

        mock_mertik.is_on = True
        assert coordinator.is_aux_on is True

    def test_light_brightness(self, coordinator, mock_mertik):
        mock_mertik.light_brightness = 200
        assert coordinator.light_brightness == 200

    def test_is_light_on(self, coordinator, mock_mertik):
        mock_mertik.is_light_on = True
        assert coordinator.is_light_on is True


class TestAsyncUpdateData:
    """Test the coordinator's _async_update_data method."""

    async def test_calls_refresh_status(self, coordinator, mock_mertik):
        """_async_update_data should call mertik.refresh_status via executor."""
        await coordinator._async_update_data()
        mock_mertik.refresh_status.assert_called_once()

    async def test_update_interval(self, coordinator):
        """Update interval should be 10 seconds."""
        from datetime import timedelta

        assert coordinator.update_interval == timedelta(seconds=10)

    async def test_raises_update_failed_on_error(self, coordinator, mock_mertik):
        """Should raise UpdateFailed when refresh_status raises."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        mock_mertik.refresh_status.side_effect = Exception("Connection lost")
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
