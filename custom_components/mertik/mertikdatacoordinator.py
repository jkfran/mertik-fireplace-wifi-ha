from datetime import timedelta
import logging

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import FLAME_MIN, FLAME_MAX

_LOGGER = logging.getLogger(__name__)
OPTIMISTIC_ON_SECONDS  = 20
OPTIMISTIC_OFF_SECONDS = 20


class MertikDataCoordinator(DataUpdateCoordinator):

    def __init__(self, hass, mertik):
        super().__init__(hass, _LOGGER, name="Mertik",
                         update_interval=timedelta(seconds=10))
        self.mertik = mertik
        self._optimistic_on_until  = None
        self._optimistic_off_until = None
        self._prev_is_on = False
        self.fire_just_turned_off = False  # set True for one cycle when fire turns off
        self._in_standby = False       # True when thermostatic standby is active
        self._pending_mode = None      # mode to apply once ignition completes
        self._heating_mode = None      # current mode set by the Heating Mode select entity
        self._was_igniting = False     # tracks igniting falling edge
        self._flame_on_since = None    # timestamp when flame first lit after ignite
        self._settle_seconds = 35      # seconds to wait after flame_on before aux_off

    # ---- On/off state ----------------------------------------------------
    # Use flame_on (flame byte > threshold) as the primary "is fire running"
    # indicator. on_flag ("FF") is only set when ignite_fireplace() is used,
    # not when set_flame_height() starts the fire.

    @property
    def is_on(self) -> bool:
        """Fire is running -- based on flame byte, standby state, or optimistic timer.

        _in_standby (pilot lit, thermostatic armed) takes priority over the
        optimistic-off timer so the Fireplace switch stays on while in standby.
        """
        if self._in_standby:
            return True
        now = dt_util.utcnow()
        if self._optimistic_off_until and now < self._optimistic_off_until:
            return False
        if self.mertik.is_flame_on or self.mertik.is_igniting:
            return True
        if self._optimistic_on_until and now < self._optimistic_on_until:
            return True
        return False

    def mark_optimistic_on(self):
        self._optimistic_off_until = None
        self._optimistic_on_until  = dt_util.utcnow() + timedelta(seconds=OPTIMISTIC_ON_SECONDS)

    def mark_optimistic_off(self):
        self._optimistic_on_until  = None
        self._optimistic_off_until = dt_util.utcnow() + timedelta(seconds=OPTIMISTIC_OFF_SECONDS)

    @property
    def heating_mode(self) -> str | None:
        return self._heating_mode

    def set_heating_mode(self, mode: str) -> None:
        self._heating_mode = mode

    def ignite_fireplace(self):
        self.mertik.ignite_fireplace()

    def guard_flame_off(self):
        self._optimistic_on_until  = None
        self._optimistic_off_until = None
        self.mertik.guard_flame_off()
        self._in_standby = False
        # Signal light entity that fire turned off (device kills light too)
        self.fire_just_turned_off = True
        self._prev_is_on = False

    def standby(self):
        """Pilot flame only -- main burners off but ignition source stays lit.
        Used by thermostatic Off so re-ignition is fast when heat is needed.
        Does NOT set fire_just_turned_off because the device keeps the light
        on in standby mode (only guard_flame_off kills the light).
        """
        self._optimistic_on_until  = None
        self._optimistic_off_until = None
        self._in_standby = True
        self.mertik.standBy()

    @property
    def is_aux_on(self) -> bool:
        return self.mertik.is_aux_on  # already gated on flame_on in mertik.py

    def aux_on(self):
        self.mertik.aux_on()

    def aux_off(self):
        self.mertik.aux_off()

    def get_flame_height(self) -> int:
        return self.mertik.get_flame_height()

    def set_flame_height(self, flame_height) -> None:
        self.mertik.set_flame_height(flame_height)

    @property
    def ambient_temperature(self) -> float:
        return self.mertik.ambient_temperature

    @property
    def is_light_on(self) -> bool:
        return self.mertik.is_light_on

    def light_on(self):
        self.mertik.light_on()

    def light_off(self):
        self.mertik.light_off()

    def set_light_brightness(self, brightness) -> None:
        self.mertik.set_light_brightness(brightness)

    @property
    def light_brightness(self) -> int:
        return self.mertik.light_brightness

    def apply_heating_mode(self, mode: str) -> None:
        """Apply a named heating mode to the physical fireplace.

        Standby is handled first -- it must never trigger ignition regardless
        of the current fire state.

        For heat modes, three cases:
        1. User switched fire OFF (is_on=False, _in_standby=False): block, do nothing.
        2. Fire physically off but optimistically on (user just pressed On, device not
           yet confirmed): call ignite_fireplace() and store mode in _pending_mode.
           check_pending_mode() applies the deferred mode once the burner is settled.
        3. Fire physically on or in thermostatic standby: apply mode immediately.
        """
        from .const import MODE_STANDBY, MODE_FULL, MODE_MEDIUM, MODE_LOW

        # Standby never ignites -- handle it unconditionally before ignition logic.
        if mode == MODE_STANDBY:
            self._pending_mode = None
            self.standby()
            return

        # Case 1: user explicitly switched off -- thermostatic control must not ignite.
        if not self.is_on and not self._in_standby:
            _LOGGER.debug(
                "apply_heating_mode: fire is off by user, not igniting for %s", mode
            )
            return

        physically_on = self.mertik.is_flame_on or self.mertik.is_igniting

        # Case 2: optimistically on (user pressed On) but fire not yet physically lit.
        if not physically_on and not self._in_standby:
            self._pending_mode = mode
            self.mertik.ignite_fireplace()
            return

        # Case 3: fire is physically on or coming from thermostatic standby.
        self._in_standby = False
        self._pending_mode = None
        if mode == MODE_FULL:
            self.mertik.set_flame_height(FLAME_MAX)
            self.mertik.aux_on()
        elif mode == MODE_MEDIUM:
            self.mertik.aux_off()
            self.mertik.set_flame_height(FLAME_MAX)
        elif mode == MODE_LOW:
            self.mertik.aux_off()
            self.mertik.set_flame_height(FLAME_MIN)

    def check_pending_mode(self) -> bool:
        """Called by the thermostatic loop each poll cycle.

        Returns True if a pending mode was applied (so the caller knows
        to skip its normal mode calculation this cycle).

        After the burner lights, we wait _settle_seconds before sending
        aux_off / set_flame_height. The device firmware ignores these
        commands if sent too soon after ignition (ACK is received but
        the physical state does not change). 35 seconds is conservative
        but reliable based on observed device behaviour.
        """
        if not self._pending_mode:
            return False
        # Still igniting -- wait
        if self.mertik.is_igniting:
            _LOGGER.debug("Waiting for ignition to complete before applying %s",
                          self._pending_mode)
            self._flame_on_since = None
            return True
        # Igniting bit just dropped False -- flame_on may lag by one poll cycle.
        if not self.mertik.is_flame_on:
            _LOGGER.debug("Igniting cleared but flame_on not yet set -- waiting")
            return True
        # Burner is lit -- start the settle timer if not already started
        if self._flame_on_since is None:
            self._flame_on_since = dt_util.utcnow()
            _LOGGER.info(
                "Burner lit, waiting %ds before applying %s",
                self._settle_seconds, self._pending_mode
            )
            return True
        # Check if enough time has passed since the burner lit
        elapsed = (dt_util.utcnow() - self._flame_on_since).total_seconds()
        if elapsed < self._settle_seconds:
            _LOGGER.debug(
                "Settling: %.0fs / %ds before applying %s",
                elapsed, self._settle_seconds, self._pending_mode
            )
            return True
        # Settle period complete -- apply the deferred mode
        _LOGGER.info(
            "Settled (%.0fs), applying deferred mode %s",
            elapsed, self._pending_mode
        )
        mode = self._pending_mode
        self._pending_mode = None
        self._flame_on_since = None
        self.apply_heating_mode(mode)
        return True

    async def _async_update_data(self):
        try:
            await self.hass.async_add_executor_job(self.mertik.refresh_status)
            # Detect when fire turns off so light entity can reset its state.
            # The device physically turns the light off when fire is extinguished.
            current_on = self.is_on
            self.fire_just_turned_off = self._prev_is_on and not current_on
            self._prev_is_on = current_on
        except Exception as err:
            raise UpdateFailed(f"Error communicating with fireplace: {err}") from err
