# Claude Code status light

A desk light that shows what Claude Code is doing:

| Light | Meaning |
|---|---|
| 🟢 Green | No session working: done and ready for new input |
| 🟠 Orange (the yellow lamp) | 1–2 sessions working |
| 🔴 Red | 3 or more sessions working at once: full load, don't start new projects |

It works through Claude Code **hooks**. Each session marks itself busy when you
send a prompt and clears itself when it finishes, and the light shows the total.

## Hardware

**Adafruit Tri-Color USB Controlled Tower Light with Buzzer**, product
[5125](https://www.adafruit.com/product/5125). It is powered and controlled
over a single USB cable and uses a CH340 USB-to-serial chip.

## Setup (on the computer the light is plugged into)

Claude Code must run on the same computer, because hooks run where Claude Code runs.

1. **Driver.** On macOS or Windows install the CH34x USB-serial driver from the
   chip maker (WCH). Linux already has it. On Linux, also let your user open the port,
   then log out and back in:

   ```bash
   sudo usermod -aG dialout $USER
   ```

2. **Get the code and pyserial:**

   ```bash
   git clone -b claude-status-light https://github.com/wumizhu/orbit150
   ```

   ```bash
   cd orbit150/status-light && python3 -m pip install -r requirements.txt
   ```

3. **Test the light.** It should cycle green → orange → red → off:

   ```bash
   python3 statuslight.py test
   ```

4. **Install the hooks** into `~/.claude/settings.json`. Your other settings are kept
   and a backup is saved first:

   ```bash
   python3 install.py
   ```

5. Restart any open Claude Code sessions so they pick up the hooks.

Keep the folder where it is: the hooks point at `statuslight.py` by its full path.
If you move it, run `python3 install.py` again.

## Settings

Edit `~/.claude/status-light/config.json`:

| Key | Default | What it does |
|---|---|---|
| `full_load` | `3` | Number of busy sessions that turns the light red |
| `port` | `null` | Serial port, e.g. `/dev/ttyUSB0`, `/dev/cu.wchusbserial1420`, `COM5`. `null` finds the light automatically |
| `stale_minutes` | `30` | A busy session with no activity for this long is forgotten (covers crashes) |
| `dry_run` | `false` | Write colors to the log instead of the device |

## Everyday commands

```bash
python3 statuslight.py status
```

Shows the busy sessions, the current color and the device port.

```bash
python3 statuslight.py reset
```

Forgets every session and shows green, useful if the light gets stuck on orange or red.

```bash
python3 statuslight.py set red
```

Forces a color by hand (`green`, `orange`, `red` or `off`). The next hook event
sets it back to the real state.

```bash
python3 install.py --uninstall
```

Removes the hooks.

## Troubleshooting

Problems are logged to `~/.claude/status-light/statuslight.log`. Hooks never
print anything or fail, so a missing or unplugged light never interrupts Claude Code.

- **"no tower light found"**: the driver isn't installed, or the light's chip differs.
  Set `port` in `config.json` by hand.
- **"pyserial is not installed"**: install it with the same Python that `install.py`
  wrote into the hooks (shown in `~/.claude/settings.json`).
- **Wrong lamp lights up**: the byte codes in `statuslight.py` (`LAMP_ON`, `LAMP_OFF`)
  come from Adafruit's example code. Adjust them if your unit differs.

## Tests

```bash
python3 -m unittest -v
```

The tests use a fake serial port, so no light is needed.
