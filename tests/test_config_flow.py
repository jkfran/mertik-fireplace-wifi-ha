"""Tests for the Mertik config flow."""

from unittest.mock import patch, MagicMock

import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.mertik.const import (
    CONF_LOW_THRESHOLD,
    CONF_HIGH_THRESHOLD,
    CONF_TEMP_SENSOR,
    CONF_TEMP_STEP,
    DEFAULT_LOW_THRESHOLD,
    DEFAULT_HIGH_THRESHOLD,
)

from custom_components.mertik.const import DOMAIN


@pytest.fixture(autouse=True)
def mock_setup_entry(enable_custom_integrations):
    """Prevent actual setup during config flow tests."""
    with (
        patch("custom_components.mertik.async_setup_entry", return_value=True),
        patch("custom_components.mertik.async_setup", return_value=True),
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
    assert result["data"]["name"] == "My Fireplace"
    assert result["data"]["host"] == "192.168.1.100"


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


async def test_user_flow_invalid_thresholds(
    hass: HomeAssistant, mock_connection_success
):
    """Test that invalid threshold values (low >= high) show an error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "name": "My Fireplace",
            "host": "192.168.1.100",
            CONF_LOW_THRESHOLD: 5.0,
            CONF_HIGH_THRESHOLD: 5.0,  # equal: invalid
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_thresholds"}


# ---------------------------------------------------------------------------
# Reconfigure flow
# ---------------------------------------------------------------------------


async def test_reconfigure_shows_form(hass: HomeAssistant, mock_connection_success):
    """Reconfigure flow shows form pre-filled with current entry data."""
    entry = await _create_entry(hass, mock_connection_success)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"


async def test_reconfigure_updates_host_and_name(
    hass: HomeAssistant, mock_connection_success
):
    """Successful reconfigure updates the entry and reloads."""
    entry = await _create_entry(hass, mock_connection_success)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"name": "Renamed Fireplace", "host": "192.168.1.200"},
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["name"] == "Renamed Fireplace"
    assert entry.data["host"] == "192.168.1.200"


async def test_reconfigure_same_host_name_change(
    hass: HomeAssistant, mock_connection_success
):
    """Reconfiguring with the same host (e.g. just renaming) succeeds."""
    entry = await _create_entry(hass, mock_connection_success)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"name": "Living Room Fire", "host": "192.168.1.100"},
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["name"] == "Living Room Fire"


async def test_reconfigure_connection_failure(
    hass: HomeAssistant, mock_connection_success
):
    """Connection failure during reconfigure shows an error."""
    entry = await _create_entry(hass, mock_connection_success)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    with patch(
        "custom_components.mertik.config_flow._test_connection", return_value=False
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"name": "My Fireplace", "host": "192.168.1.99"},
        )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reconfigure_invalid_thresholds(
    hass: HomeAssistant, mock_connection_success
):
    """Invalid thresholds are rejected during reconfigure."""
    entry = await _create_entry(hass, mock_connection_success)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "name": "My Fireplace",
            "host": "192.168.1.100",
            CONF_LOW_THRESHOLD: 5.0,
            CONF_HIGH_THRESHOLD: 5.0,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_thresholds"}


async def test_reconfigure_duplicate_host(hass: HomeAssistant, mock_connection_success):
    """Cannot reconfigure to a host already used by another entry."""
    # Create two entries with different hosts
    entry1 = await _create_entry(hass, mock_connection_success)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"name": "Second Fireplace", "host": "192.168.1.101"},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY

    # Try to reconfigure entry1 to use entry2's host
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry1.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"name": "My Fireplace", "host": "192.168.1.101"},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "already_configured"}


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------


async def _create_entry(hass, mock_connection_success):
    """Helper: run user flow to completion and return the created entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"name": "My Fireplace", "host": "192.168.1.100"},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    return hass.config_entries.async_entries(DOMAIN)[0]


async def test_options_flow_shows_form(hass: HomeAssistant, mock_connection_success):
    """Test that the options flow displays a form on init."""
    entry = await _create_entry(hass, mock_connection_success)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"


async def test_options_flow_saves_valid_thresholds(
    hass: HomeAssistant, mock_connection_success
):
    """Test that valid thresholds are saved to entry options."""
    entry = await _create_entry(hass, mock_connection_success)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_LOW_THRESHOLD: 1.5,
            CONF_HIGH_THRESHOLD: 4.0,
            CONF_TEMP_SENSOR: "",
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_LOW_THRESHOLD] == 1.5
    assert entry.options[CONF_HIGH_THRESHOLD] == 4.0


async def test_options_flow_rejects_invalid_thresholds(
    hass: HomeAssistant, mock_connection_success
):
    """Test that low >= high is rejected with an error."""
    entry = await _create_entry(hass, mock_connection_success)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_LOW_THRESHOLD: 3.0,
            CONF_HIGH_THRESHOLD: 3.0,
            CONF_TEMP_SENSOR: "",
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_thresholds"}


async def test_options_flow_rejects_invalid_temp_step(
    hass: HomeAssistant, mock_connection_success
):
    """Test that a zero or negative temperature step is rejected."""
    entry = await _create_entry(hass, mock_connection_success)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_LOW_THRESHOLD: 1.0,
            CONF_HIGH_THRESHOLD: 2.0,
            CONF_TEMP_SENSOR: "",
            CONF_TEMP_STEP: 0.0,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_TEMP_STEP: "invalid_temp_step"}


async def test_options_flow_previous_sensor_gone_falls_back(
    hass: HomeAssistant, mock_connection_success
):
    """If previously saved sensor no longer exists, the form still opens."""
    entry = await _create_entry(hass, mock_connection_success)
    hass.config_entries.async_update_entry(
        entry, options={CONF_TEMP_SENSOR: "sensor.nonexistent"}
    )
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM


# ---------------------------------------------------------------------------
# _test_connection helper
# ---------------------------------------------------------------------------


def test_test_connection_success():
    """_test_connection returns True when socket connects."""
    from custom_components.mertik.config_flow import _test_connection

    with patch("custom_components.mertik.config_flow.socket.socket") as mock_cls:
        mock_sock = MagicMock()
        mock_cls.return_value = mock_sock
        result = _test_connection("192.168.1.100")

    assert result is True
    mock_sock.connect.assert_called_once_with(("192.168.1.100", 2000))


def test_test_connection_failure():
    """_test_connection returns False when socket raises OSError."""
    from custom_components.mertik.config_flow import _test_connection

    with patch("custom_components.mertik.config_flow.socket.socket") as mock_cls:
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = OSError("Connection refused")
        mock_cls.return_value = mock_sock
        result = _test_connection("192.168.1.100")

    assert result is False


# ---------------------------------------------------------------------------
# _temp_sensor_options helper
# ---------------------------------------------------------------------------


async def test_temp_sensor_options_includes_builtin(hass: HomeAssistant):
    """_temp_sensor_options always includes the built-in Mertik handset entry."""
    from custom_components.mertik.config_flow import _temp_sensor_options

    options = _temp_sensor_options(hass)
    assert "" in options
    assert "Mertik handset" in options[""]


async def test_temp_sensor_options_with_registered_sensors(hass: HomeAssistant):
    """_temp_sensor_options includes external temp sensors, skips Mertik own sensor."""
    from custom_components.mertik.config_flow import _temp_sensor_options
    from homeassistant.components.sensor import SensorDeviceClass
    from custom_components.mertik.const import DOMAIN

    hass.states.async_set(
        "sensor.living_room", "22.5",
        {"device_class": SensorDeviceClass.TEMPERATURE, "friendly_name": "Living Room"},
    )
    hass.states.async_set(
        "sensor.mertik_internal", "21.0",
        {"device_class": SensorDeviceClass.TEMPERATURE},
    )
    # sensor.no_state intentionally has no state → exercises the `continue` branch

    external = MagicMock()
    external.entity_id = "sensor.living_room"
    external.domain = "sensor"
    external.platform = "weather"  # not DOMAIN → included

    mertik_sensor = MagicMock()
    mertik_sensor.entity_id = "sensor.mertik_internal"
    mertik_sensor.domain = "sensor"
    mertik_sensor.platform = DOMAIN  # own sensor → skipped

    no_state = MagicMock()
    no_state.entity_id = "sensor.no_state"

    with patch("custom_components.mertik.config_flow.er.async_get") as mock_er:
        mock_registry = MagicMock()
        mock_registry.entities.values.return_value = [external, mertik_sensor, no_state]
        mock_er.return_value = mock_registry
        options = _temp_sensor_options(hass)

    assert "sensor.living_room" in options
    assert "Living Room" in options["sensor.living_room"]
    assert "sensor.mertik_internal" not in options
    assert "sensor.no_state" not in options
    assert "" in options
