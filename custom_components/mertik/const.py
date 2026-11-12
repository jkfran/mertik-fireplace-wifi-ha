"""Constants for the Mertik Maxitrol integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "mertik"
MANUFACTURER = "Mertik Maxitrol"

CONF_MAC = "mac"
# Name the WiFi module gives itself when asked, e.g. "mmWiFiBoxV2".
CONF_MODEL = "model"
# Option: a Home Assistant temperature sensor for the thermostat to regulate on.
CONF_TEMPERATURE_SENSOR = "temperature_sensor"

UPDATE_INTERVAL = timedelta(seconds=10)

# Requested values are shown for this long while the fireplace catches up (the
# valve needs up to ten seconds to move).
OPTIMISTIC_SECONDS = 12.0
# Commands given while the fireplace is lighting are kept this long at most.
PENDING_TIMEOUT_SECONDS = 300.0
# The receiver ignores an ignition right after a shutdown.
REIGNITE_DELAY_SECONDS = 15.0
# How often the module at the stored address is asked whether it is still this
# fireplace (addresses get handed out again). It is also asked whenever the
# connection comes back, and before every ignition.
IDENTITY_CHECK_SECONDS = 300.0
# A temperature sensor that has not reported for this long is not regulated on:
# one whose battery died keeps showing its last value. Long enough for sensors
# that report once an hour whatever happens.
SENSOR_STALE_SECONDS = 5400.0
# Before a command, the module is asked who it is unless it was asked this
# recently.
IDENTITY_FRESH_SECONDS = 30.0
# A fireplace told to turn off that reads off is taken at its word only after
# this long: an ignition started with the handset a moment earlier shows late.
OFF_CONFIRM_SECONDS = 20.0
# An off that was not obeyed is sent again at most this often.
OFF_RETRY_SECONDS = 10.0
