# Claude Code status light

A desk light that shows what Claude Code is doing:

| Light | Meaning |
|---|---|
| 🟢 Green | No session working: done and ready for new input |
| 🟠 Orange | 1–2 sessions working |
| 🔴 Red | 3 or more sessions working at once: full load, don't start new projects |

It works through Claude Code **hooks**. Each session marks itself busy when you
send a prompt and clears itself when it finishes, and the light shows the total.

Claude Code must run on the computer the light is plugged into, because hooks
run where Claude Code runs.

Three kinds of light are supported:
- **DIY**: an RP2040 board with an RGB LED. Cheapest, no soldering needed.
- **RGB keyboard**: the whole keyboard glows the status color, through
  [OpenRGB](https://openrgb.org). Written for the **Razer Ornata V3 X** on Windows.
- **Tower**: Adafruit Tri-Color USB Controlled Tower Light,
  product [5125](https://www.adafruit.com/product/5125). Ready-made and pricier.

---

## Option A: build the DIY light

### Shopping list

| Part | Notes |
|---|---|
| **Waveshare RP2040-Zero** | Thumb-sized board with USB-C and a built-in RGB LED. Sold by Waveshare, Amazon, AliExpress and electronics shops. Either version (with or without pin headers) is fine; you don't need the pins |
| **USB-C cable that carries data** | Some cheap cables only charge. If the board never shows up on your computer, try another cable |
| **A diffuser** | A ping-pong ball with a hole cut in it, a frosted bottle cap, or a small frosted jar. It spreads the tiny LED into a soft glow |

Other RP2040 boards with a built-in RGB LED also work (for example the Seeed XIAO
RP2040). Change `PIN` in `diy/main.py` to that board's LED pin.

**Optional, brighter:** add a WS2812B LED stick or ring (8–16 LEDs). Solder three
wires: stick `5V` → board `5V`, `GND` → `GND`, `DIN` → `GP0`. Then set `PIN = 0`
and `NUM_LEDS` to the number of LEDs in `diy/main.py`.

### 1. Put MicroPython on the board

1. Download the MicroPython `.uf2` file for the **Raspberry Pi Pico** from
   <https://micropython.org/download/RPI_PICO/>. The RP2040-Zero uses the Pico firmware.
2. Hold the **BOOT** button on the board, plug it into the computer, then let go.
   A drive called `RPI-RP2` appears.
3. Drag the `.uf2` file onto that drive. The board restarts by itself and the drive disappears.

### 2. Copy the status-light program onto the board

```bash
python3 -m pip install mpremote
```

```bash
mpremote cp diy/main.py :main.py
```

```bash
mpremote reset
```

The LED should flash red → orange → green and then turn off. That self-test runs
every time the board gets power.

If red and green are swapped, set `SWAP_RED_GREEN = True` in `diy/main.py` and copy it again.

### 3. Mount it

Put the board inside the diffuser, run the cable out the back, and stand it
somewhere you can see it. A dab of hot glue or Blu Tack holds it in place.

Then continue with **Connect it to Claude Code** below.

---

## Option B: RGB keyboard (Razer Ornata V3 X) through OpenRGB

OpenRGB is free software that controls RGB lighting on many brands. The status
script asks it to color the keyboard. This works on Windows and Linux; OpenRGB's
Mac support is limited.

Other keyboards OpenRGB supports work the same way, for example the SteelSeries
Apex 3, Corsair K55 RGB PRO or Logitech G213.

1. **Quit Razer Synapse** if it's installed, and stop it from starting with Windows
   (Task Manager → Startup apps). Otherwise it fights OpenRGB over the colors.
2. **Install OpenRGB** from <https://openrgb.org> and open it. Check that the
   **Devices** tab lists **Razer Ornata V3 X**, and that clicking a color in OpenRGB
   changes the keyboard. If it isn't listed, this keyboard revision isn't supported yet.
3. **Turn on the SDK server**: in OpenRGB open the **SDK Server** tab and click
   **Start Server** (port 6742).
4. **Make OpenRGB start by itself** so the light works after a restart: in
   **Settings**, enable *Start at login*, *Start minimized* and *Start server*.
5. Continue with **Connect it to Claude Code** below, and install with
   `--device openrgb`.

The keyboard shows one color across all keys: green, orange or red.

---

## Option C: Adafruit tower light

On macOS or Windows install the CH34x USB-serial driver from the chip maker (WCH).
Linux already has it. Then continue below.

---

## Connect it to Claude Code

**On Windows**, type `python` (or `py`) wherever these steps say `python3`. Claude Code
on Windows also needs [Git for Windows](https://git-scm.com/download/win), which it
uses to run hooks.

1. **Linux only:** let your user open serial ports, then log out and back in:

   ```bash
   sudo usermod -aG dialout $USER
   ```

2. **Get the code and its Python packages:**

   ```bash
   git clone -b claude-status-light https://github.com/wumizhu/orbit150
   ```

   ```bash
   cd orbit150/status-light && python3 -m pip install -r requirements.txt
   ```

3. **Test the light.** It should cycle green → orange → red → off. For the RGB
   keyboard, run the install step (4) with `--device openrgb` first, so the test
   knows to use OpenRGB:

   ```bash
   python3 statuslight.py test
   ```

4. **Install the hooks** into `~/.claude/settings.json`. Your other settings are kept
   and a backup is saved first:

   ```bash
   python3 install.py
   ```

   For the RGB keyboard, use this instead:

   ```bash
   python3 install.py --device openrgb
   ```

5. Restart any open Claude Code sessions so they pick up the hooks.

Keep the folder where it is: the hooks point at `statuslight.py` by its full path.
If you move it, run `python3 install.py` again.

## Settings

Edit `~/.claude/status-light/config.json`:

| Key | Default | What it does |
|---|---|---|
| `full_load` | `3` | Number of busy sessions that turns the light red |
| `device` | `null` | `"diy"`, `"tower"` or `"openrgb"`. `null` uses whichever USB light is plugged in |
| `port` | `null` | Serial port, e.g. `/dev/ttyACM0`, `/dev/cu.usbmodem1101`, `COM5`. `null` finds the light automatically. If you set it, also set `device` |
| `stale_minutes` | `30` | A busy session with no activity for this long is forgotten (covers crashes) |
| `openrgb_match` | `""` | Only color OpenRGB devices whose name contains this, e.g. `"Ornata"`. Empty colors every keyboard |
| `openrgb_host`, `openrgb_port` | `127.0.0.1`, `6742` | Where OpenRGB's SDK server listens |
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

- **"no status light found"**: check the cable carries data, and for the tower light
  that the driver is installed. Otherwise set `port` and `device` in `config.json` by hand.
- **"cannot reach OpenRGB"**: OpenRGB isn't running, or its SDK server isn't started
  (OpenRGB → SDK Server → Start Server).
- **"OpenRGB found no device"**: OpenRGB doesn't see the keyboard. Quit Razer Synapse,
  then in OpenRGB click Rescan Devices. The log line lists what OpenRGB does see.
- **Keyboard flickers between colors**: another lighting app (Razer Synapse) is still running.
- **"pyserial is not installed"**: install it with the same Python that `install.py`
  wrote into the hooks (shown in `~/.claude/settings.json`).
- **DIY light stopped reacting after using `mpremote` or Thonny**: those tools pause
  the program on the board. Unplug and replug it.
- **Tower light: wrong lamp lights up**: the byte codes in `statuslight.py`
  (`LAMP_ON`, `LAMP_OFF`) come from Adafruit's example code. Adjust them if your unit differs.

## Tests

```bash
python3 -m unittest -v
```

The tests use a fake serial port and a fake OpenRGB, so no light is needed.
