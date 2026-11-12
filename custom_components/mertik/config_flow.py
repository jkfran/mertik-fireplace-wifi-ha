"""Setting up a fireplace, changing its address, and its options."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.device_registry import format_mac

from .const import CONF_MAC, CONF_MODEL, CONF_TEMPERATURE_SENSOR, DOMAIN
from .discovery import Module, discover, discover_host
from .mertik import Mertik, MertikError

DEFAULT_NAME = "Fireplace"


def _can_connect(host: str) -> bool:
    """Whether a fireplace answers a status request at this address."""
    try:
        Mertik(host)
    except MertikError:
        return False
    return True


class MertikConfigFlow(ConfigFlow, domain=DOMAIN):
    """Mertik config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._modules: list[Module] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> MertikOptionsFlow:
        return MertikOptionsFlow()

    def _host_selector(self) -> Any:
        """A list of the modules found, in which any other address can be typed."""
        if not self._modules:
            return str
        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(
                        value=module.host,
                        label=f"{module.host} ({module.name}, {module.mac})",
                    )
                    for module in self._modules
                ],
                custom_value=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )

    def _found(self) -> str:
        if not self._modules:
            return "-"
        return ", ".join(module.host for module in self._modules)

    async def _async_module_at(self, host: str) -> Module | None:
        """The module answering at an address: from the search, or asked directly."""
        for module in self._modules:
            if module.host == host:
                return module
        return await self.hass.async_add_executor_job(discover_host, host)

    def _is_another_entry(self, entry: ConfigEntry, mac: str) -> bool:
        """Whether a MAC address identifies a fireplace set up as another entry."""
        return any(
            other.entry_id != entry.entry_id
            and mac in (other.unique_id, other.data.get(CONF_MAC))
            for other in self._async_current_entries(include_ignore=False)
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a fireplace found on the network, or type its address."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            module = await self._async_module_at(host)
            # Entries made before 2.0 are identified by their address.
            self._async_abort_entries_match({CONF_HOST: host})
            await self.async_set_unique_id(module.mac if module else host)
            self._abort_if_unique_id_configured(updates={CONF_HOST: host})

            if not await self.hass.async_add_executor_job(_can_connect, host):
                errors["base"] = "cannot_connect"
            else:
                data = {CONF_NAME: user_input[CONF_NAME], CONF_HOST: host}
                if module:
                    data[CONF_MAC] = module.mac
                    data[CONF_MODEL] = module.name
                return self.async_create_entry(title=user_input[CONF_NAME], data=data)
        else:
            self._modules = await self.hass.async_add_executor_job(discover)

        configured = {entry.data.get(CONF_HOST) for entry in self._async_current_entries()}
        new = [module.host for module in self._modules if module.host not in configured]
        suggested = (user_input or {}).get(CONF_HOST) or (new[0] if new else vol.UNDEFINED)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_NAME, default=(user_input or {}).get(CONF_NAME, DEFAULT_NAME)
                ): str,
                vol.Required(CONF_HOST, default=suggested): self._host_selector(),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={"found": self._found()},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the address of the fireplace."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            module = await self._async_module_at(host)
            known_mac = entry.data.get(CONF_MAC)
            if module and (
                (known_mac and module.mac != known_mac)
                or self._is_another_entry(entry, module.mac)
            ):
                errors["base"] = "wrong_device"
            elif not await self.hass.async_add_executor_job(_can_connect, host):
                errors["base"] = "cannot_connect"
            else:
                updates: dict[str, Any] = {CONF_HOST: host}
                unique_id = entry.unique_id
                if module:
                    updates[CONF_MAC] = module.mac
                    updates[CONF_MODEL] = module.name
                    unique_id = module.mac
                elif not known_mac:
                    unique_id = host
                return self.async_update_reload_and_abort(
                    entry, unique_id=unique_id, data_updates=updates
                )
        else:
            self._modules = await self.hass.async_add_executor_job(discover)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_HOST, default=(user_input or {}).get(CONF_HOST, entry.data[CONF_HOST])
                ): self._host_selector()
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "current": entry.data[CONF_HOST],
                "found": self._found(),
            },
        )

    async def async_step_dhcp(self, discovery_info: Any) -> ConfigFlowResult:
        """Follow a fireplace that is already set up to a new address.

        Only modules Home Assistant already knows by MAC address get here.
        """
        await self.async_set_unique_id(format_mac(discovery_info.macaddress))
        self._abort_if_unique_id_configured(updates={CONF_HOST: discovery_info.ip})
        return self.async_abort(reason="not_configured")


class MertikOptionsFlow(OptionsFlow):
    """Options: the temperature sensor for the thermostat."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            options = {}
            if sensor := user_input.get(CONF_TEMPERATURE_SENSOR):
                options[CONF_TEMPERATURE_SENSOR] = sensor
            return self.async_create_entry(data=options)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_TEMPERATURE_SENSOR,
                    description={
                        "suggested_value": self.config_entry.options.get(CONF_TEMPERATURE_SENSOR)
                    },
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        filter=selector.EntityFilterSelectorConfig(
                            domain="sensor", device_class="temperature"
                        )
                    )
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
