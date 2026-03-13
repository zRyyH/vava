from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

import config as _cfg
import pocketbase_client as _pb
from hotkey import GlobalHotkey
from server import WinControlServer
from ui.config_panel import ConfigPanel
from ui.log_panel import LogPanel
from ui.macro import MacroPanel
from ui.styles import DARK_STYLE

# ── Constantes de layout ──────────────────────────────────────────────────────

_ICON_BAR_W  = 54
_PAGE_BAR_W  = 220

_ICON_BTN_STYLE = """
QPushButton {
    border: none; border-radius: 6px; background: transparent;
    font-size: 20px; color: #666; padding: 0;
}
QPushButton:hover  { background: #2a2a2a; color: #ccc; }
QPushButton:checked {
    background: #1a3a5c; color: #6ec6f5;
    border-left: 3px solid #6ec6f5; border-radius: 0;
}
"""


class _PBAuthThread(QThread):
    success = Signal(str)
    failure = Signal(str)

    def __init__(self, url: str, email: str, password: str, parent=None):
        super().__init__(parent)
        self._url      = url
        self._email    = email
        self._password = password

    def run(self):
        try:
            client = _pb.init_shared(self._url, self._email, self._password)
            self.success.emit(client.authenticate())
        except Exception as exc:
            self.failure.emit(str(exc))


class _SidebarPage(QWidget):
    def __init__(self, title: str, embedded: QWidget | None = None):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 14, 10, 8)
        lay.setSpacing(8)
        lbl = QLabel(title.upper())
        lbl.setStyleSheet("color:#888; font-size:10px; font-weight:bold; letter-spacing:1px;")
        lay.addWidget(lbl)
        if embedded is not None:
            lay.addWidget(embedded, 1)
        else:
            lay.addStretch(1)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Brain — Win Control")
        self.setMinimumSize(1100, 640)

        self.server = WinControlServer()
        self._active_client: str | None = None
        self._connected_clients: set[str] = set()
        self._last_window_count: int | None = None

        self._build_ui()
        self._connect_signals()
        self._load_config()
        self.server.start()
        self._hotkey = GlobalHotkey(self)
        self._hotkey.triggered.connect(self._on_stop_hotkey)
        self._hotkey.start()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # icon bar
        icon_bar = QWidget()
        icon_bar.setObjectName("iconbar")
        icon_bar.setFixedWidth(_ICON_BAR_W)
        icon_bar.setStyleSheet("QWidget#iconbar { background:#151515; border-right:1px solid #2e2e2e; }")
        ib_lay = QVBoxLayout(icon_bar)
        ib_lay.setContentsMargins(4, 8, 4, 8)
        ib_lay.setSpacing(2)

        brand = QLabel("⬡")
        brand.setAlignment(Qt.AlignCenter)
        brand.setStyleSheet("font-size:22px; color:#6ec6f5; padding:8px 0 16px 0;")
        ib_lay.addWidget(brand)

        self._icon_buttons: list[QPushButton] = []
        self._stacked      = QStackedWidget()
        self._page_stacked = QStackedWidget()

        page_sidebar = QWidget()
        page_sidebar.setObjectName("pagesidebar")
        page_sidebar.setFixedWidth(_PAGE_BAR_W)
        page_sidebar.setStyleSheet(
            "QWidget#pagesidebar { background:#1a1a1a; border-right:1px solid #2e2e2e; }"
        )
        ps_lay = QVBoxLayout(page_sidebar)
        ps_lay.setContentsMargins(0, 0, 0, 0)
        ps_lay.addWidget(self._page_stacked)

        # panels
        self.macro_panel  = MacroPanel()
        self.config_panel = ConfigPanel()
        self.log_panel    = LogPanel()

        for icon, tooltip, panel in [
            ("⚡", "Automação",   self.macro_panel),
            ("⚙", "Configuração", self.config_panel),
            ("📋", "Logs",        self.log_panel),
        ]:
            self._add_page(icon, tooltip, _SidebarPage(tooltip), panel, ib_lay)

        ib_lay.addStretch(1)

        right = QWidget()
        right_lay = QHBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)
        right_lay.addWidget(page_sidebar)
        right_lay.addWidget(self._stacked, 1)

        root.addWidget(icon_bar)
        root.addWidget(right, 1)

        self._switch_page(0)
        self.statusBar().showMessage("Iniciando servidor…")
        self.setStyleSheet(DARK_STYLE)

    def _add_page(self, icon: str, tooltip: str,
                  sidebar: QWidget, main: QWidget, ib_lay):
        btn = QPushButton(icon)
        btn.setCheckable(True)
        btn.setToolTip(tooltip)
        btn.setStyleSheet(_ICON_BTN_STYLE)
        btn.setFixedSize(_ICON_BAR_W - 8, 44)
        idx = len(self._icon_buttons)
        self._page_stacked.addWidget(sidebar)
        self._stacked.addWidget(main)
        btn.clicked.connect(lambda _, i=idx: self._switch_page(i))
        self._icon_buttons.append(btn)
        ib_lay.addWidget(btn, 0, Qt.AlignHCenter)

    def _switch_page(self, index: int):
        self._page_stacked.setCurrentIndex(index)
        self._stacked.setCurrentIndex(index)
        for i, btn in enumerate(self._icon_buttons):
            btn.setChecked(i == index)

    # ── Signals ───────────────────────────────────────────────────────────────

    def _connect_signals(self):
        self.server.status_changed.connect(self.statusBar().showMessage)
        self.server.status_changed.connect(lambda m: self.log_panel.log("info", m))
        self.server.client_connected.connect(self._on_client_connected)
        self.server.client_disconnected.connect(self._on_client_disconnected)
        self.server.response_received.connect(self._on_response)

        self.macro_panel.command_requested.connect(self._send_command)
        self.macro_panel.log_event.connect(self.log_panel.log)

        self.config_panel.pb_saved.connect(self._pb_login)
        self.config_panel.arduino_saved.connect(self._on_arduino_port_saved)
        self.config_panel.request_com_ports.connect(self._request_com_ports)
        self.config_panel.client_selected.connect(self._on_client_selected)

    def _request_com_ports(self):
        if not self._active_client:
            self.log_panel.log("info", "Nenhum client conectado para consultar portas COM.")
            return
        self._send_command("list_com_ports", {"_silent": True})

    def _on_arduino_port_saved(self, port: str):
        for cid in list(self._connected_clients):
            prev = self._active_client
            self._active_client = cid
            self._send_command("init_hid", {"port": port} if port else {})
            self._active_client = prev
        self.log_panel.log("info", f"Arduino HID: porta → {port or 'auto-detect'}")

    def _on_client_connected(self, client_id: str):
        self._connected_clients.add(client_id)
        self.config_panel.add_client(client_id)
        arduino_port = _cfg.load().get("arduino", {}).get("port", "")
        prev = self._active_client
        self._active_client = client_id
        self._send_command("init_hid", {"port": arduino_port} if arduino_port else {})
        self._active_client = prev
        if self._active_client is None:
            self._on_client_selected(client_id)

    def _on_client_disconnected(self, client_id: str):
        self._connected_clients.discard(client_id)
        self.config_panel.remove_client(client_id)
        self.log_panel.log("info", f"Cliente desconectado: {client_id}")
        if self._active_client == client_id:
            self._active_client = None
            self.macro_panel.stop()

    def _on_client_selected(self, client_id: str):
        self._active_client = client_id
        self.config_panel.set_active_client(client_id)
        self.log_panel.log("info", f"Cliente ativo: {client_id}")
        self.macro_panel.stop()
        self.macro_panel.start_monitoring()
        self._send_command("list_windows", {})

    def _send_command(self, action: str, params: dict):
        if not self._active_client:
            self.statusBar().showMessage("No client selected")
            return
        silent = params.pop("_silent", False)
        if not silent and action not in ("get_pixels", "match_templates",
                                         "check_processes", "get_window_state"):
            param_str = ", ".join(f"{k}={v}" for k, v in params.items()) if params else "—"
            self.log_panel.log("cmd", f"{action}  {param_str}")
        self.server.send_command(self._active_client, action, params or None)

    def _on_response(self, client_id: str, msg: dict):
        if client_id != self._active_client:
            return

        action = msg.get("action", "")
        if not msg.get("ok", False):
            err = msg.get("error", "?")
            self.statusBar().showMessage(f"Error: {err}")
            self.log_panel.log("error", f"{action} → {err}")
            return

        if action == "list_windows":
            windows = msg.get("data") or []
            self.macro_panel.update_remote_windows(windows)
            if self._last_window_count != len(windows):
                self.log_panel.log("resp", f"list_windows → {len(windows)} janelas")
            self._last_window_count = len(windows)

        elif action == "check_processes":
            results = (msg.get("data") or {}).get("results") or []
            self.macro_panel.update_process_status(results)

        elif action == "get_window_state":
            data = msg.get("data") or {}
            if data.get("hwnd"):
                self.macro_panel.update_window_state(data)

        elif action == "list_com_ports":
            ports = (msg.get("data") or {}).get("ports", [])
            self.config_panel.populate_com_ports(ports)
            self.log_panel.log("resp", f"list_com_ports → {len(ports)} porta(s)")

        elif action == "window_action":
            self.log_panel.log("resp", "window_action → ok")
            self._send_command("list_windows", {})

        elif action == "get_pixels":
            self.macro_panel.update_pixels(msg.get("data") or [])

        elif action == "match_templates":
            self.macro_panel.update_image_matches((msg.get("data") or {}).get("results") or [])

        elif action == "open_process":
            pid = msg.get("data", {}).get("pid", "?")
            self.statusBar().showMessage(f"Process opened: PID {pid}")
            self.log_panel.log("resp", f"open_process → PID {pid}")
            self._send_command("list_windows", {})

        elif action == "list_directory":
            data = msg.get("data") or {}
            path    = data.get("path", "")
            entries = data.get("entries", [])
            self.macro_panel.update_browser(entries, path)
            self.log_panel.log("resp", f"list_directory → {path}  ({len(entries)} itens)")

        else:
            self.log_panel.log("resp", f"{action} → ok")

    def _on_stop_hotkey(self):
        self.macro_panel.stop()
        self.log_panel.log("info", "⏹ Parado via Shift+Backspace")
        self.statusBar().showMessage("Polling parado")

    # ── Persistência ──────────────────────────────────────────────────────────

    def _load_config(self):
        data = _cfg.load()
        if macros_data := data.get("macros"):
            self.macro_panel.load_state(macros_data)
            self.log_panel.log("info", "Config carregado")
        if geo := data.get("geometry"):
            self.restoreGeometry(bytes.fromhex(geo))
        self._pb_login()

    def _pb_login(self):
        pb = _cfg.load().get("pocketbase", {})
        url   = pb.get("url", "").strip()
        email = pb.get("email", "").strip()
        if not url or not email:
            return
        self._pb_thread = _PBAuthThread(url, email, pb.get("password", ""), self)
        self._pb_thread.success.connect(self._on_pb_auth_ok)
        self._pb_thread.failure.connect(self._on_pb_auth_fail)
        self.log_panel.log("info", "PocketBase: autenticando…")
        self._pb_thread.start()

    def _on_pb_auth_ok(self, _token: str):
        self.log_panel.log("info", "PocketBase: sessão iniciada ✓")
        self.statusBar().showMessage("PocketBase OK", 3000)
        self.config_panel.set_pb_status(True, "sessão iniciada")

    def _on_pb_auth_fail(self, err: str):
        self.log_panel.log("error", f"PocketBase: falha no login — {err}")
        self.config_panel.set_pb_status(False, err)

    def closeEvent(self, event):
        data = _cfg.load()
        data["macros"]   = self.macro_panel.dump_state()
        data["geometry"] = bytes(self.saveGeometry()).hex()
        _cfg.save(data)
        self._hotkey.stop()
        super().closeEvent(event)
