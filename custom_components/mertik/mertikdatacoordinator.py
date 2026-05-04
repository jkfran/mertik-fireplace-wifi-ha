from datetime import timedelta
import logging

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .mertik import Mertik
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
        self._was_igniting = False     # tracks igniting falling edge

    # ---- On/off state ----------------------------------------------------
    # Use flame_on (flame byte > threshold) as the primary "is fire running"
    # indicator. on_flag ("FF") is only set when ignite_fireplace() is used,
    # not when set_flame_height() starts the fire.

    @property
    def is_on(self) -> bool:
        """Fire is running -- based on flame byte OR optimistic timer."""
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

        If the fire is in standby (pilot lit), we skip ignite and go
        straight to set_flame_height -- fast re-ignition.

        If fully off, we send ignite_fireplace() then store the target
        mode in _pending_mode. The thermostatic loop detects the igniting
        bit falling False and calls apply_heating_mode again to set the
        correct flame height and aux state once the burner is confirmed lit.
        Sending flame height commands during ignition is ignored by the
        device, so we must wait.
        """
        from .const import MODE_FULL, MODE_MEDIUM, MODE_LOW
        needs_ignite = not self.is_on and not self._in_standby
        self._in_standby = False  # leaving standby regardless

        if needs_ignite:
            # Fire is fully off -- ignite and defer the rest until lit
            self.mertik.ignite_fireplace()
            self.mark_optimistic_on()
            self._pending_mode = mode
            _LOGGER.info("Igniting for mode %s -- will apply once burner is lit", mode)
            return

        # Fire is already on (or coming from standby) -- apply mode now
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
        """
        if not self._pending_mode:
            return False
        # Still igniting -- wait
        if self.mertik.is_igniting:
            _LOGGER.debug("Waiting for ignition to complete before applying %s",
                          self._pending_mode)
            return True
        # Igniting bit just dropped False -- flame_on may lag by one poll cycle.
        # Keep _pending_mode alive and wait one more cycle before applying.
        if not self.mertik.is_flame_on:
            _LOGGER.debug("Igniting cleared but flame_on not yet set -- waiting")
            return True
        # Burner is lit -- apply the deferred mode
        _LOGGER.info("Ignition complete, applying deferred mode %s", self._pending_mode)
        mode = self._pending_mode
        self._pending_mode = None
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
