from dataclasses import dataclass, field
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QDialog, QDialogButtonBox,
    QLineEdit, QGridLayout, QAbstractItemView,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor


@dataclass
class PixelMonitor:
    name: str
    x: int
    y: int
    exp_r: int
    exp_g: int
    exp_b: int
    tolerance: int = 10
    # runtime state
    cur_r: int = field(default=0, compare=False)
    cur_g: int = field(default=0, compare=False)
    cur_b: int = field(default=0, compare=False)
    active: bool = field(default=False, compare=False)

    def matches(self):
        return (
            abs(self.cur_r - self.exp_r) <= self.tolerance and
            abs(self.cur_g - self.exp_g) <= self.tolerance and
            abs(self.cur_b - self.exp_b) <= self.tolerance
        )


class PixelPanel(QWidget):
    command_requested = Signal(str, dict)

    # columns
    COL_NAME = 0
    COL_XY   = 1
    COL_EXP  = 2
    COL_CUR  = 3
    COL_MATCH = 4

    def __init__(self):
        super().__init__()
        self._monitors: list[PixelMonitor] = []
        self._waiting = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        # Header
        top = QHBoxLayout()
        lbl = QLabel("Pixel Monitors")
        lbl.setStyleSheet("font-weight:bold; font-size:14px;")
        top.addWidget(lbl)
        top.addStretch()

        top.addWidget(QLabel("ms"))
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(16, 5000)
        self.spin_interval.setValue(100)
        self.spin_interval.valueChanged.connect(lambda v: self._timer.setInterval(v))
        top.addWidget(self.spin_interval)

        self.btn_toggle = QPushButton("Start")
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.clicked.connect(self._toggle)
        top.addWidget(self.btn_toggle)
        lay.addLayout(top)

        # Table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Nome", "X, Y", "Esperado", "Atual", "Match"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        lay.addWidget(self.table, 1)

        # Buttons
        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ Adicionar")
        btn_add.clicked.connect(self._add_monitor)
        btn_row.addWidget(btn_add)
        btn_remove = QPushButton("Remover")
        btn_remove.clicked.connect(self._remove_selected)
        btn_row.addWidget(btn_remove)
        btn_row.addStretch()
        lay.addLayout(btn_row)

    def _toggle(self, checked: bool):
        if checked:
            self.btn_toggle.setText("Stop")
            self._timer.start(self.spin_interval.value())
        else:
            self.btn_toggle.setText("Start")
            self._timer.stop()
            self._waiting = False

    def _poll(self):
        if self._waiting or not self._monitors:
            return
        positions = [{"x": m.x, "y": m.y} for m in self._monitors]
        self._waiting = True
        self.command_requested.emit("get_pixels", {"positions": positions})

    def update_pixels(self, results: list[dict]):
        self._waiting = False
        lookup = {(r["x"], r["y"]): r for r in results}
        for i, mon in enumerate(self._monitors):
            pix = lookup.get((mon.x, mon.y))
            if pix:
                mon.cur_r = pix["r"]
                mon.cur_g = pix["g"]
                mon.cur_b = pix["b"]
                mon.active = mon.matches()
            self._update_row(i, mon)

    def _update_row(self, row: int, mon: PixelMonitor):
        exp_color = QColor(mon.exp_r, mon.exp_g, mon.exp_b)
        cur_color = QColor(mon.cur_r, mon.cur_g, mon.cur_b)

        self.table.item(row, self.COL_EXP).setBackground(exp_color)
        self.table.item(row, self.COL_EXP).setForeground(QColor("white") if exp_color.lightness() < 128 else QColor("black"))
        self.table.item(row, self.COL_EXP).setText(f"#{mon.exp_r:02X}{mon.exp_g:02X}{mon.exp_b:02X}")

        self.table.item(row, self.COL_CUR).setBackground(cur_color)
        self.table.item(row, self.COL_CUR).setForeground(QColor("white") if cur_color.lightness() < 128 else QColor("black"))
        self.table.item(row, self.COL_CUR).setText(f"#{mon.cur_r:02X}{mon.cur_g:02X}{mon.cur_b:02X}")

        match_item = self.table.item(row, self.COL_MATCH)
        if mon.active:
            match_item.setText("✓ ATIVO")
            match_item.setForeground(QColor("#4ec94e"))
        else:
            match_item.setText("✗")
            match_item.setForeground(QColor("#e05555"))

    def _add_monitor(self):
        dlg = AddPixelDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        mon = dlg.result_monitor()
        self._monitors.append(mon)
        self._insert_row(len(self._monitors) - 1, mon)

    def _insert_row(self, row: int, mon: PixelMonitor):
        self.table.insertRow(row)
        self.table.setItem(row, self.COL_NAME,  QTableWidgetItem(mon.name))
        self.table.setItem(row, self.COL_XY,    QTableWidgetItem(f"{mon.x}, {mon.y}"))
        self.table.setItem(row, self.COL_EXP,   QTableWidgetItem(""))
        self.table.setItem(row, self.COL_CUR,   QTableWidgetItem(""))
        self.table.setItem(row, self.COL_MATCH, QTableWidgetItem("—"))
        self._update_row(row, mon)

    def _remove_selected(self):
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)
            del self._monitors[row]

    def stop(self):
        self._timer.stop()
        self._waiting = False
        self.btn_toggle.setChecked(False)
        self.btn_toggle.setText("Start")


class AddPixelDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Adicionar Monitor de Pixel")
        lay = QGridLayout(self)

        lay.addWidget(QLabel("Nome:"), 0, 0)
        self.inp_name = QLineEdit("Pixel 1")
        lay.addWidget(self.inp_name, 0, 1, 1, 3)

        lay.addWidget(QLabel("X:"), 1, 0)
        self.spin_x = QSpinBox(); self.spin_x.setRange(0, 9999)
        lay.addWidget(self.spin_x, 1, 1)
        lay.addWidget(QLabel("Y:"), 1, 2)
        self.spin_y = QSpinBox(); self.spin_y.setRange(0, 9999)
        lay.addWidget(self.spin_y, 1, 3)

        lay.addWidget(QLabel("R esperado:"), 2, 0)
        self.spin_r = QSpinBox(); self.spin_r.setRange(0, 255)
        lay.addWidget(self.spin_r, 2, 1)
        lay.addWidget(QLabel("G:"), 2, 2)
        self.spin_g = QSpinBox(); self.spin_g.setRange(0, 255)
        lay.addWidget(self.spin_g, 2, 3)

        lay.addWidget(QLabel("B:"), 3, 0)
        self.spin_b = QSpinBox(); self.spin_b.setRange(0, 255)
        lay.addWidget(self.spin_b, 3, 1)
        lay.addWidget(QLabel("Tolerância:"), 3, 2)
        self.spin_tol = QSpinBox(); self.spin_tol.setRange(0, 255); self.spin_tol.setValue(10)
        lay.addWidget(self.spin_tol, 3, 3)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns, 4, 0, 1, 4)

    def result_monitor(self) -> PixelMonitor:
        return PixelMonitor(
            name=self.inp_name.text() or "Pixel",
            x=self.spin_x.value(),
            y=self.spin_y.value(),
            exp_r=self.spin_r.value(),
            exp_g=self.spin_g.value(),
            exp_b=self.spin_b.value(),
            tolerance=self.spin_tol.value(),
        )
