"""Tests for integration setup and teardown."""

from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.mertik import (
    async_setup_entry,
    async_unload_entry,
    async_setup,
    async_remove_config_entry_device,
)
from custom_components.mertik.coordinator import MertikDataCoordinator

_FIRST_REFRESH = (
    "custom_components.mertik.coordinator."
    "MertikDataCoordinator.async_config_entry_first_refresh"
)

PLATFORMS = ["climate", "light", "number", "select", "sensor", "switch"]


@pytest.fixture
def mock_config_entry_ha():
    """Config entry mock with HA-compatible attributes."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    return MockConfigEntry(
        domain="mertik",
        entry_id="test_entry_abc",
        title="Test Fire",
        data={"host": "192.168.1.55"},
        options={},
    )


class TestAsyncSetup:
    async def test_returns_true(self, hass: HomeAssistant):
        result = await async_setup(hass, {})
        assert result is True


class TestAsyncSetupEntry:
    @pytest.fixture(autouse=True)
    def mock_mertik_class(self):
        with patch(
            "custom_components.mertik.Mertik.async_connect",
            new_callable=AsyncMock,
        ) as mock_connect:
            mock_device = MagicMock()
            mock_connect.return_value = mock_device
            self.mock_async_connect = mock_connect
            self.mock_device = mock_device
            yield

    @pytest.fixture(autouse=True)
    def mock_forward_setups(self):
        with patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=AsyncMock,
        ) as mock_forward:
            self.mock_forward = mock_forward
            yield

    @pytest.fixture(autouse=True)
    def mock_first_refresh(self):
        with patch(_FIRST_REFRESH, new_callable=AsyncMock) as mock_refresh:
            self.mock_first_refresh = mock_refresh
            yield

    async def test_creates_mertik_with_host(self, hass, mock_config_entry_ha):
        await async_setup_entry(hass, mock_config_entry_ha)
        self.mock_async_connect.assert_called_once_with("192.168.1.55")

    async def test_stores_coordinator_in_runtime_data(self, hass, mock_config_entry_ha):
        await async_setup_entry(hass, mock_config_entry_ha)
        assert isinstance(mock_config_entry_ha.runtime_data, MertikDataCoordinator)

    async def test_coordinator_has_mertik_device(self, hass, mock_config_entry_ha):
        await async_setup_entry(hass, mock_config_entry_ha)
        assert mock_config_entry_ha.runtime_data.mertik is self.mock_device

    async def test_forwards_platforms(self, hass, mock_config_entry_ha):
        await async_setup_entry(hass, mock_config_entry_ha)
        self.mock_forward.assert_called_once_with(mock_config_entry_ha, PLATFORMS)

    async def test_returns_true(self, hass, mock_config_entry_ha):
        result = await async_setup_entry(hass, mock_config_entry_ha)
        assert result is True

    async def test_calls_first_refresh(self, hass, mock_config_entry_ha):
        await async_setup_entry(hass, mock_config_entry_ha)
        self.mock_first_refresh.assert_called_once()

    async def test_multiple_entries(self, hass, mock_config_entry_ha):
        await async_setup_entry(hass, mock_config_entry_ha)
        entry2 = MagicMock()
        entry2.entry_id = "test_entry_xyz"
        entry2.data = {"name": "Second Fire", "host": "192.168.1.56"}
        entry2.options = {}
        await async_setup_entry(hass, entry2)
        assert isinstance(mock_config_entry_ha.runtime_data, MertikDataCoordinator)
        assert isinstance(entry2.runtime_data, MertikDataCoordinator)


class TestAsyncSetupEntryFirstRefreshFailure:
    @pytest.fixture(autouse=True)
    def mock_mertik_class(self):
        with patch(
            "custom_components.mertik.Mertik.async_connect",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ):
            yield

    @pytest.fixture(autouse=True)
    def mock_forward_setups(self):
        with patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=AsyncMock,
        ):
            yield

    async def test_first_refresh_failure_raises_config_entry_not_ready(
        self, hass, mock_config_entry_ha
    ):
        with patch(
            _FIRST_REFRESH,
            new_callable=AsyncMock,
            side_effect=ConfigEntryNotReady("Device unavailable"),
        ):
            with pytest.raises(ConfigEntryNotReady):
                await async_setup_entry(hass, mock_config_entry_ha)


class TestAsyncSetupEntryConnectionFailure:
    @pytest.fixture(autouse=True)
    def mock_mertik_class(self):
        with patch(
            "custom_components.mertik.Mertik.async_connect",
            new_callable=AsyncMock,
            side_effect=Exception("Connection refused"),
        ) as mock_connect:
            self.mock_async_connect = mock_connect
            yield

    @pytest.fixture(autouse=True)
    def mock_forward_setups(self):
        with patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=AsyncMock,
        ) as mock_forward:
            self.mock_forward = mock_forward
            yield

    async def test_raises_config_entry_not_ready(self, hass, mock_config_entry_ha):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, mock_config_entry_ha)

    async def test_does_not_set_runtime_data_on_failure(
        self, hass, mock_config_entry_ha
    ):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, mock_config_entry_ha)
        assert not hasattr(mock_config_entry_ha, "runtime_data") or not isinstance(
            mock_config_entry_ha.runtime_data, MertikDataCoordinator
        )

    async def test_does_not_forward_platforms_on_failure(
        self, hass, mock_config_entry_ha
    ):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, mock_config_entry_ha)
        self.mock_forward.assert_not_called()


class TestAsyncUnloadEntry:
    @pytest.fixture(autouse=True)
    def mock_unload_platforms(self):
        with patch(
            "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_unload:
            self.mock_unload = mock_unload
            yield

    @pytest.fixture
    def entry_with_runtime_data(self, mock_config_entry_ha):
        mock_config_entry_ha.runtime_data = MagicMock()
        mock_config_entry_ha.runtime_data.mertik.close = AsyncMock()
        return mock_config_entry_ha

    async def test_unloads_platforms(self, hass, entry_with_runtime_data):
        await async_unload_entry(hass, entry_with_runtime_data)
        self.mock_unload.assert_called_once_with(entry_with_runtime_data, PLATFORMS)

    async def test_closes_socket_on_success(self, hass, entry_with_runtime_data):
        await async_unload_entry(hass, entry_with_runtime_data)
        entry_with_runtime_data.runtime_data.mertik.close.assert_called_once()

    async def test_returns_true_on_success(self, hass, entry_with_runtime_data):
        result = await async_unload_entry(hass, entry_with_runtime_data)
        assert result is True

    async def test_returns_false_on_failure(self, hass, entry_with_runtime_data):
        self.mock_unload.return_value = False
        result = await async_unload_entry(hass, entry_with_runtime_data)
        assert result is False

    async def test_does_not_close_socket_on_failure(
        self, hass, entry_with_runtime_data
    ):
        self.mock_unload.return_value = False
        await async_unload_entry(hass, entry_with_runtime_data)
        entry_with_runtime_data.runtime_data.mertik.close.assert_not_called()


class TestAsyncRemoveConfigEntryDevice:
    async def test_returns_true(self, hass, mock_config_entry_ha):
        device_entry = MagicMock()
        result = await async_remove_config_entry_device(
            hass, mock_config_entry_ha, device_entry
        )
        assert result is True
