# Mertik Maxitrol Fireplace — Home Assistant Integration

A Home Assistant custom integration for gas fireplaces controlled by the
**Mertik Maxitrol myfire WiFi box** (B6R-WME / B6R-W2BE-0 and similar).

This implementation adds thermostatic control which can use the Maxitrol
handset as the temperature sensor, or any other HA temperature sensor.
Of course the sensor needs to be in the room with the fire!

This is a substantially enhanced fork of
[jkfran/mertik-fireplace-wifi-ha](https://github.com/jkfran/mertik-fireplace-wifi-ha).
The wire protocol was reverse-engineered through PCAPdroid packet captures of
the official myfire app, cross-referenced with community work by
[erdebee](https://github.com/erdebee/homey-mertik-wifi),
[rbrondgeest](https://github.com/rbrondgeest/homey-mertik-wifi), and
[tritter](https://github.com/tritter/homebridge-mertik-fireplace).

See [PROTOCOL.md](PROTOCOL.md) for full wire-level documentation.

---

## What's new vs the original

| Feature | Original | This fork |
|---------|----------|-----------|
| On / Off | ✅ | ✅ |
| Flame height (1–13 steps) | ✅ (broken) | ✅ fixed |
| Light on/off + dimming | ✅ (broken) | ✅ fixed |
| Aux / rear burner | ✅ (broken) | ✅ fixed |
| Temperature sensor | ✅ (broken) | ✅ fixed |
| APP mode handshake | ❌ | ✅ |
| Light stays on when fire turns off | ❌ | ✅ |
| Heating mode selector | ❌ | ✅ |
| Thermostatic control | ❌ | ✅ |
| Selectable external temperature sensor | ❌ | ✅ |
| Adjustable thermostat thresholds | ❌ | ✅ |

---

## Compatible hardware

| WiFi Box Part No. | Status |
|---|---|
| B6R-WME | Confirmed working |
| B6R-W2BE-0 | Confirmed working |
| B6R-WWN | Likely working, unconfirmed |

Tested against a **B6R-H8TV4PB** receiver. The same WiFi box is sold under
many brand names: RAISfire, Gazco MyFire, Trimline Fires, Thermocet,
ITALKERO, Signi, SAFIRE, attika, Ortal, and Fire Connects.

---

## Entities

| Entity | Type | Notes |
|--------|------|-------|
| Fireplace | Switch | Main on/off |
| Aux | Switch | Rear / second burner |
| Flame Height | Number | Steps 1–13; shows 0 when fire is off |
| Light | Light | Dimmable; stays on when fire is turned off |
| Ambient Temperature | Sensor | Room temperature from paired handset |
| Heating Mode | Select | Standby / Full Heat / Medium Heat / Low Heat / Thermostatic |
| Thermostat | Climate | Setpoint display and thermostatic control |

---

## Heating modes

Select the mode using the **Heating Mode** entity:

| Mode | Behaviour |
|------|-----------|
| **Standby** | Pilot flame only; main burners off but instant re-ignition |
| **Full Heat** | Both burners, maximum flame |
| **Medium Heat** | Front burner only, maximum flame |
| **Low Heat** | Front burner only, minimum flame |
| **Thermostatic** | HA automatically controls the heating mode based on room temperature vs setpoint |

To turn the fire off, use the **Fireplace** switch. This extinguishes both
the main burners and the pilot flame.

### Thermostatic control

Set the target temperature using the **Thermostat** entity's temperature
slider. HA reads the current room temperature every 10 seconds and applies
the appropriate heating mode:

| Room temperature vs setpoint | Mode applied |
|------------------------------|--------------|
| At or above setpoint | Standby (pilot flame only) |
| Within low threshold (default 1 °C) | Low Heat |
| Within high threshold (default 2 °C) | Medium Heat |
| More than high threshold below | Full Heat |

When the room reaches the setpoint the main burners are extinguished but
the **pilot flame remains lit**, allowing fast re-ignition when the room
cools. To extinguish the pilot as well, turn off the Fireplace switch.

The default thresholds are 1 °C (Low) and 2 °C (High) and are adjustable via
**Settings → Devices & Services → Mertik → Configure**.

**Cold start behaviour** — when the thermostat calls for heat from fully off,
the fire ignites at full heat (both burners). After the burner is confirmed
lit and a 35-second settle period, the correct mode (Low / Medium / Full) is
applied automatically. This delay is required because the device ignores
flame height and aux commands in the seconds immediately after ignition.

### Temperature sensor

By default the thermostat uses the ambient temperature from the fireplace's
own handset sensor. You can select any other HA temperature sensor via
**Settings → Devices & Services → Mertik → Configure**.

> **Note:** The handset sensor only transmits temperature when it has entered
> APP mode (indicated by "APP" on the handset display). If no temperature
> appears, configure an external sensor — any HA `sensor` with
> `device_class: temperature` appears in the dropdown.

---

## Data updates

The integration communicates with the fireplace over a **direct local TCP connection** (port 2000) with no cloud dependency. There is no push notification mechanism — the device does not send unsolicited updates.

HA **polls the device every 10 seconds** by sending a status request and parsing the response. Each poll refreshes:

- On/off state and flame status
- Ignition and shutdown flags
- Ambient temperature (from the handset sensor)

The 10-second interval is chosen for two reasons:
1. **Thermostatic control** — the control loop runs on every poll and must react to temperature changes promptly to avoid overshooting the target.
2. **Optimistic state window** — after a command (e.g. turn on), the integration shows the new state optimistically for up to 20 seconds while the device executes the request. A slower poll interval would leave the UI unresponsive for an unacceptable portion of the ignition cycle.

**Optimistic state model** — because the device takes several seconds to physically execute commands (ignition, shutdown), the integration maintains local optimistic state between polls. For example, after pressing "On", the Fireplace switch shows as on immediately; if the device has not confirmed the change within 20 seconds, the state reverts to what the device reports. This avoids a flickering UI during normal use.

There is no user-configurable polling interval. The interval is fixed because the thermostatic control algorithm depends on a consistent polling rate.

---

## Installation

### HACS (recommended)
1. HACS → Integrations → ⋮ → Custom repositories
2. Add this repository URL, category: Integration
3. Install "Mertik Maxitrol Fireplace", restart HA

### Manual
1. Copy `custom_components/mertik/` into `config/custom_components/`
2. Restart Home Assistant

### Configuration
**Settings → Devices & Services → Add Integration → Mertik Maxitrol**

Enter the IP address of your myfire WiFi box. Assign a static DHCP lease
so the IP does not change.

#### Initial setup parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| **Name** | Yes | Display name for the device in Home Assistant |
| **Host** | Yes | IP address of the myfire WiFi box (e.g. `192.168.1.100`) |
| **Low Heat threshold** | No | Degrees °C below the thermostat setpoint at which Low Heat is applied. Default: `1.0`. Must be greater than 0 and less than the Full Heat threshold. |
| **Full Heat threshold** | No | Degrees °C below the thermostat setpoint at which Full Heat is applied. Default: `2.0`. Must be greater than the Low Heat threshold. |

#### Options (Settings → Devices & Services → Mertik Maxitrol → Configure)

| Parameter | Description |
|-----------|-------------|
| **Temperature sensor** | HA temperature sensor entity to use for thermostatic control. Leave empty to use the Mertik handset's built-in sensor. Any `sensor` entity with `device_class: temperature` appears in the dropdown. |
| **Low Heat threshold** | See above. Can be adjusted without restarting HA. |
| **Full Heat threshold** | See above. Can be adjusted without restarting HA. |

### Removing the integration

1. **Settings → Devices & Services → Mertik Maxitrol → ⋮ → Delete**
   This removes the integration and all its entities from Home Assistant.
2. *(HACS installs only)* Open HACS → Integrations → Mertik Maxitrol Fireplace →
   **Remove** to uninstall the component files, then restart Home Assistant.
3. *(Manual installs only)* Delete the `custom_components/mertik/` folder from
   your config directory and restart Home Assistant.

The myfire WiFi box requires no additional steps — it continues to operate
normally via the physical handset after the integration is removed.

### Startup safety automation

The integration does not send a turn-off command at startup — doing so
interferes with the device's flame height control. Add this automation to
ensure the fire is off after every HA restart:

```yaml
alias: "Fireplace off on HA start"
trigger:
  - platform: homeassistant
    event: start
action:
  - delay: "00:00:10"
  - service: switch.turn_off
    target:
      entity_id: switch.fireplace
```

---

## Known limitations

**Flame height feedback** — The device status packet always reports the
post-ignition baseline flame level regardless of `set_flame_height` commands.
Flame height is therefore tracked locally from commands. The audible beep and
physical flame change confirm the command was received and executed.

**Fireplace switch takes precedence over thermostatic control** — turning the
fire off via the Fireplace switch prevents the thermostat from re-igniting it,
even if the room temperature drops below the setpoint. To resume thermostatic
control, turn the Fireplace switch back on.

**Rear burner at ignition** — Both burners light physically at ignition.
The integration sends `aux_on` immediately after ignite so the Aux switch
shows On and can be turned off.

**Light when fire turns off** — The device physically extinguishes the light
when the fire is turned off. The integration detects this and immediately
re-sends the light on command at the previous brightness, so the light
remains on. If you want the light to go off with the fire, turn it off
manually before turning off the fire.

**Handset APP mode** — The handset shows "APP" only when specific conditions
are met. Controls work correctly regardless of whether "APP" is displayed.

---

## Disclaimer

This integration controls a gas appliance. Use at your own risk. The authors
accept no responsibility for any damage or injury. Always ensure your
fireplace has a working ODS (Oxygen Depletion Sensor) and is maintained by
a qualified engineer.
