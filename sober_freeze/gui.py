"""A small control window: freeze/thaw Sober or the focused app, see what's frozen, and the
auto-unfreeze setting.  Everything goes through the same modules the CLI uses."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QCheckBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

from . import config as config_mod
from . import core, state, units

FOCUS_DELAY = 3


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sober Freeze")
        self.setMinimumWidth(420)
        self._building = False
        self._countdown = 0
        col = QVBoxLayout(self)

        self.sober_label = QLabel()
        self.sober_label.setStyleSheet("font-size: 15pt; font-weight: 600;")
        col.addWidget(self.sober_label)
        row = QHBoxLayout()
        self.btn_freeze = QPushButton("Freeze Sober")
        self.btn_thaw = QPushButton("Thaw Sober")
        self.btn_toggle = QPushButton("Toggle")
        for b, fn in ((self.btn_freeze, lambda: self._do("freeze", False)),
                      (self.btn_thaw, lambda: self._do("thaw", False)),
                      (self.btn_toggle, lambda: self._do("toggle", False))):
            b.clicked.connect(fn)
            row.addWidget(b)
        col.addLayout(row)

        self.btn_focused = QPushButton()
        self.btn_focused.clicked.connect(self._start_focused)
        col.addWidget(self.btn_focused)
        self._reset_focused_button()

        col.addWidget(QLabel("Frozen by sober-freeze:"))
        self.frozen = QListWidget()
        self.frozen.setMaximumHeight(110)
        col.addWidget(self.frozen)
        row = QHBoxLayout()
        self.btn_thaw_sel = QPushButton("Thaw selected")
        self.btn_thaw_sel.clicked.connect(self._thaw_selected)
        self.btn_thaw_all = QPushButton("Thaw all")
        self.btn_thaw_all.clicked.connect(self._thaw_all)
        row.addWidget(self.btn_thaw_sel)
        row.addWidget(self.btn_thaw_all)
        col.addLayout(row)

        col.addWidget(QLabel("Auto-unfreeze"))
        row = QHBoxLayout()
        self.auto = QCheckBox("Thaw automatically after")
        self.seconds = QSpinBox()
        self.seconds.setRange(config_mod.MIN_SECONDS, config_mod.MAX_SECONDS)
        self.seconds.setSuffix(" s")
        self.seconds.setSingleStep(5)
        self.auto.toggled.connect(self._config_edited)
        self.seconds.valueChanged.connect(self._config_edited)
        row.addWidget(self.auto)
        row.addWidget(self.seconds)
        row.addStretch()
        col.addLayout(row)

        self.daemon_label = QLabel()
        self.daemon_label.setWordWrap(True)
        col.addWidget(self.daemon_label)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        col.addWidget(self.message)

        self._load_config()
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    # -- config ---------------------------------------------------------------------------------
    def _load_config(self) -> None:
        self._building = True
        cfg = config_mod.load()
        self.auto.setChecked(cfg.auto_unfreeze)
        self.seconds.setValue(cfg.auto_unfreeze_seconds)
        self.seconds.setEnabled(cfg.auto_unfreeze)
        self._building = False

    def _config_edited(self, *_):
        if self._building:
            return
        cfg = config_mod.Config(self.auto.isChecked(), self.seconds.value()).sanitize()
        config_mod.save(cfg)
        self.seconds.setEnabled(cfg.auto_unfreeze)

    # -- actions ---------------------------------------------------------------------------------
    def _say(self, res: core.Result) -> None:
        self.message.setText(res.message)
        self.refresh()

    def _do(self, what: str, focused: bool) -> None:
        t, err = core.resolve(focused)
        if t is None:
            self._say(core.Result(False, err))
            return
        self._say(getattr(core, what)(t))

    def _start_focused(self) -> None:
        if self._countdown:
            return
        self._countdown = FOCUS_DELAY
        self._tick_focused()

    def _tick_focused(self) -> None:
        if self._countdown > 0:
            self.btn_focused.setText(f"Switch to the window now… toggling in {self._countdown}")
            self._countdown -= 1
            QTimer.singleShot(1000, self._tick_focused)
        else:
            self._reset_focused_button()
            self._do("toggle", True)

    def _reset_focused_button(self) -> None:
        self.btn_focused.setText(f"Toggle the focused window  (waits {FOCUS_DELAY} s so you can switch to it)")

    def _thaw_selected(self) -> None:
        item = self.frozen.currentItem()
        if item is None:
            return
        unit = item.data(Qt.ItemDataRole.UserRole)
        e = state.entries().get(unit, {})
        self._say(core.thaw(core.Target(unit, e.get("cgroup", ""), e.get("label", unit))))

    def _thaw_all(self) -> None:
        results = core.thaw_all()
        self.message.setText("; ".join(r.message for r in results) or "nothing frozen by sober-freeze")
        self.refresh()

    # -- refresh -----------------------------------------------------------------------------------
    def refresh(self) -> None:
        unit = units.sober_unit()
        if unit is None:
            self.sober_label.setText("Sober: not running")
            sober_up = False
        else:
            cg = units.cgroup_of(unit)
            frozen = bool(cg and units.is_frozen(cg))
            self.sober_label.setText("Sober: " + ("FROZEN" if frozen else "running"))
            sober_up = True
        for b in (self.btn_freeze, self.btn_thaw, self.btn_toggle):
            b.setEnabled(sober_up)
        selected = self.frozen.currentItem().data(Qt.ItemDataRole.UserRole) if self.frozen.currentItem() else None
        self.frozen.clear()
        now = time.time()
        for unit, e in state.entries().items():
            item = QListWidgetItem(f"{e.get('label', unit)}  —  {int(now - float(e.get('since', now)))} s")
            item.setData(Qt.ItemDataRole.UserRole, unit)
            self.frozen.addItem(item)
            if unit == selected:
                self.frozen.setCurrentItem(item)
        up = state.daemon_running()
        self.daemon_label.setText(
            "Background service: running." if up else
            "Background service: NOT running — auto-unfreeze and the hold key need it "
            "(enable services.sober-freeze, or run `sober-freeze daemon`).")


def run() -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("sober-freeze")
    w = Window()
    w.show()
    return app.exec()
