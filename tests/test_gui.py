import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

from sober_freeze import config, core, gui, state
from test_core import FakeSystem  # noqa: F401  (fixture helper)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp, monkeypatch):
    sysd = FakeSystem(monkeypatch)
    w = gui.Window()
    w.timer.stop()
    yield w, sysd
    w.close()


def test_gui_shows_status_and_buttons_freeze_and_thaw_sober(win):
    w, sysd = win
    assert w.sober_label.text() == "Sober: running"
    w.btn_freeze.click()
    assert w.sober_label.text() == "Sober: FROZEN" and w.frozen.count() == 1
    w.btn_thaw.click()
    assert w.sober_label.text() == "Sober: running" and w.frozen.count() == 0


def test_gui_buttons_disabled_when_sober_is_closed(win):
    w, sysd = win
    sysd.sober_up = False
    w.refresh()
    assert w.sober_label.text() == "Sober: not running" and not w.btn_freeze.isEnabled()


def test_gui_auto_unfreeze_controls_write_the_config_file(win):
    w, _ = win
    assert w.auto.isChecked() and w.seconds.value() == 20
    w.seconds.setValue(35)
    assert config.load().auto_unfreeze_seconds == 35
    w.auto.setChecked(False)
    assert config.load().auto_unfreeze is False and not w.seconds.isEnabled()


def test_gui_loads_existing_config(qapp, monkeypatch):
    FakeSystem(monkeypatch)
    config.save(config.Config(False, 90))
    w = gui.Window()
    w.timer.stop()
    assert not w.auto.isChecked() and w.seconds.value() == 90
    w.close()


def test_gui_focused_toggle_counts_down_then_acts_on_the_focused_window(win, monkeypatch):
    w, sysd = win
    sysd.focused = (5, "kate")
    sysd.pid_units[5] = "app-kate-1.scope"
    w._countdown = 0
    monkeypatch.setattr(gui.QTimer, "singleShot", staticmethod(lambda ms, fn: None))   # drive it by hand
    w._start_focused()
    assert "toggling in 3" in w.btn_focused.text()
    w._tick_focused(); w._tick_focused(); w._tick_focused()
    assert sysd.calls[-1] == ("freeze", "app-kate-1.scope")
    assert w.frozen.count() == 1
    w.frozen.setCurrentRow(0)
    w._thaw_selected()
    assert sysd.calls[-1] == ("thaw", "app-kate-1.scope") and w.frozen.count() == 0
