# Mertik Maxitrol myfire WiFi Box — Wire Protocol

Reverse-engineered from multiple sources:
- **Primary**: PCAPdroid packet capture of the Android myfire app
  (`com.iqontrol.mertik`) against a B6R-H8TV4PB receiver
- **Community**: [erdebee/homey-mertik-wifi](https://github.com/erdebee/homey-mertik-wifi)
  and [rbrondgeest/homey-mertik-wifi](https://github.com/rbrondgeest/homey-mertik-wifi)
  (Homey platform, JavaScript source)
- **Community**: [tritter/homebridge-mertik-fireplace](https://github.com/tritter/homebridge-mertik-fireplace)
  (Homebridge platform, TypeScript source)

---

## Transport

| Property | Value |
|---|---|
| Protocol | **TCP** |
| Port | **2000** |
| Connection | Persistent (one client at a time — the device drops previous client when a new one connects) |

---

## Packet format

All packets begin with a fixed **11-byte prefix** followed by a command
payload and terminated by `0x03` (ASCII ETX). The prefix and commands
are transmitted as raw bytes (not hex-encoded text).

```
Prefix (11 bytes):  02 33 30 33 30 33 30 33 30 38 30
Command payload:    varies by command (see table below)
Terminator:         03
```

Some commands (aux on/off) are additionally followed by `0x0A` (LF).

---

## Command table

All values are the **command payload bytes** appended after the prefix.
The device echoes a short acknowledgement for each command received.

| Command | Payload (hex) | ASCII equiv | Notes |
|---------|--------------|-------------|-------|
| Status poll | `30 33 03` | `03\x03` | Request current status |
| **APP mode** | `30 31 03` | `01\x03` | Puts WiFi box into app mode; device responds with model/firmware info |
| Ignite / ON | `31 41 03` | `1A\x03` | |
| Guard flame OFF | `31 30 03` | `10\x03` | Full off including pilot |
| Standby / pilot | `31 36 30 30 03` | `1600\x03` | |
| ECO mode | `42 33 30 31 03` | `B301\x03` | |
| Manual mode | `42 30 03` | `B0\x03` | Exit ECO or thermostat |
| Aux / rear burner ON | `32 30 30 31 03 0A` | `2001\x03\n` | |
| Aux / rear burner OFF | `32 30 30 30 03 0A` | `2000\x03\n` | |
| Light ON | `33 30 30 31 03` | `3001\x03` | |
| Light OFF | `33 30 30 30 03` | `3000\x03` | |
| Flame height | `31 36 <VV> 03` | `16{VV}\x03` | VV = 2-char ASCII hex (see table) |
| Light brightness | `33 30 46 45 <BB><BB> 03` | `30FE{BB}{BB}\x03` | BB = brightness code (see below) |
| **Thermostat** | `42 31 <TT> 03` | `B1{TT}\x03` | TT = temp in 0.5°C steps (see below) |

### Flame height codes

12 hardware steps, encoded as 2 ASCII hex characters:

| Step | Code | Raw byte |
|------|------|----------|
| 1 (min) | `38 30` = "80" | 0x80 = 128 |
| 2 | `38 42` = "8B" | 0x8B = 139 |
| 3 | `39 37` = "97" | 0x97 = 151 |
| 4 | `41 32` = "A2" | 0xA2 = 162 |
| 5 | `41 45` = "AE" | 0xAE = 174 |
| 6 | `42 39` = "B9" | 0xB9 = 185 |
| 7 | `43 35` = "C5" | 0xC5 = 197 |
| 8 | `44 30` = "D0" | 0xD0 = 208 |
| 9 | `44 43` = "DC" | 0xDC = 220 |
| 10 | `45 37` = "E7" | 0xE7 = 231 |
| 11 | `46 33` = "F3" | 0xF3 = 243 |
| 12 (max) | `46 46` = "FF" | 0xFF = 255 |

The status packet flame field is decoded as:
`step = round((raw - 128) / 128 * 12) + 1` giving values 1–13
(13 for the maximum 0xFF, matching the device's own reporting).

**Note:** The status packet flame field always reports the post-ignition
baseline (~0x8F = step 2) regardless of `set_flame_height` commands.
Flame height is therefore tracked locally from commands, confirmed by
device ACK and audible beep.

### Light brightness codes

Brightness is encoded as a 2-character ASCII hex value, sent **twice**
(e.g. `6363` for minimum). Range: `36 33` ("63") to `46 42` ("FB").

Mapping from HA brightness (0–255):
```
normalized = (brightness - 1) / 254 * 100
level = 36 + round(normalized / 100 * 8)
if level >= 40: level += 1   # device skips 40
code = f"{level:02d}"        # sent as 2-char ASCII, repeated twice
```

### Thermostat temperature encoding

Range 5.0–36.0 °C in 0.5 °C steps. Encoding:
```
byte_value = round(temp_C * 2)   # half-degree units
TT = f"{byte_value:02X}"         # 2 uppercase ASCII hex chars
```
Example: 21.5 °C → 43 → `"2B"` → payload `42 31 32 42 03`

---

## APP mode handshake

The myfire app sends this sequence on connect to enable full status
reporting and put the handset into APP mode:

1. `CMD_STATUS` — initial status poll
2. `CMD_APP_MODE` (`01\x03`) — device responds with 144-byte device info packet containing model number and firmware version

The device info response starts with `303030300001` and contains the
model string (e.g. `B6R-H8TV4P`) in ASCII.

**Note:** Three additional commands observed in app captures (`50ff00`,
`50ff01`, `C2`) have been omitted — they do not respond within 3 seconds
and their delayed responses corrupt subsequent command/response pairing.
The handshake functions correctly without them.

---

## Status packet

The device sends a status packet in response to every command and on
its own polling cycle. The packet is **108 bytes** for the B6R-H8TV4PB.

After stripping the leading STX byte (`0x02`), parse the remaining ASCII
characters as pairs of hex digits at these offsets:

| Offset | Field | Encoding | Notes |
|--------|-------|----------|-------|
| [0:12] | Prefix | — | Always `303030300003` |
| [12:14] | Config byte | — | Constant per device (e.g. `C6`) |
| [14:16] | ON flag | `FF`=on, `00`=off | Transitional values during ignition |
| [16:20] | Status bits | 16-bit big-endian | See bit table below |
| [18:20] | Flame byte | raw value | `>0x7B` = burner running |
| [20:22] | Light byte | — | `0xCC` constant on B6R-H8TV4PB; not used |
| [22:24] | Constant | — | Always `04`; purpose unknown |
| [24:26] | Mode byte | — | `00`=manual, `20`=thermostatic active |
| [26:28] | Unknown | — | Always `00` in observed packets |
| [28:30] | Handset fault | — | `00`=OK, `06`=F44 (handset not connected) |
| [30:32] | Internal temp | raw / 10 = °C | Near-firebox sensor (~10 °C); **unreliable for room temp** |
| [32:34] | Unknown | — | Always `00` in observed packets |
| [34:36] | Room temp | raw / 10 = °C | e.g. `C8` = 200 → 20.0 °C; unreliable when handset has a fault |
| [36:60] | Room name | ASCII | Name set in myfire app, padded with `0xFF` |

### Status bit field [16:20] (16 bits, numbered from MSB=0)

| Bit | Meaning |
|-----|---------|
| 7 | Shutting down |
| 8 | Guard / pilot flame on |
| 9 | Aux / rear burner on |
| 11 | Igniting |
| 13 | Light on (reliable only when fire is running) |

### Flame byte interpretation

The flame byte at [18:20] is the authoritative indicator of whether the
burner is running:

- `<= 0x7B` (123): burner off (includes transitional values during ignition)
- `> 0x7B`: burner running

**Important:** During ignition the device sends transitional status packets
with flame bytes below the threshold even though the fire is starting.
State tracking must only reset on the **falling edge** (was-on → now-off),
not on any off reading, to avoid spuriously resetting during ignition.

### Temperature

Two temperature fields exist in the status packet:

- **[30:32] Internal temp** — a near-firebox sensor that reads approximately
  10 °C regardless of room temperature. Not useful for thermostatic control.

- **[34:36] Room temp** — populated via the 868 MHz RF link to the handset.
  Reads 0x00 if the handset is not in APP mode. When the handset has a fault
  (e.g. F44 — out of range or low battery), this field may report a meaningless
  value and should not be trusted. The integration discards this value whenever
  `handset_fault [28:30]` is non-zero and no external HA sensor is configured.

### Handset fault

The byte at [28:30] reports handset connectivity:

| Value | Meaning |
|-------|---------|
| `00` | Handset OK |
| `06` | F44 — handset not in range or low battery |

This field does not clear immediately when the handset returns to range; it
reflects the device's internal RF pairing state and may persist for some time.

---

## Sniffing your own device

```bash
# Linux/Raspberry Pi
sudo tcpdump -i any -w mertik.pcap 'tcp port 2000'

# Android (no root required)
# Use PCAPdroid app, target app: com.iqontrol.mertik
```

Open the capture in Wireshark and filter with `tcp.port == 2000`.
