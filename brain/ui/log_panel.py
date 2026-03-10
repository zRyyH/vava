from __future__ import annotations

import time
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QLabel, QCheckBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor, QFont

# level → (html color, prefix)
_LEVELS = {
    "cmd":      ("#5b9bd5", "→ CMD"),
    "resp":     ("#4ec94e", "← RSP"),
    "macro":    ("#e5c07b", "◆ MCR"),
    "trigger":  ("#c678dd", "⬤ TRG"),
    "error":    ("#e06c75", "✖ ERR"),
    "info":     ("#abb2bf", "ℹ INF"),
}
_MAX_LINES = 600


class LogPanel(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._filters: set[str] = set(_LEVELS.keys())
        self._paused = False
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)

        # ── toolbar ──
        bar = QHBoxLayout()
        lbl = QLabel("Logs")
        lbl.setStyleSheet("font-weight:bold;")
        bar.addWidget(lbl)
        bar.addSpacing(8)

        self._checks: dict[str, QCheckBox] = {}
        labels = {
            "cmd": "Cmds", "resp": "Resp", "macro": "Macros",
            "trigger": "Triggers", "error": "Erros", "info": "Info",
        }
        for key, text in labels.items():
            cb = QCheckBox(text)
            cb.setChecked(True)
            cb.toggled.connect(lambda checked, k=key: self._toggle_filter(k, checked))
            self._checks[key] = cb
            bar.addWidget(cb)

        bar.addStretch()

        self._btn_pause = QPushButton("⏸ Pausar")
        self._btn_pause.setCheckable(True)
        self._btn_pause.setFixedWidth(80)
        self._btn_pause.toggled.connect(self._on_pause)
        bar.addWidget(self._btn_pause)

        btn_clear = QPushButton("🗑 Limpar")
        btn_clear.setFixedWidth(80)
        btn_clear.clicked.connect(self._text.clear if hasattr(self, '_text') else lambda: None)
        bar.addWidget(btn_clear)
        root.addLayout(bar)

        # ── text area ──
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QTextEdit.NoWrap)
        font = QFont("Consolas", 9)
        self._text.setFont(font)
        self._text.setStyleSheet("background:#1e2127; color:#abb2bf; border:none;")
        root.addWidget(self._text, 1)

        # fix the clear button now that _text exists
        btn_clear.clicked.disconnect()
        btn_clear.clicked.connect(self._text.clear)

    def _toggle_filter(self, key: str, checked: bool):
        if checked:
            self._filters.add(key)
        else:
            self._filters.discard(key)

    def _on_pause(self, paused: bool):
        self._paused = paused
        self._btn_pause.setText("▶ Retomar" if paused else "⏸ Pausar")

    def log(self, level: str, message: str):
        if self._paused:
            return
        if level not in self._filters:
            return

        color, prefix = _LEVELS.get(level, ("#abb2bf", "   "))
        ts = time.strftime("%H:%M:%S")

        # truncate long messages
        if len(message) > 300:
            message = message[:297] + "…"

        line = (
            f'<span style="color:#4b5263;">[{ts}]</span> '
            f'<span style="color:{color};font-weight:bold;">{prefix}</span> '
            f'<span style="color:#abb2bf;">{_escape(message)}</span>'
        )

        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.End)
        if self._text.document().blockCount() > _MAX_LINES:
            cursor.movePosition(QTextCursor.Start)
            cursor.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor, 50)
            cursor.removeSelectedText()
            cursor.movePosition(QTextCursor.End)
        self._text.append(line)
        self._text.verticalScrollBar().setValue(
            self._text.verticalScrollBar().maximum()
        )


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
