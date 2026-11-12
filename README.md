# Mertik Maxitrol Fireplace for Home Assistant

Control a gas fireplace that has a Mertik Maxitrol WiFi module from Home Assistant: ignite it, turn
it off, set the flame, the second burner and the light, and let a thermostat hold the room
temperature. Everything runs on your local network; no cloud account is involved.

These are the fireplaces you control from your phone with the MyFire app or one of its branded
versions, such as Valor 10 Remote, Gazco MyFire, Barbas Gas or Trimline Fires. The list is under
[Compatibility](#compatibility).

[![Tests](https://github.com/jkfran/mertik-fireplace-wifi-ha/actions/workflows/tests.yml/badge.svg)](https://github.com/jkfran/mertik-fireplace-wifi-ha/actions/workflows/tests.yml)

## Compatibility

Many fireplace makers fit the Mertik Maxitrol WiFi module, sold as the *myfire Wi-Fi Box* of the
GV60 control system, and have their own version of its app. If you control your fireplace with one
of these iOS or Android apps, it has this module (the names are those in the App Store and on Google
Play in November 2026):

- MyFire (Mertik Maxitrol's own app)
- attika Fire
- Barbas Gas (Barbas and Bellfires)
- Brunner WiFi-control (on Google Play just WiFi-control)
- Element4 ProControl (on Google Play just ProControl)
- Fire Connects
- Gazco MyFire
- ITALKERO Fires
- Ortal Heating Solutions
- Planika Gas Control
- RAIS Gas (called RAISfire before)
- SAFIRE
- Signi Fires
- Trimline Fires (thermoCet International)
- Valor 10 Remote
- Wanders Ecowave (on Google Play just Wanders)

Such a fireplace most likely works with this integration. Valor, Bellfires and Gazco fireplaces have
been reported to work with it or with one of its forks. What is not known is the newest generation
of the module, the last row here:

| Part No. | Compatible? | Found automatically? |
|---|---|---|
| B6R-WME | Yes | Yes |
| B6R-W2BE-0 | Yes | Yes |
| B6R-W2ZV-0 | Yes | Not reported |
| B6R-WWN | Yes | Not sure; one report says no |
| B6R-W3… | Not known | Not known |

The app's setup guide calls the B6R-W… boxes V1, the B6R-W2… boxes V2 and the B6R-W3… boxes V3. A
V1 or V2 box with another ending than the ones in the table probably works too. The V3 box is the
newer one, which the app finds over Bluetooth during setup. No report of one has reached this
project, so whether it speaks the same protocol is not known. If you have one, or an app or a module
that is not listed here, a report of what works is welcome.

The WiFi module must be connected to your network (set that up with the manufacturer's app) and
Home Assistant must be able to reach it on TCP port 2000. Home Assistant 2024.12 or newer.

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
- If the old address goes to another fireplace, that one is not controlled in this one's place. The
  integration asks the module who it is before every ignition, before any other command unless it
  asked in the last half minute, whenever the connection comes back, and every few minutes.
- A fireplace cannot be added twice.

Modules that do not answer the search work too, by their IP address alone; give those a fixed
address in your router.

## Using it

**Turning on.** Igniting takes about a minute, and the fireplace must be left alone meanwhile.
Status reads *Igniting* until the fire has settled. Anything you set during that time (flame height,
secondary burner, mode, thermostat) is kept and applied once the fire is lit, so an automation can
turn the fireplace on and set the flame in one go.

**Turning off.** Status reads *Shutting down* for about half a minute. The fireplace cannot be
ignited during a shutdown or in the first seconds after it; Home Assistant tells you so instead of
sending a command the fireplace would ignore.

An off is not taken for done until the fireplace has been seen to obey. A fireplace that is
igniting refuses commands; if you turn it off in that minute, the switch reads off at once and the
command is sent again, every ten seconds at most, until the fireplace reports that it is shutting
down or off. The same happens when the fireplace could not be reached, or acknowledged the command
and burned on. While the WiFi module has no link to the fireplace, which is what an ignition looks
like, Home Assistant waits for the link instead of sending into it. If the fireplace has still not
turned off after five minutes, Home Assistant gives up and raises a repair that says so.

Within those five minutes the off is carried out as soon as it can be, whatever happened at the
fireplace in between. If it was out of reach, and someone turned it off and lit it again by hand
meanwhile, it is turned off once more when it answers again. Turning it on in Home Assistant is what
calls an owed off off.

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
handset reporting a temperature the thermostat refuses to start and points you to the other way.

**With any temperature sensor.** Under the integration's **Configure**, pick a temperature sensor.
Home Assistant then regulates the flame itself: full flame when the room is a degree or more below
the target, a low flame close to it, and down to the pilot once the room is warm enough. It changes
the flame at most every two minutes. It goes down to the pilot when the sensor has been unavailable
for five minutes, or has not reported anything for an hour and a half: a sensor with a dead battery
keeps showing its last value. A sensor that only reports changes can trip this in a room that holds
its temperature exactly; the flame comes back with its next report. Choosing eco or thermostat mode
on the handset ends the regulating, so that two regulators never work against each other.

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
- The ignite command only goes to a fireplace whose status was read a moment before and says off.
  It is never sent twice: once it has left, the fireplace counts as igniting for a minute, even if
  no answer came back.
- The fireplace switch does not become unavailable when the fireplace stops answering, because
  Home Assistant does not pass commands on to unavailable entities. It reads *unknown*, and turning
  it off still works as described above. The exception is a start of Home Assistant during which
  the fireplace cannot be reached at all: until it can, the integration has no entities to show.
- While the fireplace ignites or shuts down, nothing but "off" is sent to it.
- Think about who and what can reach that switch: voice assistants, dashboards on shared tablets,
  automations. Consider an automation that turns the fireplace off after a few hours.
- It does not replace the fireplace's own safety devices or your attention.

## Troubleshooting

**Entities are unavailable and the switch reads unknown.** Either Home Assistant cannot reach the
WiFi module (check its address under Reconfigure), or the module has lost its radio link to the
receiver in the fireplace.
In the second case the *Receiver* sensor reads disconnected and a repair appears under **Settings →
Repairs**; the manufacturer's app shows fault F43. Check the receiver's power or batteries. Using
the handset, or switching the fireplace's power off and on, usually brings the link back.

**You replaced the WiFi module.** A module with another MAC address is another fireplace to the
integration. Remove the fireplace from Home Assistant and add it again.

**A repair says the fireplace did not turn off.** Home Assistant sent the command for five
minutes and the fireplace kept burning. Turn it off with the handset and look for the cause: the
receiver's batteries, or the WiFi module's link to it. The repair goes away when the fireplace is
off.

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
