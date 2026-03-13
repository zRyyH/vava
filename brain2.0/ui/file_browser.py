"""
Diálogos para navegar em sistema de arquivos remoto e selecionar executáveis.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
)


class RemoteFileBrowser(QDialog):
    """Navega em diretórios remotos (recebe listagens via sinal)."""

    path_selected   = Signal(str)
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
        if item and item.data(Qt.UserRole)["is_dir"]:
            entry = item.data(Qt.UserRole)
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
            full = (f"{self._current_path.rstrip(sep)}{sep}{entry['name']}"
                    if self._current_path else entry["name"])
            self.path_selected.emit(full)
        self.accept()


class AddPathDialog(QDialog):
    """Diálogo para adicionar um executável à lista de janelas salvas."""

    browse_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Adicionar Janela")
        self.setMinimumWidth(420)
        self._browser: RemoteFileBrowser | None = None

        lay = QFormLayout(self)
        lay.setSpacing(6)

        self._inp_path = QLineEdit()
        self._inp_path.setPlaceholderText(r"ex: C:\Games\App\app.exe")
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
        self._browser = RemoteFileBrowser(self)
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
