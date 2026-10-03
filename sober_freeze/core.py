"""Freeze / thaw / toggle a target (Sober, or whatever window is focused)."""
from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass

from . import focus, state, units


@dataclass
class Target:
    unit: str
    cgroup: str
    label: str


@dataclass
class Result:
    ok: bool
    message: str


def resolve_sober() -> "tuple[Target | None, str]":
    unit = units.sober_unit()
    if unit is None:
        return None, "Sober isn't running"
    cg = units.cgroup_of(unit)
    if cg is None:
        return None, f"couldn't find the cgroup of {unit}"
    return Target(unit, cg, "Sober"), ""


def resolve_focused() -> "tuple[Target | None, str]":
    if not focus.available():
        return None, "kdotool not found (needed to learn which window is focused)"
    got = focus.focused()
    if got is None:
        return None, "couldn't read the focused window"
    pid, wclass = got
    unit = units.unit_for_pid(pid)
    if unit is None:
        return None, f"the focused window ({wclass or pid}) isn't running as its own app unit"
    why = units.refusal(unit)
    if why:
        return None, f"not freezing the focused window ({wclass or pid}): {why}"
    cg = units.cgroup_of(unit)
    if cg is None:
        return None, f"couldn't find the cgroup of {unit}"
    return Target(unit, cg, wclass or unit), ""


def resolve(focused: bool) -> "tuple[Target | None, str]":
    return resolve_focused() if focused else resolve_sober()


def freeze(t: Target, by: str = "cli") -> Result:
    out = units.systemctl("freeze", t.unit)
    if out is None or out.returncode != 0:
        err = (out.stderr.strip() if out is not None else "systemctl failed")
        return Result(False, f"couldn't freeze {t.label}: {err}")
    state.add(t.unit, t.cgroup, t.label, by, time.time())
    return Result(True, f"{t.label} frozen")


def thaw(t: Target) -> Result:
    out = units.systemctl("thaw", t.unit)
    state.remove(t.unit)
    if out is None or out.returncode != 0:
        err = (out.stderr.strip() if out is not None else "systemctl failed")
        return Result(False, f"couldn't thaw {t.label}: {err}")
    return Result(True, f"{t.label} thawed")


def toggle(t: Target, by: str = "cli") -> Result:
    return thaw(t) if units.is_frozen(t.cgroup) else freeze(t, by)


def thaw_all() -> "list[Result]":
    results = []
    for unit, e in state.entries().items():
        results.append(thaw(Target(unit, e.get("cgroup", ""), e.get("label", unit))))
    return results


def notify(title: str, body: str) -> None:
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "-t", "1500", title, body], check=False)
