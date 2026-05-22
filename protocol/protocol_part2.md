# DigiTech RP360XP — Communication Protocol Reference
## Part 2: Device → Host (RP360XP side)

> **Status**: Reverse-engineered by serial MitM capture (May 2026).  
> **Scope**: Messages initiated by the RP360XP without a prior host request — physical controls, preset navigation, and session lifecycle.

---

## 1. Overview

The RP360XP sends unsolicited messages to the host in three situations:

| Situation | Verb | Trigger |
|-----------|------|---------|
| Effect toggle (footswitch / toe switch) | `"np"` | User presses a footswitch assigned to an effect slot |
| Preset change (auxiliary footswitch) | `"cm"` | User navigates to next/previous preset |
| Session close | implicit | Nexus sends `["sbs", N, "", 0]`; device ACKs |

The device sends **nothing** when no host is connected. The serial port is silent until the host opens it and sends the init sequence (Part 1 §3).

---

## 2. Cold Boot Behaviour

On USB connection (cold boot), the device:
- Sends **no spontaneous data** — it waits for the host to speak first
- Resets its **DEV_SEQ counter to 0** (the counter is RAM-only, not persisted across power cycles)
- Is immediately ready to respond to `["rp", 0, "STATE"]`

This confirms that **all communication is host-initiated** at the protocol level. The device is purely reactive until the subscription (`["sbs", N, "", 1]`) is sent, after which it begins sending unsolicited `"np"` and `"cm"` notifications.

---

## 3. Effect Toggle Notification (`"np"`)

Sent when the user presses a footswitch or the toe switch on the RP360XP.

### Format

```
← ["np", DEV_SEQ, "preset/fxc/SLOT/ENABLE", VALUE]
```

| Field | Description |
|-------|-------------|
| `DEV_SEQ` | Device sequence counter, incremented for each message |
| `"preset/fxc/SLOT/ENABLE"` | Path to the toggled parameter; `SLOT` = effect chain slot (0–9) |
| `VALUE` | `1` = effect enabled, `0` = effect bypassed — **the resulting state**, not the direction of the press |

### Host response

The host must acknowledge with a standard ACK frame (type `0x02`).

### Example sequence

```
← ["np", 106, "preset/fxc/7/ENABLE", 1]   ← footswitch pressed: slot 7 is now ON
→ (ACK)
← ["np", 107, "preset/fxc/7/ENABLE", 0]   ← footswitch released: slot 7 is now OFF
→ (ACK)
```

Each physical press generates **two messages**: one on press (contact closed) and one on release (contact open). The `VALUE` reflects the **resulting state** of the effect after the toggle — it alternates between 0 and 1 on successive presses of the same switch.

### Footswitch → slot mapping

The mapping between physical footswitches and effect slots is defined in the preset's `ctrls` object (see Part 1 §9):

| Physical control | `ctrls` key | Typical slot |
|-----------------|-------------|-------------|
| Footswitch A (left) | `ctrlA` | `fxc/7` (modulation) |
| Footswitch B (middle) | `ctrlB` | `fxc/2` (dist/OD) or `fxc/8` (delay) |
| Footswitch C (right) | `ctrlC` | `fxc/9` (reverb) |
| Toe switch (expression pedal) | `ctrlVSw` | `fxc/0` (wah) |

The actual mapping is preset-dependent — always read it from `ctrls` in the active preset JSON.

---

## 4. Preset Change Notification (`"cm"`)

Sent when the user navigates to a different preset using the auxiliary footswitch (next/previous preset buttons).

### Format

```
← ["cm", DEV_SEQ, "banks/user/N", "preset"]
```

| Field | Description |
|-------|-------------|
| `DEV_SEQ` | Device sequence counter |
| `"banks/user/N"` | Target preset slot, zero-based index |
| `"preset"` | Constant string — indicates the object type being changed |

### Host response

Upon receiving `"cm"`, Nexus:
1. ACKs the notification
2. Reads the new preset content
3. Checks the dirty flag

```
← ["cm", DEV_SEQ, "banks/user/N", "preset"]
→ (ACK)
→ ["rc",  SEQ,   "preset"]
→ ["rp",  SEQ+1, "system/PRESETDIRTY"]
← ["rpr", ...,   SEQ+1, 0]
```

### Navigation behaviour

- One `"cm"` message per button press (no press/release pair unlike `"np"`)
- `N` is the **absolute zero-based slot index** of the destination preset
- Navigation is linear: next increments `N` by 1, previous decrements by 1
- Wrapping behaviour at boundaries (slot 0 and slot 98) not yet captured

### Difference from host-initiated preset load

| | Host-initiated (`"mc"`) | Device-initiated (`"cm"`) |
|--|------------------------|--------------------------|
| Direction | Host → Device | Device → Host |
| Verb | `"mc"` | `"cm"` |
| Argument order | `("banks/user/N", "preset")` | `("banks/user/N", "preset")` |
| Host follow-up | None required | Must read preset + check DIRTY |

Note that `"cm"` and `"mc"` share the same argument structure. The verb encodes the direction: `mc` = *move command* (host orders), `cm` = *change message* (device reports).

---

## 5. Subscription and Session Lifecycle

### Subscribe (init)

Sent once by the host during initialisation, after `STATE`, `VERSION`, and `SYNC`:

```
→ ["sbs", SEQ, "", 1]
← ["ack", DEV_SEQ, SEQ]
```

`1` = subscribe. After this, the device begins sending unsolicited `"np"` and `"cm"` notifications.

### Unsubscribe (session close)

Sent by the host when closing the session (Nexus quit, or user declines the "save changes?" prompt):

```
→ ["sbs", SEQ, "", 0]
← ["ack", DEV_SEQ, SEQ]
```

`0` = unsubscribe. After this, the device stops sending unsolicited notifications. The serial port goes quiet until a new host session begins.

### Session close triggered by "decline save"

When Nexus detects unsaved changes and the user declines to save, the unsubscribe is sent immediately:

```
→ ["sbs", 106, "", 0]
← ["ack", 114, 106]
```

This is the **only** message exchanged on a clean close with no pending save — no teardown handshake, no state reset command.

---

## 6. DEV_SEQ Counter Behaviour

The device maintains a single global sequence counter (`DEV_SEQ`) that increments for every message it sends, regardless of type:

| Property | Value |
|----------|-------|
| Initial value after cold boot | `0` |
| Persistence across power cycles | **No** — RAM only, resets to 0 on USB reconnect |
| Scope | All device messages: `rpr`, `ack`, `np`, `cm` |
| Increment | +1 per message sent |

The counter observed in session_01 started at 661 because the device had already exchanged 661 messages since its last power cycle before that capture began.

The host does not need to track `DEV_SEQ` for correctness — it is informational and used for correlation between requests and responses.

---

## 7. Known Unknowns

| Area | Status |
|------|--------|
| Preset navigation via on-device buttons (not auxiliary footswitch) | Not yet captured — likely `"cm"` with the same format |
| Bank boundary wrapping (next from slot 98, previous from slot 0) | Not yet captured |
| Factory preset navigation from device side | Not yet captured |
| Auxiliary footswitch third button (looper and other functions) | Out of scope for now |
| Expression pedal position | **Does not send position data** — pedal movement is not reported over serial |
| Device-initiated messages other than `"np"` and `"cm"` | None observed |
| Behaviour if host does not ACK a `"np"` or `"cm"` | Unknown — retransmission policy unclear |

---

*Captured and analysed: May 2026. Contributions welcome.*

