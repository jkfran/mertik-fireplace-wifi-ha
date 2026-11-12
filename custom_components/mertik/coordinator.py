"""Polls the fireplace and carries out what the entities ask for."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import math
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    CONF_MAC,
    CONF_TEMPERATURE_SENSOR,
    DOMAIN,
    IDENTITY_CHECK_SECONDS,
    OPTIMISTIC_SECONDS,
    PENDING_TIMEOUT_SECONDS,
    REIGNITE_DELAY_SECONDS,
    UPDATE_INTERVAL,
)
from .discovery import discover_host
from .mertik import (
    MODE_ECO,
    MODE_MANUAL,
    MODE_THERMOSTAT,
    STATE_IGNITING,
    STATE_OFF,
    STATE_ON,
    STATE_SHUTTING_DOWN,
    STATE_STANDBY,
    Mertik,
    MertikError,
    MertikReceiverError,
)
from .thermostat import FLAME_HEIGHT, ThermostatState

_LOGGER = logging.getLogger(__name__)

type MertikConfigEntry = ConfigEntry[MertikDataCoordinator]

_PILOT_STATES = (STATE_ON, STATE_STANDBY)


class MertikDataCoordinator(DataUpdateCoordinator[None]):
    """One fireplace: its state, and the commands sent to it."""

    config_entry: MertikConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: MertikConfigEntry,
        mertik: Mertik,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"Mertik {entry.title}",
            update_interval=UPDATE_INTERVAL,
        )
        self.mertik = mertik
        self._clock = clock
        # Requested values, shown until the fireplace reports them itself.
        self._overlay: dict[str, tuple[Any, float]] = {}
        # Commands given while the fireplace was lighting, sent once it is lit.
        self._pending: dict[str, Any] = {}
        self._pending_since: float | None = None
        self._pending_task: asyncio.Task[None] | None = None
        self._off_since: float | None = None
        self._last_state: str | None = mertik.state
        # Setting up has just made sure the module is this fireplace.
        self._identity_checked_at = self._clock()
        self._reload_scheduled = False
        self.thermostat = ThermostatState()

    # --- State ---------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """The fireplace answers and the box still has its link to the receiver."""
        return self.last_update_success and not self.mertik.receiver_lost

    @property
    def state(self) -> str | None:
        return self.mertik.state

    @property
    def is_on(self) -> bool:
        """On, in standby or lighting: the fireplace has been turned on."""
        return self.mertik.is_on

    @property
    def is_pilot_on(self) -> bool:
        return self.mertik.is_pilot_on

    @property
    def is_burning(self) -> bool:
        return self.mertik.is_burning

    @property
    def is_igniting(self) -> bool:
        return self.mertik.is_igniting

    @property
    def is_shutting_down(self) -> bool:
        return self.mertik.is_shutting_down

    def _shown(self, key: str, reported: Any) -> Any:
        """A requested value while it is fresh, otherwise the reported one."""
        if (entry := self._overlay.get(key)) is not None:
            value, until = entry
            if self._clock() < until:
                return value
            del self._overlay[key]
        return reported

    def _expect(self, key: str, value: Any) -> None:
        self._overlay[key] = (value, self._clock() + OPTIMISTIC_SECONDS)

    @property
    def flame_height(self) -> int:
        if "flame_height" in self._pending:
            return self._pending["flame_height"]
        return self._shown("flame_height", self.mertik.flame_height)

    def get_flame_height(self) -> int:
        return self.flame_height

    @property
    def is_aux_on(self) -> bool:
        """The secondary burner; it reads off while the fireplace itself is off."""
        if "aux" in self._pending:
            return self._pending["aux"]
        return self._shown("aux", self.mertik.is_aux_on) and (
            self.is_pilot_on or self.is_igniting
        )

    @property
    def is_light_on(self) -> bool:
        return self._shown("light", self.mertik.is_light_on)

    @property
    def light_brightness(self) -> int:
        if not self.is_light_on:
            return 0
        return self._shown("brightness", self.mertik.light_brightness)

    @property
    def mode(self) -> str | None:
        return self._shown("mode", self.mertik.mode)

    @property
    def ambient_temperature(self) -> float | None:
        """Room temperature from the handset."""
        return self.mertik.ambient_temperature

    @property
    def target_temperature(self) -> float | None:
        """Target temperature of the fireplace's own thermostat."""
        return self.mertik.target_temperature

    # --- Thermostat sensor -----------------------------------------------------------

    @property
    def temperature_sensor(self) -> str | None:
        """The Home Assistant sensor the thermostat regulates on, if one is set."""
        return self.config_entry.options.get(CONF_TEMPERATURE_SENSOR) or None

    @property
    def sensor_temperature(self) -> float | None:
        """Reading of that sensor in Celsius, None while it has none."""
        if (entity_id := self.temperature_sensor) is None:
            return None
        if (state := self.hass.states.get(entity_id)) is None:
            return None
        try:
            value = float(state.state)
        except ValueError:
            return None
        if not math.isfinite(value):
            return None
        if state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) == UnitOfTemperature.FAHRENHEIT:
            value = TemperatureConverter.convert(
                value, UnitOfTemperature.FAHRENHEIT, UnitOfTemperature.CELSIUS
            )
        return value

    @property
    def room_temperature(self) -> float | None:
        """The temperature the thermostat works with."""
        if self.temperature_sensor is not None:
            return self.sensor_temperature
        return self.ambient_temperature

    @property
    def is_thermostat_on(self) -> bool:
        if self.temperature_sensor is not None:
            return self.thermostat.active or "thermostat" in self._pending
        return self.mode == MODE_THERMOSTAT and self.is_pilot_on

    @property
    def thermostat_target(self) -> float | None:
        if self.temperature_sensor is not None:
            return self.thermostat.target
        return self.target_temperature

    # --- Polling ---------------------------------------------------------------------

    async def _async_update_data(self) -> None:
        recovering = not self.last_update_success
        try:
            await self.hass.async_add_executor_job(self.mertik.refresh_status)
        except MertikError as err:
            raise UpdateFailed(f"Error communicating with fireplace: {err}") from err
        # A connection that comes back may come back to another device: after
        # a router restart the addresses can have been dealt out anew.
        check_due = self._clock() - self._identity_checked_at >= IDENTITY_CHECK_SECONDS
        if (recovering or check_due) and await self._async_is_another_fireplace():
            raise UpdateFailed("Another fireplace answers at this fireplace's address")
        self._after_status()

    async def _async_is_another_fireplace(self) -> bool:
        """Whether the module at the stored address has stopped being this fireplace.

        The module is asked for its MAC address. One that does not answer is
        given the benefit of the doubt, and so is an entry that never learned
        its MAC address. On a mismatch the entry is set up again, which looks
        for the fireplace at its new address.
        """
        known_mac = self.config_entry.data.get(CONF_MAC)
        if known_mac is None:
            return False
        module = await self.hass.async_add_executor_job(discover_host, self.mertik.ip)
        self._identity_checked_at = self._clock()
        if module is None or module.mac == known_mac:
            return False
        if not self._reload_scheduled:
            self._reload_scheduled = True
            _LOGGER.error(
                "%s: another fireplace now answers at %s. It will not be controlled; "
                "looking for this fireplace at its new address",
                self.name,
                self.mertik.ip,
            )
            self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
        return True

    def _after_status(self) -> None:
        """Follow up on a fresh status: state changes, waiting commands, thermostat."""
        state = self.state
        now = self._clock()
        if state != self._last_state:
            if state == STATE_OFF:
                self._off_since = now
            self._last_state = state
        if state in (STATE_OFF, STATE_SHUTTING_DOWN):
            self._pending.clear()
            self._pending_since = None
            # The thermostat ends with the fire; it never lights it again.
            self.thermostat.active = False
        if self.temperature_sensor is None:
            # Without a sensor the fireplace's own thermostat is the one in use.
            self.thermostat.active = False
        self._update_issues()
        if self._pending_task is None or self._pending_task.done():
            if self._pending or self.thermostat.active:
                self._pending_task = self.config_entry.async_create_background_task(
                    self.hass, self._async_follow_up(), f"{DOMAIN} follow-up"
                )

    def _update_issues(self) -> None:
        issue_id = f"receiver_lost_{self.config_entry.entry_id}"
        if self.mertik.receiver_lost:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="receiver_lost",
                translation_placeholders={"name": self.config_entry.title},
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    async def _async_follow_up(self) -> None:
        """Send what was asked for during ignition, then let the thermostat act."""
        try:
            await self._async_send_pending()
            await self._async_run_thermostat()
        except HomeAssistantError as err:
            _LOGGER.warning("%s: %s", self.name, err)

    async def _async_send_pending(self) -> None:
        if not self._pending:
            return
        now = self._clock()
        if self._pending_since is not None and now - self._pending_since > PENDING_TIMEOUT_SECONDS:
            _LOGGER.warning("%s did not light in time; dropping %s", self.name, self._pending)
            self._pending.clear()
            return
        if self.state not in _PILOT_STATES:
            return
        pending, self._pending = self._pending, {}
        self._pending_since = None
        # Secondary burner before flame height: an aux command sent while the valve
        # moves is refused.
        if "aux" in pending:
            await self.async_set_aux(pending["aux"])
        if "flame_height" in pending:
            await self.async_set_flame_height(pending["flame_height"])
        if "mode" in pending:
            await self.async_set_mode(pending["mode"])
        if "thermostat" in pending:
            await self.async_set_thermostat(pending["thermostat"])

    def _remember(self, key: str, value: Any) -> None:
        """Keep a command for when the fireplace is lit."""
        if not self._pending:
            self._pending_since = self._clock()
        self._pending[key] = value
        self.async_update_listeners()

    # --- Commands ------------------------------------------------------------------

    async def _async_send(self, func: Callable[..., None], *args: Any) -> None:
        try:
            await self.hass.async_add_executor_job(func, *args)
        except MertikReceiverError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="no_receiver"
            ) from err
        except MertikError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="cannot_reach",
                translation_placeholders={"error": str(err)},
            ) from err

    async def _async_refresh_after_command(self) -> None:
        """Read the status a command leaves behind and show it."""
        try:
            await self.hass.async_add_executor_job(self.mertik.refresh_status)
        except MertikError as err:
            # The command itself went through; the next poll brings the status.
            _LOGGER.debug("Status after a command not read: %s", err)
            self.async_update_listeners()
            return
        self._after_status()
        self.async_set_updated_data(None)

    def _require_lit(self) -> None:
        if self.state not in _PILOT_STATES:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="fireplace_off"
            )

    async def async_turn_on(self) -> None:
        """Ignite the fireplace, unless it is on already."""
        state = self.state
        if state in (STATE_ON, STATE_STANDBY, STATE_IGNITING):
            return
        just_went_off = (
            self._off_since is not None
            and self._clock() - self._off_since < REIGNITE_DELAY_SECONDS
        )
        if state == STATE_SHUTTING_DOWN or just_went_off:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="shutting_down"
            )
        # Never light a fire without knowing it is this one.
        if await self._async_is_another_fireplace():
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="wrong_device"
            )
        await self._async_send(self.mertik.ignite_fireplace)
        await self._async_refresh_after_command()

    async def async_turn_off(self) -> None:
        """Turn the fireplace off completely, pilot included."""
        self._pending.clear()
        self._pending_since = None
        self.thermostat.active = False
        self._overlay.clear()
        await self._async_send(self.mertik.guard_flame_off)
        await self._async_refresh_after_command()

    async def async_set_flame_height(self, flame_height: int, *, by_thermostat: bool = False) -> None:
        """Set flame step 1-12, or 0 to go down to the pilot."""
        flame_height = int(flame_height)
        if not by_thermostat:
            # A hand on the flame takes over from the thermostat.
            self.thermostat.active = False
            self._pending.pop("thermostat", None)
        if self.state == STATE_IGNITING:
            self._remember("flame_height", flame_height)
            return
        self._require_lit()
        await self._async_send(self.mertik.set_flame_height, flame_height)
        self._expect("flame_height", flame_height)
        await self._async_refresh_after_command()

    async def async_set_aux(self, on: bool) -> None:
        """Enable or disable the secondary burner."""
        if self.state == STATE_IGNITING:
            self._remember("aux", on)
            return
        if self.state not in _PILOT_STATES:
            if not on:
                return
            self._require_lit()
        await self._async_send(self.mertik.aux_on if on else self.mertik.aux_off)
        self._expect("aux", on)
        await self._async_refresh_after_command()

    async def async_set_light(self, on: bool, brightness: int | None = None) -> None:
        """Switch the light, optionally to a brightness of 1-255."""
        if not on:
            await self._async_send(self.mertik.light_off)
            self._expect("light", False)
            await self._async_refresh_after_command()
            return
        if brightness is not None:
            await self._async_send(self.mertik.set_light_brightness, brightness)
            self._expect("brightness", brightness)
            await self._async_refresh_after_command()
        if not self.mertik.is_light_on:
            await self._async_send(self.mertik.light_on)
        self._expect("light", True)
        await self._async_refresh_after_command()

    async def async_set_mode(self, mode: str) -> None:
        """Switch between manual, eco and the fireplace's own thermostat mode."""
        if mode not in (MODE_MANUAL, MODE_ECO, MODE_THERMOSTAT):
            raise ServiceValidationError(f"Unknown mode: {mode}")
        self.thermostat.active = False
        self._pending.pop("thermostat", None)
        if self.state == STATE_IGNITING:
            self._remember("mode", mode)
            return
        if mode == MODE_MANUAL:
            await self._async_send(self.mertik.set_manual)
        else:
            self._require_lit()
            if mode == MODE_ECO:
                await self._async_send(self.mertik.set_eco)
            else:
                await self._async_send(
                    self.mertik.set_thermostat, self.target_temperature or 20.0
                )
        self._expect("mode", mode)
        await self._async_refresh_after_command()

    async def async_set_thermostat(self, temperature: float, *, must_start: bool = True) -> None:
        """Regulate towards a temperature.

        With a temperature sensor set in the options Home Assistant does the
        regulating; otherwise the fireplace's own thermostat mode does. Neither
        ignites the fireplace: it has to be on already. With must_start False
        and Home Assistant regulating, a target given while the fireplace is off
        is just kept for later.
        """
        self.thermostat.target = temperature
        if self.state == STATE_IGNITING:
            self._remember("thermostat", temperature)
            return
        if (
            not must_start
            and self.temperature_sensor is not None
            and self.state not in _PILOT_STATES
        ):
            self.async_update_listeners()
            return
        self._require_lit()
        if self.temperature_sensor is None:
            await self._async_send(self.mertik.set_thermostat, temperature)
            self._expect("mode", MODE_THERMOSTAT)
            await self._async_refresh_after_command()
            return
        if self.mode in (MODE_THERMOSTAT, MODE_ECO):
            # Home Assistant regulates the flame itself, in manual mode.
            await self._async_send(self.mertik.set_manual)
            self._expect("mode", MODE_MANUAL)
        if not self.thermostat.active:
            self.thermostat.active = True
            self.thermostat.last_change = None
            self.thermostat.sensor_missing_since = None
            self.thermostat.sensor_lost = False
        await self._async_run_thermostat()
        self.async_update_listeners()

    async def async_stop_thermostat(self) -> None:
        """Stop regulating. The fire keeps burning as it is."""
        self._pending.pop("thermostat", None)
        if self.temperature_sensor is not None:
            self.thermostat.active = False
            self.async_update_listeners()
            return
        await self._async_send(self.mertik.set_manual)
        self._expect("mode", MODE_MANUAL)
        await self._async_refresh_after_command()

    async def _async_run_thermostat(self) -> None:
        """Let the Home Assistant thermostat move the flame if it wants to."""
        if not self.thermostat.active or self.state not in _PILOT_STATES:
            return
        now = self._clock()
        was_lost = self.thermostat.sensor_lost
        level = self.thermostat.decide(
            now=now,
            room=self.sensor_temperature,
            burning=self.is_burning,
            flame_height=self.mertik.flame_height,
        )
        if self.thermostat.sensor_lost and not was_lost:
            _LOGGER.warning(
                "%s: no reading from %s, turning the flame down to the pilot",
                self.name,
                self.temperature_sensor,
            )
        if level is None:
            return
        self.thermostat.last_change = now
        await self.async_set_flame_height(FLAME_HEIGHT[level], by_thermostat=True)
