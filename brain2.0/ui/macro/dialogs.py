"""
Diálogos do editor de macros:
  - AddTriggerDialog       — trigger por pixel
  - ImageTriggerDialog     — trigger por imagem (template matching)
  - AddWindowTriggerDialog — trigger por estado da janela
  - KeyCaptureWidget       — campo que captura combinação de teclas
  - AddActionDialog        — ação de macro
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from ui.macro.models import (
    MODIFIER_VKS, TriggerCondition, ImageTriggerCondition,
    WindowTriggerCondition, MacroAction, _WIN_TRIG_NEEDS_VALUE,
    format_combo,
)
from ui.window_picker import pick_from_window, pick_region_from_window


# ── AddTriggerDialog ──────────────────────────────────────────────────────────

class AddTriggerDialog(QDialog):
    def __init__(self, parent=None, existing: TriggerCondition | None = None):
        super().__init__(parent)
        self.setWindowTitle("Editar Trigger" if existing else "Adicionar Trigger")
        lay = QGridLayout(self)

        btn_pick = QPushButton("🖥 Selecionar da Janela…")
        btn_pick.clicked.connect(self._pick_from_window)
        lay.addWidget(btn_pick, 0, 0, 1, 4)

        lay.addWidget(QLabel("X:"), 1, 0)
        self.spin_x = QSpinBox(); self.spin_x.setRange(0, 9999)
        lay.addWidget(self.spin_x, 1, 1)
        lay.addWidget(QLabel("Y:"), 1, 2)
        self.spin_y = QSpinBox(); self.spin_y.setRange(0, 9999)
        lay.addWidget(self.spin_y, 1, 3)

        lay.addWidget(QLabel("R:"), 2, 0)
        self.spin_r = QSpinBox(); self.spin_r.setRange(0, 255)
        lay.addWidget(self.spin_r, 2, 1)
        lay.addWidget(QLabel("G:"), 2, 2)
        self.spin_g = QSpinBox(); self.spin_g.setRange(0, 255)
        lay.addWidget(self.spin_g, 2, 3)

        lay.addWidget(QLabel("B:"), 3, 0)
        self.spin_b = QSpinBox(); self.spin_b.setRange(0, 255)
        lay.addWidget(self.spin_b, 3, 1)
        lay.addWidget(QLabel("Tolerância:"), 3, 2)
        self.spin_tol = QSpinBox(); self.spin_tol.setRange(0, 255); self.spin_tol.setValue(10)
        lay.addWidget(self.spin_tol, 3, 3)

        self._color_preview = QLabel("   ")
        self._color_preview.setAutoFillBackground(True)
        self._color_preview.setFixedHeight(20)
        lay.addWidget(self._color_preview, 4, 0, 1, 4)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns, 5, 0, 1, 4)

        for sp in (self.spin_r, self.spin_g, self.spin_b):
            sp.valueChanged.connect(self._update_color_preview)

        if existing:
            self.spin_x.setValue(existing.x)
            self.spin_y.setValue(existing.y)
            self.spin_r.setValue(existing.exp_r)
            self.spin_g.setValue(existing.exp_g)
            self.spin_b.setValue(existing.exp_b)
            self.spin_tol.setValue(existing.tolerance)
            self._update_color_preview()

    def _update_color_preview(self):
        r, g, b = self.spin_r.value(), self.spin_g.value(), self.spin_b.value()
        pal = self._color_preview.palette()
        pal.setColor(self._color_preview.backgroundRole(), QColor(r, g, b))
        self._color_preview.setPalette(pal)

    def _pick_from_window(self):
        result = pick_from_window(self)
        if result is None:
            return
        self.spin_x.setValue(result["x"])
        self.spin_y.setValue(result["y"])
        self.spin_r.setValue(result["r"])
        self.spin_g.setValue(result["g"])
        self.spin_b.setValue(result["b"])
        self._update_color_preview()

    def result(self) -> TriggerCondition:
        return TriggerCondition(
            x=self.spin_x.value(), y=self.spin_y.value(),
            exp_r=self.spin_r.value(), exp_g=self.spin_g.value(), exp_b=self.spin_b.value(),
            tolerance=self.spin_tol.value(),
        )


# ── ImageTriggerDialog ────────────────────────────────────────────────────────

class ImageTriggerDialog(QDialog):
    """Configura threshold de um ImageTriggerCondition e mostra preview."""

    def __init__(
        self,
        pixmap: "QPixmap | None",
        parent=None,
        existing: ImageTriggerCondition | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Configurar Image Trigger")
        self._template_b64 = ""

        lay = QVBoxLayout(self)

        self._lbl_preview = QLabel()
        self._lbl_preview.setAlignment(Qt.AlignCenter)
        self._lbl_preview.setMinimumHeight(80)
        self._lbl_preview.setStyleSheet("background:#222; border:1px solid #444;")
        lay.addWidget(self._lbl_preview)

        if pixmap is not None:
            import base64
            from PySide6.QtCore import QBuffer, QIODevice
            buf = QBuffer()
            buf.open(QIODevice.WriteOnly)
            pixmap.save(buf, "PNG")
            self._template_b64 = base64.b64encode(bytes(buf.data())).decode()
            self._lbl_preview.setPixmap(pixmap.scaledToHeight(min(pixmap.height(), 200)))
        elif existing is not None:
            import base64
            from PySide6.QtGui import QPixmap as _QPixmap
            self._template_b64 = existing.template_b64
            try:
                px = _QPixmap()
                px.loadFromData(base64.b64decode(existing.template_b64))
                self._lbl_preview.setPixmap(px.scaledToHeight(min(px.height(), 200)))
            except Exception:
                pass

        th_row = QHBoxLayout()
        th_row.addWidget(QLabel("Confiança mínima:"))
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(1, 100)
        init_th = existing.threshold if existing else 0.80
        self._slider.setValue(int(init_th * 100))
        th_row.addWidget(self._slider, 1)
        self._spin_th = QDoubleSpinBox()
        self._spin_th.setRange(0.01, 1.0)
        self._spin_th.setSingleStep(0.05)
        self._spin_th.setDecimals(2)
        self._spin_th.setValue(init_th)
        self._spin_th.setFixedWidth(70)
        th_row.addWidget(self._spin_th)
        lay.addLayout(th_row)

        self._slider.valueChanged.connect(lambda v: self._spin_th.setValue(v / 100))
        self._spin_th.valueChanged.connect(lambda v: self._slider.setValue(int(v * 100)))

        hint = QLabel("≥0.90 = correspondência exata.  <0.70 = aceita variações.")
        hint.setStyleSheet("color:#888; font-size:10px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        btns.button(QDialogButtonBox.Ok).setEnabled(bool(self._template_b64))
        lay.addWidget(btns)

    def result(self) -> ImageTriggerCondition:
        return ImageTriggerCondition(
            template_b64=self._template_b64,
            threshold=self._spin_th.value(),
        )


# ── AddWindowTriggerDialog ────────────────────────────────────────────────────

class AddWindowTriggerDialog(QDialog):
    def __init__(self, parent=None, existing: WindowTriggerCondition | None = None):
        super().__init__(parent)
        self.setWindowTitle(
            "Editar Trigger de Janela" if existing else "Adicionar Trigger de Janela"
        )
        lay = QFormLayout(self)

        self.combo_cond = QComboBox()
        self.combo_cond.addItems([
            "found", "not_found", "minimized", "maximized", "normal",
            "width", "height", "pos_x", "pos_y",
        ])
        self.combo_cond.currentTextChanged.connect(self._refresh)
        lay.addRow("Condição:", self.combo_cond)

        self._lbl_op = QLabel("Operador:")
        self.combo_op = QComboBox()
        self.combo_op.addItems(["==", "!=", ">", "<", ">=", "<="])
        lay.addRow(self._lbl_op, self.combo_op)

        self._lbl_val = QLabel("Valor (px):")
        self.spin_val = QSpinBox()
        self.spin_val.setRange(0, 99999)
        lay.addRow(self._lbl_val, self.spin_val)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addRow(btns)

        if existing:
            self.combo_cond.setCurrentText(existing.condition)
            self.combo_op.setCurrentText(existing.operator)
            self.spin_val.setValue(existing.value)

        self._refresh(self.combo_cond.currentText())

    def _refresh(self, condition: str):
        needs = condition in _WIN_TRIG_NEEDS_VALUE
        self._lbl_op.setVisible(needs)
        self.combo_op.setVisible(needs)
        self._lbl_val.setVisible(needs)
        self.spin_val.setVisible(needs)
        self.adjustSize()

    def result(self) -> WindowTriggerCondition:
        return WindowTriggerCondition(
            condition=self.combo_cond.currentText(),
            operator=self.combo_op.currentText(),
            value=self.spin_val.value(),
        )


# ── KeyCaptureWidget ──────────────────────────────────────────────────────────

class KeyCaptureWidget(QLineEdit):
    """Campo read-only que captura combinação de teclas ao pressionar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._vk: int = 0
        self._modifiers: list[int] = []
        self.setPlaceholderText("Clique aqui e pressione uma tecla…")
        self.setReadOnly(True)
        self.setToolTip("Clique no campo e pressione a combinação de teclas desejada.")

    @property
    def vk(self) -> int:
        return self._vk

    @property
    def modifiers(self) -> list[int]:
        return self._modifiers

    def set_combo(self, vk: int, modifiers: list[int]):
        self._vk = vk
        self._modifiers = modifiers
        if vk:
            self.setText(format_combo(vk, modifiers))

    def keyPressEvent(self, event: QKeyEvent):
        vk = event.nativeVirtualKey()
        if not vk or vk in MODIFIER_VKS:
            return
        qt_mods = event.modifiers()
        mods: list[int] = []
        if qt_mods & Qt.ControlModifier:
            mods.append(0x11)
        if qt_mods & Qt.ShiftModifier:
            mods.append(0x10)
        if qt_mods & Qt.AltModifier:
            mods.append(0x12)
        if qt_mods & Qt.MetaModifier:
            mods.append(0x5B)
        self._vk = vk
        self._modifiers = mods
        self.setText(format_combo(vk, mods))


# ── AddActionDialog ───────────────────────────────────────────────────────────

class AddActionDialog(QDialog):
    def __init__(
        self,
        parent=None,
        existing: MacroAction | None = None,
        saved_windows: list[dict] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Editar Ação" if existing else "Adicionar Ação")
        self._saved_windows = saved_windows or []
        self._lay = QGridLayout(self)
        self._param_widgets: dict[str, QWidget] = {}
        self._wa_sub_container: QWidget | None = None
        self._wa_sub_layout: QFormLayout | None = None

        self._lay.addWidget(QLabel("Tipo:"), 0, 0)
        self.combo = QComboBox()
        self.combo.addItems([
            "click", "move_mouse", "key_press", "wait",
            "dynamic_input", "window_action",
        ])
        self.combo.currentTextChanged.connect(self._refresh_params)
        self._lay.addWidget(self.combo, 0, 1, 1, 3)

        self.btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btns.accepted.connect(self.accept)
        self.btns.rejected.connect(self.reject)

        if existing:
            self.combo.blockSignals(True)
            self.combo.setCurrentText(existing.type)
            self.combo.blockSignals(False)
            self._refresh_params(existing.type)
            self._fill_params(existing.params)
        else:
            self._refresh_params("click")

    # ── param building ────────────────────────────────────────────────────────

    def _clear_params(self):
        # remove all rows after first 2 (type label + type combo)
        while self._lay.count() > 2:
            item = self._lay.takeAt(2)
            w = item.widget() if item else None
            if w and w is not self.btns:
                w.deleteLater()
        self._param_widgets.clear()
        self._wa_sub_container = None
        self._wa_sub_layout = None

    def _add_spin(self, row: int, label: str, key: str,
                  min_: int, max_: int, default: int):
        self._lay.addWidget(QLabel(label), row, 0)
        sp = QSpinBox()
        sp.setRange(min_, max_)
        sp.setValue(default)
        self._lay.addWidget(sp, row, 1, 1, 3)
        self._param_widgets[key] = sp

    def _add_line(self, row: int, label: str, key: str, default: str = "") -> QLineEdit:
        self._lay.addWidget(QLabel(label), row, 0)
        le = QLineEdit()
        le.setText(default)
        self._lay.addWidget(le, row, 1, 1, 3)
        self._param_widgets[key] = le
        return le

    def _refresh_params(self, type_: str):
        self._clear_params()
        row = 1

        if type_ in ("click", "move_mouse"):
            btn_pick = QPushButton("🖥 Selecionar da Janela…")
            btn_pick.clicked.connect(self._pick_from_window)
            self._lay.addWidget(btn_pick, row, 0, 1, 4); row += 1
            self._add_spin(row, "X:", "x", 0, 9999, 0); row += 1
            self._add_spin(row, "Y:", "y", 0, 9999, 0); row += 1
            if type_ == "click":
                self._lay.addWidget(QLabel("Botão:"), row, 0)
                cb = QComboBox()
                cb.addItems(["left", "right", "middle"])
                self._lay.addWidget(cb, row, 1)
                self._param_widgets["button"] = cb
                row += 1

        elif type_ == "key_press":
            self._lay.addWidget(QLabel("Tecla:"), row, 0)
            kw = KeyCaptureWidget()
            self._lay.addWidget(kw, row, 1, 1, 3)
            self._param_widgets["key_combo"] = kw
            row += 1

        elif type_ == "wait":
            self._add_spin(row, "ms:", "ms", 0, 60000, 500); row += 1

        elif type_ == "dynamic_input":
            self._add_line(row, "Collection:", "collection", "accounts"); row += 1
            filter_edit = self._add_line(row, "Filtro:", "filter"); row += 1
            filter_edit.setPlaceholderText('ex: status = "active"')
            sort_edit = self._add_line(row, "Sort:", "sort"); row += 1
            sort_edit.setPlaceholderText("ex: -created,+username")
            self._add_line(row, "Coluna:", "column", "password"); row += 1
            self._add_spin(row, "Índice:", "index", 0, 9999, 0); row += 1
            btn_preview = QPushButton("🔍 Pré-visualizar colunas…")
            btn_preview.clicked.connect(self._preview_columns)
            self._lay.addWidget(btn_preview, row, 0, 1, 4); row += 1

        elif type_ == "window_action":
            self._lay.addWidget(QLabel("Ação:"), row, 0)
            cb = QComboBox()
            cb.addItems([
                "minimize", "maximize", "restore", "close", "focus",
                "bring_to_front", "resize", "move", "set_fullscreen",
                "set_windowed", "open_window",
            ])
            self._lay.addWidget(cb, row, 1, 1, 3)
            self._param_widgets["wa"] = cb
            row += 1

            self._wa_sub_container = QWidget()
            self._wa_sub_layout = QFormLayout(self._wa_sub_container)
            self._wa_sub_layout.setContentsMargins(0, 0, 0, 0)
            self._lay.addWidget(self._wa_sub_container, row, 0, 1, 4)
            row += 1

            cb.currentTextChanged.connect(self._refresh_wa_sub)
            self._refresh_wa_sub(cb.currentText())

        self._lay.addWidget(self.btns, row, 0, 1, 4)

    def _refresh_wa_sub(self, action: str):
        if self._wa_sub_layout is None:
            return
        while self._wa_sub_layout.rowCount() > 0:
            self._wa_sub_layout.removeRow(0)
        for key in ("path", "width", "height", "x", "y"):
            self._param_widgets.pop(key, None)

        if action in ("resize", "set_size"):
            w = QSpinBox(); w.setRange(0, 9999); w.setValue(800)
            self._wa_sub_layout.addRow("Largura:", w)
            self._param_widgets["width"] = w
            h = QSpinBox(); h.setRange(0, 9999); h.setValue(600)
            self._wa_sub_layout.addRow("Altura:", h)
            self._param_widgets["height"] = h
        elif action == "move":
            x = QSpinBox(); x.setRange(-9999, 9999)
            self._wa_sub_layout.addRow("X:", x)
            self._param_widgets["x"] = x
            y = QSpinBox(); y.setRange(-9999, 9999)
            self._wa_sub_layout.addRow("Y:", y)
            self._param_widgets["y"] = y
        elif action == "open_window":
            cb_win = QComboBox()
            for sw in self._saved_windows:
                cb_win.addItem(sw.get("alias", sw["path"]), sw["path"])
            if not self._saved_windows:
                cb_win.addItem("(nenhuma janela salva)", "")
            self._wa_sub_layout.addRow("Janela:", cb_win)
            self._param_widgets["path"] = cb_win

    # ── fill existing values ──────────────────────────────────────────────────

    def _fill_params(self, params: dict):
        # migração: "action" → "wa"
        if "wa" in self._param_widgets and "wa" not in params and "action" in params:
            params = dict(params)
            params["wa"] = params.pop("action")

        for key, widget in self._param_widgets.items():
            if isinstance(widget, KeyCaptureWidget):
                vk = int(params.get("vk", 0))
                mods = list(params.get("modifiers", []))
                if vk:
                    widget.set_combo(vk, mods)
                continue
            if key not in params:
                continue
            val = params[key]
            if isinstance(widget, QSpinBox):
                widget.setValue(int(val))
            elif key == "path" and isinstance(widget, QComboBox):
                for i in range(widget.count()):
                    if widget.itemData(i) == val:
                        widget.setCurrentIndex(i)
                        break
            elif isinstance(widget, QComboBox):
                widget.setCurrentText(str(val))
            elif isinstance(widget, QLineEdit):
                widget.setText(str(val))

    # ── helpers ───────────────────────────────────────────────────────────────

    def _pick_from_window(self):
        result = pick_from_window(self)
        if result is None:
            return
        if "x" in self._param_widgets:
            self._param_widgets["x"].setValue(result["x"])
        if "y" in self._param_widgets:
            self._param_widgets["y"].setValue(result["y"])

    def _preview_columns(self):
        from PySide6.QtWidgets import QMessageBox
        import pocketbase_client as _pb
        client = _pb.get_shared()
        if client is None:
            QMessageBox.warning(self, "PocketBase", "Sessão não iniciada.")
            return
        coll_w = self._param_widgets.get("collection")
        collection = coll_w.text().strip() if isinstance(coll_w, QLineEdit) else ""
        if not collection:
            QMessageBox.warning(self, "PocketBase", "Preencha 'Collection' primeiro.")
            return
        filter_w = self._param_widgets.get("filter")
        filter_expr = filter_w.text().strip() if isinstance(filter_w, QLineEdit) else ""
        try:
            records = client.fetch_records(collection, filter_expr=filter_expr, per_page=1)
            if not records:
                QMessageBox.information(self, "PocketBase", "Nenhum registro encontrado.")
                return
            lines = ["<b>Colunas disponíveis:</b>"]
            for k, v in records[0].items():
                lines.append(f"• <b>{k}</b>: {str(v)[:50]}")
            QMessageBox.information(self, f"Preview — {collection}", "<br>".join(lines))
        except Exception as exc:
            QMessageBox.critical(self, "Erro", str(exc))

    def result(self) -> MacroAction:
        type_ = self.combo.currentText()
        params: dict = {}
        for key, widget in self._param_widgets.items():
            if isinstance(widget, KeyCaptureWidget):
                params["vk"] = widget.vk
                params["modifiers"] = widget.modifiers
            elif isinstance(widget, QSpinBox):
                params[key] = widget.value()
            elif key == "path" and isinstance(widget, QComboBox):
                params[key] = widget.currentData() or widget.currentText()
            elif isinstance(widget, QComboBox):
                params[key] = widget.currentText()
            elif isinstance(widget, QLineEdit):
                params[key] = widget.text()
        return MacroAction(type=type_, params=params)
