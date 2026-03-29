import logging
import socket

from typing import Any, Dict, Optional

from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_HOST
import voluptuous as vol

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DEVICE_SCHEMA = vol.Schema(
    {vol.Required(CONF_NAME): str, vol.Required(CONF_HOST): str}
)


class MertikConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Mertik config flow."""

    async def async_step_user(self, device_input: Optional[Dict[str, Any]] = None):
        """Invoked when a user initiates a flow via the user interface."""
        errors: Dict[str, str] = {}
        if device_input is not None:
            host = device_input[CONF_HOST]

            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()

            can_connect = await self.hass.async_add_executor_job(
                _test_connection, host
            )
            if not can_connect:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title="Mertik Maxitrol", data=device_input
                )

        return self.async_show_form(
            step_id="user", data_schema=DEVICE_SCHEMA, errors=errors
        )


def _test_connection(host: str) -> bool:
    """Test if the fireplace is reachable on TCP port 2000."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((host, 2000))
        sock.close()
        return True
    except OSError:
        return False
