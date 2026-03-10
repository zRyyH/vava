from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QListWidget, QListWidgetItem
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor


class ClientsPanel(QWidget):
    client_selected = Signal(str)  # client_id

    def __init__(self):
        super().__init__()
        self._clients: dict[str, QListWidgetItem] = {}
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        lbl = QLabel("Clients")
        lbl.setStyleSheet("font-weight:bold; font-size:14px;")
        lay.addWidget(lbl)

        self.list = QListWidget()
        self.list.setMinimumWidth(200)
        self.list.currentItemChanged.connect(self._on_selection)
        lay.addWidget(self.list, 1)

    def _on_selection(self, current, _previous):
        if current:
            self.client_selected.emit(current.data(Qt.UserRole))

    def add_client(self, client_id: str):
        item = QListWidgetItem(f"● {client_id}")
        item.setData(Qt.UserRole, client_id)
        item.setForeground(QColor("#4ec94e"))
        self._clients[client_id] = item
        self.list.addItem(item)

    def remove_client(self, client_id: str):
        item = self._clients.pop(client_id, None)
        if item:
            row = self.list.row(item)
            self.list.takeItem(row)

    def selected_client(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None
