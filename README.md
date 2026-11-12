# Mertik Maxitrol Fireplace for Home Assistant

Control a gas fireplace that has a Mertik Maxitrol WiFi module from Home Assistant: ignite it, turn
it off, set the flame, the second burner and the light, and let a thermostat hold the room
temperature. Everything runs on your local network; no cloud account is involved.

[![Tests](https://github.com/jkfran/mertik-fireplace-wifi-ha/actions/workflows/tests.yml/badge.svg)](https://github.com/jkfran/mertik-fireplace-wifi-ha/actions/workflows/tests.yml)

## What you get

| Entity | Type | What it does |
|---|---|---|
| *(the fireplace's name)* | Switch | On ignites the fireplace. Off turns it off completely, pilot included. |
| Flame Height | Number | 12 steps, like the handset. 0 is standby: main burner off, pilot on. |
| Secondary burner | Switch | The second burner of dual-burner fireplaces. |
| Light | Light | The fireplace light, dimmable. Works with the fire off. |
| Mode | Select | Manual, Thermostat or Eco: the mode the fireplace itself is in. |
| Thermostat | Climate | Holds a room temperature while the fire is on. See [Thermostat](#thermostat). |
| Status | Sensor | Off, Standby, Igniting, On or Shutting down. |
| Ambient Temperature | Sensor | Room temperature measured by the handset. |
| Pilot flame | Binary sensor | On while the pilot burns. |
| Receiver, Remote | Binary sensors | Whether the WiFi module reaches the fireplace, and whether a handset reports to it. |

Disabled by default, for diagnosing: Igniting, Shutting down, Fault, Fan, Fan level and IP address.

## Compatibility

Fireplaces with one of these Mertik Maxitrol WiFi modules:

| Part No. | Compatible? | Found automatically? |
|---|---|---|
| B6R-WME | Yes | Yes |
| B6R-W2BE-0 | Yes | Yes |
| B6R-WWN | Yes | Not sure |

These are the fireplaces you can control with one of these apps: MyFire, Trimline Fires, RAISfire,
Gazco MyFire, Thermocet International, Fire Connects, ITALKERO Fires, Signi Fires, SAFIRE, attika
Fire, Ortal Heating Solutions, Barbas Gas.

The WiFi module must be connected to your network (set that up with the manufacturer's app) and
Home Assistant must be able to reach it on TCP port 2000. Home Assistant 2024.12 or newer.

## Installation

**HACS** (the **Marketplace** in Home Assistant 2026.11 and later): add
`https://github.com/jkfran/mertik-fireplace-wifi-ha` as a custom repository of type *Integration*,
install *Mertik Maxitrol Fireplace*, and restart Home Assistant.

**By hand:** copy the `custom_components/mertik` folder into the `custom_components` folder of your
Home Assistant configuration and restart.

## Setup

Go to **Settings → Devices & services → Add integration** and pick **Mertik Maxitrol Fireplace**.

Home Assistant searches your network for WiFi modules and offers the ones it finds. If yours is not
in the list (the search does not cross into other subnets or VLANs), type its IP address; your
router's client list shows it.

The fireplace is remembered by the MAC address of its module, not by its IP address:

- If the module gets a new address, Home Assistant follows it. If that ever fails, change the
  address by hand under the integration's **⋮ → Reconfigure**.
- A fireplace cannot be added twice.

## Using it

**Turning on.** Igniting takes about a minute, and the fireplace must be left alone meanwhile.
Status reads *Igniting* until the fire has settled. Anything you set during that time (flame height,
secondary burner, mode, thermostat) is kept and applied once the fire is lit, so an automation can
turn the fireplace on and set the flame in one go.

**Turning off.** Status reads *Shutting down* for about half a minute. The fireplace cannot be
ignited during a shutdown or in the first seconds after it; Home Assistant tells you so instead of
sending a command the fireplace would ignore.

**Standby.** Setting Flame Height to 0 turns the main burner off and leaves the pilot on. The
fireplace still counts as on, and any flame height brings the burner back without a new ignition.

**Mode.** *Eco* lets the fireplace vary its flame to save gas. *Thermostat* is the fireplace's own
thermostat (next section). *Manual* is a fixed flame height.

**Secondary burner.** Turn it off to run on the primary burner only. It reads off while the
fireplace is off.

## Thermostat

The Thermostat entity works in one of two ways.

**With the handset (default).** It drives the fireplace's own thermostat mode, the one you set on
the remote. The fireplace measures the room with the handset and adjusts its flame. Without a
handset reporting to the fireplace there is no room temperature, and this cannot work.

**With any temperature sensor.** Under the integration's **Configure**, pick a temperature sensor.
Home Assistant then regulates the flame itself: full flame when the room is a degree or more below
the target, a low flame close to it, and down to the pilot once the room is warm enough. It changes
the flame at most every two minutes, and goes down to the pilot if the sensor stops reporting.

Either way:

- **The thermostat never ignites the fireplace.** Turn the fireplace on first; the thermostat
  refuses to start otherwise. When the fire goes out or is turned off, Home Assistant stops
  regulating and does not start again by itself.
- Turning the thermostat off returns to a manual flame. The fire keeps burning; use the fireplace
  switch to turn it off.
- Setting the flame height by hand takes over from Home Assistant's thermostat.

## Safety

This integration controls a gas appliance.

- It only ignites the fireplace when you, or an automation you wrote, turn the fireplace switch on.
  Nothing else in it lights a fire: not the thermostat, not a flame height, not a restart of Home
  Assistant.
- An ignite command is never sent twice, and never to a fireplace that is already on.
- Think about who and what can reach that switch: voice assistants, dashboards on shared tablets,
  automations. Consider an automation that turns the fireplace off after a few hours.
- It does not replace the fireplace's own safety devices or your attention.

## Troubleshooting

**Entities are unavailable.** Either Home Assistant cannot reach the WiFi module (check its
address under Reconfigure), or the module has lost its radio link to the receiver in the fireplace.
In the second case the *Receiver* sensor reads disconnected and a repair appears under **Settings →
Repairs**; the manufacturer's app shows fault F43. Check the receiver's power or batteries. Using
the handset, or switching the fireplace's power off and on, usually brings the link back.

**Ambient Temperature is unknown.** No handset is reporting to the fireplace (the app shows F44).
The *Remote* sensor tells you.

**The app stops working.** Some modules serve one connection at a time. The integration only
connects for a moment every ten seconds, which leaves room for the app, but two apps open at once
can still get in each other's way.

**Reporting a problem.** Download the diagnostics from the integration's page (**⋮ → Download
diagnostics**) and include them. They hold the last status frame of your fireplace, which is what
is needed to see what it reports. The IP and MAC addresses are removed.

## Upgrading from 1.x

Your entities keep their IDs, names and history. What changes:

- Flame Height now starts at 0 (standby) and reads the handset's steps correctly. Steps 8 to 12 used
  to read as 9 to 13.
- The fireplace switch reads on whenever the pilot burns, so also in standby and while igniting.
  Turning it on when it is already on does nothing; it used to send another ignite.
- A cold fireplace that reports a full burner output no longer shows as on.
- Ambient Temperature is unknown when no handset reports one. It used to show a constant, meaningless
  number.
- The lowest brightness settings of the light now light it. On some fireplaces they did not.
- The integration recognises the fireplace by its MAC address and follows it to a new IP address.

## Development

```
pip install -r requirements_test.txt
pytest tests/
```

The tests run against a scripted fireplace, without network access.
[`PROTOCOL.md`](PROTOCOL.md) describes the protocol and where each fact comes from.
`tools/mertik_cli.py` finds modules and prints what a fireplace reports; it only reads.

Most of what is known about a burning fire comes from one fireplace each. If yours behaves
differently, its diagnostics are the most useful thing you can share.

## Credits

This integration grew out of [`djerik/mertik-ha`](https://github.com/djerik/mertik-ha). It builds
on the work of people who measured their own fireplaces and published what they found:

- [@dennisbrouwer91](https://github.com/dennisbrouwer91): the thermostat entity and pilot detection.
- [@diederikm](https://github.com/diederikm): the status word, the fireplace states and the most
  complete protocol description.
- [@DaveJesse](https://github.com/DaveJesse): command timing, the receiver and handset faults, light
  levels.
- [@dsmagghe](https://github.com/dsmagghe): discovery and the MAC address as identity.
- [@vanDonselaar](https://github.com/vanDonselaar) and [@fmarceau90](https://github.com/fmarceau90):
  standby and flame handling.
- [`omarshahine/valor-fireplace-cli`](https://github.com/omarshahine/valor-fireplace-cli) and
  [`tritter/homebridge-mertik-fireplace`](https://github.com/tritter/homebridge-mertik-fireplace).

## Disclaimer

Use this integration at your own risk. It is not affiliated with or endorsed by Mertik Maxitrol,
and its authors take no responsibility for any damage that follows from its use.
