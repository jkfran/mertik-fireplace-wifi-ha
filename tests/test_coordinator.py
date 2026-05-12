"""Tests for the MertikDataCoordinator."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from homeassistant.util import dt as dt_util

from custom_components.mertik.mertikdatacoordinator import (
    MertikDataCoordinator,
    OPTIMISTIC_ON_SECONDS,
    OPTIMISTIC_OFF_SECONDS,
)


@pytest.fixture
def mock_mertik():
    mertik = MagicMock()
    mertik.is_flame_on = False
    mertik.is_igniting = False
    mertik.is_aux_on = False
    mertik.ambient_temperature = 20.0
    return mertik


@pytest.fixture
def coordinator(hass, mock_mertik):
    return MertikDataCoordinator(hass, mock_mertik)


class TestOptimisticState:
    def test_is_on_false_by_default(self, coordinator, mock_mertik):
        mock_mertik.is_flame_on = False
        mock_mertik.is_igniting = False
        assert coordinator.is_on is False

    def test_is_on_true_when_flame_on(self, coordinator, mock_mertik):
        mock_mertik.is_flame_on = True
        assert coordinator.is_on is True

    def test_is_on_true_when_igniting(self, coordinator, mock_mertik):
        mock_mertik.is_igniting = True
        assert coordinator.is_on is True

    def test_optimistic_on(self, coordinator, mock_mertik):
        mock_mertik.is_flame_on = False
        mock_mertik.is_igniting = False
        coordinator.mark_optimistic_on()
        assert coordinator.is_on is True

    def test_optimistic_on_expires(self, coordinator, mock_mertik):
        mock_mertik.is_flame_on = False
        mock_mertik.is_igniting = False
        coordinator.mark_optimistic_on()
        future = dt_util.utcnow() + timedelta(seconds=OPTIMISTIC_ON_SECONDS + 1)
        with patch.object(dt_util, "utcnow", return_value=future):
            assert coordinator.is_on is False

    def test_optimistic_off(self, coordinator, mock_mertik):
        mock_mertik.is_flame_on = True
        coordinator.mark_optimistic_off()
        assert coordinator.is_on is False

    def test_optimistic_off_expires(self, coordinator, mock_mertik):
        mock_mertik.is_flame_on = True
        coordinator.mark_optimistic_off()
        future = dt_util.utcnow() + timedelta(seconds=OPTIMISTIC_OFF_SECONDS + 1)
        with patch.object(dt_util, "utcnow", return_value=future):
            assert coordinator.is_on is True

    def test_optimistic_on_clears_optimistic_off(self, coordinator, mock_mertik):
        mock_mertik.is_flame_on = True
        coordinator.mark_optimistic_off()
        assert coordinator.is_on is False
        coordinator.mark_optimistic_on()
        assert coordinator.is_on is True

    def test_optimistic_off_clears_optimistic_on(self, coordinator, mock_mertik):
        mock_mertik.is_flame_on = False
        mock_mertik.is_igniting = False
        coordinator.mark_optimistic_on()
        assert coordinator.is_on is True
        coordinator.mark_optimistic_off()
        assert coordinator.is_on is False


class TestCoordinatorDelegation:
    def test_ignite_fireplace(self, coordinator, mock_mertik):
        coordinator.ignite_fireplace()
        mock_mertik.ignite_fireplace.assert_called_once()

    def test_guard_flame_off_clears_optimistic(self, coordinator, mock_mertik):
        coordinator.mark_optimistic_on()
        coordinator.guard_flame_off()
        mock_mertik.guard_flame_off.assert_called_once()
        assert coordinator._optimistic_on_until is None
        assert coordinator._optimistic_off_until is None

    def test_aux_on(self, coordinator, mock_mertik):
        coordinator.aux_on()
        mock_mertik.aux_on.assert_called_once()

    def test_aux_off(self, coordinator, mock_mertik):
        coordinator.aux_off()
        mock_mertik.aux_off.assert_called_once()

    def test_get_flame_height(self, coordinator, mock_mertik):
        mock_mertik.get_flame_height.return_value = 5
        assert coordinator.get_flame_height() == 5

    def test_set_flame_height(self, coordinator, mock_mertik):
        coordinator.set_flame_height(7)
        mock_mertik.set_flame_height.assert_called_once_with(7)

    def test_light_on(self, coordinator, mock_mertik):
        coordinator.light_on()
        mock_mertik.light_on.assert_called_once()

    def test_light_off(self, coordinator, mock_mertik):
        coordinator.light_off()
        mock_mertik.light_off.assert_called_once()

    def test_set_light_brightness(self, coordinator, mock_mertik):
        coordinator.set_light_brightness(128)
        mock_mertik.set_light_brightness.assert_called_once_with(128)

    def test_ambient_temperature(self, coordinator, mock_mertik):
        mock_mertik.ambient_temperature = 22.5
        assert coordinator.ambient_temperature == 22.5

    def test_is_aux_on_delegates_to_mertik(self, coordinator, mock_mertik):
        """is_aux_on passes through mertik.is_aux_on directly.
        Gating on flame_on is handled inside mertik.py's is_aux_on property.
        """
        mock_mertik.is_aux_on = False
        assert coordinator.is_aux_on is False
        mock_mertik.is_aux_on = True
        assert coordinator.is_aux_on is True


class TestAsyncUpdateData:
    async def test_calls_refresh_status(self, coordinator, mock_mertik):
        await coordinator._async_update_data()
        mock_mertik.refresh_status.assert_called_once()

    async def test_update_interval(self, coordinator):
        assert coordinator.update_interval == timedelta(seconds=10)

    async def test_raises_update_failed_on_error(self, coordinator, mock_mertik):
        from homeassistant.helpers.update_coordinator import UpdateFailed
        mock_mertik.refresh_status.side_effect = Exception("Connection lost")
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()


class TestThermostaticIgnitionGuard:
    """Thermostatic control must not ignite when the Fireplace switch is off.

    The user explicitly turning the fire off via the Fireplace switch must
    take precedence over the thermostatic schedule at all times.
    """

    @pytest.fixture
    def coordinator_off(self, hass, mock_mertik):
        """Coordinator with fire off and not in standby (user switched off)."""
        coord = MertikDataCoordinator(hass, mock_mertik)
        mock_mertik.is_flame_on = False
        mock_mertik.is_igniting = False
        coord._in_standby = False   # user switched off -- not thermostatic standby
        return coord

    @pytest.fixture
    def coordinator_standby(self, hass, mock_mertik):
        """Coordinator in thermostatic standby (pilot lit, thermostat controls it)."""
        coord = MertikDataCoordinator(hass, mock_mertik)
        mock_mertik.is_flame_on = True   # pilot counts as flame_on
        mock_mertik.is_igniting = False
        coord._in_standby = True
        return coord

    def test_apply_heating_mode_blocked_when_user_switched_off(
        self, coordinator_off, mock_mertik
    ):
        """apply_heating_mode must not ignite when fire is off and not in standby."""
        coordinator_off.apply_heating_mode("Full Heat")
        # ignite_fireplace must NOT have been called
        mock_mertik.ignite_fireplace.assert_not_called()

    def test_apply_heating_mode_blocked_for_all_modes_when_off(
        self, coordinator_off, mock_mertik
    ):
        """Guard applies to all heat modes, not just Full Heat."""
        from custom_components.mertik.const import MODE_LOW, MODE_MEDIUM, MODE_FULL
        for mode in (MODE_FULL, MODE_MEDIUM, MODE_LOW):
            mock_mertik.reset_mock()
            coordinator_off.apply_heating_mode(mode)
            mock_mertik.ignite_fireplace.assert_not_called(), (
                f"ignite_fireplace should not be called for {mode} when fire is off"
            )

    def test_apply_heating_mode_allowed_from_standby(
        self, coordinator_standby, mock_mertik
    ):
        """Thermostatic standby -> apply mode without re-igniting (pilot already lit)."""
        coordinator_standby.apply_heating_mode("Low Heat")
        # ignite_fireplace must NOT be called -- fire goes from pilot to Low Heat
        mock_mertik.ignite_fireplace.assert_not_called()
        # But flame height and aux commands ARE sent
        mock_mertik.aux_off.assert_called_once()
        mock_mertik.set_flame_height.assert_called_once()

    def test_guard_flame_off_clears_standby_flag(self, coordinator_standby):
        """Turning the fire off via the switch must clear _in_standby."""
        assert coordinator_standby._in_standby is True
        coordinator_standby.guard_flame_off()
        assert coordinator_standby._in_standby is False

    def test_standby_sets_in_standby_flag(self, coordinator_off):
        """standby() must set _in_standby so thermostat can re-ignite."""
        assert coordinator_off._in_standby is False
        coordinator_off.standby()
        assert coordinator_off._in_standby is True


class TestThermostaticScenarios:
    """End-to-end thermostatic behaviour scenarios.

    Thresholds: low=1.0C, high=2.0C (defaults as of v2.3).

    Tests use the real MertikDataCoordinator with a mocked Mertik device
    and a mocked HA state machine for the Heating Mode select entity.
    The climate entity's _run_thermostatic_logic is called directly.
    """

    SETPOINT = 20.0
    LOW_THRESH  = 1.0
    HIGH_THRESH = 2.0

    @pytest.fixture
    def climate_entity(self, hass, mock_mertik):
        """Climate entity wired to a real coordinator, fire off by default."""
        from custom_components.mertik.climate import MertikClimateEntity as MertikThermostatEntity
        from custom_components.mertik.mertikdatacoordinator import MertikDataCoordinator

        coord = MertikDataCoordinator(hass, mock_mertik)
        coord._low_thresh  = self.LOW_THRESH
        coord._high_thresh = self.HIGH_THRESH

        mock_mertik.is_flame_on = False
        mock_mertik.is_igniting = False
        coord._in_standby = False

        entity = MertikThermostatEntity.__new__(MertikThermostatEntity)
        entity.hass          = hass
        entity._dataservice  = coord
        entity._target_temp  = self.SETPOINT
        entity._low_thresh   = self.LOW_THRESH
        entity._high_thresh  = self.HIGH_THRESH
        entity._last_applied_mode = None
        entity._temp_sensor_entity_id = "sensor.test_temp"
        return entity, coord, mock_mertik

    def _set_temp(self, hass, temp):
        """Inject a temperature reading into the HA state machine."""
        from unittest.mock import MagicMock
        state = MagicMock()
        state.state = str(temp)
        state.attributes = {"unit_of_measurement": "°C"}
        hass.states.async_set("sensor.test_temp", str(temp))

    def _set_heating_mode(self, hass, mode):
        """Inject a Heating Mode select state."""
        from custom_components.mertik.climate import SELECT_ENTITY_SUFFIX
        from custom_components.mertik.const import DOMAIN
        # The climate entity resolves select entity via _select_entity_id()
        # We inject it directly via the method mock
        pass

    # ── helpers ──────────────────────────────────────────────────────────────

    def _run(self, entity, coord, mock_mertik, current_temp):
        """Run one cycle of thermostatic logic with the given temperature."""
        from unittest.mock import patch, MagicMock
        from custom_components.mertik.const import MODE_THERMO
        state = MagicMock()
        state.state = MODE_THERMO
        with patch.object(entity, '_select_entity_id', return_value='select.test_heating_mode'), \
             patch.object(entity, '_get_current_temperature', return_value=current_temp):
            entity._run_thermostatic_logic()

    # ─────────────────────────────────────────────────────────────────────────
    # Scenario 1: fire On, room above setpoint -> Standby, no ignition
    # ─────────────────────────────────────────────────────────────────────────
    def test_scenario_01_above_setpoint_goes_standby(self, climate_entity):
        """Room temp above setpoint: Heating Mode = Standby, no ignition."""
        entity, coord, mock_mertik = climate_entity
        mock_mertik.is_flame_on = True
        coord._in_standby = False

        self._run(entity, coord, mock_mertik, current_temp=20.5)

        mock_mertik.ignite_fireplace.assert_not_called()
        mock_mertik.standBy.assert_called_once()

    # ─────────────────────────────────────────────────────────────────────────
    # Scenario 2: fire On, 0.5C below -> ignite then Low Heat, light reset
    # ─────────────────────────────────────────────────────────────────────────
    def test_scenario_02_cold_start_low_heat(self, climate_entity):
        """0.5C below setpoint: cold start ignition, settles into Low Heat."""
        entity, coord, mock_mertik = climate_entity
        # Fire fully off, user has not switched it off (simulate "On" switch pressed)
        mock_mertik.is_flame_on = False
        mock_mertik.is_igniting = False
        coord._in_standby = False
        # Mark fire as on from user's switch press
        mock_mertik.is_flame_on = False
        coord._optimistic_on_until = None
        # Simulate Fireplace switch ON (is_on via optimistic)
        coord.mark_optimistic_on()

        self._run(entity, coord, mock_mertik, current_temp=19.5)

        # Ignition triggered, pending mode = Low Heat
        mock_mertik.ignite_fireplace.assert_called_once()
        assert coord._pending_mode == "Low Heat"

        # Simulate ignition completing: igniting->False, flame_on->True
        mock_mertik.is_igniting = False
        mock_mertik.is_flame_on = True
        # Advance settle timer past _settle_seconds
        from unittest.mock import patch
        from homeassistant.util import dt as dt_util
        from datetime import timedelta
        coord._flame_on_since = dt_util.utcnow() - timedelta(seconds=36)
        coord.check_pending_mode()

        # Low Heat commands sent
        mock_mertik.aux_off.assert_called()
        mock_mertik.set_flame_height.assert_called()
        # Light should be restored (fire_just_turned_off was True during ignition)
        assert coord._pending_mode is None

    # ─────────────────────────────────────────────────────────────────────────
    # Scenario 3: fire On, 1.5C below -> ignite then Medium Heat, light reset
    # ─────────────────────────────────────────────────────────────────────────
    def test_scenario_03_cold_start_medium_heat(self, climate_entity):
        """1.5C below setpoint: cold start ignition, settles into Medium Heat."""
        entity, coord, mock_mertik = climate_entity
        mock_mertik.is_flame_on = False
        mock_mertik.is_igniting = False
        coord.mark_optimistic_on()

        self._run(entity, coord, mock_mertik, current_temp=18.5)

        mock_mertik.ignite_fireplace.assert_called_once()
        assert coord._pending_mode == "Medium Heat"

        mock_mertik.is_igniting = False
        mock_mertik.is_flame_on = True
        from datetime import timedelta
        from homeassistant.util import dt as dt_util
        coord._flame_on_since = dt_util.utcnow() - timedelta(seconds=36)
        coord.check_pending_mode()

        mock_mertik.aux_off.assert_called()
        mock_mertik.set_flame_height.assert_called()
        assert coord._pending_mode is None

    # ─────────────────────────────────────────────────────────────────────────
    # Scenario 4: fire On, 2.5C below -> ignite then Full Heat, light reset
    # ─────────────────────────────────────────────────────────────────────────
    def test_scenario_04_cold_start_full_heat(self, climate_entity):
        """2.5C below setpoint: cold start ignition, settles into Full Heat."""
        entity, coord, mock_mertik = climate_entity
        mock_mertik.is_flame_on = False
        mock_mertik.is_igniting = False
        coord.mark_optimistic_on()

        self._run(entity, coord, mock_mertik, current_temp=17.5)

        mock_mertik.ignite_fireplace.assert_called_once()
        assert coord._pending_mode == "Full Heat"

        mock_mertik.is_igniting = False
        mock_mertik.is_flame_on = True
        from datetime import timedelta
        from homeassistant.util import dt as dt_util
        coord._flame_on_since = dt_util.utcnow() - timedelta(seconds=36)
        coord.check_pending_mode()

        mock_mertik.set_flame_height.assert_called()
        mock_mertik.aux_on.assert_called()
        assert coord._pending_mode is None

    # ─────────────────────────────────────────────────────────────────────────
    # Scenario 5: not yet ignited, standby mode, temp drops -> ignite + Low Heat
    # ─────────────────────────────────────────────────────────────────────────
    def test_scenario_05_pilot_cold_start_from_standby_drop(self, climate_entity):
        """Not yet ignited. Temp drops 0.2C below setpoint -> ignite then Low Heat."""
        entity, coord, mock_mertik = climate_entity
        mock_mertik.is_flame_on = False
        mock_mertik.is_igniting = False
        coord._in_standby = False
        coord.mark_optimistic_on()
        entity._last_applied_mode = "Standby"

        self._run(entity, coord, mock_mertik, current_temp=19.9)

        # Not above setpoint, diff=0.1 < LOW_THRESH=1.0 -> Low Heat
        mock_mertik.ignite_fireplace.assert_called_once()
        assert coord._pending_mode == "Low Heat"

    # ─────────────────────────────────────────────────────────────────────────
    # Scenario 6: previously ignited (pilot/standby), temp drops -> Low Heat
    # ─────────────────────────────────────────────────────────────────────────
    def test_scenario_06_from_standby_pilot_to_low_heat(self, climate_entity):
        """Fire in standby (pilot lit). Temp drops -> Low Heat, no re-ignition."""
        entity, coord, mock_mertik = climate_entity
        mock_mertik.is_flame_on = True   # pilot counts
        mock_mertik.is_igniting = False
        coord._in_standby = True
        entity._last_applied_mode = "Standby"

        self._run(entity, coord, mock_mertik, current_temp=19.9)

        mock_mertik.ignite_fireplace.assert_not_called()
        mock_mertik.aux_off.assert_called()
        mock_mertik.set_flame_height.assert_called()

    # ─────────────────────────────────────────────────────────────────────────
    # Scenario 7: Low Heat, temp rises above setpoint -> Standby (no guard_flame_off)
    # ─────────────────────────────────────────────────────────────────────────
    def test_scenario_07_low_heat_to_standby_on_warmup(self, climate_entity):
        """Room warms above setpoint from Low Heat -> Standby. Pilot stays lit."""
        entity, coord, mock_mertik = climate_entity
        mock_mertik.is_flame_on = True
        mock_mertik.is_igniting = False
        coord._in_standby = False
        entity._last_applied_mode = "Low Heat"

        self._run(entity, coord, mock_mertik, current_temp=20.1)

        mock_mertik.standBy.assert_called_once()
        mock_mertik.guard_flame_off.assert_not_called()

    # ─────────────────────────────────────────────────────────────────────────
    # Scenario 8: Low Heat, temp drops 1.0C -> Medium Heat
    # ─────────────────────────────────────────────────────────────────────────
    def test_scenario_08_low_heat_to_medium_on_drop(self, climate_entity):
        """1.5C below setpoint from Low Heat -> escalates to Medium Heat."""
        entity, coord, mock_mertik = climate_entity
        mock_mertik.is_flame_on = True
        mock_mertik.is_igniting = False
        coord._in_standby = False
        entity._last_applied_mode = "Low Heat"

        # was at 19.5 (-0.5C), drops 1.0C to 18.5 (-1.5C) -> Medium Heat
        self._run(entity, coord, mock_mertik, current_temp=18.5)

        mock_mertik.aux_off.assert_called()
        mock_mertik.set_flame_height.assert_called()
        # Verify Medium Heat uses FLAME_MAX
        from custom_components.mertik.const import FLAME_MAX
        mock_mertik.set_flame_height.assert_called_with(FLAME_MAX)

    # ─────────────────────────────────────────────────────────────────────────
    # Scenario 9: Medium Heat, temp rises 1.0C -> Low Heat
    # ─────────────────────────────────────────────────────────────────────────
    def test_scenario_09_medium_heat_to_low_on_rise(self, climate_entity):
        """Temp rises from 1.5C to 0.5C below setpoint -> Medium to Low Heat."""
        entity, coord, mock_mertik = climate_entity
        mock_mertik.is_flame_on = True
        mock_mertik.is_igniting = False
        coord._in_standby = False
        entity._last_applied_mode = "Medium Heat"

        # was 18.5 (-1.5C), rises to 19.5 (-0.5C) -> Low Heat
        self._run(entity, coord, mock_mertik, current_temp=19.5)

        from custom_components.mertik.const import FLAME_MIN
        mock_mertik.aux_off.assert_called()
        mock_mertik.set_flame_height.assert_called_with(FLAME_MIN)

    # ─────────────────────────────────────────────────────────────────────────
    # Scenario 10: Medium Heat, temp drops 1.0C -> Full Heat
    # ─────────────────────────────────────────────────────────────────────────
    def test_scenario_10_medium_heat_to_full_on_drop(self, climate_entity):
        """Temp drops from 1.5C to 2.5C below setpoint -> Medium to Full Heat."""
        entity, coord, mock_mertik = climate_entity
        mock_mertik.is_flame_on = True
        mock_mertik.is_igniting = False
        coord._in_standby = False
        entity._last_applied_mode = "Medium Heat"

        # was 18.5 (-1.5C), drops to 17.5 (-2.5C) -> Full Heat
        self._run(entity, coord, mock_mertik, current_temp=17.5)

        from custom_components.mertik.const import FLAME_MAX
        mock_mertik.set_flame_height.assert_called_with(FLAME_MAX)
        mock_mertik.aux_on.assert_called()

    # ─────────────────────────────────────────────────────────────────────────
    # Scenario 11: Full Heat, temp rises 1.0C -> Medium Heat
    # ─────────────────────────────────────────────────────────────────────────
    def test_scenario_11_full_heat_to_medium_on_rise(self, climate_entity):
        """Temp rises from 2.5C to 1.5C below setpoint -> Full to Medium Heat."""
        entity, coord, mock_mertik = climate_entity
        mock_mertik.is_flame_on = True
        mock_mertik.is_igniting = False
        coord._in_standby = False
        entity._last_applied_mode = "Full Heat"

        # was 17.5 (-2.5C), rises to 18.5 (-1.5C) -> Medium Heat
        self._run(entity, coord, mock_mertik, current_temp=18.5)

        from custom_components.mertik.const import FLAME_MAX
        mock_mertik.aux_off.assert_called()
        mock_mertik.set_flame_height.assert_called_with(FLAME_MAX)
