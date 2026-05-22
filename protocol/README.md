# DigiTech RP360XP — Communication Protocol Reference
## Part 1: Host → Device (Nexus/PC side)

> **Status**: Reverse-engineered by serial MitM capture (May 2026).  
> **Connection**: USB virtual COM port — VID:PID `1210:0032` — 115200 baud, 8N1.  
> **Not MIDI, not HID** — pure serial framing over USB CDC.

---

## 1. Frame Format

Every message exchanged on the serial link — in both directions — follows the same binary framing:

```
┌────┬────┬────┬────┬────┬────┬────┬────┬──────────────┬────┐
│ 55 │ LL │ LL │ TT │ S1 │ S1 │ S2 │ S2 │  JSON payload │ CC │
└────┴────┴────┴────┴────┴────┴────┴────┴──────────────┴────┘
  [0]  [1]  [2]  [3]  [4]  [5]  [6]  [7]   [8 … n-1]   [n]
```

| Field | Size | Description |
|-------|------|-------------|
| `0x55` | 1 byte | Sync byte — constant, marks start of every frame |
| `LL LL` | 2 bytes | Payload length, **little-endian**. Counts bytes from `[3]` to `[n-1]` inclusive (i.e. `TT + S1 + S1 + S2 + S2 + JSON`). Total frame size = `LL + 3`. |
| `TT` | 1 byte | Frame type (see table below) |
| `S1 S1` | 2 bytes | Host sequence counter, **little-endian 16-bit**. Incremented by host for each new request (`b[4]=0x00`, `b[5]=N`). |
| `S2 S2` | 2 bytes | Device sequence counter, **little-endian 16-bit**. Set by device in responses; echoed by host in ACKs. |
| JSON | 0–N bytes | UTF-8/ASCII JSON payload (array format, no terminator). May be empty. |
| `CC` | 1 byte | Checksum: `(256 − sum(b[1 … n-1])) mod 256` |

### Frame Types

| `TT` | Direction | Meaning |
|------|-----------|---------|
| `0x43` | Host → Device | **Request** — carries a JSON command |
| `0x42` | Device → Host | **Response** — carries a JSON reply |
| `0x41` | Device → Host | **Response** (split / continuation) |
| `0x02` | Host → Device | **ACK** — acknowledges a device response (no JSON payload) |
| `0xF4` / various | Device → Host | **Chunk header** — marks the start of a JSON data segment within a streaming response (see §6) |

### Checksum

```python
def checksum(frame_bytes):
    # frame_bytes = complete frame including 0x55 header
    return (256 - sum(frame_bytes[1:-1])) % 256
```

The checksum covers bytes `[1]` through `[n-1]` (everything except the sync byte and the checksum itself).

### ACK Frame (host → device)

When the device sends a response, the host must acknowledge it:

```
55 06 00 02  SD_HI SD_LO  00 42  CC
```

`SD_HI SD_LO` are the two sequence bytes from the device response being acknowledged (`b[4]` and `b[5]` of the response frame). `0x42` in `b[7]` appears to be a constant flag in ACK frames.

---

## 2. JSON Command Format

All JSON payloads are **arrays**. There are several command verbs:

### Host → Device commands

| Verb | Pattern | Description |
|------|---------|-------------|
| `"rp"` | `["rp", SEQ, "path"]` | **Read parameter** — request a value |
| `"rc"` | `["rc", SEQ, "path"]` | **Read content** — request a full object (e.g. preset) |
| `"ssc"` | `["ssc", SEQ, "path", VALUE]` | **Set / store content** — write a value or object |
| `"sp"` | `["sp", SEQ, "path", VALUE]` | **Set parameter** — write a single parameter |
| `"mc"` | `["mc", SEQ, "src", "dst"]` | **Move/copy** — load or save a preset slot |
| `"sbs"` | `["sbs", SEQ, "", 1]` | **Subscribe** — sent once during init (purpose: event subscription) |

### Device → Host responses

| Verb | Pattern | Description |
|------|---------|-------------|
| `"rpr"` | `["rpr", DEV_SEQ, HOST_SEQ, VALUE]` | Response to `"rp"` |
| `"rcr"` | `["rcr", DEV_SEQ, HOST_SEQ, {object}]` | Response to `"rc"` (may be chunked) |
| `"ack"` | `["ack", DEV_SEQ, HOST_SEQ]` | Acknowledgement of `"ssc"`, `"sp"`, or `"mc"` |
| `"np"` | `["np", DEV_SEQ, "path", VALUE]` | **Unsolicited notification** — device-initiated (e.g. footswitch press) |

### Sequence numbers

Two independent counters run in parallel:

- **Host sequence** (`b[5]` of request frame, also `HOST_SEQ` in JSON): starts at 0 at each Nexus session, incremented by 1 for each new request.
- **Device JSON sequence** (`DEV_SEQ` in JSON): a persistent counter on the device, survives power cycles, starts wherever it left off.
- **Device frame sequence** (`b[4:6]` of response frames): a separate persistent frame-level counter, also survives power cycles.

---

## 3. Initialization Sequence

Sent by Nexus immediately after opening the COM port:

```
> ["rp",   0, "STATE"]
< ["rpr",  N, 0, 0]

> ["rp",   1, "VERSION"]
< ["rpr",  N, 1, 16973824]          ← firmware version as integer

> ["sbs",  2, "", 1]                ← subscribe (event notifications)
< ["ack",  N, 2]

> ["rp",   3, "system/SYNC"]
< ["rpr",  N, 3, "96B5698274E44742..."]   ← sync token (hash string)

> ["rp",   4, "banks/user/0/name"]
< ["rpr",  N, 4, "My"]
> ["rp",   5, "banks/user/1/name"]
< ["rpr",  N, 5, "My blues/rock"]
...
> ["rp", 102, "banks/user/98/name"]
< ["rpr",  N, 102, "Best Solo"]     ← reads all 99 user preset names

> ["rp", 103, "system/LAST PRES"]
< ["rpr",  N, 103, 23]              ← index of last active preset

> ["rc", 104, "preset"]             ← read current preset (streaming, see §6)
< (chunked binary response)

> ["rp", 105, "system/PRESETDIRTY"]
< ["rpr",  N, 105, 0]               ← 0 = clean, non-zero = unsaved changes
```

**Notes:**
- The 99 user preset name reads (indices 4–102) are pipelined: Nexus sends multiple requests without waiting for each response.
- Factory preset names are **not** read at startup — only user preset names.
- `VERSION` returns `16973824` = `0x01030000` → firmware version `1.3.0.0`.

---

## 4. Preset Navigation

### Load a user preset

```
> ["mc", SEQ, "banks/user/N", "preset"]
> ["rc", SEQ, "preset"]                  ← read the now-active preset (streaming, see §6)
> ["rp", SEQ, "system/PRESETDIRTY"]
< ["rpr", ..., SEQ, 0]
```

`N` is zero-based (UI slot 1 = index 0).

### Load a factory preset

```
> ["mc", SEQ, "banks/factory/N", "preset"]
> ["rp", SEQ, "system/PRESETDIRTY"]
< ["rpr", ..., SEQ, 0]
```

Factory presets: no `["rc", ...]` — Nexus does **not** read back the preset content after loading a factory preset.

### `"mc"` argument order

| Order | Meaning |
|-------|---------|
| `["mc", SEQ, "banks/user/N", "preset"]` | **Load** slot N into active preset |
| `["mc", SEQ, "preset", "banks/user/N"]` | **Save** active preset to slot N |

The direction of the copy follows the argument order: `src → dst`.

---

## 5. Preset Modification

### Set a single parameter

```
> ["sp", SEQ, "preset/fxc/SLOT/PARAM", VALUE]
< ["ack", ...]
```

Or using the relative path form seen in some contexts:
```
> ["ssc", SEQ, "../../fxc/SLOT/fx/PARAM", VALUE]
```

### Enable / disable an effect slot

```
> ["sp",  SEQ, "preset/fxc/3/ENABLE", 0]   ← bypass slot 3
> ["sp",  SEQ, "preset/fxc/3/ENABLE", 1]   ← enable slot 3
< ["ack", ...]
```

### Device-initiated toggle (footswitch)

The device sends unsolicited notifications when the user presses a footswitch:

```
< ["np", DEV_SEQ, "preset/fxc/7/ENABLE", 1]   ← footswitch enabled slot 7
> (ACK)
```

### Rename a preset (in memory)

```
> ["sp", SEQ, "preset/name", "new name"]
< ["ack", ...]
```

### PRESETDIRTY flag

`"system/PRESETDIRTY"` returns an integer, not a boolean:
- `0` = preset is clean (matches stored version)
- Non-zero = preset has unsaved changes (value observed: `40`)

---

## 6. Reading a Preset (streaming response)

Preset content responses (`"rcr"`) are delivered as a **continuous byte stream** on the serial link, not as self-contained framed packets. The JSON payload is segmented into chunks by the device's serial buffer, with each segment prefixed by a 10-byte header.

### Request

```
> ["rc", SEQ, "preset"]           ← read active preset
> ["rc", SEQ, "banks/user/N"]     ← read a specific slot (used during backup)
```

During a full backup, multiple `"rc"` requests are **pipelined** — the host sends several requests without waiting for each response. The device interleaves the responses in the serial stream.

### Stream structure

Each `"rcr"` response is delivered as one or more segments. Each segment has the form:

```
55 00 01 TT  H4 H5 H6 H7  00 00  [JSON bytes …]  CC
│            │              │     │               │
│            └── 6 bytes    │     └── JSON part   └── 1-byte checksum
│                header     └── 2-byte prefix (always 0x00 0x00)
└── sync + len=256 (LE) + type
```

| Field | Value | Notes |
|-------|-------|-------|
| `55 00 01` | constant | Marks the start of every segment |
| `TT` | `0xF4` for first and full segments; varies for last segment | The type byte of continuation/last segments varies; it is **not** a checksum of the payload |
| `H4..H7` | `00 42 HH LL` | `HH LL` is a monotonically increasing global chunk counter on the device |
| `00 00` | constant | 2-byte padding prefix before the JSON content |
| JSON bytes | variable | Portion of the `["rcr", ...]` JSON array |
| `CC` | 1 byte | Checksum of the entire message: `(256 − sum(all_bytes_from_[1]_to_last_JSON_byte)) % 256` |

**Full segments** (when the JSON portion is ~495 bytes) have `len=256` in the frame header (total = 259 bytes). The `CC` byte at the end of a full segment is the checksum of that segment's contribution — it appears in the stream **immediately before** the `55 00 01` marker of the next segment, and must be **discarded** during reassembly.

**Last segment** has a shorter payload and its `CC` is the final checksum of the complete message.

### Interleaved frames

During pipelined backup, other device frames (short ACKs, `"rpr"` responses) appear interleaved in the stream between segments of a `"rcr"` response. These are standard framed messages starting with `55 LL LL TT` where `len < 256`; they must be skipped during reassembly.

### Reassembly algorithm

```python
def extract_rcr(stream, start_pos):
    """
    Extract and reassemble a ["rcr", ...] JSON message from the raw device stream.
    start_pos: byte offset of the '[' of ["rcr" in the stream.
    Returns the complete JSON string.
    """
    json_bytes = bytearray()
    pos = start_pos
    in_string = False
    escape_next = False
    bracket_depth = 0

    while pos < len(stream):
        b = stream[pos]

        # Detect any protocol frame header: 0x55 LL LL TT ...
        if b == 0x55 and pos + 3 < len(stream):
            plen = stream[pos+1] | (stream[pos+2] << 8)
            flen = plen + 3

            if plen == 256:
                # Full preset segment: discard the checksum byte just added,
                # skip the 10-byte segment header, continue with JSON content.
                if json_bytes:
                    json_bytes.pop()          # remove preceding CC byte
                pos += 10                     # skip: 55 00 01 TT H4 H5 H6 H7 00 00
                continue

            if plen < 256 and flen < 300:
                # Short interleaved frame (ACK, rpr, etc.): skip entirely.
                if json_bytes:
                    json_bytes.pop()          # remove preceding CC byte
                pos += flen
                continue

        # Track JSON structure to detect the end of the message
        c = chr(b) if 32 <= b < 128 else None
        if escape_next:
            escape_next = False
        elif c == '\\' and in_string:
            escape_next = True
        elif c == '"':
            in_string = not in_string

        if not in_string:
            if c in ('[', '{'):
                bracket_depth += 1
            elif c in (']', '}'):
                bracket_depth -= 1
                if bracket_depth == 0:
                    json_bytes.append(b)
                    return json_bytes.decode('ascii')

        json_bytes.append(b)
        pos += 1

    return json_bytes.decode('ascii')
```

The resulting JSON has the form `["rcr", DEV_SEQ, HOST_SEQ, {preset object}]`. The preset object structure is described in §9.

---

## 7. Saving a Preset

### Quick Store (overwrite current slot)

```
> ["rp",  SEQ, "system/PRESETDIRTY"]
< ["rpr", ..., SEQ, VALUE]               ← check if dirty (non-zero = modified)

> ["mc", SEQ, "preset", "banks/user/N"]  ← save active preset to slot N
< ["ack", ...]

> ["mc", SEQ, "banks/user/M", "preset"]  ← reload same slot (confirm)
> ["rc", SEQ, "preset"]                  ← re-read preset content
> ["rp", SEQ, "system/PRESETDIRTY"]
< ["rpr", ..., SEQ, 0]
```

If `PRESETDIRTY` is 0, Nexus does nothing (no store performed).

### Store New (save to a different slot with a new name)

```
> ["rp", SEQ, "system/PRESETDIRTY"]
< ["rpr", ..., SEQ, VALUE]

> ["sp",  SEQ, "preset/name", "new name"]   ← rename in memory first
< ["ack", ...]

> ["mc", SEQ, "preset", "banks/user/N"]     ← save to target slot N
< ["ack", ...]
```

---

## 8. Backup and Restore

### Export all banks (full backup)

Nexus reads all 99 user presets sequentially:

```
> ["rc", SEQ,   "banks/user/0"]
> ["rc", SEQ+1, "banks/user/1"]   ← requests are pipelined
...
> ["rc", SEQ+98, "banks/user/98"]
< (streaming responses, interleaved — see §6)
```

The resulting data is saved locally as a `.rp360b` file (see §10).  
**No device interaction is needed for export** — Nexus exports from its local cache if the data is already loaded.

### Import all banks (full restore)

Each preset is sent one at a time using `"ssc"` with a path of `"banks/user"` and a JSON object keyed by slot index:

```
> ["ssc", SEQ,   "banks/user", {"0":  {preset JSON}}]   ← sent in 249-byte chunks
< ["ack", ..., SEQ]

> ["ssc", SEQ+1, "banks/user", {"1":  {preset JSON}}]
< ["ack", ..., SEQ+1]
...
> ["ssc", SEQ+98, "banks/user", {"98": {preset JSON}}]
< ["ack", ..., SEQ+98]
```

### Export single preset

No serial communication — Nexus exports from local memory. Output is a `.rp360p` file (see §10).

### Import single preset (to active slot)

```
> ["ssc", SEQ, "", {"preset": {preset JSON}}]   ← empty path = active preset
< (chunked, multiple frames)

> ["rp", SEQ, "system/PRESETDIRTY"]
< ["rpr", ..., SEQ, 40]                          ← non-zero after import
```

---

## 9. Preset JSON Structure

```json
{
  "preset": {
    "name": "Preset Name",
    "PRS LEVL": 78,
    "FACTMODIFY": 1,
    "fxc": {
      "0": { "ENABLE": 0, "fx": { "name": "wah.CRY WAH",   "PEDAL": 0, "WAH LEVL": 6 } },
      "1": { "ENABLE": 0, "fx": { "name": "cmpr.DIGICOMP", "LEVEL": 70, "SUSTAIN": 50, "TONE": 50, "ATTACK": 0 } },
      "2": { "ENABLE": 0, "fx": { "name": "dist.SCREAMER", "DRIVE": 50, "TONE": 70, "LEVEL": 50 } },
      "3": { "ENABLE": 1, "fx": { "name": "amp.MASTRVOL",  "CABINET": 11, "GAIN": 99, "LEVEL": 77, "BASS": 45, "MID": 45, "TREBLE": 45 } },
      "4": { "ENABLE": 0, "name": "eq.EQ", "LOW LEVL": 12, "LOW FREQ": 9, "LOW BW": 1, "MID LEVL": 15, "MID FREQ": 35, "MID BW": 1, "HIGHLEVL": 10, "HIGHFREQ": 15, "HIGH BW": 1 },
      "5": { "ENABLE": 1, "fx": { "name": "gate.GATE",     "THRESHLD": 30, "ATTEN": 25, "ATTACK": 0, "RELEASE": 0 } },
      "6": { "name": "vol.VOLUME", "VOLUME": 99 },
      "7": { "ENABLE": 0, "fx": { "name": "mod.DETUNE",    "SHIFT": 12, "LEVEL": 99 } },
      "8": { "ENABLE": 0, "fx": { "name": "dly.ANALOG",    "TIME": 340, "REPEATS": 25, "DLY LEVL": 35, "TAP DIV": 3 } },
      "9": { "ENABLE": 1, "fx": { "name": "rvb.LEX ROOM",  "DECAY": 75, "LIVENESS": 50, "PREDELAY": 1, "RVB LEVL": 30 } }
    },
    "ctrls": {
      "treadle":    { "LNK": "../../fxc/6/VOLUME",    "MIN": 0, "MAX": 99 },
      "altTreadle": { "LNK": "../../fxc/0/fx/PEDAL",  "MIN": 0, "MAX": 99 },
      "ctrlVSw":    { "LNK": "../../fxc/0/ENABLE" },
      "ctrlA":      { "LNK": "../../fxc/7/ENABLE" },
      "ctrlB":      { "LNK": "../../fxc/8/ENABLE" },
      "ctrlC":      { "LNK": "../../fxc/9/ENABLE" },
      "lfo1":       {}
    }
  }
}
```

**Effect slots** (`fxc/0` … `fxc/9`):

| Slot | Role |
|------|------|
| 0 | Wah / expression |
| 1 | Compressor |
| 2 | Distortion / overdrive |
| 3 | Amp + cabinet |
| 4 | EQ (special structure — no `fx` sub-object) |
| 5 | Noise gate |
| 6 | Volume pedal (no `ENABLE`, no `fx`) |
| 7 | Modulation |
| 8 | Delay |
| 9 | Reverb |

**Effect model name format**: `"category.MODELNAME"` (e.g. `"amp.800 JCM"`, `"dist.SCREAMER"`, `"rvb.LEX HALL"`).

**`FACTMODIFY`**: integer indicating how many factory preset parameters have been modified (0 = unmodified factory preset).

**`ctrls` links**: use relative paths (`../../fxc/N/...`) that resolve from the `ctrls` object up to the preset root, then down to the target parameter.

---

## 10. File Formats

### `.rp360p` — Single preset

Plain JSON file, directly the preset object (without the `"preset"` wrapper):

```json
{
  "name": "Rock Stack",
  "PRS LEVL": 78,
  "FACTMODIFY": 1,
  "fxc": { ... },
  "ctrls": { ... }
}
```

### `.rp360b` — Full bank backup

99 preset JSON objects (same format as `.rp360p`), concatenated and separated by `##`:

```
{ "name": "Preset 0", ... }
##{ "name": "Preset 1", ... }
##{ "name": "Preset 2", ... }
...
##{ "name": "Preset 98", ... }
```

Note: the `##` separator has **no** newline before `{` — parsing must split on `\n##` or `##` at the start of a line.

---

## 11. Options / Firmware Query

When the user opens the Options dialog in Nexus:

```
> ["rp", SEQ, "VERSION"]
< ["rpr", ..., SEQ, 16973824]
```

`16973824` = `0x01030000` → firmware `1.3.0.0` (big-endian byte interpretation: `01 03 00 00`).

---

## 12. Session Close

When Nexus is closed, it sends a clean termination sequence (exact content to be documented — observed to complete normally even if a prior session ended abruptly, suggesting stateless reconnection).

---

## 13. Known Unknowns

The following areas are **not yet documented** and are targets for Part 2 (Device-initiated) and Part 3 (Effect model catalogue):

| Area | Status |
|------|--------|
| Checksum verification of full streaming response | Algorithm identified; full validation pending |
| `"sbs"` command semantics | Unknown — likely event subscription |
| Device-initiated `"np"` notification full path catalogue | Partial (ENABLE observed) |
| Factory preset content reading | Not captured (Nexus doesn't read it) |
| Effect model list / parameter ranges | Unknown — possibly device-provided |
| Expression pedal / LFO assignment commands | Not yet captured |
| Stompbox mode commands | Not yet captured |
| Delete / reorder effects in chain | Not yet captured |
| Error / NACK responses from device | Not yet observed |
| Reconnection handshake (device-side) | Not yet captured |

---

*Captured and analysed: May 2026. Contributions welcome.*
