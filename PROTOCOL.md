# Mertik Maxitrol WiFi module protocol

The local protocol of the Mertik Maxitrol WiFi modules (B6R-WME, B6R-WWN, B6R-W2BE-0, B6R-W2ZV-0) that
the MyFire app and its white-label versions use. This is what `custom_components/mertik/mertik.py`
and `discovery.py` implement.

Nothing here comes from the manufacturer. Each statement carries the letter of its source:

| | Source |
|---|---|
| **J** | Measured for this repository on a fireplace whose module answers as `mmWiFiBoxV2` (2026-11): with the fire off, both with and without a handset reporting, and one session with the fire lit, without a handset reporting, polled every 5 seconds from the moment it burned; the ignition itself was not recorded |
| **D** | [`diederikm/mertik-fireplace-wifi-ha`](https://github.com/diederikm/mertik-fireplace-wifi-ha) `PROTOCOL.md`: measurements on a Bellfires fireplace with a B6R-W2BE-0 module, and the names the vendor apps use |
| **G** | [`DaveJesse/mertik-fireplace-wifi-with-thermostat`](https://github.com/DaveJesse/mertik-fireplace-wifi-with-thermostat) `PROTOCOL.md`: measurements on a Gazco fireplace |
| **V** | [`omarshahine/valor-fireplace-cli`](https://github.com/omarshahine/valor-fireplace-cli) `PROTOCOL.md` |
| **T** | [`tritter/homebridge-mertik-fireplace`](https://github.com/tritter/homebridge-mertik-fireplace) |
| **A** | [`ggreenland/alflex-b6r-hatv4p-protocol`](https://github.com/ggreenland/alflex-b6r-hatv4p-protocol): captures of what the Valor app and a Valor fireplace send each other. The values are taken from there; what they mean is this document's reading |
| **S** | [`dsmagghe/mertik-ha`](https://github.com/dsmagghe/mertik-ha): discovery |
| **O** | The original notes in this repository and [`djerik/mertik-ha`](https://github.com/djerik/mertik-ha) |

Most statements about a burning fire rest on one fireplace each (D or G). Where sources
disagree or nobody measured, it says so. See [What is not known](#what-is-not-known).

## Transport

- TCP port **2000**, no authentication. Everything between the frame markers is ASCII. **O**
- A B6R-W2BE-0 serves one client at a time and pushes status frames on an open socket; a second
  client gets stale data or none. **D** The `mmWiFiBoxV2` answered a second client while Home
  Assistant held a connection, and pushed nothing while the fire was off. **J**
- The Valor app keeps one connection open while it is in use and asks for the status about every
  5 seconds. **A**
- This integration opens one short connection per request and closes it again. That works on both
  kinds of module and leaves the vendor app room to connect.

## Discovery

Send the four bytes `00 01 00 F6` over UDP to port **30718**, as a broadcast or to one address. A
module answers to port **30719** of the sender, whatever port the query came from. **S J**

The answer seen is 30 bytes: a 24-byte name field with `FF` filling the bytes in front of the name,
then the 6-byte MAC address. **J**

```
FF FF FF FF FF FF FF FF FF FF FF FF FF 6D 6D 57 69 46 69 42 6F 78 56 32  xx xx xx xx xx xx
                                       m  m  W  i  F  i  B  o  x  V  2   MAC address
```

## Frames

```
request:  STX  "3030303080"  <command id, 2 chars>  <payload>  ETX
reply:    STX  <header, 10 chars>  <command id, 2 chars>  <payload>  ETX
```

- STX is `0x02`, ETX is `0x03`. As bytes, every request starts `02 33 30 33 30 33 30 33 30 38 30`. **O**
- The reply header is `3030303000` or `0303000000`; the `mmWiFiBoxV2` and A's module send the
  second. **O J A**
- The secondary burner commands are followed by a line feed (`0x0A`) after ETX. **O**
- One read can hold several frames or part of one. Split on STX and ETX, drop anything before an STX,
  and take the newest status frame. **D**
- A control command is acknowledged with a frame holding the header and the command id. The
  acknowledgement can arrive after a status frame. **G**
- A reply with id `E1` (seen as `…E101`) means the module has no radio link to the receiver in the
  fireplace. The vendor app shows this as fault F43. **G**

## Commands

The text after the request header:

| Command | Meaning | Source |
|---|---|---|
| `03` | Read the status | O |
| `01` | Read device information | D |
| `1A` | Ignite | O |
| `10` | Off, pilot included | O |
| `16` + 2 hex | Burner output, `80` (low) to `FF` (high) | O V |
| `1600` | Standby: main burner off, pilot stays on. Does not light a cold fireplace | O G |
| `2001` / `2000` | Secondary burner (aux) on / off | O |
| `3001` / `3000` | Light on / off | O |
| `30FE` + 2 hex | Light level | O |
| `B0` | Manual mode | O T |
| `B201` | Thermostat mode | T V |
| `B2FD` + 4 hex | Thermostat target, degrees Celsius x10 (`00D7` = 21.5) | T V |
| `B301` | Eco mode | O |

Ids the vendor apps know that this integration does not send: `40` fan, `50` LED, `B1` countdown
timer, `A0` week program, `06` clock, `05` name, `D1` settings, `C0`-`C2` fault history, `0C`
reboot. **D O** Nobody has documented what the apps send with them.

When they start, the apps read more than the status: `50FF00` and `50FF01`, by their id the two LED
channels, and in the MyFire app `C2`, the last fault. **A G D** A Valor answered the first two with
`000080FF00000A` and `000180FF00000A` whether the fire burned or not; **A** a Gazco answered none of
the three within 3 seconds. **G** The Valor app also sends `FE00` and then `01` at its start and
before a `1A`, half a second apart, and `FE00` does not always get an answer. **A** `FE` is one of
the ids the apps use for the module itself; what it does here is not known. **D** The Home Assistant
integrations, this one included, ignite with `1A` alone.

## Status frame

Character positions after STX:

| Chars | Field | Notes |
|---|---|---|
| 0-9 | Header | |
| 10-11 | Command id | `03` |
| 12-13 | Setup state | Feature bits, see below |
| 14-15 | Burner output | `00`-`FF`, see [Burner output](#burner-output) |
| 16-19 | State word | 16 bits, see below |
| 20-21 | Light level | Also reported with the light off **D** |
| 22-23 | Fan level | |
| 24 | Mode | `0` manual, `1` thermostat, `2` eco **T D** |
| 26-27 | Flags | `01` countdown, `02` thermostat, `08` child lock, `10` program. Unverified **D** |
| 28-31 | Room temperature x10 | From the handset. `0666` while no handset reports one (the app shows F44) **G J**. A handset reports by itself every five to six minutes, also while the fire is off and its display reads OFF **J**; G's README has its handset report only while it shows APP. When a handset stops sending, its last reading stays for about 90 minutes before `0666` **G** |
| 32-35 | Target temperature x10 | `00C8` = 20.0 |
| 36- | Name | ASCII as hex, padded with `FF` (zeros on the module measured here) |

A status frame read from a `mmWiFiBoxV2` with the fire off: **J**

```
0303000000 03 47 00 8003 00 00 0 0 00 0666 00C8 0000…  043E01
header     id |  |  |    |  |  |   |  |    target 20.0
              |  |  |    |  |  |   |  room: no reading
              |  |  |    |  |  |   flags
              |  |  |    |  |  mode: manual
              |  |  |    |  fan level
              |  |  |    light level
              |  |  state word
              |  burner output
              setup state
```

With a handset reporting, the state word has the handset bit as well and the room temperature reads,
for instance, `00FA`: 25.0. **J**

### Setup state

In the vendor apps these are feature bits, in the order fan, light, aux, LED 0, LED 1, cloud, setup
complete, timer. **D** Three values are known: `47` on the module measured here **J**, `C6` on a
Gazco **G** and `5C` on a Valor. **A** With fan as the lowest bit, all three have "setup complete",
the Gazco has light, aux and timer, and the Valor has aux and both LEDs, which its app asks for.
That fits what is known of those fireplaces, but nobody has confirmed the order.

### State word

| Bit | Name in the vendor apps | Meaning |
|---|---|---|
| `0x8000` | receiver connected | The module has its radio link to the receiver |
| `0x0200` | handset connected | Set on D's fireplace, never on G's although its handset works. On the module measured here it is set while a handset reports and clear while none does **J**. A room temperature other than `0666` is the better sign |
| `0x0100` | shutting down | |
| `0x0080` | pilot | Set whenever the pilot burns: fire on, and standby |
| `0x0040` | fan | |
| `0x0010` | igniting | |
| `0x0008` | aux | Secondary burner enabled; stays set in standby and with the fire off |
| `0x0004` | light | |
| `0x0002` | faulted | A fault is stored. It stays set until the error is cleared in the app **G**. `8003` was read from a fireplace that was off and whose handset was not reporting (room temperature `0666`); the bit was still set twenty minutes after a handset reported again **J** |
| `0x0001` | module connected | |

Read the word as 16 bits. Older code padded it to 8, which shifts every bit whenever the top bit is
clear. **D**

### What state the fireplace is in

In this order: **D**

1. `0x0100` set: **shutting down**.
2. `0x0010` set: **igniting**.
3. `0x0080` clear: **off**. The burner output says nothing here: a cold fireplace can report `FF`.
4. Burner output above `40`: **on**. Otherwise **standby** (pilot only).

A Valor shows the same bits. In two ignitions the igniting bit was set for 19 and 24 seconds and
cleared in the frame in which the pilot bit came on. After an off the pilot bit stayed for about 20
seconds, and `0x0100` cleared in the same frame as it. The aux bit followed the secondary burner
commands. **A**

The receiver bit `0x8000` drops for 20 to 30 seconds during every ignition and shutdown, and the
frames sent meanwhile are unreliable: the pilot bit and the burner output come and go. **D** Most
such frames measured still had the igniting bit (`021A`, `001B`, `001D`) or the shutting-down bit
(`0183`, `01C7`). **D G** Two seen late in an ignition, `028A` and `008A`, had neither. **D**

What this integration makes of that:

- A frame without the receiver bit is not taken over; the last frame that had it stays in force. A
  module that has never shown the bit is not judged on it.
- An **ignition** counts as under way until 60 seconds after its last sign: the ignite command, a
  frame with the igniting bit (with or without the receiver bit), or a frame without the receiver
  bit while igniting. Until then the fireplace reads as igniting whatever the box reports. That
  covers the fire that is lit but has to hold, and the "off" the receiver reports between two of
  its own attempts (see the table below). Only the flame height and the pilot flame that are shown
  follow the reports meanwhile: for most of that minute the fire burns.
- A fire that reads lit where it read off a poll before was lit with the handset between two polls.
  It gets the same 60 seconds.
- A **shutdown** counts as under way for 20 seconds after an acknowledged off command, and the
  count starts again with every frame that lacks the receiver bit or has the shutting-down bit.
  A frame with the receiver bit that reads off ends it.
- Frames without the receiver bit cannot keep either going for ever: an ignition ends at the latest
  180 seconds after its last certain sign (the command, or a frame with both the receiver and the
  igniting bit), a shutdown 90 seconds after the acknowledged command.
- An acknowledged off does not end an ignition that is under way. The receiver may have ignored
  it, and "off" is also what it reports between two attempts; only the ignition's time running out
  settles it.
- Once the receiver bit has been missing for 45 seconds, or the box has answered `E101` for that
  long, the link counts as lost, whatever the reason.

Frames from a relight on which the pilot only held at the third try: **D**

| Output | State word | Reads as |
|---|---|---|
| `00` | `820A` | off |
| `00` | `821A` | igniting |
| `00` | `021A` | unreliable, link down |
| `FF` | `828A` | on |
| `FF` | `028A` | unreliable, link down |
| `00` | `820A` | off: the pilot went out, the receiver tries again |

A session on the `mmWiFiBoxV2`, one frame every 5 seconds: **J**

| Asked for | Output | State word | |
|---|---|---|---|
| Ignite (`1A`) | `FF` | `808B` | As first read, 90 seconds after the command: burning, secondary burner on |
| Flame step 6 (`16B9`) | `B5` | `808B` | |
| Flame step 1 (`1680`) | `FF`, then `80` | `808B` | Full for one frame before the lowest |
| Standby (`1600`) | `00` | `808B` | The pilot bit stays |
| Flame step 12 (`16FF`) | `FF` | `808B` | Burning again within 8 seconds, without an ignition |
| Secondary burner off (`2000`), on (`2001`) | `FF` | `8083`, `808B` | |
| Eco (`B301`) | `B8` | `808B` | Mode `2`; the output moved within 5 seconds |
| Manual (`B0`) | `B8` | `808B` | Mode `0`; the output stayed |
| Secondary burner off, then off (`10`) | `FF`, then `00` | `8183` | Shutting down, pilot bit still set |
| | `00` | `800B` | Off after 15 to 20 seconds, and the aux bit is back |

The receiver bit was set in every frame of that session, the shutdown included.

## Burner output

The handset has 12 flame steps. Their outputs are `80 8B 97 A2 AE B9 C5 D0 DC E7 F3 FF`. **O V**

The output is one continuous byte, and thermostat and eco mode move it freely between the steps, so
a reading is mapped to the nearest step. Measured values: **D**

| Situation | Output |
|---|---|
| Off, igniting, shutting down | `00` |
| Standby | `00`, later `20` |
| Lowest real flame seen (handset "flame wave") | `69` |
| Lowest and highest manual step | `80` and `FF` |

The Valor app sets any output from `80` to `FF`, not only the twelve steps, and that Valor reported
`76` and `7A` while it burned, which the app had not set. **A** Step 6, sent as `B9`, read back as
`B5`, and after the lowest step was asked for the output read `FF` for a moment before `80`. **J**

## Light

The vendor app's slider sends levels `66` to `FF`. **D** On a Gazco fire the levels `63` and `66`
leave the light dark, `77` is very dim, and above `CC` little changes. **G** This integration spreads
brightness over `77` to `FB` and clamps what it reads back to that range. A light whose level read
`00` came on with `3001` at level `80`. **J**

## Timing

Measured on a Gazco fire: **G**

- A command sent before the previous one was acknowledged (within about a second) was answered with
  `E101` in 12 of 13 cases, and once the receiver stayed lost for 90 minutes. This integration waits
  up to 3 seconds for the acknowledgement and then 2 seconds before the next command.
- Send nothing for about a minute while the fireplace ignites. A command sent 2 seconds after the
  ignite was answered with `E101` every time.
- A secondary burner command sent 2 seconds after a change of the burner output was refused while
  the valve moved. This integration sets the secondary burner first and the flame second, and
  otherwise waits 10 seconds after a flame change.
- An ignite sent in the first frame that showed the fire out, 25 seconds after the off command, was
  acknowledged and ignored; 35 seconds later it worked. This integration refuses to ignite until the
  fire has read off for 15 seconds.

Status requests are not control commands and can be sent at any time. A reply took at most 0.6
seconds in the captures of the Valor app **A** and under 0.2 seconds on the `mmWiFiBoxV2` with the
fire off. **J**

### What this integration sends, and when

- **Ignite** only to a fireplace that reads off, with its status read a moment before, and never
  twice: a second ignite could restart an ignition under way. From the moment the command is handed
  to the connection the fireplace counts as igniting, also if no acknowledgement or an `E101` comes
  back. The command may have arrived all the same, and a stray `E101` can precede the real answer.
- **Off** always, whatever the state and the receiver bit say: turning off must not depend on a
  reading being right. It counts as obeyed only when a frame with the receiver bit, read after the
  command, has the shutting-down bit, or reads off with no ignition under way and at least 20
  seconds after the command (an ignition started with the handset a moment before shows late).
  Until then the command is sent again after a poll, at most every 10 seconds, for 5 minutes. It is
  not repeated into a missing receiver bit, unless the bit has been missing for 45 seconds.
- **Burner output, secondary burner, eco, thermostat** only while the fireplace reads on or standby.
- **Light and manual mode** not while it ignites or shuts down.
- Nothing but off while the receiver bit is missing: the box refuses it then, and commands sent at
  such moments are what cost a receiver for 90 minutes.

The state is looked at once the command has its turn on the line, so a flame command cannot slip in
behind an off that was on its way.

An `E101` counts as the answer only if no acknowledgement follows within a second. A status frame
is never an answer to a command: boxes push those unasked, and one must not make a refused command
look carried out. A command that brought nothing but status frames in 3 seconds is taken as sent,
in case there are boxes that do not acknowledge, but not as carried out.

Every command except ignite sets an absolute state, so sending it twice does no harm.

## Device information

The answer to command `01` has 110 characters after the command id while no handset reports and 130
while one does **J**; A's has 130. **A** Character positions after STX, as for the status frame:

| Chars | Content |
|---|---|
| 12-25 | `00540000000005` on both |
| 26-37 | The MAC address of the module |
| 38-43 | `160205` here and `170116` on A's, which may be a date |
| 44-53 | Zeros |
| 54-55 | `5A` here, `F0` on A's |
| 56-69 | The ASCII text `88.p131` on both, which looks like a firmware version |
| 70-75 | Zeros |
| 76-83 | `B844402C` on both |
| 84-113 | Zeros |
| 114-119 | Zeros while no handset reports. With one, `3600FF` here **J** and `1D00FF` on A's |
| 120-139 | Only there while a handset reports: its part number as ASCII, such as `B6R-H8TV4P` **G** or `B6R-HATV4P` **A** |
| last 2 | `00` |

The text at 120-139 is the part number of the handset, cut to ten characters: the module only sends
it while a handset reports, and it matches the label on the handset. **J** G gives it as the part
number of the receiver. **G** The integration reads none of these fields; it keeps the reply for its
diagnostics download, with the MAC address removed.

## What is not known

- Whether everything above holds on fireplaces other than the four measured. Reports are welcome as
  an [issue](https://github.com/jkfran/mertik-fireplace-wifi-ha/issues): the integration's
  diagnostics download contains the last status frame and the device information reply, with the MAC
  address removed.
- Whether any of it holds on the newest module. The vendor app's setup guide tells three generations
  apart by part number: B6R-W… (V1), B6R-W2… (V2) and B6R-W3… (V3), which the app finds over
  Bluetooth during setup. Every module whose part number was reported is a V1 or a V2.
- The fan. The apps have a command id `40` and the status frame has a fan bit and a fan level, but
  nobody has documented the payload from a fireplace with a fan. The integration only reports the
  two status fields, as diagnostic entities that are disabled by default.
- The flags at chars 26-27 and the bits of the setup state.
- The fields after the name. The vendor apps read an icon, the WiFi signal, the handset mode, pilot
  and burner voltages and the handset signal there. **D** The `mmWiFiBoxV2` ends its frame with three
  bytes after a 32-byte name: `04`, a value that changes from one read to the next (`3E` to `47`
  seen), and `01`. **J** A's module ends the same way, with the middle value between `3F` and `4D`.
  **A** That fits icon, WiFi signal and handset mode, but nobody has confirmed it.
- Whether `B2FD` alone changes the target without entering thermostat mode.
- What a module does with a light level between the ones the app's slider can send.

## Other commands

From the original notes in this repository; not used by the integration. **O**

**Clock, command `06`.** Payload `FE` plus the date and time to set it, `FF` to read it. The date and
time are seven values of two hex characters each: year (without the century), month, day, weekday
(1 Monday to 7 Sunday), hour, minute, second. `2023-01-21 22:14:47`, a Saturday, is
`17 01 15 06 16 0E 2F`.

**Settings, command `D1`.** Carries the icon shown in the app (`00` oven, `01` single bed, `02`
double bed, `03` chair, `04` couch), the name of the fireplace, and a feature mask with bits for
timer, fan, light and aux. The exact layout was never worked out.
