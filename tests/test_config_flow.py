"""Tests for the Mertik config flow."""

from unittest.mock import patch

import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.mertik.const import DOMAIN


@pytest.fixture(autouse=True)
def mock_setup_entry(enable_custom_integrations):
    """Prevent actual setup during config flow tests."""
    with patch(
        "custom_components.mertik.async_setup_entry", return_value=True
    ), patch(
        "custom_components.mertik.async_setup", return_value=True
    ):
        yield


@pytest.fixture
def mock_connection_success():
    """Mock a successful connection test."""
    with patch(
        "custom_components.mertik.config_flow._test_connection", return_value=True
    ):
        yield


@pytest.fixture
def mock_connection_failure():
    """Mock a failed connection test."""
    with patch(
        "custom_components.mertik.config_flow._test_connection", return_value=False
    ):
        yield


async def test_user_flow_shows_form(hass: HomeAssistant):
    """Test that the user step shows the configuration form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_user_flow_creates_entry(hass: HomeAssistant, mock_connection_success):
    """Test that submitting valid data creates a config entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"name": "My Fireplace", "host": "192.168.1.100"},
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Mertik Maxitrol"
    assert result["data"] == {"name": "My Fireplace", "host": "192.168.1.100"}


async def test_user_flow_connection_error(hass: HomeAssistant, mock_connection_failure):
    """Test that connection failure shows error and re-displays form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"name": "My Fireplace", "host": "192.168.1.100"},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_recover_after_error(
    hass: HomeAssistant, mock_connection_failure
):
    """Test that user can retry after a connection error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # First attempt fails
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"name": "My Fireplace", "host": "192.168.1.100"},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    # Second attempt succeeds
    with patch(
        "custom_components.mertik.config_flow._test_connection", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"name": "My Fireplace", "host": "192.168.1.100"},
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_user_flow_duplicate_host(hass: HomeAssistant, mock_connection_success):
    """Test that adding the same host twice is rejected."""
    # First entry succeeds
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"name": "My Fireplace", "host": "192.168.1.100"},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY

    # Second entry with same host is aborted
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"name": "Another Name", "host": "192.168.1.100"},
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_different_hosts_allowed(
    hass: HomeAssistant, mock_connection_success
):
    """Test that different hosts can be added."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"name": "Fireplace 1", "host": "192.168.1.100"},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"name": "Fireplace 2", "host": "192.168.1.101"},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
