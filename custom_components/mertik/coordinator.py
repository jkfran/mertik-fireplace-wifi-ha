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
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    CONF_MAC,
    CONF_TEMPERATURE_SENSOR,
    DOMAIN,
    IDENTITY_CHECK_SECONDS,
    IDENTITY_FRESH_SECONDS,
    OFF_CONFIRM_SECONDS,
    OFF_RETRY_SECONDS,
    OPTIMISTIC_SECONDS,
    PENDING_TIMEOUT_SECONDS,
    REIGNITE_DELAY_SECONDS,
    SENSOR_STALE_SECONDS,
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
    MertikStateError,
)
from .thermostat import FLAME_HEIGHT, ThermostatState

_LOGGER = logging.getLogger(__name__)

type MertikConfigEntry = ConfigEntry[MertikDataCoordinator]

_PILOT_STATES = (STATE_ON, STATE_STANDBY)
# The order commands kept during an ignition are sent in. Secondary burner
# before flame height: it is refused while the valve moves to a new flame.
_PENDING_ORDER = ("aux", "flame_height", "light", "mode", "thermostat")


def issue_id(entry: ConfigEntry) -> str:
    """The repair raised when the box loses its link to the receiver."""
    return f"receiver_lost_{entry.entry_id}"


def off_failed_issue_id(entry: ConfigEntry) -> str:
    """The repair raised when the fireplace did not turn off when told to."""
    return f"off_failed_{entry.entry_id}"


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
        # Counts the times the fireplace was told to turn off: commands that
        # were waiting when that happened must not be sent after it.
        self._generation = 0
        self._follow_up_running = False
        # The fireplace is being turned on: its state is checked, then the
        # ignite command sent. While the command is on its way the fireplace
        # already counts as igniting.
        self._turning_on = False
        self._ignite_in_flight = False
        # Set once a turn-on that is being checked has gone ahead or was
        # refused. Other commands wait for that before deciding what to do.
        self._turn_on_decided: asyncio.Event | None = None
        # The fireplace was told to turn off and has not been seen to obey:
        # since when, when the command last went out, and how many reliable
        # frames had come in by then (a later one has to show it obeyed).
        self._off_wanted_since: float | None = None
        self._off_sent_at: float | None = None
        self._off_serial = 0
        self._off_since: float | None = None
        # The Home Assistant thermostat: when it took over, and whether the
        # fireplace has been seen in manual mode since.
        self._thermostat_started_at: float | None = None
        self._saw_manual = False
        self._last_state: str | None = mertik.state
        # Setting up has just made sure the module is this fireplace.
        self._identity_checked_at = self._clock()
        self._reload_scheduled = False
        self.thermostat = ThermostatState()

    # --- What a reload has to keep ---------------------------------------------------

    def memory(self) -> dict[str, Any]:
        """What the coordinator that replaces this one has to know.

        A reload must not make it possible to ignite twice in a row, or forget
        that the fireplace was told to turn off, or what waits for the fire.
        What the protocol layer knows is not handed on when its last status
        came from another fireplace at this address.
        """
        return {
            "protocol": None if self._reload_scheduled else self.mertik.memory(),
            "off_since": self._off_since,
            "off_wanted_since": self._off_wanted_since,
            "pending": dict(self._pending),
            "pending_since": self._pending_since,
        }

    def restore(self, memory: dict[str, Any]) -> None:
        """Take over from the coordinator this one replaces (same clock)."""
        self._off_since = memory.get("off_since")
        self._off_wanted_since = memory.get("off_wanted_since")
        # Frames read from now on are the ones that can show an off obeyed.
        self._off_serial = self.mertik.status_serial
        self._pending = dict(memory.get("pending") or {})
        self._pending_since = memory.get("pending_since")
        self._last_state = self.mertik.state

    # --- State ---------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """The fireplace answers and the box still has its link to the receiver."""
        return (
            self.last_update_success
            and self.mertik.status is not None
            and not self.mertik.receiver_lost
        )

    @property
    def state(self) -> str | None:
        if self._ignite_in_flight:
            return STATE_IGNITING
        return self.mertik.state

    @property
    def _lighting(self) -> bool:
        """Commands given now wait for the fire instead of being sent."""
        return self.state == STATE_IGNITING

    async def _async_turn_on_decided(self) -> None:
        """Wait out the moment in which a turn-on is being checked.

        Whether a command given then is sent, kept for the fire or refused
        depends on how that turns out.
        """
        if (decided := self._turn_on_decided) is not None:
            await decided.wait()

    @property
    def is_on(self) -> bool:
        """On, in standby or lighting: the fireplace has been turned on."""
        if self._off_wanted_since is not None:
            # Told to turn off; it will be as soon as it takes the command.
            return False
        return self.state in (STATE_ON, STATE_STANDBY, STATE_IGNITING)

    @property
    def is_pilot_on(self) -> bool:
        return self.state in _PILOT_STATES

    @property
    def is_burning(self) -> bool:
        return self.state == STATE_ON

    @property
    def is_igniting(self) -> bool:
        return self.state == STATE_IGNITING

    @property
    def is_shutting_down(self) -> bool:
        return self.state == STATE_SHUTTING_DOWN

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
        """The flame height to show.

        During an ignition this is what the fireplace reports, so that a fire
        that burns already does not read 0 until it counts as lit.
        """
        if "flame_height" in self._pending:
            return self._pending["flame_height"]
        return self._shown("flame_height", self.mertik.reported_flame_height)

    @property
    def pilot_flame(self) -> bool:
        """Whether the pilot burns, to show: also during an ignition under way."""
        return self.mertik.reported_pilot

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
        if "light" in self._pending:
            return self._pending["light"][0]
        return self._shown("light", self.mertik.is_light_on)

    @property
    def light_brightness(self) -> int:
        if not self.is_light_on:
            return 0
        if "light" in self._pending and self._pending["light"][1] is not None:
            return self._pending["light"][1]
        return self._shown("brightness", self.mertik.light_brightness)

    @property
    def mode(self) -> str | None:
        if "mode" in self._pending:
            return self._pending["mode"]
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
        """Reading of that sensor in Celsius, None while it has none to trust."""
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
        # A sensor whose battery died keeps its last value for ever. One that
        # has not reported for this long is not heated on.
        age = dt_util.utcnow() - state.last_reported
        if age.total_seconds() > SENSOR_STALE_SECONDS:
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
        if "thermostat" in self._pending:
            return True
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
        if self._reload_scheduled:
            # Found out already; nothing goes to this address any more.
            return True
        known_mac = self.config_entry.data.get(CONF_MAC)
        if known_mac is None:
            return False
        module = await self.hass.async_add_executor_job(discover_host, self.mertik.ip)
        self._identity_checked_at = self._clock()
        if module is None or module.mac == known_mac:
            return False
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
            if not self._turning_on:
                self._drop_pending("the fireplace is not lit any more")
            # The thermostat ends with the fire; it never lights it again.
            self.thermostat.active = False
        self._settle_owed_off(now)
        if state == STATE_OFF:
            ir.async_delete_issue(
                self.hass, DOMAIN, off_failed_issue_id(self.config_entry)
            )
        if self.temperature_sensor is None:
            # Without a sensor the fireplace's own thermostat is the one in use.
            self.thermostat.active = False
        self._update_issues()
        if self._follow_up_running:
            return
        if self._pending or self.thermostat.active or self._off_wanted_since is not None:
            # Set before the task exists: it may run its first steps at once.
            self._follow_up_running = True
            self.config_entry.async_create_background_task(
                self.hass, self._async_follow_up(), f"{DOMAIN} follow-up"
            )

    def _settle_owed_off(self, now: float) -> None:
        """Stop owing an off once the fireplace has been seen to obey.

        Only a frame the box vouches for, read after the off was asked for,
        counts: one with the shutting-down bit, or one that reads off with no
        ignition under way and after long enough for an ignition started with
        the handset a moment before to have shown. What the integration itself
        assumes after an acknowledgement does not count.
        """
        if self._off_wanted_since is None:
            return
        status = self.mertik.status
        if status is None or self.mertik.status_serial <= self._off_serial:
            return
        if self.mertik.link_down:
            return
        obeying = status.state == STATE_SHUTTING_DOWN
        is_off = (
            self.mertik.state == STATE_OFF
            and now - self._off_wanted_since >= OFF_CONFIRM_SECONDS
        )
        if obeying or is_off:
            self._off_wanted_since = None

    def _update_issues(self) -> None:
        if self.mertik.receiver_lost:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id(self.config_entry),
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="receiver_lost",
                translation_placeholders={"name": self.config_entry.title},
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id(self.config_entry))

    async def _async_follow_up(self) -> None:
        """Turn off if that is still owed, send what waited for the fire, regulate."""
        try:
            await self._async_send_wanted_off()
            await self._async_send_pending()
            await self._async_run_thermostat()
        except HomeAssistantError as err:
            _LOGGER.warning("%s: %s", self.name, err)
        except Exception:  # noqa: BLE001 (a background task must not die unseen)
            _LOGGER.exception("%s: unexpected error while following up", self.name)
        finally:
            self._follow_up_running = False

    async def _async_send_wanted_off(self) -> None:
        """Send the off command again until the fireplace has taken it."""
        if self._off_wanted_since is None:
            return
        now = self._clock()
        if now - self._off_wanted_since > PENDING_TIMEOUT_SECONDS:
            self._off_wanted_since = None
            _LOGGER.error(
                "%s did not turn off within %d minutes of being told to. "
                "Check the fireplace",
                self.name,
                PENDING_TIMEOUT_SECONDS // 60,
            )
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                off_failed_issue_id(self.config_entry),
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="off_failed",
                translation_placeholders={"name": self.config_entry.title},
            )
            self.async_update_listeners()
            return
        if self._off_sent_at is not None and now - self._off_sent_at < OFF_RETRY_SECONDS:
            return
        if self.mertik.link_down and not self.mertik.receiver_lost:
            # The receiver is busy (an ignition looks like this) and the box
            # would refuse. The poll that shows the link again sends it.
            return
        if (
            self.mertik.state == STATE_OFF
            and self.mertik.status_serial > self._off_serial
        ):
            # It reads off. The off stays owed a little longer, in case an
            # ignition started with the handset has not shown yet.
            return
        self._off_sent_at = now
        try:
            await self._async_send(self._repeat_off)
        except HomeAssistantError as err:
            _LOGGER.debug("%s: still to be turned off (%s)", self.name, err)
            return
        await self._async_refresh_after_command()

    def _repeat_off(self) -> None:
        """Send the off again; what the box reports stays what is shown."""
        self.mertik.guard_flame_off(assume_shutdown=False)

    async def _async_send_pending(self) -> None:
        if not self._pending:
            return
        now = self._clock()
        if self._pending_since is not None and now - self._pending_since > PENDING_TIMEOUT_SECONDS:
            self._drop_pending("the fireplace did not settle in time", everything=True)
            return
        state = self.state
        if state == STATE_OFF and not self._turning_on:
            # Nothing but the light is left by now: it works with the fire off.
            light = self._pending.pop("light", None)
            self._drop_pending("the fireplace is not lit", everything=True)
            if light is not None:
                await self.async_set_light(*light)
            return
        if state not in _PILOT_STATES:
            return
        generation = self._generation
        pending, self._pending = self._pending, {}
        self._pending_since = None
        for key in _PENDING_ORDER:
            if key not in pending:
                continue
            if generation != self._generation and key != "light":
                # Turned off in the meantime: nothing more for the fire.
                continue
            value = pending[key]
            if key == "aux":
                await self.async_set_aux(value)
            elif key == "flame_height":
                await self.async_set_flame_height(value)
            elif key == "light":
                await self.async_set_light(*value)
            elif key == "mode":
                await self.async_set_mode(value)
            else:
                await self.async_set_thermostat(value)

    def _remember(self, key: str, value: Any) -> None:
        """Keep a command for when the fireplace is lit."""
        if not self._pending:
            self._pending_since = self._clock()
        self._pending[key] = value
        self.async_update_listeners()

    def _drop_pending(self, reason: str, *, everything: bool = False) -> None:
        """Give up on what waited for the fire.

        A light command is kept unless everything goes: the light does not need
        the fire, only a moment in which the fireplace takes commands.
        """
        kept = {}
        if not everything and "light" in self._pending:
            kept["light"] = self._pending["light"]
        if dropped := sorted(set(self._pending) - set(kept)):
            _LOGGER.warning("%s: not sending %s, %s", self.name, dropped, reason)
        self._pending = kept
        if not kept:
            self._pending_since = None

    # --- Commands ------------------------------------------------------------------

    async def _async_send(self, func: Callable[..., None], *args: Any) -> None:
        """Send a command to the fireplace, having made sure it is this one."""
        if (
            self._reload_scheduled
            or self._clock() - self._identity_checked_at > IDENTITY_FRESH_SECONDS
        ) and await self._async_is_another_fireplace():
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="wrong_device"
            )
        try:
            await self.hass.async_add_executor_job(func, *args)
        except MertikError as err:
            raise self._translated(err) from err

    def _translated(self, err: MertikError) -> HomeAssistantError:
        """The Home Assistant error for what went wrong with a command."""
        if isinstance(err, MertikStateError):
            # The fireplace changed state between the request and its turn.
            return self._state_error(err.state)
        if isinstance(err, MertikReceiverError):
            return HomeAssistantError(
                translation_domain=DOMAIN, translation_key="no_receiver"
            )
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="cannot_reach",
            translation_placeholders={"error": str(err)},
        )

    @staticmethod
    def _state_error(state: str | None) -> HomeAssistantError:
        """The error for a command the fireplace cannot take in its state."""
        if state is None:
            return HomeAssistantError(
                translation_domain=DOMAIN, translation_key="no_receiver"
            )
        key = {
            STATE_SHUTTING_DOWN: "shutting_down",
            STATE_IGNITING: "igniting",
        }.get(state, "fireplace_off")
        return ServiceValidationError(translation_domain=DOMAIN, translation_key=key)

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
        if (state := self.state) not in _PILOT_STATES:
            raise self._state_error(state)

    async def async_turn_on(self) -> None:
        """Ignite the fireplace, unless it is on already.

        The ignite command only ever goes to a fireplace that has just been
        seen to be off, and to the right one.
        """
        if self._turning_on:
            return
        self._turning_on = True
        decided = self._turn_on_decided = asyncio.Event()
        generation = self._generation
        try:
            try:
                await self.hass.async_add_executor_job(self.mertik.refresh_status)
            except MertikError as err:
                raise self._translated(err) from err
            # A shutdown that fell between two polls is taken note of here.
            self._after_status()
            state = self.state
            if state in (STATE_ON, STATE_STANDBY, STATE_IGNITING):
                # It is on, and is to stay on: an off still owed is called off.
                self._off_wanted_since = None
                return
            if state is None or self.mertik.link_down:
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="no_receiver"
                )
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
            if generation != self._generation:
                # Told to turn off while this was being checked: off it stays.
                return
            self._off_wanted_since = None
            # From here on other commands wait for the fire, as during any ignition.
            self._ignite_in_flight = True
            decided.set()
            try:
                await self.hass.async_add_executor_job(self.mertik.ignite_fireplace)
            except MertikStateError as err:
                if err.state not in (STATE_ON, STATE_STANDBY, STATE_IGNITING):
                    raise self._state_error(err.state) from err
                # Lit in the instant between the look and the command: fine.
            except MertikError as err:
                raise self._translated(err) from err
            finally:
                self._ignite_in_flight = False
                self._turning_on = False
                await self._async_refresh_after_command()
        finally:
            self._turning_on = False
            self._turn_on_decided = None
            decided.set()
            self.async_update_listeners()

    async def async_turn_off(self) -> None:
        """Turn the fireplace off completely, pilot included.

        The command is sent whatever the fireplace seems to be doing. If it is
        not taken (a fireplace that is igniting refuses commands), it is sent
        again after every poll until the fireplace is seen to shut down.
        """
        self._generation += 1
        self._drop_pending("the fireplace was turned off")
        self.thermostat.active = False
        self._overlay.clear()
        now = self._clock()
        self._off_wanted_since = now
        self._off_sent_at = now
        self._off_serial = self.mertik.status_serial
        try:
            await self._async_send(self.mertik.guard_flame_off)
        except HomeAssistantError:
            if self.mertik.state != STATE_IGNITING:
                # Not expected, so the caller is told; it stays owed all the same.
                self.async_update_listeners()
                raise
            _LOGGER.info(
                "%s is busy igniting and did not take the command to turn off; "
                "it is sent again until it does",
                self.name,
            )
        await self._async_refresh_after_command()

    async def async_set_flame_height(self, flame_height: int, *, by_thermostat: bool = False) -> None:
        """Set flame step 1-12, or 0 to go down to the pilot."""
        await self._async_turn_on_decided()
        flame_height = int(flame_height)
        if not by_thermostat:
            # A hand on the flame takes over from the thermostat.
            self.thermostat.active = False
            self._pending.pop("thermostat", None)
        if self._lighting:
            self._remember("flame_height", flame_height)
            return
        self._require_lit()
        await self._async_send(self.mertik.set_flame_height, flame_height)
        self._expect("flame_height", flame_height)
        await self._async_refresh_after_command()

    async def async_set_aux(self, on: bool) -> None:
        """Enable or disable the secondary burner."""
        await self._async_turn_on_decided()
        if self._lighting:
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
        await self._async_turn_on_decided()
        if self._lighting or self.state == STATE_SHUTTING_DOWN:
            # The receiver is left alone while it lights the fire or puts it
            # out; the light follows once it takes commands again.
            self._remember("light", (on, brightness))
            return
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

    def _require_handset(self) -> None:
        """The fireplace's own thermostat measures with the handset."""
        if self.ambient_temperature is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_handset"
            )

    async def async_set_mode(self, mode: str) -> None:
        """Switch between manual, eco and the fireplace's own thermostat mode."""
        if mode not in (MODE_MANUAL, MODE_ECO, MODE_THERMOSTAT):
            raise ServiceValidationError(f"Unknown mode: {mode}")
        await self._async_turn_on_decided()
        if mode == MODE_THERMOSTAT:
            self._require_handset()
        self.thermostat.active = False
        self._pending.pop("thermostat", None)
        if self._lighting:
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
        await self._async_turn_on_decided()
        if self.temperature_sensor is None:
            self._require_handset()
        self.thermostat.target = temperature
        if self._lighting:
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
            self._thermostat_started_at = self._clock()
            self._saw_manual = False
        await self._async_run_thermostat()
        self.async_update_listeners()

    async def async_stop_thermostat(self) -> None:
        """Stop regulating. The fire keeps burning as it is."""
        self._pending.pop("thermostat", None)
        if self.temperature_sensor is not None:
            self.thermostat.active = False
            self.async_update_listeners()
            return
        await self.async_set_mode(MODE_MANUAL)

    async def _async_run_thermostat(self) -> None:
        """Let the Home Assistant thermostat move the flame if it wants to."""
        if not self.thermostat.active or self.state not in _PILOT_STATES:
            return
        if self.mertik.link_down:
            # What the box reports cannot be trusted right now, and it would
            # refuse the command.
            return
        now = self._clock()
        if self._thermostat_started_at is None:
            # Resumed after a restart.
            self._thermostat_started_at = now
        reported = self.mertik.mode
        if reported == MODE_MANUAL:
            self._saw_manual = True
        elif reported in (MODE_THERMOSTAT, MODE_ECO):
            # Two regulators on one flame would fight. If the fireplace was in
            # manual mode before, someone chose this on the handset, and the
            # handset wins. If it never got there, it is given a minute to
            # follow the command that took it out of its own mode.
            if not self._saw_manual and now - self._thermostat_started_at < 60.0:
                return
            self.thermostat.active = False
            _LOGGER.info(
                "%s is in %s mode%s; the thermostat steps back",
                self.name,
                reported,
                ", chosen on the handset" if self._saw_manual else " and did not leave it",
            )
            self.async_update_listeners()
            return
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
