# Raspberry Pi 4 — Serial MitM Setup

## Hardware

- **Power**: 5V on GPIO pins 2 and 4, GND on pins 6 and 9 (double up wires on both rails to reduce voltage drop).
- **PC connection**: USB-C port of the Pi 4 connected to the PC — the Pi presents itself as a DigiTech RP360 serial device.
- **RP360XP connection**: plugged into any USB-A port of the Pi 4.

## Gadget Initialization

After each reboot, the USB gadget must be configured before connecting the USB-C cable to the PC:

```bash
sudo gadget-setup.sh
```

gadget-setup.sh is [there](scripts/gadget-setup.sh)

This loads the `libcomposite` kernel module and configures a CDC-ACM USB gadget with the RP360XP's VID/PID (`1210:0032`), making the Pi appear as a DigiTech RP360 to the PC.


## Capture

Once the gadget is active and the USB-C cable is connected, start the relay and capture script:

```bash
sudo python3 mitm_serial.py
```

mitm_serial.py is [there](scripts/mitm_serial.py)

The script relays traffic transparently between `/dev/ttyGS0` (PC side) and `/dev/ttyACM0` (RP360XP side) at 115200 baud. All traffic is logged to `capture.log` (append mode — existing captures are preserved across sessions).

Press **Enter** at any time to insert an annotated marker into the log, useful for correlating captures with specific UI interactions in Nexus.

The script reconnects automatically if the USB-C cable is disconnected and reconnected.

## Gadget Teardown

```bash
sudo gadget-teardown.sh
```

gadget-teardown.sh is [there](scripts/gadget-teardown.sh)

Deactivates the gadget and unloads `libcomposite`.
