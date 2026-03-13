from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

import config as _cfg


class ConfigPanel(QWidget):
    """Página de configurações: porta do servidor, Arduino HID e PocketBase."""

    pb_saved         = Signal()      # credenciais PB salvas
    arduino_saved    = Signal(str)   # porta COM configurada
    request_com_ports = Signal()     # solicita portas ao client ativo
    client_selected  = Signal(str)   # client_id escolhido

    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        title = QLabel("Configurações")
        title.setStyleSheet("font-weight:bold; font-size:16px; color:#6ec6f5;")
        root.addWidget(title)

        root.addWidget(self._build_client_group())
        root.addWidget(self._build_server_group())
        root.addWidget(self._build_arduino_group())
        root.addWidget(self._build_pocketbase_group())

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_save = QPushButton("Salvar")
        self._btn_save.setFixedWidth(100)
        self._btn_save.clicked.connect(self._save)
        btn_row.addWidget(self._btn_save)
        root.addLayout(btn_row)
        root.addStretch()

    def _build_client_group(self) -> QGroupBox:
        grp = QGroupBox("Cliente Ativo")
        form = QFormLayout(grp)
        form.setSpacing(8)
        self.combo_client = QComboBox()
        self.combo_client.setPlaceholderText("Nenhum client conectado")
        form.addRow("Client:", self.combo_client)
        self.lbl_client_hint = QLabel("Nenhum client conectado.")
        self.lbl_client_hint.setStyleSheet("color:#888; font-size:10px;")
        form.addRow("", self.lbl_client_hint)
        return grp

    def _build_server_group(self) -> QGroupBox:
        grp = QGroupBox("Servidor")
        form = QFormLayout(grp)
        form.setSpacing(8)
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1024, 65535)
        self.spin_port.setValue(8765)
        self.spin_port.setToolTip(
            "Porta TCP onde o Brain escuta conexões dos clientes.\n"
            "Alterar requer reiniciar a aplicação."
        )
        form.addRow("Porta:", self.spin_port)
        hint = QLabel("⚠ Alterar a porta requer reiniciar a aplicação.")
        hint.setStyleSheet("color:#888; font-size:10px;")
        form.addRow("", hint)
        return grp

    def _build_arduino_group(self) -> QGroupBox:
        grp = QGroupBox("Arduino HID (32u4)")
        form = QFormLayout(grp)
        form.setSpacing(8)

        port_row = QHBoxLayout()
        self.combo_com = QComboBox()
        self.combo_com.setEditable(True)
        self.combo_com.setPlaceholderText("auto-detect")
        self.combo_com.setMinimumWidth(120)
        port_row.addWidget(self.combo_com, 1)

        btn_refresh = QPushButton("↺")
        btn_refresh.setFixedWidth(32)
        btn_refresh.setToolTip("Consultar portas disponíveis no client")
        btn_refresh.clicked.connect(self.request_com_ports)
        port_row.addWidget(btn_refresh)
        form.addRow("Porta COM:", port_row)

        self.lbl_ard_hint = QLabel("Deixe em branco para auto-detectar pelo VID do Arduino.")
        self.lbl_ard_hint.setStyleSheet("color:#888; font-size:10px;")
        form.addRow("", self.lbl_ard_hint)
        return grp

    def _build_pocketbase_group(self) -> QGroupBox:
        grp = QGroupBox("PocketBase")
        form = QFormLayout(grp)
        form.setSpacing(8)

        self.inp_pb_url = QLineEdit()
        self.inp_pb_url.setPlaceholderText("http://localhost:8090")
        form.addRow("URL:", self.inp_pb_url)

        self.inp_pb_email = QLineEdit()
        self.inp_pb_email.setPlaceholderText("admin@example.com")
        form.addRow("E-mail:", self.inp_pb_email)

        self.inp_pb_password = QLineEdit()
        self.inp_pb_password.setEchoMode(QLineEdit.Password)
        self.inp_pb_password.setPlaceholderText("••••••••")
        form.addRow("Senha:", self.inp_pb_password)

        self.lbl_pb_status = QLabel("—")
        self.lbl_pb_status.setStyleSheet("color:#888; font-size:11px;")
        form.addRow("Status:", self.lbl_pb_status)
        return grp

    # ── Clients ───────────────────────────────────────────────────────────────

    def add_client(self, client_id: str):
        self.combo_client.addItem(client_id, userData=client_id)
        count = self.combo_client.count()
        self.lbl_client_hint.setText(f"{count} client(s) conectado(s).")
        if count == 1:
            self.combo_client.setCurrentIndex(0)

    def remove_client(self, client_id: str):
        idx = self.combo_client.findData(client_id)
        if idx >= 0:
            self.combo_client.removeItem(idx)
        count = self.combo_client.count()
        self.lbl_client_hint.setText(
            "Nenhum client conectado." if count == 0 else f"{count} client(s) conectado(s)."
        )

    def set_active_client(self, client_id: str):
        idx = self.combo_client.findData(client_id)
        if idx >= 0:
            self.combo_client.setCurrentIndex(idx)

    def populate_com_ports(self, ports: list[dict]):
        """Recebe lista de dicts {device, description} vindos do client."""
        current = self.combo_com.currentText().strip()
        self.combo_com.clear()
        self.combo_com.addItem("")
        for p in ports:
            device = p.get("device", "")
            desc = p.get("description", device)
            self.combo_com.addItem(f"{device}  —  {desc}", userData=device)
        if current:
            idx = self.combo_com.findText(current)
            if idx >= 0:
                self.combo_com.setCurrentIndex(idx)
            else:
                self.combo_com.setEditText(current)
        self.lbl_ard_hint.setText(f"{len(ports)} porta(s) encontrada(s) no client.")

    def set_pb_status(self, ok: bool, msg: str):
        if ok:
            self.lbl_pb_status.setText(f"✓ {msg}")
            self.lbl_pb_status.setStyleSheet("color:#4ec94e; font-size:11px;")
        else:
            self.lbl_pb_status.setText(f"✗ {msg}")
            self.lbl_pb_status.setStyleSheet("color:#e06060; font-size:11px;")

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self):
        data = _cfg.load()
        self.spin_port.setValue(data.get("server_port", 8765))
        self.combo_com.setEditText(data.get("arduino", {}).get("port", ""))
        pb = data.get("pocketbase", {})
        self.inp_pb_url.setText(pb.get("url", ""))
        self.inp_pb_email.setText(pb.get("email", ""))
        self.inp_pb_password.setText(pb.get("password", ""))

    def _save(self):
        data = _cfg.load()
        data["server_port"] = self.spin_port.value()

        raw_port = self.combo_com.currentText().strip()
        data.setdefault("arduino", {})["port"] = raw_port.split()[0] if raw_port else ""

        pb = data.setdefault("pocketbase", {})
        pb["url"]      = self.inp_pb_url.text().strip()
        pb["email"]    = self.inp_pb_email.text().strip()
        pb["password"] = self.inp_pb_password.text()

        _cfg.save(data)

        self._btn_save.setText("✓ Salvo!")
        QTimer.singleShot(1500, lambda: self._btn_save.setText("Salvar"))

        self.pb_saved.emit()
        self.arduino_saved.emit(data["arduino"]["port"])
        if selected := self.combo_client.currentData():
            self.client_selected.emit(selected)
