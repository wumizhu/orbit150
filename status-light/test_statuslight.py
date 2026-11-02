"""Tests for the status light. Run with:  python3 -m unittest -v  (from this folder)"""
import io
import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import install  # noqa: E402
import statuslight as sl  # noqa: E402


class FakeSerial:
    """Stands in for pyserial; records every byte written."""
    written = []

    def __init__(self, port, baud, timeout=None):
        self.port = port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def write(self, data):
        FakeSerial.written.append((self.port, bytes(data)))

    def flush(self):
        pass


fake_serial = types.SimpleNamespace(Serial=FakeSerial, SerialException=OSError)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"STATUS_LIGHT_HOME": self.tmp.name})
        self.env.start()
        FakeSerial.written = []
        self.cfg = dict(sl.DEFAULTS, port="/dev/fake")

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def hook(self, event, session):
        with mock.patch.dict(sys.modules, {"serial": fake_serial}):
            return sl.handle_hook({"hook_event_name": event, "session_id": session}, self.cfg)


class ColorTests(Base):
    def test_color_thresholds(self):
        self.assertEqual(sl.color_for(0, 3), "green")
        self.assertEqual(sl.color_for(1, 3), "orange")
        self.assertEqual(sl.color_for(2, 3), "orange")
        self.assertEqual(sl.color_for(3, 3), "red")
        self.assertEqual(sl.color_for(5, 3), "red")

    def test_commands_light_exactly_one_lamp(self):
        self.assertEqual(sl.commands_for("green"), bytes([0x21, 0x22, 0x28, 0x14]))
        self.assertEqual(sl.commands_for("orange"), bytes([0x21, 0x24, 0x28, 0x12]))
        self.assertEqual(sl.commands_for("red"), bytes([0x22, 0x24, 0x28, 0x11]))
        self.assertEqual(sl.commands_for("off"), bytes([0x21, 0x22, 0x24, 0x28]))

    def test_diy_commands_are_words(self):
        self.assertEqual(sl.commands_for("orange", "diy"), b"orange\n")
        self.assertEqual(sl.commands_for("off", "diy"), b"off\n")

    def test_auto_detect_picks_light_by_usb_id(self):
        ports = [types.SimpleNamespace(device="/dev/ttyS0", vid=None, pid=None),
                 types.SimpleNamespace(device="/dev/ttyACM0", vid=0x2E8A, pid=0x0005)]
        list_ports = types.SimpleNamespace(comports=lambda: ports)
        tools = types.SimpleNamespace(list_ports=list_ports)
        with mock.patch.dict(sys.modules, {"serial": fake_serial, "serial.tools": tools}):
            self.assertEqual(sl.find_port(dict(sl.DEFAULTS)), ("/dev/ttyACM0", "diy"))
            self.assertEqual(sl.find_port(dict(sl.DEFAULTS, device="tower")), (None, None))

    def test_diy_light_gets_words_over_serial(self):
        self.cfg["device"] = "diy"
        self.hook("UserPromptSubmit", "a")
        self.assertEqual(FakeSerial.written[-1], ("/dev/fake", b"orange\n"))


class HookFlowTests(Base):
    def test_one_session_prompt_then_stop(self):
        self.assertEqual(self.hook("SessionStart", "a"), "green")
        self.assertEqual(self.hook("UserPromptSubmit", "a"), "orange")
        self.assertEqual(self.hook("Stop", "a"), "green")
        self.assertEqual([w[1][-1] for w in FakeSerial.written], [0x14, 0x12, 0x14])

    def test_three_sessions_is_full_load(self):
        self.hook("UserPromptSubmit", "a")
        self.hook("UserPromptSubmit", "b")
        self.assertEqual(self.hook("UserPromptSubmit", "c"), "red")
        self.assertEqual(self.hook("Stop", "b"), "orange")
        self.hook("SessionEnd", "a")
        self.assertEqual(self.hook("Stop", "c"), "green")

    def test_repeat_prompts_from_one_session_count_once(self):
        for _ in range(5):
            color = self.hook("UserPromptSubmit", "a")
        self.assertEqual(color, "orange")

    def test_tool_events_only_write_on_change(self):
        self.hook("UserPromptSubmit", "a")
        before = len(FakeSerial.written)
        for _ in range(10):
            self.hook("PostToolUse", "a")
        self.assertEqual(len(FakeSerial.written), before)

    def test_stale_session_is_forgotten(self):
        self.hook("UserPromptSubmit", "crashed")
        old = time.time() - 31 * 60
        os.utime(sl.sessions_dir() / "crashed", (old, old))
        self.assertEqual(sl.busy_sessions(30), [])
        self.assertEqual(self.hook("SessionStart", "new"), "green")

    def test_odd_session_ids_stay_inside_state_dir(self):
        self.hook("UserPromptSubmit", "../../etc/passwd")
        names = [p.name for p in sl.sessions_dir().iterdir()]
        self.assertEqual(len(names), 1)
        self.assertNotIn("/", names[0])

    def test_missing_device_does_not_crash_and_retries(self):
        self.cfg["port"] = None
        with mock.patch.object(sl, "find_port", return_value=(None, None)):
            self.assertEqual(self.hook("UserPromptSubmit", "a"), "orange")
        self.assertFalse((sl.state_dir() / "last_color").exists())
        # Once the light is plugged in, the next tool event catches it up.
        self.cfg["port"] = "/dev/fake"
        self.hook("PostToolUse", "a")
        self.assertEqual(FakeSerial.written[-1][1][-1], 0x12)

    def test_cli_hook_is_silent_and_never_fails(self):
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO("not json")), mock.patch("sys.stdout", out):
            self.assertEqual(sl.main(["hook"]), 0)
        self.assertEqual(out.getvalue(), "")


class FakeOpenRGB:
    """Stands in for openrgb-python: one Razer keyboard and one RAM stick."""
    KEYBOARD, DRAM = "keyboard", "dram"
    refuse_connection = False

    class Device:
        def __init__(self, name, type_, modes):
            self.name, self.type = name, type_
            self.modes = [types.SimpleNamespace(name=m) for m in modes]
            self.mode, self.color = None, None

        def set_mode(self, mode):
            self.mode = mode

        def set_color(self, color):
            self.color = color

    def __init__(self):
        self.devices = [
            self.Device("Razer Ornata V3 X", self.KEYBOARD, ["Direct", "Off", "Static", "Breathing"]),
            self.Device("Kingston Fury DDR5", self.DRAM, ["Direct", "Static"]),
        ]
        self.disconnected = 0
        fake = self

        class Client:
            def __init__(self, host, port, name):
                if FakeOpenRGB.refuse_connection:
                    raise ConnectionRefusedError("refused")
                self.devices = fake.devices

            def disconnect(self):
                fake.disconnected += 1

        self.modules = {
            "openrgb": types.SimpleNamespace(OpenRGBClient=Client),
            "openrgb.utils": types.SimpleNamespace(
                DeviceType=types.SimpleNamespace(KEYBOARD=self.KEYBOARD),
                RGBColor=lambda r, g, b: (r, g, b)),
        }


class OpenRGBTests(Base):
    def setUp(self):
        super().setUp()
        self.cfg["device"] = "openrgb"
        self.orgb = FakeOpenRGB()
        FakeOpenRGB.refuse_connection = False

    def hook(self, event, session):
        with mock.patch.dict(sys.modules, self.orgb.modules):
            return sl.handle_hook({"hook_event_name": event, "session_id": session}, self.cfg)

    def test_keyboard_follows_sessions_and_ram_is_left_alone(self):
        keyboard, ram = self.orgb.devices
        self.hook("UserPromptSubmit", "a")
        self.assertEqual((keyboard.mode, keyboard.color), ("direct", (255, 80, 0)))
        self.hook("UserPromptSubmit", "b")
        self.hook("UserPromptSubmit", "c")
        self.assertEqual(keyboard.color, (255, 0, 0))
        for s in "abc":
            self.hook("Stop", s)
        self.assertEqual(keyboard.color, (0, 255, 0))
        self.assertIsNone(ram.color)
        self.assertEqual(self.orgb.disconnected, 6)  # every connection is closed

    def test_match_by_name(self):
        self.cfg["openrgb_match"] = "fury"
        self.hook("UserPromptSubmit", "a")
        self.assertEqual(self.orgb.devices[1].color, (255, 80, 0))
        self.assertIsNone(self.orgb.devices[0].color)

    def test_openrgb_not_running_is_logged_not_raised(self):
        FakeOpenRGB.refuse_connection = True
        self.assertEqual(self.hook("UserPromptSubmit", "a"), "orange")
        self.assertIn("SDK server", (sl.state_dir() / "statuslight.log").read_text())
        self.assertFalse((sl.state_dir() / "last_color").exists())


class InstallTests(Base):
    def test_install_sets_device_and_keeps_other_config(self):
        settings = Path(self.tmp.name) / "settings.json"
        config = sl.state_dir() / "config.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({"full_load": 4}))
        with mock.patch("sys.stdout", io.StringIO()):
            install.main(["--settings", str(settings), "--device", "openrgb"])
        cfg = json.loads(config.read_text())
        self.assertEqual((cfg["device"], cfg["full_load"]), ("openrgb", 4))
        cmd = json.loads(settings.read_text())["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertNotIn("\\", cmd)

    def test_install_keeps_other_hooks_and_is_idempotent(self):
        settings = Path(self.tmp.name) / "settings.json"
        mine = {"type": "command", "command": "echo hi"}
        settings.write_text(json.dumps({"model": "x", "hooks": {"Stop": [{"hooks": [mine]}]}}))
        with mock.patch("sys.stdout", io.StringIO()):
            install.main(["--settings", str(settings)])
            install.main(["--settings", str(settings)])
        data = json.loads(settings.read_text())
        self.assertEqual(data["model"], "x")
        stop_cmds = [h["command"] for g in data["hooks"]["Stop"] for h in g["hooks"]]
        self.assertEqual(stop_cmds.count("echo hi"), 1)
        self.assertEqual(sum("statuslight.py" in c for c in stop_cmds), 1)
        for event in install.EVENTS:
            self.assertIn(event, data["hooks"])

        with mock.patch("sys.stdout", io.StringIO()):
            install.main(["--settings", str(settings), "--uninstall"])
        data = json.loads(settings.read_text())
        self.assertEqual(data["hooks"], {"Stop": [{"hooks": [mine]}]})


if __name__ == "__main__":
    unittest.main()
