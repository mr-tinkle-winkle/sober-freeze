"""
Finding the systemd unit (= cgroup) to freeze.

Freezing is the cgroup freezer through ``systemctl --user freeze`` -- it stops every process in
the unit (the game keeps its memory and state, just gets no CPU), and works on any app systemd
tracks as its own unit.  Flatpaks get ``app-flatpak-<id>-<n>.scope``; KDE launches other apps as
``app-<name>...`` scopes/services.

Freezing "the focused window" means freezing that window's *whole unit*, which can contain more
than the window (every window of a Flatpak, helper processes, and for some launchers the
launcher itself).  So only ``app-*`` units are ever allowed, desktop-shell units and this
program's own unit are refused, and the answer to "which unit?" always comes from the window's
real pid -- never a guess.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

SOBER_GLOB = "app-flatpak-org.vinegarhq.Sober-*.scope"
ALLOWED = re.compile(r"^app-.+\.(scope|service)$")
REFUSED = re.compile(r"plasma|kwin|xdg-desktop|dbus|pipewire|wireplumber|kded|kglobalaccel|ksmserver|"
                     r"polkit|sober-freeze|systemd|gnome-shell", re.IGNORECASE)


def systemctl(*args: str, timeout: float = 5.0) -> "subprocess.CompletedProcess | None":
    try:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def sober_unit() -> "str | None":
    out = systemctl("list-units", "--plain", "--no-legend", SOBER_GLOB)
    if out is None or out.returncode != 0:
        return None
    for line in out.stdout.splitlines():
        if line.split():
            return line.split()[0]
    return None


def cgroup_of(unit: str) -> "str | None":
    out = systemctl("show", "-p", "ControlGroup", "--value", unit)
    if out is None or out.returncode != 0 or not out.stdout.strip():
        return None
    return out.stdout.strip().lstrip("/")


def is_frozen(cgroup: str) -> "bool | None":
    """True / False, or None if the cgroup no longer exists (the app closed)."""
    try:
        text = Path("/sys/fs/cgroup", cgroup, "cgroup.events").read_text()
    except OSError:
        return None
    return "frozen 1" in text


def unit_from_cgroup_file(text: str) -> "str | None":
    """The ``app.slice`` unit named in the contents of /proc/<pid>/cgroup, if any."""
    for line in text.splitlines():
        path = line.rpartition("::")[2] if "::" in line else line.rsplit(":", 1)[-1]
        if "/app.slice/" in path:
            unit = path.split("/app.slice/", 1)[1].split("/")[0]
            if unit:
                return unit
    return None


def unit_for_pid(pid: int) -> "str | None":
    try:
        return unit_from_cgroup_file(Path(f"/proc/{int(pid)}/cgroup").read_text())
    except (OSError, ValueError):
        return None


def refusal(unit: str, own_unit: "str | None" = None) -> "str | None":
    """Why this unit must not be frozen (None = fine)."""
    if own_unit is None:
        own_unit = unit_for_pid(os.getpid())
    if unit == own_unit:
        return "that is the app this command is running from (freezing it would freeze sober-freeze itself)"
    if not ALLOWED.match(unit):
        return f"{unit} is not an application unit (only app-* units can be frozen)"
    if REFUSED.search(unit):
        return f"{unit} looks like part of the desktop session; not freezing it"
    return None
