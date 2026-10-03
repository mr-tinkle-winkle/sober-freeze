"""
``sober-freeze daemon`` -- the background part (a systemd user service):

  * the auto-unfreeze watchdog: anything frozen through sober-freeze is thawed after the
    configured number of seconds (setting read live from the config file);
  * optionally, hold-to-freeze: while a key (or key combo) is held the target is frozen, and
    thawed on release.  The key is read passively from /dev/input (needs the ``input`` group),
    so it still reaches the focused window.
"""
from __future__ import annotations

import logging
import selectors
import signal
import time

from . import config as config_mod
from . import core, state, units

logger = logging.getLogger("sober_freeze.daemon")
POLL = 0.25


class Watchdog:
    """Pure-ish: all effects are injected so it can be tested."""

    def __init__(self, *, load=config_mod.load, mtime=config_mod.mtime, entries=state.entries,
                 is_frozen=None, thaw_unit=None, clock=time.time, notify=lambda t, b: None):
        self._load, self._mtime, self._entries = load, mtime, entries
        self._is_frozen = is_frozen or (lambda cg: units.is_frozen(cg))
        self._clock, self._notify = clock, notify
        self._thaw_unit = thaw_unit or self._default_thaw
        self._seen = -1.0
        self.cfg = config_mod.Config()

    @staticmethod
    def _default_thaw(unit, entry):
        return core.thaw(core.Target(unit, entry.get("cgroup", ""), entry.get("label", unit))).ok

    def step(self) -> "list[str]":
        """One pass; returns the labels it thawed."""
        m = self._mtime()
        if m != self._seen:
            self._seen, self.cfg = m, self._load()
        thawed = []
        now = self._clock()
        for unit, e in self._entries().items():
            frozen = self._is_frozen(e.get("cgroup", ""))
            if not frozen:                         # thawed by someone else, or the app closed
                state.remove(unit)
                continue
            if self.cfg.auto_unfreeze and now - float(e.get("since", now)) >= self.cfg.auto_unfreeze_seconds:
                if self._thaw_unit(unit, e):
                    thawed.append(e.get("label", unit))
                    self._notify("sober-freeze", f"Auto-unfroze {e.get('label', unit)}")
        return thawed


class Hold:
    """Key-state machine: all keys of the combo down -> on_down(); any released -> on_up()."""

    def __init__(self, combo, on_down, on_up):
        self.combo, self.on_down, self.on_up = set(combo), on_down, on_up
        self.down: set = set()
        self.active = False

    def event(self, code: int, value: int) -> None:
        if code not in self.combo or value == 2:               # not ours / autorepeat
            return
        (self.down.add if value else self.down.discard)(code)
        held = self.combo <= self.down
        if held and not self.active:
            self.active = True
            self.on_down()
        elif not held and self.active:
            self.active = False
            self.on_up()

    def release_all(self) -> None:
        self.down.clear()
        if self.active:
            self.active = False
            self.on_up()


class HoldAction:
    """What holding does: freeze the target on press, thaw that same target on release."""

    def __init__(self, focused: bool):
        self.focused = focused
        self.held: "core.Target | None" = None

    def down(self) -> None:
        t, err = core.resolve(self.focused)
        if t is None:
            logger.info("hold ignored: %s", err)
            return
        res = core.freeze(t, by="hold")
        logger.info("%s", res.message)
        if res.ok:
            self.held = t

    def up(self) -> None:
        t, self.held = self.held, None
        if t is not None:
            logger.info("%s", core.thaw(t).message)


def run(hold_key: str = "", hold_focused: bool = False) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    lock = state.acquire_daemon_lock()
    if lock is None:
        logger.error("another sober-freeze daemon is already running")
        return 1

    sel = selectors.DefaultSelector()
    devices: dict = {}
    hold = None
    action = HoldAction(hold_focused)
    if hold_key:
        import evdev
        from evdev import ecodes

        try:
            combo = {ecodes.ecodes[n.strip()] for n in hold_key.split("+")}
        except KeyError as e:
            logger.error("unknown key name: %s", e)
            return 2
        hold = Hold(combo, action.down, action.up)

        def rescan():
            for path in evdev.list_devices():
                if path in devices:
                    continue
                try:
                    dev = evdev.InputDevice(path)
                    keys = set(dev.capabilities().get(ecodes.EV_KEY, []))
                except OSError:
                    continue
                if keys & combo:
                    devices[path] = dev
                    sel.register(dev, selectors.EVENT_READ, path)
    else:
        def rescan():
            return None

    def drop(path):
        dev = devices.pop(path, None)
        if dev is not None:
            sel.unregister(dev)
            dev.close()
        if hold:
            hold.release_all()               # a vanished device can never send the release

    def bye(*_):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)

    dog = Watchdog(notify=core.notify)
    last_scan = last_dog = 0.0
    logger.info("running (hold key: %s)", hold_key or "none")
    try:
        while True:
            now = time.monotonic()
            if hold and now - last_scan > 3:
                rescan()
                last_scan = now
            for key, _ in sel.select(timeout=POLL):
                try:
                    for ev in key.fileobj.read():
                        if ev.type == 1:        # EV_KEY
                            hold.event(ev.code, ev.value)
                except OSError:
                    drop(key.data)
            if time.monotonic() - last_dog >= 0.5:
                dog.step()
                last_dog = time.monotonic()
    finally:
        if hold:
            hold.release_all()               # never leave something frozen because this process ended
    return 0
