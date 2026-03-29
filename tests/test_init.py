"""Tests for integration setup and teardown."""

from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_HOST
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.mertik import async_setup_entry, async_unload_entry, async_setup
from custom_components.mertik.const import DOMAIN
from custom_components.mertik.mertikdatacoordinator import MertikDataCoordinator


@pytest.fixture
def mock_config_entry_ha():
    """Config entry mock with HA-compatible attributes."""
    entry = MagicMock()
    entry.entry_id = "test_entry_abc"
    entry.data = {"name": "Test Fire", "host": "192.168.1.55"}
    return entry


class TestAsyncSetup:
    """Test the async_setup function."""

    async def test_returns_true(self, hass: HomeAssistant):
        result = await async_setup(hass, {})
        assert result is True


class TestAsyncSetupEntry:
    """Test async_setup_entry."""

    @pytest.fixture(autouse=True)
    def mock_mertik_class(self):
        with patch("custom_components.mertik.Mertik") as mock_cls:
            mock_device = MagicMock()
            mock_cls.return_value = mock_device
            self.mock_mertik_cls = mock_cls
            self.mock_device = mock_device
            yield

    @pytest.fixture(autouse=True)
    def mock_forward_setups(self):
        """Prevent actual platform forwarding."""
        with patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=AsyncMock,
        ) as mock_forward:
            self.mock_forward = mock_forward
            yield

    async def test_creates_mertik_with_host(self, hass, mock_config_entry_ha):
        await async_setup_entry(hass, mock_config_entry_ha)
        self.mock_mertik_cls.assert_called_once_with("192.168.1.55")

    async def test_stores_coordinator_in_hass_data(self, hass, mock_config_entry_ha):
        await async_setup_entry(hass, mock_config_entry_ha)
        assert DOMAIN in hass.data
        assert mock_config_entry_ha.entry_id in hass.data[DOMAIN]
        coordinator = hass.data[DOMAIN][mock_config_entry_ha.entry_id]
        assert isinstance(coordinator, MertikDataCoordinator)

    async def test_coordinator_has_mertik_device(self, hass, mock_config_entry_ha):
        await async_setup_entry(hass, mock_config_entry_ha)
        coordinator = hass.data[DOMAIN][mock_config_entry_ha.entry_id]
        assert coordinator.mertik is self.mock_device

    async def test_forwards_platforms(self, hass, mock_config_entry_ha):
        await async_setup_entry(hass, mock_config_entry_ha)
        self.mock_forward.assert_called_once_with(
            mock_config_entry_ha, ["switch", "number", "sensor", "light"]
        )

    async def test_returns_true(self, hass, mock_config_entry_ha):
        result = await async_setup_entry(hass, mock_config_entry_ha)
        assert result is True

    async def test_multiple_entries(self, hass, mock_config_entry_ha):
        """Multiple config entries should coexist."""
        await async_setup_entry(hass, mock_config_entry_ha)

        entry2 = MagicMock()
        entry2.entry_id = "test_entry_xyz"
        entry2.data = {"name": "Second Fire", "host": "192.168.1.56"}
        await async_setup_entry(hass, entry2)

        assert mock_config_entry_ha.entry_id in hass.data[DOMAIN]
        assert entry2.entry_id in hass.data[DOMAIN]


class TestAsyncSetupEntryConnectionFailure:
    """Test async_setup_entry when the fireplace is unreachable."""

    @pytest.fixture(autouse=True)
    def mock_mertik_class(self):
        with patch("custom_components.mertik.Mertik") as mock_cls:
            mock_cls.side_effect = OSError("Connection refused")
            self.mock_mertik_cls = mock_cls
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
        """Should raise ConfigEntryNotReady when connection fails."""
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, mock_config_entry_ha)

    async def test_does_not_store_data_on_failure(self, hass, mock_config_entry_ha):
        """Should not leave stale data in hass.data on failure."""
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, mock_config_entry_ha)
        assert mock_config_entry_ha.entry_id not in hass.data.get(DOMAIN, {})

    async def test_does_not_forward_platforms_on_failure(self, hass, mock_config_entry_ha):
        """Should not attempt to set up platforms if connection failed."""
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, mock_config_entry_ha)
        self.mock_forward.assert_not_called()


class TestAsyncUnloadEntry:
    """Test async_unload_entry."""

    @pytest.fixture(autouse=True)
    def mock_unload_platforms(self):
        with patch(
            "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_unload:
            self.mock_unload = mock_unload
            yield

    async def test_unloads_platforms(self, hass, mock_config_entry_ha):
        hass.data[DOMAIN] = {mock_config_entry_ha.entry_id: MagicMock()}
        await async_unload_entry(hass, mock_config_entry_ha)
        self.mock_unload.assert_called_once_with(
            mock_config_entry_ha, ["switch", "number", "sensor", "light"]
        )

    async def test_removes_data_on_success(self, hass, mock_config_entry_ha):
        hass.data[DOMAIN] = {mock_config_entry_ha.entry_id: MagicMock()}
        result = await async_unload_entry(hass, mock_config_entry_ha)
        assert result is True
        assert mock_config_entry_ha.entry_id not in hass.data[DOMAIN]

    async def test_keeps_data_on_failure(self, hass, mock_config_entry_ha):
        self.mock_unload.return_value = False
        coordinator = MagicMock()
        hass.data[DOMAIN] = {mock_config_entry_ha.entry_id: coordinator}
        result = await async_unload_entry(hass, mock_config_entry_ha)
        assert result is False
        assert hass.data[DOMAIN][mock_config_entry_ha.entry_id] is coordinator

    async def test_handles_missing_domain_data(self, hass, mock_config_entry_ha):
        """Should not crash if DOMAIN key is missing."""
        result = await async_unload_entry(hass, mock_config_entry_ha)
        assert result is True
