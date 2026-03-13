from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QGroupBox,
    QLineEdit, QPushButton, QLabel, QSpinBox, QHBoxLayout, QComboBox,
)
from PySide6.QtCore import Signal

import config as _cfg


class ConfigPanel(QWidget):
    """Página de configurações: porta do servidor, Arduino HID e credenciais do PocketBase."""

    pb_saved = Signal()           # emitido quando credenciais PB são salvas
    arduino_saved = Signal(str)   # porta COM configurada
    request_com_ports = Signal()  # pede ao main_window que consulte o client
    client_selected = Signal(str) # client_id escolhido ao salvar

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

        # ── Cliente Ativo ─────────────────────────────────────────────────────
        grp_cli = QGroupBox("Cliente Ativo")
        cf = QFormLayout(grp_cli)
        cf.setSpacing(8)

        self.combo_client = QComboBox()
        self.combo_client.setPlaceholderText("Nenhum client conectado")
        cf.addRow("Client:", self.combo_client)

        self.lbl_client_hint = QLabel("Nenhum client conectado.")
        self.lbl_client_hint.setStyleSheet("color:#888; font-size:10px;")
        cf.addRow("", self.lbl_client_hint)

        root.addWidget(grp_cli)

        # ── Servidor ──────────────────────────────────────────────────────────
        grp_srv = QGroupBox("Servidor")
        sf = QFormLayout(grp_srv)
        sf.setSpacing(8)

        self.spin_port = QSpinBox()
        self.spin_port.setRange(1024, 65535)
        self.spin_port.setValue(8765)
        self.spin_port.setToolTip(
            "Porta TCP onde o Brain escuta conexões dos clientes.\n"
            "Alterar requer reiniciar a aplicação."
        )
        sf.addRow("Porta do servidor:", self.spin_port)

        lbl_port_hint = QLabel("⚠ Alterar a porta requer reiniciar a aplicação.")
        lbl_port_hint.setStyleSheet("color:#888; font-size:10px;")
        sf.addRow("", lbl_port_hint)

        root.addWidget(grp_srv)

        # ── Arduino HID ───────────────────────────────────────────────────────
        grp_ard = QGroupBox("Arduino HID (32u4)")
        af = QFormLayout(grp_ard)
        af.setSpacing(8)

        port_row = QHBoxLayout()
        self.combo_com = QComboBox()
        self.combo_com.setEditable(True)
        self.combo_com.setPlaceholderText("auto-detect")
        self.combo_com.setMinimumWidth(120)
        port_row.addWidget(self.combo_com, 1)

        self._btn_refresh_ports = QPushButton("↺")
        self._btn_refresh_ports.setFixedWidth(32)
        self._btn_refresh_ports.setToolTip("Consultar portas disponíveis no client")
        self._btn_refresh_ports.clicked.connect(self.request_com_ports)
        port_row.addWidget(self._btn_refresh_ports)

        af.addRow("Porta COM:", port_row)

        self.lbl_ard_hint = QLabel("Deixe em branco para auto-detectar pelo VID do Arduino.")
        self.lbl_ard_hint.setStyleSheet("color:#888; font-size:10px;")
        af.addRow("", self.lbl_ard_hint)

        root.addWidget(grp_ard)

        # ── PocketBase ────────────────────────────────────────────────────────
        grp_pb = QGroupBox("PocketBase")
        pf = QFormLayout(grp_pb)
        pf.setSpacing(8)

        self.inp_pb_url = QLineEdit()
        self.inp_pb_url.setPlaceholderText("http://localhost:8090")
        pf.addRow("URL:", self.inp_pb_url)

        self.inp_pb_email = QLineEdit()
        self.inp_pb_email.setPlaceholderText("admin@example.com")
        pf.addRow("E-mail:", self.inp_pb_email)

        self.inp_pb_password = QLineEdit()
        self.inp_pb_password.setEchoMode(QLineEdit.Password)
        self.inp_pb_password.setPlaceholderText("••••••••")
        pf.addRow("Senha:", self.inp_pb_password)

        self.lbl_pb_status = QLabel("—")
        self.lbl_pb_status.setStyleSheet("color:#888; font-size:11px;")
        pf.addRow("Status:", self.lbl_pb_status)

        root.addWidget(grp_pb)

        # ── Botão salvar ──────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_save = QPushButton("Salvar")
        self._btn_save.setFixedWidth(100)
        self._btn_save.clicked.connect(self._save)
        btn_row.addWidget(self._btn_save)
        root.addLayout(btn_row)

        root.addStretch()

    # ── Gerenciamento de clients ──────────────────────────────────────────────

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
        if count == 0:
            self.lbl_client_hint.setText("Nenhum client conectado.")
        else:
            self.lbl_client_hint.setText(f"{count} client(s) conectado(s).")

    def set_active_client(self, client_id: str):
        idx = self.combo_client.findData(client_id)
        if idx >= 0:
            self.combo_client.setCurrentIndex(idx)

    # ── Porta COM vinda do client ─────────────────────────────────────────────

    def populate_com_ports(self, ports: list[dict]):
        """Recebe lista de dicts {device, description} vindos do client."""
        current = self.combo_com.currentText().strip()
        self.combo_com.clear()
        self.combo_com.addItem("")  # blank = auto-detect
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

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self):
        data = _cfg.load()
        self.spin_port.setValue(data.get("server_port", 8765))
        arduino_port = data.get("arduino", {}).get("port", "")
        self.combo_com.setEditText(arduino_port)
        pb = data.get("pocketbase", {})
        self.inp_pb_url.setText(pb.get("url", ""))
        self.inp_pb_email.setText(pb.get("email", ""))
        self.inp_pb_password.setText(pb.get("password", ""))

    def _save(self):
        data = _cfg.load()
        data["server_port"] = self.spin_port.value()

        # Arduino HID: extract just the COM port token (first word before spaces/dash)
        raw_port = self.combo_com.currentText().strip()
        port_val = raw_port.split()[0] if raw_port else ""
        data.setdefault("arduino", {})["port"] = port_val

        data.setdefault("pocketbase", {})
        data["pocketbase"]["url"] = self.inp_pb_url.text().strip()
        data["pocketbase"]["email"] = self.inp_pb_email.text().strip()
        data["pocketbase"]["password"] = self.inp_pb_password.text()
        _cfg.save(data)
        self._btn_save.setText("✓ Salvo!")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1500, lambda: self._btn_save.setText("Salvar"))
        self.pb_saved.emit()
        self.arduino_saved.emit(port_val)
        selected_client = self.combo_client.currentData()
        if selected_client:
            self.client_selected.emit(selected_client)

    # ── Status updates ────────────────────────────────────────────────────────

    def set_pb_status(self, ok: bool, msg: str):
        if ok:
            self.lbl_pb_status.setText(f"✓ {msg}")
            self.lbl_pb_status.setStyleSheet("color:#4ec94e; font-size:11px;")
        else:
            self.lbl_pb_status.setText(f"✗ {msg}")
            self.lbl_pb_status.setStyleSheet("color:#e06060; font-size:11px;")
