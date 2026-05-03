"""Constants for the Mertik Maxitrol Fireplace integration."""

DOMAIN = "mertik"

# Config / options entry keys
CONF_LOW_THRESHOLD  = "low_threshold"
CONF_HIGH_THRESHOLD = "high_threshold"
CONF_TEMP_SENSOR    = "temperature_sensor"

# Default thermostatic thresholds (degrees C below setpoint)
DEFAULT_LOW_THRESHOLD  = 2.0   # within 2C -> Low Heat
DEFAULT_HIGH_THRESHOLD = 4.0   # more than 4C below -> Full Heat
DEFAULT_TEMP_SENSOR    = ""    # empty = use fireplace handset sensor

# Heating mode select options
MODE_OFF    = "Off"
MODE_FULL   = "Full Heat"
MODE_MEDIUM = "Medium Heat"
MODE_LOW    = "Low Heat"
MODE_THERMO = "Thermostatic"
HEATING_MODES = [MODE_OFF, MODE_FULL, MODE_MEDIUM, MODE_LOW, MODE_THERMO]

# Flame height step range
FLAME_MIN = 1
FLAME_MAX = 12   # table has 12 entries; formula gives 13 for max (0xFF)
