from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QListWidgetItem, QLabel, QDialog, QDialogButtonBox, QLineEdit,
    QFormLayout, QGroupBox, QFrame, QGridLayout,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor

import config as _cfg


class WindowsPanel(QWidget):
    """Painel de janelas salvas com monitoramento em tempo real."""

    command_requested = Signal(str, dict)

    def __init__(self):
        super().__init__()
        self._saved: list[dict] = []          # [{path, alias}]
        self._status: dict[str, dict] = {}    # path → {running, windows:[]}
        self._info_fields: dict[str, QLabel] = {}

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(500)
        self._poll_timer.timeout.connect(self._poll)

        self._build_ui()
        self._load()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        lbl = QLabel("Janelas Salvas")
        lbl.setStyleSheet("font-weight:bold; font-size:14px;")
        root.addWidget(lbl)

        self.path_list = QListWidget()
        self.path_list.setToolTip("Duplo clique para abrir o executável no cliente remoto")
        self.path_list.itemDoubleClicked.connect(self._open_selected)
        self.path_list.currentRowChanged.connect(self._on_selection_changed)
        root.addWidget(self.path_list, 1)

        btns = QHBoxLayout()
        btn_add = QPushButton("+ Adicionar")
        btn_add.clicked.connect(self._add_path)
        btns.addWidget(btn_add)
        btn_rm = QPushButton("Remover")
        btn_rm.clicked.connect(self._remove_path)
        btns.addWidget(btn_rm)
        btns.addStretch()
        root.addLayout(btns)

        # ── Info panel ────────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep)

        info_lbl = QLabel("Informações da janela selecionada")
        info_lbl.setStyleSheet("font-weight:bold; font-size:12px;")
        root.addWidget(info_lbl)

        grid = QGridLayout()
        grid.setSpacing(4)
        grid.setColumnMinimumWidth(1, 10)

        fields = [
            ("status",    "Status"),
            ("focused",   "Foco"),
            ("title",     "Título"),
            ("hwnd",      "HWND"),
            ("pid",       "PID"),
            ("tid",       "Thread ID"),
            ("class",     "Classe"),
            ("pos",       "Posição (x, y)"),
            ("size",      "Tamanho (w × h)"),
            ("rect",      "Rect (right, bottom)"),
            ("style",     "Style"),
            ("ex_style",  "ExStyle"),
        ]
        for row, (key, label) in enumerate(fields):
            lbl_k = QLabel(f"{label}:")
            lbl_k.setStyleSheet("color:#888; font-size:11px;")
            lbl_v = QLabel("—")
            lbl_v.setStyleSheet("font-size:11px;")
            lbl_v.setWordWrap(True)
            grid.addWidget(lbl_k, row, 0, Qt.AlignTop)
            grid.addWidget(lbl_v, row, 2, Qt.AlignTop)
            self._info_fields[key] = lbl_v

        root.addLayout(grid)

    # ── Monitoring ────────────────────────────────────────────────────────────

    def start_monitoring(self):
        self._poll_timer.start()
        self._poll()

    def stop_monitoring(self):
        self._poll_timer.stop()

    def _poll(self):
        if not self._saved:
            return
        paths = [e["path"] for e in self._saved]
        self.command_requested.emit("check_processes", {"paths": paths})

    def update_process_status(self, results: list[dict]):
        for r in results:
            path = r.get("path", "")
            if path:
                self._status[path] = r
        self._refresh_list()
        self._refresh_info()

    def _on_selection_changed(self, _row: int):
        self._refresh_info()

    def _refresh_info(self):
        item = self.path_list.currentItem()
        f = self._info_fields
        if item is None:
            for v in f.values():
                v.setText("—")
            return

        entry = item.data(Qt.UserRole)
        if entry is None:
            for v in f.values():
                v.setText("—")
            return

        path = entry["path"]
        status = self._status.get(path)

        if status is None:
            f["status"].setText("Aguardando…")
            f["status"].setStyleSheet("font-size:11px; color:#888;")
            for k in ("focused", "title", "hwnd", "pid", "tid", "class", "pos", "size", "rect", "style", "ex_style"):
                f[k].setText("—")
            return

        if not status.get("running"):
            f["status"].setText("Não encontrada")
            f["status"].setStyleSheet("font-size:11px; color:#e06060;")
            for k in ("focused", "title", "hwnd", "pid", "tid", "class", "pos", "size", "rect", "style", "ex_style"):
                f[k].setText("—")
            return

        windows = status.get("windows", [])
        if not windows:
            f["status"].setText("Processo rodando (sem janela visível)")
            f["status"].setStyleSheet("font-size:11px; color:#f0c040;")
            for k in ("focused", "title", "hwnd", "pid", "tid", "class", "pos", "size", "rect", "style", "ex_style"):
                f[k].setText("—")
            return

        # Prefere janela em foco; senão pega a primeira
        win = next((w for w in windows if w.get("focused")), windows[0])

        if win.get("minimized"):
            s_text, s_color = "Minimizada", "#f0c040"
        elif win.get("maximized"):
            s_text, s_color = "Maximizada", "#4ec94e"
        else:
            s_text, s_color = "Aberta", "#4ec94e"

        f["status"].setText(s_text)
        f["status"].setStyleSheet(f"font-size:11px; color:{s_color}; font-weight:bold;")
        f["focused"].setText("Sim" if win.get("focused") else "Não")
        f["focused"].setStyleSheet(
            "font-size:11px; color:#4ec94e;" if win.get("focused") else "font-size:11px; color:#888;"
        )
        f["title"].setText(win.get("title") or "—")
        f["hwnd"].setText(str(win.get("hwnd", "—")))
        f["pid"].setText(str(win.get("pid", "—")))
        f["tid"].setText(str(win.get("tid", "—")))
        f["class"].setText(win.get("class") or "—")
        f["pos"].setText(f"{win.get('x', '?')},  {win.get('y', '?')}")
        f["size"].setText(f"{win.get('width', '?')} × {win.get('height', '?')}")
        f["rect"].setText(f"right={win.get('right', '?')}  bottom={win.get('bottom', '?')}")
        style = win.get("style")
        f["style"].setText(f"{style:#010x}" if style is not None else "—")
        ex_style = win.get("ex_style")
        f["ex_style"].setText(f"{ex_style:#010x}" if ex_style is not None else "—")

    # ── List display ──────────────────────────────────────────────────────────

    def _refresh_list(self):
        cur = self.path_list.currentRow()
        self.path_list.blockSignals(True)
        self.path_list.clear()
        for entry in self._saved:
            path = entry["path"]
            alias = entry.get("alias") or path.split("\\")[-1]
            status = self._status.get(path)

            if status is None:
                badge = "?"
                color = QColor("#888")
            elif not status.get("running"):
                badge = "✗ Fechado"
                color = QColor("#e06060")
            else:
                windows = status.get("windows", [])
                if any(w["minimized"] for w in windows):
                    badge = "↓ Minimizado"
                    color = QColor("#f0c040")
                elif any(w["maximized"] for w in windows):
                    badge = "▣ Maximizado"
                    color = QColor("#4ec94e")
                else:
                    badge = "✓ Aberto"
                    color = QColor("#4ec94e")

            item = QListWidgetItem(f"{alias}  [{badge}]")
            item.setToolTip(path)
            item.setData(Qt.UserRole, entry)
            item.setForeground(color)
            self.path_list.addItem(item)
        self.path_list.blockSignals(False)
        if 0 <= cur < self.path_list.count():
            self.path_list.setCurrentRow(cur)

    # ── Add / Remove ──────────────────────────────────────────────────────────

    def _add_path(self):
        dlg = _AddPathDialog(self)
        dlg.browse_requested.connect(
            lambda p: self.command_requested.emit("list_directory", {"path": p, "_browser": True})
        )
        if dlg.exec() != QDialog.Accepted:
            return
        path, alias = dlg.result_path(), dlg.result_alias()
        if not path:
            return
        self._saved.append({"path": path, "alias": alias or path.split("\\")[-1]})
        self._refresh_list()
        self._save()
        self._poll()

    def _remove_path(self):
        row = self.path_list.currentRow()
        if row < 0 or row >= len(self._saved):
            return
        del self._saved[row]
        self._refresh_list()
        self._save()

    def _open_selected(self, _item=None):
        item = self.path_list.currentItem()
        if item is None:
            return
        entry = item.data(Qt.UserRole)
        if entry:
            self.command_requested.emit("open_process", {"path": entry["path"]})

    # ── Browser passthrough ───────────────────────────────────────────────────

    def update_browser(self, entries: list[dict], path: str):
        if hasattr(self, "_add_dlg") and self._add_dlg.isVisible():
            self._add_dlg.update_browser(entries, path)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self):
        data = _cfg.load()
        self._saved = data.get("windows_panel", {}).get("saved_paths", [])
        self._refresh_list()

    def _save(self):
        data = _cfg.load()
        data.setdefault("windows_panel", {})["saved_paths"] = self._saved
        _cfg.save(data)


# ── Dialogs ───────────────────────────────────────────────────────────────────

class _AddPathDialog(QDialog):
    """Dialog para adicionar um executável à lista de janelas salvas."""

    browse_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Adicionar Janela")
        self.setMinimumWidth(420)
        self._browser: "_RemoteFileBrowser | None" = None

        lay = QFormLayout(self)
        lay.setSpacing(6)

        self._inp_path = QLineEdit()
        self._inp_path.setPlaceholderText(r"ex: C:\Games\Riot Client\RiotClientServices.exe")
        lay.addRow("Caminho (EXE):", self._inp_path)

        self._inp_alias = QLineEdit()
        self._inp_alias.setPlaceholderText("Deixe vazio para usar o nome do arquivo")
        lay.addRow("Alias:", self._inp_alias)

        btn_browse = QPushButton("Procurar no cliente remoto…")
        btn_browse.clicked.connect(self._open_browser)
        lay.addRow("", btn_browse)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addRow(btns)

    def _open_browser(self):
        self._browser = _RemoteFileBrowser(self)
        self._browser.path_selected.connect(self._inp_path.setText)
        self._browser.browse_requested.connect(self.browse_requested)
        self._browser.show()
        self.browse_requested.emit("")

    def update_browser(self, entries: list[dict], path: str):
        if self._browser and self._browser.isVisible():
            self._browser.update_entries(entries, path)

    def result_path(self) -> str:
        return self._inp_path.text().strip()

    def result_alias(self) -> str:
        return self._inp_alias.text().strip()


class _RemoteFileBrowser(QDialog):
    path_selected = Signal(str)
    browse_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Procurar Arquivos Remotos")
        self.setMinimumSize(500, 400)
        self._current_path = ""

        lay = QVBoxLayout(self)

        path_row = QHBoxLayout()
        self.btn_up = QPushButton("↑ Acima")
        self.btn_up.clicked.connect(self._go_up)
        path_row.addWidget(self.btn_up)
        self.lbl_path = QLabel("/")
        self.lbl_path.setStyleSheet("font-weight:bold;")
        path_row.addWidget(self.lbl_path, 1)
        lay.addLayout(path_row)

        self.file_list = QListWidget()
        self.file_list.doubleClicked.connect(self._on_double_click)
        lay.addWidget(self.file_list, 1)

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
            item = QListWidgetItem(f"{'[DIR] ' if entry['is_dir'] else ''}{name}")
            item.setData(Qt.UserRole, entry)
            self.file_list.addItem(item)

    def _on_double_click(self, _index):
        item = self.file_list.currentItem()
        if not item:
            return
        entry = item.data(Qt.UserRole)
        if entry["is_dir"]:
            sep = "\\"
            new_path = (entry["name"] if not self._current_path
                        else f"{self._current_path.rstrip(sep)}{sep}{entry['name']}")
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
            sep = "\\"
            if self._current_path:
                full = f"{self._current_path.rstrip(sep)}{sep}{entry['name']}"
            else:
                full = entry["name"]
            self.path_selected.emit(full)
        self.accept()
