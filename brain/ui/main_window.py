from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter
from PySide6.QtCore import Qt, QThread, Signal

from server import WinControlServer
from ui.clients_panel import ClientsPanel
from ui.windows_panel import WindowsPanel
from ui.macro_panel import MacroPanel
from ui.log_panel import LogPanel
from ui.styles import DARK_STYLE
from hotkey import GlobalHotkey
import config as _cfg
import pocketbase_client as _pb


class _PBAuthThread(QThread):
    """Faz login no PocketBase em background e emite o resultado."""
    success = Signal(str)   # token
    failure = Signal(str)   # mensagem de erro

    def __init__(self, url: str, email: str, password: str, parent=None):
        super().__init__(parent)
        self._url = url
        self._email = email
        self._password = password

    def run(self):
        try:
            client = _pb.init_shared(self._url, self._email, self._password)
            token = client.authenticate()
            self.success.emit(token)
        except Exception as exc:
            self.failure.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Brain — Win Control")
        self.setMinimumSize(1100, 620)

        self.server = WinControlServer()
        self._active_client: str | None = None

        self._build_ui()
        self._connect_signals()
        self._load_config()
        self.server.start()
        self._hotkey = GlobalHotkey(self)
        self._hotkey.triggered.connect(self._on_stop_hotkey)
        self._hotkey.start()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(0)

        # ── painel principal (horizontal) ──
        top_widget = QWidget()
        root = QHBoxLayout(top_widget)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.clients_panel = ClientsPanel()
        root.addWidget(self.clients_panel)

        self.windows_panel = WindowsPanel()
        root.addWidget(self.windows_panel, 1)

        self.macro_panel = MacroPanel()
        root.addWidget(self.macro_panel, 3)

        # ── log panel ──
        self.log_panel = LogPanel()
        self.log_panel.setMinimumHeight(80)

        self._vsplit = QSplitter(Qt.Vertical)
        self._vsplit.addWidget(top_widget)
        self._vsplit.addWidget(self.log_panel)
        self._vsplit.setStretchFactor(0, 4)
        self._vsplit.setStretchFactor(1, 1)
        self._vsplit.setSizes([480, 160])
        outer.addWidget(self._vsplit)

        self.statusBar().showMessage("Starting server...")
        self.setStyleSheet(DARK_STYLE)

    def _connect_signals(self):
        self.server.status_changed.connect(self.statusBar().showMessage)
        self.server.status_changed.connect(lambda m: self.log_panel.log("info", m))
        self.server.client_connected.connect(self._on_client_connected)
        self.server.client_disconnected.connect(self._on_client_disconnected)
        self.server.response_received.connect(self._on_response)

        self.clients_panel.client_selected.connect(self._on_client_selected)
        self.windows_panel.command_requested.connect(self._send_command)
        self.macro_panel.command_requested.connect(self._send_command)
        self.macro_panel.log_event.connect(self.log_panel.log)

    def _on_client_connected(self, client_id: str):
        self.clients_panel.add_client(client_id)
        self.log_panel.log("info", f"Cliente conectado: {client_id}")

    def _on_client_disconnected(self, client_id: str):
        self.clients_panel.remove_client(client_id)
        self.log_panel.log("info", f"Cliente desconectado: {client_id}")
        if self._active_client == client_id:
            self._active_client = None
            self.macro_panel.stop()
            self.windows_panel.update_window_list([])

    def _on_client_selected(self, client_id: str):
        self._active_client = client_id
        self.log_panel.log("info", f"Cliente ativo: {client_id}")
        self.macro_panel.stop()
        self._send_command("list_windows", {})

    def _send_command(self, action: str, params: dict):
        if not self._active_client:
            self.statusBar().showMessage("No client selected")
            return
        # não loga comandos de polling (muito frequentes)
        if action not in ("get_pixels", "match_templates"):
            param_str = ", ".join(f"{k}={v}" for k, v in params.items()) if params else "—"
            self.log_panel.log("cmd", f"{action}  {param_str}")
        self.server.send_command(self._active_client, action, **params)

    def _on_response(self, client_id: str, msg: dict):
        if client_id != self._active_client:
            return

        action = msg.get("action", "")
        ok = msg.get("ok", False)

        if not ok:
            err = msg.get("error", "?")
            self.statusBar().showMessage(f"Error: {err}")
            self.log_panel.log("error", f"{action} → {err}")
            return

        if action == "list_windows":
            windows = msg.get("data") or []
            self.windows_panel.update_window_list(windows)
            self.macro_panel.update_remote_windows(windows)
            n = self.windows_panel.window_list.count()
            self.statusBar().showMessage(f"{n} windows")
            self.log_panel.log("resp", f"list_windows → {n} janelas")

        elif action == "get_pixels":
            self.macro_panel.update_pixels(msg.get("data") or [])

        elif action == "match_templates":
            data = msg.get("data") or {}
            self.macro_panel.update_image_matches(data.get("results") or [])

        elif action == "open_process":
            pid = msg.get("data", {}).get("pid", "?")
            self.statusBar().showMessage(f"Process opened: PID {pid}")
            self.log_panel.log("resp", f"open_process → PID {pid}")
            self._send_command("list_windows", {})

        elif action == "list_directory":
            data = msg.get("data") or {}
            path = data.get("path", "")
            entries = data.get("entries", [])
            self.windows_panel.update_browser(entries, path)
            self.log_panel.log("resp", f"list_directory → {path}  ({len(entries)} itens)")

        else:
            self.log_panel.log("resp", f"{action} → ok")

    def _on_stop_hotkey(self):
        self.macro_panel.stop()
        self.log_panel.log("info", "⏹ Parado via Shift+Backspace")
        self.statusBar().showMessage("Polling stopped")

    # ── Persistência ──────────────────────────────────────────────────────────

    def _load_config(self):
        data = _cfg.load()
        macros_data = data.get("macros")
        if macros_data:
            self.macro_panel.load_state(macros_data)
            self.log_panel.log("info", f"Config carregado — {len(macros_data.get('items', []))} macro(s)")

        geo = data.get("geometry")
        if geo:
            self.restoreGeometry(bytes.fromhex(geo))

        splitter_sizes = data.get("log_splitter")
        if splitter_sizes and hasattr(self, "_vsplit"):
            self._vsplit.setSizes(splitter_sizes)

        self._pb_login()

    def _pb_login(self):
        """Inicia login no PocketBase em background usando as credenciais salvas."""
        pb = _cfg.load().get("pocketbase", {})
        url = pb.get("url", "").strip()
        email = pb.get("email", "").strip()
        password = pb.get("password", "")
        if not url or not email:
            return
        self._pb_thread = _PBAuthThread(url, email, password, self)
        self._pb_thread.success.connect(self._on_pb_auth_ok)
        self._pb_thread.failure.connect(self._on_pb_auth_fail)
        self.log_panel.log("info", "PocketBase: autenticando…")
        self._pb_thread.start()

    def _on_pb_auth_ok(self, token: str):
        self.log_panel.log("info", f"PocketBase: sessão iniciada ✓")
        self.statusBar().showMessage("PocketBase OK", 3000)

    def _on_pb_auth_fail(self, err: str):
        self.log_panel.log("error", f"PocketBase: falha no login — {err}")

    def closeEvent(self, event):
        data = _cfg.load()
        data["macros"] = self.macro_panel.dump_state()
        data["geometry"] = bytes(self.saveGeometry()).hex()
        if hasattr(self, "_vsplit"):
            data["log_splitter"] = self._vsplit.sizes()
        _cfg.save(data)
        self._hotkey.stop()
        super().closeEvent(event)
