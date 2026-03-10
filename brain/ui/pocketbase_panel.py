"""Dialog de configurações do PocketBase."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

import config as _cfg
from pocketbase_client import PocketBaseClient


class PocketBaseSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurações PocketBase")
        self.setMinimumWidth(420)
        self._build_ui()
        self._load()

    def _build_ui(self):
        lay = QVBoxLayout(self)

        # ── Conexão ──────────────────────────────────────────────────────────
        grp_conn = QGroupBox("Conexão (Superuser)")
        form_conn = QFormLayout(grp_conn)

        self.inp_url = QLineEdit()
        self.inp_url.setPlaceholderText("http://localhost:8090")
        form_conn.addRow("URL:", self.inp_url)

        self.inp_email = QLineEdit()
        self.inp_email.setPlaceholderText("admin@exemplo.com")
        form_conn.addRow("E-mail:", self.inp_email)

        self.inp_password = QLineEdit()
        self.inp_password.setEchoMode(QLineEdit.Password)
        self.inp_password.setPlaceholderText("senha")
        form_conn.addRow("Senha:", self.inp_password)

        lbl_note = QLabel("Autentica via <b>_superusers</b> (admin do PocketBase).")
        lbl_note.setStyleSheet("color: #aaa; font-size: 11px;")
        form_conn.addRow("", lbl_note)

        lay.addWidget(grp_conn)

        # ── Teste ─────────────────────────────────────────────────────────────
        test_row = QHBoxLayout()
        self._btn_test = QPushButton("Testar conexão")
        self._btn_test.clicked.connect(self._test_connection)
        test_row.addWidget(self._btn_test)
        self._lbl_status = QLabel("")
        self._lbl_status.setWordWrap(True)
        test_row.addWidget(self._lbl_status, 1)
        lay.addLayout(test_row)

        # ── OK / Cancel ───────────────────────────────────────────────────────
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._save_and_accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    # ── Persistência ──────────────────────────────────────────────────────────

    def _load(self):
        pb = _cfg.load().get("pocketbase", {})
        self.inp_url.setText(pb.get("url", ""))
        self.inp_email.setText(pb.get("email", ""))
        self.inp_password.setText(pb.get("password", ""))

    def _save_and_accept(self):
        data = _cfg.load()
        data["pocketbase"] = {
            "url": self.inp_url.text().strip(),
            "email": self.inp_email.text().strip(),
            "password": self.inp_password.text(),
        }
        _cfg.save(data)
        self.accept()

    # ── Teste ─────────────────────────────────────────────────────────────────

    def _test_connection(self):
        url = self.inp_url.text().strip()
        email = self.inp_email.text().strip()
        password = self.inp_password.text()

        if not url:
            self._set_status("URL não preenchida.", error=True)
            return

        self._btn_test.setEnabled(False)
        self._set_status("Conectando…")

        try:
            client = PocketBaseClient(url, email, password)
            client.authenticate()
            self._set_status("✓ Conexão OK!", error=False)
        except Exception as exc:
            self._set_status(f"✗ Erro: {exc}", error=True)
        finally:
            self._btn_test.setEnabled(True)

    def _set_status(self, msg: str, error: bool = False):
        color = "#d9534f" if error else "#5cb85c"
        self._lbl_status.setText(f'<span style="color:{color}">{msg}</span>')
