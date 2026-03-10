from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QListWidgetItem, QLabel, QSpinBox, QLineEdit, QComboBox,
    QGroupBox, QGridLayout, QDialog, QDialogButtonBox,
)
from PySide6.QtCore import Qt, Signal


class WindowsPanel(QWidget):
    command_requested = Signal(str, dict)  # action, params
    window_selected = Signal(int)          # hwnd
    browse_requested = Signal(str)         # path to list

    def __init__(self):
        super().__init__()
        self.windows_cache = []
        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # Window list header + refresh
        top = QHBoxLayout()
        lbl = QLabel("Windows")
        lbl.setStyleSheet("font-weight:bold; font-size:14px;")
        top.addWidget(lbl)
        top.addStretch()
        self.btn_refresh = QPushButton("Refresh")
        top.addWidget(self.btn_refresh)
        root.addLayout(top)

        self.window_list = QListWidget()
        root.addWidget(self.window_list, 1)

        # Open process
        grp_open = QGroupBox("Open Process")
        ol = QHBoxLayout(grp_open)
        self.input_path = QLineEdit()
        self.input_path.setPlaceholderText("Path to executable (e.g. C:\\\\Windows\\\\notepad.exe)")
        ol.addWidget(self.input_path, 1)
        self.btn_browse = QPushButton("Browse")
        ol.addWidget(self.btn_browse)
        self.btn_open = QPushButton("Open")
        ol.addWidget(self.btn_open)
        root.addWidget(grp_open)

        # Window actions
        grp_win = QGroupBox("Window Actions")
        g = QGridLayout(grp_win)
        self.btn_focus = QPushButton("Focus")
        self.btn_minimize = QPushButton("Minimize")
        self.btn_maximize = QPushButton("Maximize")
        self.btn_restore = QPushButton("Restore")
        self.btn_close = QPushButton("Close")
        self.btn_fullscreen = QPushButton("Fullscreen")
        self.btn_windowed = QPushButton("Windowed")
        g.addWidget(self.btn_focus, 0, 0)
        g.addWidget(self.btn_minimize, 0, 1)
        g.addWidget(self.btn_maximize, 0, 2)
        g.addWidget(self.btn_restore, 0, 3)
        g.addWidget(self.btn_close, 1, 0)
        g.addWidget(self.btn_fullscreen, 1, 1)
        g.addWidget(self.btn_windowed, 1, 2)
        root.addWidget(grp_win)

        # Move / Resize
        grp_pos = QGroupBox("Move / Resize")
        pos_lay = QHBoxLayout(grp_pos)
        for name in ("x", "y", "w", "h"):
            pos_lay.addWidget(QLabel(name.upper()))
            sb = QSpinBox()
            sb.setRange(0, 9999)
            sb.setValue(0 if name in ("x", "y") else 800)
            setattr(self, f"spin_{name}", sb)
            pos_lay.addWidget(sb)
        self.btn_move = QPushButton("Apply")
        pos_lay.addWidget(self.btn_move)
        root.addWidget(grp_pos)

        # Mouse
        grp_mouse = QGroupBox("Mouse")
        ml = QHBoxLayout(grp_mouse)
        ml.addWidget(QLabel("X"))
        self.spin_mx = QSpinBox()
        self.spin_mx.setRange(0, 9999)
        ml.addWidget(self.spin_mx)
        ml.addWidget(QLabel("Y"))
        self.spin_my = QSpinBox()
        self.spin_my.setRange(0, 9999)
        ml.addWidget(self.spin_my)
        self.combo_btn = QComboBox()
        self.combo_btn.addItems(["left", "right", "middle"])
        ml.addWidget(self.combo_btn)
        self.btn_click = QPushButton("Click")
        ml.addWidget(self.btn_click)
        self.btn_move_mouse = QPushButton("Move")
        ml.addWidget(self.btn_move_mouse)
        root.addWidget(grp_mouse)

        # Keyboard
        grp_kb = QGroupBox("Keyboard")
        kl = QHBoxLayout(grp_kb)
        self.input_key = QLineEdit()
        self.input_key.setPlaceholderText("Virtual key code (e.g. 13=Enter)")
        kl.addWidget(self.input_key)
        self.btn_key = QPushButton("Send Key")
        kl.addWidget(self.btn_key)
        root.addWidget(grp_kb)

    def _connect_signals(self):
        self.window_list.currentItemChanged.connect(self._on_window_changed)
        self.btn_refresh.clicked.connect(lambda: self.command_requested.emit("list_windows", {}))
        self.btn_browse.clicked.connect(self._open_browser)
        self.btn_open.clicked.connect(self._open_process)
        for action in ("focus", "minimize", "maximize", "restore", "close", "set_fullscreen", "set_windowed"):
            btn = getattr(self, f"btn_{action.replace('set_', '')}")
            btn.clicked.connect(lambda checked=False, a=action: self._win_cmd(a))
        self.btn_move.clicked.connect(self._move_resize)
        self.btn_click.clicked.connect(self._do_click)
        self.btn_move_mouse.clicked.connect(self._do_move_mouse)
        self.btn_key.clicked.connect(self._do_key)

    def _on_window_changed(self, current, _previous):
        if current:
            hwnd = current.data(Qt.UserRole)
            if hwnd is not None:
                self.window_selected.emit(hwnd)

    def _selected_hwnd(self):
        item = self.window_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _win_cmd(self, action):
        hwnd = self._selected_hwnd()
        if hwnd is not None:
            self.command_requested.emit(action, {"hwnd": hwnd})

    def _open_browser(self):
        self._browser_dialog = RemoteFileBrowser(self)
        self._browser_dialog.path_selected.connect(self.input_path.setText)
        self._browser_dialog.browse_requested.connect(
            lambda p: self.command_requested.emit("list_directory", {"path": p, "_browser": True})
        )
        self._browser_dialog.show()
        # Request root listing
        self.command_requested.emit("list_directory", {"path": "", "_browser": True})

    def update_browser(self, entries: list[dict], path: str):
        if hasattr(self, "_browser_dialog") and self._browser_dialog.isVisible():
            self._browser_dialog.update_entries(entries, path)

    def _open_process(self):
        path = self.input_path.text().strip()
        if path:
            self.command_requested.emit("open_process", {"path": path})

    def _move_resize(self):
        hwnd = self._selected_hwnd()
        if hwnd is not None:
            self.command_requested.emit("move_resize", {
                "hwnd": hwnd,
                "x": self.spin_x.value(), "y": self.spin_y.value(),
                "width": self.spin_w.value(), "height": self.spin_h.value(),
            })

    def _do_click(self):
        self.command_requested.emit("click", {
            "x": self.spin_mx.value(), "y": self.spin_my.value(),
            "button": self.combo_btn.currentText(),
        })

    def _do_move_mouse(self):
        self.command_requested.emit("move_mouse", {
            "x": self.spin_mx.value(), "y": self.spin_my.value(),
        })

    def _do_key(self):
        txt = self.input_key.text().strip()
        if txt.isdigit():
            self.command_requested.emit("key_press", {"vk": int(txt)})

    def update_window_list(self, windows: list[dict]):
        self.windows_cache = windows
        self.window_list.clear()
        for w in windows:
            title = w.get("title", "")
            if not title:
                continue
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, w["hwnd"])
            self.window_list.addItem(item)


class RemoteFileBrowser(QDialog):
    path_selected = Signal(str)
    browse_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Browse Remote Files")
        self.setMinimumSize(500, 400)
        self._current_path = ""

        lay = QVBoxLayout(self)

        # Path bar
        path_lay = QHBoxLayout()
        self.btn_up = QPushButton("Up")
        self.btn_up.clicked.connect(self._go_up)
        path_lay.addWidget(self.btn_up)
        self.lbl_path = QLabel("/")
        self.lbl_path.setStyleSheet("font-weight:bold;")
        path_lay.addWidget(self.lbl_path, 1)
        lay.addLayout(path_lay)

        # File list
        self.file_list = QListWidget()
        self.file_list.doubleClicked.connect(self._on_double_click)
        lay.addWidget(self.file_list, 1)

        # Buttons
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def update_entries(self, entries: list[dict], path: str):
        self._current_path = path
        self.lbl_path.setText(path or "Drives")
        self.file_list.clear()
        for entry in entries:
            name = entry["name"]
            is_dir = entry["is_dir"]
            item = QListWidgetItem(f"{'[DIR] ' if is_dir else ''}{name}")
            item.setData(Qt.UserRole, entry)
            self.file_list.addItem(item)

    def _on_double_click(self, index):
        item = self.file_list.currentItem()
        if not item:
            return
        entry = item.data(Qt.UserRole)
        if entry["is_dir"]:
            new_path = entry["name"] if not self._current_path else f"{self._current_path.rstrip(chr(92))}\\{entry['name']}"
            self.browse_requested.emit(new_path)

    def _go_up(self):
        if not self._current_path:
            return
        parent = self._current_path.rstrip("\\")
        if "\\" in parent:
            parent = parent[:parent.rindex("\\")]
            if len(parent) == 2 and parent[1] == ":":
                parent += "\\"
        else:
            parent = ""
        self.browse_requested.emit(parent)

    def _accept(self):
        item = self.file_list.currentItem()
        if item:
            entry = item.data(Qt.UserRole)
            if entry["is_dir"]:
                full = entry["name"] if not self._current_path else f"{self._current_path.rstrip(chr(92))}\\{entry['name']}"
            else:
                full = f"{self._current_path.rstrip(chr(92))}\\{entry['name']}" if self._current_path else entry["name"]
            self.path_selected.emit(full)
        self.accept()
