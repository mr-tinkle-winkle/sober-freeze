"""
Command line entry point.

    sober-freeze [freeze|thaw|toggle|status] [--override-to-focused] [-q]
    sober-freeze thaw --all
    sober-freeze list
    sober-freeze auto-unfreeze [on|off|toggle|status] [--seconds N]
    sober-freeze gui
    sober-freeze daemon [--hold-key KEY_SCROLLLOCK] [--hold-override-to-focused]

With no action it toggles.  Everything except ``gui`` and ``daemon`` is Qt-free and quick.
"""
from __future__ import annotations

import argparse
import sys
import time

from . import __version__
from . import config as config_mod
from . import core, state, units

OVERRIDE = ("--override-to-focused", "--overrideToFocused")


def _add_target_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument(*OVERRIDE, dest="focused", action="store_true",
                   help="act on the currently focused window's app instead of Sober")
    p.add_argument("-q", "--quiet", action="store_true", help="no desktop notification")


def _report(res: core.Result, quiet: bool, title: str = "sober-freeze") -> int:
    print(res.message if res.ok else f"sober-freeze: {res.message}", file=sys.stdout if res.ok else sys.stderr)
    if not quiet:
        core.notify(title, res.message)
    return 0 if res.ok else 1


def _auto_note() -> str:
    cfg = config_mod.load()
    if cfg.auto_unfreeze and not state.daemon_running():
        return ("  (auto-unfreeze is on, but the background service isn't running, so nothing will "
                "thaw it for you: start `sober-freeze daemon` / enable services.sober-freeze)")
    return ""


def _cmd_action(args) -> int:
    t, err = core.resolve(args.focused)
    if t is None:
        if args.cmd == "status":
            print("not available: " + err)
        else:
            _report(core.Result(False, err), args.quiet)
        return 1
    if args.cmd == "status":
        frozen = units.is_frozen(t.cgroup)
        print(f"{t.label}: {'frozen' if frozen else 'running'}")
        return 0
    if args.cmd == "freeze":
        res = core.freeze(t)
    elif args.cmd == "thaw":
        res = core.thaw(t)
    else:
        res = core.toggle(t)
    code = _report(res, args.quiet)
    if res.ok and "frozen" in res.message and "thawed" not in res.message:
        note = _auto_note()
        if note:
            print(note.strip())
    return code


def _cmd_thaw_all(args) -> int:
    results = core.thaw_all()
    for r in results:
        print(r.message)
    if not results:
        print("nothing frozen by sober-freeze")
    return 0 if all(r.ok for r in results) else 1


def _cmd_list(_args) -> int:
    entries = state.entries()
    if not entries:
        print("nothing frozen by sober-freeze")
        return 0
    now = time.time()
    for unit, e in entries.items():
        print(f"{e.get('label', unit)}  ({unit})  frozen {int(now - float(e.get('since', now)))}s ago by {e.get('by', '?')}")
    return 0


def describe_auto(cfg: config_mod.Config) -> str:
    return f"auto-unfreeze: {'on' if cfg.auto_unfreeze else 'off'} ({cfg.auto_unfreeze_seconds} s)"


def _cmd_auto(args) -> int:
    cfg = config_mod.load()
    changed = False
    if args.value == "on":
        cfg.auto_unfreeze, changed = True, True
    elif args.value == "off":
        cfg.auto_unfreeze, changed = False, True
    elif args.value == "toggle":
        cfg.auto_unfreeze, changed = not cfg.auto_unfreeze, True
    if args.seconds is not None:
        cfg.auto_unfreeze_seconds, changed = args.seconds, True
    cfg.sanitize()
    if changed:
        config_mod.save(cfg)
    print(describe_auto(cfg))
    if changed and cfg.auto_unfreeze and not state.daemon_running():
        print("note: the background service isn't running, so this has no effect until it is "
              "(`sober-freeze daemon`).")
    return 0


def main(argv: "list[str] | None" = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--version")):
        argv.insert(0, "toggle")                     # bare `sober-freeze [--override-to-focused]`

    p = argparse.ArgumentParser(prog="sober-freeze", description="Freeze / thaw Sober, or the focused app.")
    p.add_argument("--version", action="version", version=f"sober-freeze {__version__}")
    sub = p.add_subparsers(dest="cmd")
    for name, text in (("toggle", "freeze if running, thaw if frozen (default)"), ("freeze", "freeze"),
                       ("thaw", "thaw"), ("status", "print frozen / running")):
        sp = sub.add_parser(name, help=text)
        _add_target_flags(sp)
        if name == "thaw":
            sp.add_argument("--all", action="store_true", help="thaw everything sober-freeze has frozen")
    sub.add_parser("list", help="what sober-freeze currently has frozen")
    a = sub.add_parser("auto-unfreeze", help="thaw automatically after a delay: on | off | toggle | status")
    a.add_argument("value", nargs="?", choices=("on", "off", "toggle", "status"), default="status")
    a.add_argument("--seconds", type=int, help="delay before thawing (1-3600)")
    sub.add_parser("gui", help="open the settings / control window")
    d = sub.add_parser("daemon", help="background service: auto-unfreeze + hold key (what the service runs)")
    d.add_argument("--hold-key", default="", help="evdev key or combo (KEY_LEFTCTRL+KEY_F9): hold to freeze")
    d.add_argument(*[f.replace("override", "hold-override") for f in OVERRIDE[:1]], dest="hold_focused",
                   action="store_true", help="hold key freezes the focused window instead of Sober")
    args = p.parse_args(argv)

    if args.cmd in ("toggle", "freeze", "thaw", "status"):
        if args.cmd == "thaw" and args.all:
            return _cmd_thaw_all(args)
        return _cmd_action(args)
    if args.cmd == "list":
        return _cmd_list(args)
    if args.cmd == "auto-unfreeze":
        return _cmd_auto(args)
    if args.cmd == "gui":
        from . import gui
        return gui.run()
    if args.cmd == "daemon":
        from . import daemon
        return daemon.run(args.hold_key, args.hold_focused)
    p.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
