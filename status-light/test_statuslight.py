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
        with mock.patch.object(sl, "find_port", return_value=None):
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


class InstallTests(Base):
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
