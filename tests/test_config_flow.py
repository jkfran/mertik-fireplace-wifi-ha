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


async def test_user_flow_shows_form(hass: HomeAssistant):
    """Test that the user step shows the configuration form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_user_flow_creates_entry(hass: HomeAssistant):
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
