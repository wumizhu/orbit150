#!/usr/bin/env python3
"""Drive a green/orange/red USB status light from Claude Code hooks.

Supported lights:
    tower   = Adafruit Tri-Color USB Tower Light (product 5125)
    diy     = an RP2040 board with an RGB LED running diy/main.py
    openrgb = an RGB keyboard (or other device) controlled through OpenRGB

    green  = no session is working, ready for new input
    orange = 1 or more sessions working (the tower's yellow lamp)
    red    = `full_load` or more sessions working at once, no room for new work

Each Claude Code session marks itself busy in a small state directory when you
send a prompt and clears itself when it stops. The light shows the total.

Usage:
    statuslight.py hook            # called by Claude Code hooks, reads JSON on stdin
    statuslight.py set COLOR       # green | orange | red | off
    statuslight.py status          # print busy sessions, color and device port
    statuslight.py test            # cycle through every color
    statuslight.py reset           # forget all sessions and show green
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt

DEFAULTS = {
    "device": None,        # "tower", "diy" or "openrgb"; None = whichever USB light is plugged in
    "port": None,          # e.g. "/dev/ttyACM0", "/dev/cu.usbmodem1101", "COM5"; None = auto-detect
    "full_load": 3,        # this many busy sessions turns the light red
    "stale_minutes": 30,   # a busy session with no activity for this long is forgotten
    "baud": 9600,
    "openrgb_host": "127.0.0.1",
    "openrgb_port": 6742,
    "openrgb_match": "",   # only light OpenRGB devices whose name contains this, e.g. "Ornata"; "" = every keyboard
    "dry_run": False,      # log colors instead of talking to the device
}

# Single-byte commands for the Adafruit Tri-Color USB Tower Light (product 5125).
LAMP_ON = {"red": 0x11, "yellow": 0x12, "green": 0x14}
LAMP_OFF = {"red": 0x21, "yellow": 0x22, "green": 0x24}
BUZZER_OFF = 0x28
COLOR_TO_LAMP = {"green": "green", "orange": "yellow", "red": "red", "off": None}

# RGB values for lights that can show any color (OpenRGB devices).
COLOR_TO_RGB = {"green": (0, 255, 0), "orange": (255, 80, 0), "red": (255, 0, 0), "off": (0, 0, 0)}

# USB ids used to auto-detect each light: the tower's CH340 serial chip, and
# MicroPython on an RP2040 board.
USB_IDS = {(0x1A86, 0x7523): "tower", (0x2E8A, 0x0005): "diy"}

BUSY_EVENTS = {"UserPromptSubmit", "PreToolUse", "PostToolUse"}
IDLE_EVENTS = {"Stop", "SessionEnd"}


def state_dir():
    return Path(os.environ.get("STATUS_LIGHT_HOME") or Path.home() / ".claude" / "status-light")


def sessions_dir():
    return state_dir() / "sessions"


def load_config():
    cfg = dict(DEFAULTS)
    path = state_dir() / "config.json"
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text()))
        except (OSError, ValueError) as e:
            log(f"ignoring unreadable config {path}: {e}")
    if os.environ.get("STATUS_LIGHT_PORT"):
        cfg["port"] = os.environ["STATUS_LIGHT_PORT"]
    if os.environ.get("STATUS_LIGHT_FULL_LOAD"):
        cfg["full_load"] = int(os.environ["STATUS_LIGHT_FULL_LOAD"])
    if os.environ.get("STATUS_LIGHT_DRY_RUN"):
        cfg["dry_run"] = os.environ["STATUS_LIGHT_DRY_RUN"] not in ("", "0", "false")
    return cfg


def log(msg):
    path = state_dir() / "statuslight.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 256 * 1024:
            path.write_text("")
        with path.open("a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


# --- session bookkeeping ---------------------------------------------------

def _session_file(session_id):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown")
    return sessions_dir() / safe


def mark_busy(session_id):
    path = _session_file(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(time.time()))


def mark_idle(session_id):
    try:
        _session_file(session_id).unlink()
    except FileNotFoundError:
        pass


def busy_sessions(stale_minutes, now=None):
    """Return the ids of busy sessions, deleting ones that have gone stale."""
    now = now or time.time()
    busy = []
    if not sessions_dir().exists():
        return busy
    for path in sessions_dir().iterdir():
        try:
            if now - path.stat().st_mtime > stale_minutes * 60:
                path.unlink()
                log(f"forgot stale session {path.name}")
            else:
                busy.append(path.name)
        except FileNotFoundError:
            pass
    return sorted(busy)


def color_for(busy_count, full_load):
    if busy_count <= 0:
        return "green"
    if busy_count >= full_load:
        return "red"
    return "orange"


# --- device ----------------------------------------------------------------

def commands_for(color, device="tower"):
    """Bytes that switch the light to show only `color`."""
    if device == "diy":
        return f"{color}\n".encode()
    lamp = COLOR_TO_LAMP[color]
    cmds = [LAMP_OFF[name] for name in ("red", "yellow", "green") if name != lamp]
    cmds.append(BUZZER_OFF)
    if lamp:
        cmds.append(LAMP_ON[lamp])
    return bytes(cmds)


def find_port(cfg):
    """Return (port, device) for the light to use, or (None, None)."""
    if cfg.get("port"):
        return cfg["port"], cfg.get("device") or "tower"
    try:
        from serial.tools import list_ports
    except ImportError:
        return None, None
    for p in list_ports.comports():
        device = USB_IDS.get((p.vid, p.pid))
        if device and cfg.get("device") in (None, device):
            return p.device, device
    return None, None


def send_openrgb(color, cfg):
    """Set every matching OpenRGB device (keyboards by default) to `color`."""
    try:
        from openrgb import OpenRGBClient
        from openrgb.utils import DeviceType, RGBColor
    except ImportError:
        log("openrgb-python is not installed: python -m pip install openrgb-python")
        return False
    try:
        client = OpenRGBClient(cfg["openrgb_host"], cfg["openrgb_port"], "claude-status-light")
    except (OSError, TimeoutError) as e:
        log(f"cannot reach OpenRGB at {cfg['openrgb_host']}:{cfg['openrgb_port']}; "
            f"is OpenRGB running with its SDK server on? ({e})")
        return False
    try:
        match = (cfg.get("openrgb_match") or "").lower()
        if match:
            devices = [d for d in client.devices if match in d.name.lower()]
        else:
            devices = [d for d in client.devices if d.type == DeviceType.KEYBOARD]
        if not devices:
            log(f"OpenRGB found no device matching {match or 'type keyboard'}; "
                f"it sees: {', '.join(d.name for d in client.devices) or 'nothing'}")
            return False
        for dev in devices:
            # "Direct" lets software set colors live; a few devices only offer "Static".
            names = {m.name.lower() for m in dev.modes}
            for mode in ("direct", "static"):
                if mode in names:
                    dev.set_mode(mode)
                    break
            dev.set_color(RGBColor(*COLOR_TO_RGB[color]))
        log(f"light -> {color} (OpenRGB: {', '.join(d.name for d in devices)})")
        return True
    finally:
        client.disconnect()


def send(color, cfg):
    if cfg.get("dry_run"):
        log(f"[dry run] light -> {color}")
        return True
    if cfg.get("device") == "openrgb":
        return send_openrgb(color, cfg)
    try:
        import serial
    except ImportError:
        log("pyserial is not installed: python3 -m pip install pyserial")
        return False
    port, device = find_port(cfg)
    if not port:
        log("no status light found; plug it in or set \"port\" in config.json")
        return False
    try:
        with serial.Serial(port, cfg.get("baud", 9600), timeout=1) as dev:
            dev.write(commands_for(color, device))
            dev.flush()
    except (serial.SerialException, OSError) as e:
        log(f"could not write to {port}: {e}")
        return False
    log(f"light -> {color} ({device} on {port})")
    return True


# --- glue ------------------------------------------------------------------

class _Lock:
    """Serialize hooks from parallel sessions so they don't fight over the port."""

    def __enter__(self):
        state_dir().mkdir(parents=True, exist_ok=True)
        self.f = (state_dir() / "lock").open("w")
        if fcntl:
            fcntl.flock(self.f, fcntl.LOCK_EX)
        else:
            msvcrt.locking(self.f.fileno(), msvcrt.LK_LOCK, 1)
        return self

    def __exit__(self, *exc):
        if fcntl:
            fcntl.flock(self.f, fcntl.LOCK_UN)
        else:
            self.f.seek(0)
            msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
        self.f.close()


def update_light(cfg, only_if_changed=False):
    color = color_for(len(busy_sessions(cfg["stale_minutes"])), cfg["full_load"])
    last_file = state_dir() / "last_color"
    last = last_file.read_text().strip() if last_file.exists() else None
    if only_if_changed and color == last:
        return color
    if send(color, cfg):
        last_file.write_text(color)
    return color


def handle_hook(payload, cfg):
    event = payload.get("hook_event_name", "")
    session_id = payload.get("session_id", "unknown")
    with _Lock():
        if event in BUSY_EVENTS:
            mark_busy(session_id)
        elif event in IDLE_EVENTS:
            mark_idle(session_id)
        # Tool events fire constantly; only touch the device when the color changes.
        return update_light(cfg, only_if_changed=event in ("PreToolUse", "PostToolUse"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("hook")
    p_set = sub.add_parser("set")
    p_set.add_argument("color", choices=["green", "orange", "red", "off"])
    sub.add_parser("status")
    sub.add_parser("test")
    sub.add_parser("reset")
    args = parser.parse_args(argv)
    cfg = load_config()

    if args.cmd == "hook":
        # Never break Claude Code: swallow every error, print nothing, exit 0.
        try:
            handle_hook(json.load(sys.stdin), cfg)
        except Exception as e:
            log(f"hook error: {e!r}")
        return 0

    if args.cmd == "set":
        return 0 if send(args.color, cfg) else 1

    if args.cmd == "status":
        busy = busy_sessions(cfg["stale_minutes"])
        print(f"busy sessions: {len(busy)} (red at {cfg['full_load']})")
        for s in busy:
            print(f"  {s}")
        print(f"color: {color_for(len(busy), cfg['full_load'])}")
        if cfg["dry_run"]:
            print("device: dry run")
        elif cfg.get("device") == "openrgb":
            print(f"device: OpenRGB at {cfg['openrgb_host']}:{cfg['openrgb_port']}")
        else:
            port, device = find_port(cfg)
            print(f"device: {f'{device} on {port}' if port else 'not found'}")
        return 0

    if args.cmd == "test":
        ok = True
        for color in ("green", "orange", "red", "off"):
            print(color)
            ok = send(color, cfg) and ok
            time.sleep(1.5)
        if not ok:
            print(f"some commands failed, see {state_dir() / 'statuslight.log'}")
        with _Lock():
            update_light(cfg)
        return 0 if ok else 1

    if args.cmd == "reset":
        with _Lock():
            for path in sessions_dir().glob("*") if sessions_dir().exists() else []:
                path.unlink()
            print(update_light(cfg))
        return 0


if __name__ == "__main__":
    sys.exit(main())
