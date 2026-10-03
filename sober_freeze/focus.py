"""The focused window's process, via kdotool (KDE Plasma; same route as sober-console)."""
from __future__ import annotations

import shutil
import subprocess


def _kdotool(*args: str, timeout: float = 2.0) -> "str | None":
    try:
        out = subprocess.run(["kdotool", *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def available() -> bool:
    return shutil.which("kdotool") is not None


def focused() -> "tuple[int, str] | None":
    """(pid, window class) of the active window, or None when it can't be read."""
    wid = _kdotool("getactivewindow")
    if not wid:
        return None
    pid = _kdotool("getwindowpid", wid)
    if not pid or not pid.isdigit():
        return None
    return int(pid), _kdotool("getwindowclassname", wid) or ""
