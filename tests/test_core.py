import pytest

from sober_freeze import cli, config, core, daemon, focus, state, units


# ---- fake systemd -----------------------------------------------------------------------------
class FakeSystem:
    def __init__(self, monkeypatch):
        self.frozen = {}          # cgroup -> bool
        self.calls = []
        self.sober = "app-flatpak-org.vinegarhq.Sober-1.scope"
        self.sober_up = True
        self.focused = None       # (pid, class)
        self.pid_units = {}
        monkeypatch.setattr(units, "sober_unit", lambda: self.sober if self.sober_up else None)
        monkeypatch.setattr(units, "cgroup_of", lambda u: f"cg/{u}")
        monkeypatch.setattr(units, "is_frozen", lambda cg: self.frozen.get(cg))
        monkeypatch.setattr(units, "systemctl", self.systemctl)
        monkeypatch.setattr(units, "unit_for_pid", lambda pid: self.pid_units.get(pid))
        monkeypatch.setattr(units, "unit_for_pid", lambda pid: self.pid_units.get(pid))
        monkeypatch.setattr(focus, "available", lambda: True)
        monkeypatch.setattr(focus, "focused", lambda: self.focused)
        monkeypatch.setattr(core, "notify", lambda *a: None)
        monkeypatch.setattr(cli.core, "notify", lambda *a: None)

    def systemctl(self, *args, **kw):
        self.calls.append(args)
        verb, unit = args[0], args[1]
        self.frozen[f"cg/{unit}"] = verb == "freeze"

        class R:
            returncode, stdout, stderr = 0, "", ""
        return R()


@pytest.fixture
def sysd(monkeypatch):
    return FakeSystem(monkeypatch)


def test_toggle_sober_freezes_then_thaws_and_records_state(sysd):
    t, _ = core.resolve(False)
    assert core.toggle(t).message == "Sober frozen"
    assert sysd.frozen["cg/" + sysd.sober] is True and sysd.sober in state.entries()
    assert core.toggle(t).message == "Sober thawed"
    assert sysd.frozen["cg/" + sysd.sober] is False and state.entries() == {}


def test_sober_not_running_is_a_clear_error(sysd):
    sysd.sober_up = False
    t, err = core.resolve(False)
    assert t is None and err == "Sober isn't running"


def test_override_to_focused_targets_the_focused_windows_unit_not_sober(sysd):
    sysd.focused = (555, "firefox")
    sysd.pid_units[555] = "app-firefox-1234.scope"
    t, err = core.resolve(True)
    assert err == "" and t.unit == "app-firefox-1234.scope" and t.label == "firefox"
    core.freeze(t)
    assert sysd.calls == [("freeze", "app-firefox-1234.scope")]       # Sober untouched


@pytest.mark.parametrize("unit", ["plasma-plasmashell.service", "app-plasma-foo.scope", "session-3.scope",
                                  "app-org.kde.kwin_wayland.service", "app-dbus-broker.service", "sober-freeze.service"])
def test_desktop_session_units_are_never_frozen(sysd, unit):
    sysd.focused = (9, "x")
    sysd.pid_units[9] = unit
    t, err = core.resolve(True)
    assert t is None and err


def test_focused_resolution_failures(sysd):
    sysd.focused = None
    assert "couldn't read" in core.resolve(True)[1]
    sysd.focused = (7, "foo")
    assert "isn't running as its own app unit" in core.resolve(True)[1]


def test_session_looking_app_units_are_refused_with_a_session_reason():
    assert "desktop session" in units.refusal("app-plasma-foo.scope", own_unit="x")
    assert "desktop session" in units.refusal("app-org.kde.kwin_wayland.service", own_unit="x")
    assert "not an application unit" in units.refusal("session-3.scope", own_unit="x")


def test_own_unit_is_refused(monkeypatch):
    assert "freezing it would freeze sober-freeze itself" in units.refusal("app-x.scope", own_unit="app-x.scope")
    assert units.refusal("app-x.scope", own_unit="app-y.scope") is None


def test_unit_from_cgroup_file():
    txt = "0::/user.slice/user-1000.slice/user@1000.service/app.slice/app-flatpak-org.vinegarhq.Sober-9.scope/sub\n"
    assert units.unit_from_cgroup_file(txt) == "app-flatpak-org.vinegarhq.Sober-9.scope"
    assert units.unit_from_cgroup_file("0::/user.slice/user-1000.slice/session-2.scope\n") is None


def test_thaw_all_thaws_everything_it_froze(sysd):
    a = core.Target("app-a.scope", "cg/app-a.scope", "A")
    b = core.Target("app-b.scope", "cg/app-b.scope", "B")
    core.freeze(a)
    core.freeze(b)
    assert len(core.thaw_all()) == 2 and state.entries() == {}
    assert not any(sysd.frozen.values())


# ---- auto-unfreeze watchdog ---------------------------------------------------------------------
def make_dog(sysd, clock, **cfg):
    config.save(config.Config(**cfg))
    sysd.notes = []
    return daemon.Watchdog(clock=lambda: clock[0], notify=lambda t, b: sysd.notes.append(b))


def test_watchdog_thaws_after_the_configured_delay(sysd):
    clock = [1000.0]
    dog = make_dog(sysd, clock, auto_unfreeze=True, auto_unfreeze_seconds=20)
    t, _ = core.resolve(False)
    state.add(t.unit, t.cgroup, t.label, "cli", 1000.0)
    sysd.frozen[t.cgroup] = True
    clock[0] = 1019
    assert dog.step() == []
    clock[0] = 1020
    assert dog.step() == ["Sober"] and sysd.frozen[t.cgroup] is False and state.entries() == {}
    assert sysd.notes == ["Auto-unfroze Sober"]


def test_watchdog_does_nothing_when_auto_unfreeze_is_off(sysd):
    clock = [0.0]
    dog = make_dog(sysd, clock, auto_unfreeze=False)
    t, _ = core.resolve(False)
    state.add(t.unit, t.cgroup, t.label, "cli", 0.0)
    sysd.frozen[t.cgroup] = True
    clock[0] = 10_000
    assert dog.step() == [] and sysd.frozen[t.cgroup] is True


def test_watchdog_picks_up_setting_changes_live(sysd, tmp_path):
    import os
    import time
    clock = [100.0]
    dog = make_dog(sysd, clock, auto_unfreeze=False, auto_unfreeze_seconds=5)
    t, _ = core.resolve(False)
    state.add(t.unit, t.cgroup, t.label, "cli", 100.0)
    sysd.frozen[t.cgroup] = True
    clock[0] = 200
    assert dog.step() == []                                   # off
    config.save(config.Config(auto_unfreeze=True, auto_unfreeze_seconds=5))
    os.utime(config.config_path(), (time.time() + 5, time.time() + 5))   # a distinct mtime
    assert dog.step() == ["Sober"]                            # on, and already past the delay


def test_watchdog_forgets_things_thawed_elsewhere_or_closed(sysd):
    clock = [0.0]
    dog = make_dog(sysd, clock)
    state.add("app-a.scope", "cg/app-a.scope", "A", "cli", 0.0)
    sysd.frozen["cg/app-a.scope"] = False                    # thawed by hand
    state.add("app-b.scope", "cg/app-b.scope", "B", "cli", 0.0)   # cgroup gone -> is_frozen None
    dog.step()
    assert state.entries() == {}


# ---- hold key ---------------------------------------------------------------------------------------
def test_hold_freezes_while_held_and_thaws_on_release_ignoring_autorepeat():
    log = []
    h = daemon.Hold({1, 2}, lambda: log.append("down"), lambda: log.append("up"))
    h.event(1, 1)
    assert log == []
    h.event(2, 1)
    h.event(2, 2)
    h.event(1, 2)
    h.event(99, 1)
    assert log == ["down"]
    h.event(2, 0)
    assert log == ["down", "up"]
    h.event(2, 1)
    assert log == ["down", "up", "down"]
    h.release_all()
    assert log[-1] == "up" and not h.active


def test_hold_action_thaws_the_same_target_it_froze(sysd):
    sysd.focused = (555, "firefox")
    sysd.pid_units[555] = "app-firefox-1.scope"
    act = daemon.HoldAction(focused=True)
    act.down()
    sysd.focused = (1, "other")                               # focus changes while held
    sysd.pid_units[1] = "app-other.scope"
    act.up()
    assert sysd.calls == [("freeze", "app-firefox-1.scope"), ("thaw", "app-firefox-1.scope")]


def test_hold_with_sober_not_running_is_a_noop(sysd):
    sysd.sober_up = False
    act = daemon.HoldAction(focused=False)
    act.down()
    act.up()
    assert sysd.calls == []


# ---- CLI --------------------------------------------------------------------------------------------------
def test_bare_command_toggles_sober(sysd, capsys):
    assert cli.main([]) == 0
    assert "Sober frozen" in capsys.readouterr().out
    assert cli.main([]) == 0
    assert "Sober thawed" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--override-to-focused", "--overrideToFocused"])
@pytest.mark.parametrize("argv_prefix", [[], ["toggle"], ["freeze"]])
def test_override_flag_both_spellings_with_and_without_an_action(sysd, capsys, flag, argv_prefix):
    sysd.focused = (5, "kate")
    sysd.pid_units[5] = "app-kate-1.scope"
    assert cli.main(argv_prefix + [flag]) == 0
    assert sysd.calls[-1] == ("freeze", "app-kate-1.scope")


def test_override_refusal_exits_nonzero_with_a_reason(sysd, capsys):
    sysd.focused = (5, "x")
    sysd.pid_units[5] = "plasma-plasmashell.service"
    assert cli.main(["toggle", "--override-to-focused", "-q"]) == 1
    assert "not freezing the focused window" in capsys.readouterr().err and sysd.calls == []


def test_status_and_list_and_thaw_all(sysd, capsys):
    assert cli.main(["status"]) == 0 and "Sober: running" in capsys.readouterr().out
    cli.main(["freeze", "-q"])
    cli.main(["status"])
    assert "Sober: frozen" in capsys.readouterr().out.splitlines()[-1]
    cli.main(["list"])
    assert "Sober" in capsys.readouterr().out
    assert cli.main(["thaw", "--all"]) == 0
    cli.main(["list"])
    assert "nothing frozen" in capsys.readouterr().out


def test_thaw_all_works_even_when_sober_is_closed(sysd, capsys):
    cli.main(["freeze", "-q"])
    sysd.sober_up = False
    assert cli.main(["thaw", "--all"]) == 0


def test_auto_unfreeze_command_reads_and_writes_the_config(sysd, capsys):
    assert cli.main(["auto-unfreeze"]) == 0
    assert "auto-unfreeze: on (20 s)" in capsys.readouterr().out
    cli.main(["auto-unfreeze", "off"])
    assert config.load().auto_unfreeze is False
    cli.main(["auto-unfreeze", "toggle"])
    assert config.load().auto_unfreeze is True
    cli.main(["auto-unfreeze", "on", "--seconds", "45"])
    assert config.load().auto_unfreeze_seconds == 45
    cli.main(["auto-unfreeze", "--seconds", "100000"])
    assert config.load().auto_unfreeze_seconds == config.MAX_SECONDS


def test_freeze_warns_when_auto_unfreeze_is_on_but_nothing_is_watching(sysd, capsys):
    cli.main(["freeze", "-q"])
    assert "background service isn't running" in capsys.readouterr().out


def test_config_defaults_and_bad_values(tmp_path):
    assert config.load() == config.Config(True, 20)
    f = tmp_path / "c.toml"
    f.write_text('auto_unfreeze = "yes"\nauto_unfreeze_seconds = true\n')
    assert config.load(f) == config.Config(True, 20)


def test_daemon_lock_is_exclusive():
    assert not state.daemon_running()
    held = state.acquire_daemon_lock()
    assert held and state.daemon_running() and state.acquire_daemon_lock() is None
    held.close()
    assert not state.daemon_running()


def test_control_commands_do_not_import_qt():
    import subprocess
    import sys
    code = ("import sys; from sober_freeze import cli; cli.main(['auto-unfreeze']); "
            "assert not any(m.startswith('PySide6') for m in sys.modules)")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
