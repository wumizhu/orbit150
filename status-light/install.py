#!/usr/bin/env python3
"""Add (or remove) the status-light hooks in Claude Code's user settings.

    python3 install.py              # install into ~/.claude/settings.json
    python3 install.py --uninstall  # remove them again

Your existing settings and hooks are kept; a timestamped backup is written first.
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import statuslight  # noqa: E402

EVENTS = ["SessionStart", "UserPromptSubmit", "PostToolUse", "Stop", "SessionEnd"]
MARKER = "statuslight.py"


def hook_command():
    return f'"{sys.executable}" "{HERE / "statuslight.py"}" hook'


def strip_ours(settings):
    hooks = settings.get("hooks", {})
    for event in list(hooks):
        groups = []
        for group in hooks[event]:
            kept = [h for h in group.get("hooks", []) if MARKER not in h.get("command", "")]
            if kept:
                groups.append({**group, "hooks": kept})
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if not hooks:
        settings.pop("hooks", None)
    return settings


def add_ours(settings):
    hooks = settings.setdefault("hooks", {})
    for event in EVENTS:
        group = {"hooks": [{"type": "command", "command": hook_command(), "timeout": 5}]}
        if event == "PostToolUse":
            group = {"matcher": "*", **group}
        hooks.setdefault(event, []).append(group)
    return settings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--settings", type=Path, default=Path.home() / ".claude" / "settings.json")
    args = parser.parse_args(argv)

    settings = {}
    if args.settings.exists():
        settings = json.loads(args.settings.read_text() or "{}")
        backup = args.settings.with_name(f"settings.json.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(args.settings, backup)
        print(f"backed up {args.settings} -> {backup}")

    settings = strip_ours(settings)
    if not args.uninstall:
        settings = add_ours(settings)
    args.settings.parent.mkdir(parents=True, exist_ok=True)
    args.settings.write_text(json.dumps(settings, indent=2) + "\n")

    if args.uninstall:
        print("status-light hooks removed")
        return 0

    config = statuslight.state_dir() / "config.json"
    if not config.exists():
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps(statuslight.DEFAULTS, indent=2) + "\n")
        print(f"wrote default config {config}")

    print(f"hooks installed for: {', '.join(EVENTS)}")
    try:
        import serial  # noqa: F401
    except ImportError:
        print(f"\nnext: install pyserial ->  {sys.executable} -m pip install pyserial")
    print(f"then test the light ->  {sys.executable} {HERE / 'statuslight.py'} test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
