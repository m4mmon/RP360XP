# rp360xp — getting started

Python library and CLI for the DigiTech RP360XP guitar effects pedal.

## Requirements

- Python 3.10 or later
- The pedal connected via USB

## Installation

From the `src/` directory:

```bash
pip install -e .
```

To also install the test dependencies:

```bash
pip install -e ".[dev]"
```

> On some Linux systems pip may warn about installing into a system-managed
> environment.  Either use a virtual environment (recommended) or pass
> `--break-system-packages`.

### Virtual environment (recommended)

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Serial port permissions (Linux)

On Linux the serial device is typically `/dev/ttyACM0`.  Your user must be a
member of the `dialout` group to access it without `sudo`:

```bash
sudo usermod -aG dialout $USER
```

Log out and back in (or run `newgrp dialout`) for the change to take effect.
Verify with:

```bash
ls -l /dev/ttyACM0
# crw-rw---- 1 root dialout ...
```

## Running the tests

```bash
pytest tests/
```

## Basic usage

Connect the pedal via USB, then:

```bash
# Show the active preset
rp360xp show

# List all user presets
rp360xp list

# Listen to real-time device notifications (Ctrl-C to quit)
rp360xp listen --no-raw

# Full command reference
rp360xp --help
```

The port is auto-detected by USB vendor/product ID.  If auto-detection fails,
pass it explicitly:

```bash
rp360xp --port /dev/ttyACM0 show        # Linux
rp360xp --port COM3 show                # Windows
```
