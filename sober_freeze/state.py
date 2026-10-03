"""
What sober-freeze has frozen, so that ``thaw --all``, the GUI list and the auto-unfreeze
watchdog know about it.  A small JSON file in ``$XDG_RUNTIME_DIR`` (gone on logout/reboot,
which is also when every freeze is gone), guarded by a lock file.
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


def _dir() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    d = Path(runtime) / "sober-freeze" if runtime else Path(tempfile.gettempdir()) / f"sober-freeze-{os.getuid()}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_path() -> Path:
    return _dir() / "state.json"


def daemon_lock_path() -> Path:
    return _dir() / "daemon.lock"


@contextmanager
def _locked():
    with open(_dir() / "state.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _read() -> dict:
    try:
        data = json.loads(state_path().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data: dict) -> None:
    tmp = state_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, state_path())


def entries() -> dict:
    """{unit: {"since": epoch, "cgroup": path, "label": text, "by": who}}"""
    with _locked():
        return _read()


def add(unit: str, cgroup: str, label: str, by: str, since: float) -> None:
    with _locked():
        data = _read()
        data[unit] = {"since": since, "cgroup": cgroup, "label": label, "by": by}
        _write(data)


def remove(unit: str) -> None:
    with _locked():
        data = _read()
        if data.pop(unit, None) is not None:
            _write(data)


def daemon_running() -> bool:
    try:
        fh = open(daemon_lock_path(), "a")
    except OSError:
        return False
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    fcntl.flock(fh, fcntl.LOCK_UN)
    fh.close()
    return False


def acquire_daemon_lock():
    fh = open(daemon_lock_path(), "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh
