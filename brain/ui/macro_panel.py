from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSpinBox,
    QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
    QHeaderView, QDialog, QDialogButtonBox, QLineEdit, QGridLayout,
    QAbstractItemView, QComboBox, QSplitter, QGroupBox, QCheckBox,
    QFormLayout,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor

from ui.window_picker import pick_from_window, pick_region_from_window
import config as _cfg


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class MacroSafetyConfig:
    """Travas de segurança para execução de macros."""
    min_trigger_frames: int = 1          # polls consecutivos antes de disparar
    require_window_in_list: bool = True  # bloqueia se perfil não tiver hwnd correspondido
    confirm_pause_ms: int = 0            # pausa antes de executar (0 = imediato)


@dataclass
class ImageTriggerCondition:
    """Trigger por correspondência de imagem (template matching)."""
    template_b64: str        # PNG codificado em base64
    threshold: float = 0.80  # confiança mínima [0.0, 1.0]
    # runtime (não serializado)
    _found: bool = field(default=False, init=False, repr=False, compare=False)
    _confidence: float = field(default=0.0, init=False, repr=False, compare=False)
    _match_x: int = field(default=0, init=False, repr=False, compare=False)
    _match_y: int = field(default=0, init=False, repr=False, compare=False)

    def label(self) -> str:
        size = self._template_size()
        return f"Image {size} ≥{int(self.threshold * 100)}%"

    def _template_size(self) -> str:
        try:
            import base64, io
            from PySide6.QtGui import QImage
            data = base64.b64decode(self.template_b64)
            img = QImage.fromData(data)
            return f"{img.width()}×{img.height()}"
        except Exception:
            return "?"

    def thumbnail(self, max_h: int = 32) -> "QPixmap":
        """Retorna thumbnail do template para exibição na UI."""
        from PySide6.QtGui import QPixmap
        try:
            import base64
            data = base64.b64decode(self.template_b64)
            px = QPixmap()
            px.loadFromData(data)
            if px.height() > max_h:
                px = px.scaledToHeight(max_h)
            return px
        except Exception:
            return QPixmap()


@dataclass
class TriggerCondition:
    x: int
    y: int
    exp_r: int
    exp_g: int
    exp_b: int
    tolerance: int = 10

    def matches(self, r: int, g: int, b: int) -> bool:
        return (abs(r - self.exp_r) <= self.tolerance and
                abs(g - self.exp_g) <= self.tolerance and
                abs(b - self.exp_b) <= self.tolerance)

    def label(self) -> str:
        return f"({self.x},{self.y}) #{self.exp_r:02X}{self.exp_g:02X}{self.exp_b:02X} ±{self.tolerance}"


@dataclass
class MacroAction:
    type: str   # click | key_press | move_mouse | wait | dynamic_input
    params: dict[str, Any]

    def label(self) -> str:
        p = self.params
        if self.type == "click":
            return f"Click ({p['x']},{p['y']}) {p.get('button','left')}"
        if self.type == "key_press":
            return f"Key VK={p['vk']}"
        if self.type == "move_mouse":
            return f"Move ({p['x']},{p['y']})"
        if self.type == "wait":
            return f"Wait {p['ms']} ms"
        if self.type == "dynamic_input":
            col = p.get("column", "?")
            coll = p.get("collection", "?")
            flt = p.get("filter", "")
            srt = p.get("sort", "")
            lbl = f"DynamicInput [{coll}] col={col}"
            if flt:
                lbl += f" | filter: {flt}"
            if srt:
                lbl += f" | sort: {srt}"
            return lbl
        return self.type


@dataclass
class Macro:
    name: str
    enabled: bool = True
    triggers: list[TriggerCondition] = field(default_factory=list)
    image_triggers: list[ImageTriggerCondition] = field(default_factory=list)
    actions: list[MacroAction] = field(default_factory=list)
    cooldown_ms: int = 500
    safety: MacroSafetyConfig = field(default_factory=MacroSafetyConfig)
    # runtime (não serializado)
    _was_active: bool = field(default=False, init=False, repr=False, compare=False)
    _cooldown_until: float = field(default=0.0, init=False, repr=False, compare=False)
    _trigger_frame_count: int = field(default=0, init=False, repr=False, compare=False)
    _confirm_armed: bool = field(default=False, init=False, repr=False, compare=False)

    def has_any_trigger(self) -> bool:
        return bool(self.triggers or self.image_triggers)

    def check_triggers(self, pixel_map: dict[tuple, tuple]) -> bool:
        """Verifica todos os triggers (pixel E imagem devem ser satisfeitos)."""
        if not self.has_any_trigger():
            return False
        # Pixel triggers
        if self.triggers and not all(
            t.matches(*pixel_map.get((t.x, t.y), (0, 0, 0)))
            for t in self.triggers
        ):
            return False
        # Image triggers: usam resultado cacheado da última resposta match_templates
        if self.image_triggers and not all(t._found for t in self.image_triggers):
            return False
        return True


@dataclass
class WindowProfile:
    """Perfil de janela: agrupa macros que rodam em uma janela específica."""
    name: str
    title_pattern: str = ""   # substring case-insensitive do título (vazio = global/absoluto)
    macros: list[Macro] = field(default_factory=list)
    enabled: bool = True
    # runtime (não serializado)
    _matched_hwnd: int = field(default=0, init=False, repr=False, compare=False)

    def match_windows(self, windows: list[dict]) -> int:
        """Retorna hwnd da primeira janela cujo título contenha title_pattern, ou 0."""
        if not self.title_pattern.strip():
            return 0   # perfil global — sem janela alvo
        pat = self.title_pattern.strip().lower()
        for w in windows:
            if pat in w.get("title", "").lower():
                return w["hwnd"]
        return 0


# ── Main panel ────────────────────────────────────────────────────────────────

class MacroPanel(QWidget):
    command_requested = Signal(str, dict)
    log_event = Signal(str, str)   # (level, message)

    def __init__(self):
        super().__init__()
        self._profiles: list[WindowProfile] = []
        self._sel_profile: int = -1
        self._sel_macro: int = -1

        self._waiting = False
        self._last_pixel_map: dict = {}
        self._remote_windows: list[dict] = []

        self._action_queue: list[tuple[MacroAction, int]] = []
        self._loop_macro: Macro | None = None
        self._loop_hwnd: int = 0

        self._action_timer = QTimer(self)
        self._action_timer.setSingleShot(True)
        self._action_timer.timeout.connect(self._exec_next_action)

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)
        self._waiting_image = False   # flag para match_templates in-flight

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(1000)
        self._save_timer.timeout.connect(self._autosave)

        self._build_ui()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _cur_profile(self) -> WindowProfile | None:
        if 0 <= self._sel_profile < len(self._profiles):
            return self._profiles[self._sel_profile]
        return None

    def _cur_macro(self) -> Macro | None:
        p = self._cur_profile()
        if p and 0 <= self._sel_macro < len(p.macros):
            return p.macros[self._sel_macro]
        return None

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        # Top bar
        top = QHBoxLayout()
        lbl = QLabel("Macros")
        lbl.setStyleSheet("font-weight:bold; font-size:14px;")
        top.addWidget(lbl)
        top.addStretch()
        btn_pb = QPushButton("⚙ PocketBase")
        btn_pb.clicked.connect(self._open_pb_settings)
        top.addWidget(btn_pb)
        top.addWidget(QLabel("ms"))
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(1, 5000)
        self.spin_interval.setValue(100)
        self.spin_interval.valueChanged.connect(
            lambda v: (self._poll_timer.setInterval(v), self._schedule_save()))
        top.addWidget(self.spin_interval)
        self.btn_poll = QPushButton("Start Polling")
        self.btn_poll.setCheckable(True)
        self.btn_poll.clicked.connect(self._toggle_poll)
        top.addWidget(self.btn_poll)
        root.addLayout(top)

        # 3 colunas
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        # ── Col 1: Perfis de janela ───────────────────────────────────────────
        col1 = QWidget()
        l1 = QVBoxLayout(col1)
        l1.setContentsMargins(0, 0, 0, 0)
        l1.setSpacing(4)

        lbl_j = QLabel("Janelas")
        lbl_j.setStyleSheet("font-weight:bold; font-size:13px; color:#6ec6f5;")
        l1.addWidget(lbl_j)

        self.profile_list = QListWidget()
        self.profile_list.currentRowChanged.connect(self._on_profile_selected)
        l1.addWidget(self.profile_list, 1)

        pr = QHBoxLayout()
        btn_add_p = QPushButton("+ Janela")
        btn_add_p.clicked.connect(self._add_profile)
        pr.addWidget(btn_add_p)
        btn_del_p = QPushButton("Remover")
        btn_del_p.clicked.connect(self._remove_profile)
        pr.addWidget(btn_del_p)
        l1.addLayout(pr)

        # Editor de perfil
        self._grp_prof = QGroupBox("Configurar Janela")
        self._grp_prof.setEnabled(False)
        pe = QFormLayout(self._grp_prof)
        pe.setSpacing(4)

        self.inp_prof_name = QLineEdit()
        self.inp_prof_name.setPlaceholderText("Nome do perfil")
        self.inp_prof_name.textChanged.connect(self._on_prof_name_changed)
        pe.addRow("Nome:", self.inp_prof_name)

        self.inp_prof_pattern = QLineEdit()
        self.inp_prof_pattern.setPlaceholderText("ex: Notepad  (vazio = global)")
        self.inp_prof_pattern.setToolTip(
            "Substring case-insensitive do título da janela.\n"
            "Aplica-se à primeira janela cujo título contenha esse texto.\n"
            "Vazio = perfil global (coordenadas absolutas, sem hwnd)."
        )
        self.inp_prof_pattern.textChanged.connect(self._on_prof_pattern_changed)
        pe.addRow("Padrão de título:", self.inp_prof_pattern)

        self.chk_prof_enabled = QCheckBox("Perfil ativo")
        self.chk_prof_enabled.setChecked(True)
        self.chk_prof_enabled.toggled.connect(self._on_prof_enabled_changed)
        pe.addRow("", self.chk_prof_enabled)

        self.lbl_prof_status = QLabel("—")
        self.lbl_prof_status.setStyleSheet("color:#888; font-size:11px;")
        pe.addRow("Status:", self.lbl_prof_status)

        l1.addWidget(self._grp_prof)
        splitter.addWidget(col1)

        # ── Col 2: Macros do perfil ───────────────────────────────────────────
        col2 = QWidget()
        l2 = QVBoxLayout(col2)
        l2.setContentsMargins(0, 0, 0, 0)
        l2.setSpacing(4)

        lbl_m = QLabel("Macros")
        lbl_m.setStyleSheet("font-weight:bold; font-size:13px; color:#6ec6f5;")
        l2.addWidget(lbl_m)

        self.macro_list = QListWidget()
        self.macro_list.currentRowChanged.connect(self._on_macro_selected)
        l2.addWidget(self.macro_list, 1)

        mr = QHBoxLayout()
        btn_add_m = QPushButton("+ Macro")
        btn_add_m.clicked.connect(self._add_macro)
        mr.addWidget(btn_add_m)
        btn_dup_m = QPushButton("Dup")
        btn_dup_m.clicked.connect(self._duplicate_macro)
        mr.addWidget(btn_dup_m)
        btn_del_m = QPushButton("Remover")
        btn_del_m.clicked.connect(self._remove_macro)
        mr.addWidget(btn_del_m)
        l2.addLayout(mr)

        mr2 = QHBoxLayout()
        btn_up_m = QPushButton("↑")
        btn_up_m.clicked.connect(self._move_macro_up)
        mr2.addWidget(btn_up_m)
        btn_dn_m = QPushButton("↓")
        btn_dn_m.clicked.connect(self._move_macro_down)
        mr2.addWidget(btn_dn_m)
        mr2.addStretch()
        l2.addLayout(mr2)

        splitter.addWidget(col2)

        # ── Col 3: Editor do macro ────────────────────────────────────────────
        col3 = QWidget()
        l3 = QVBoxLayout(col3)
        l3.setContentsMargins(4, 0, 0, 0)
        l3.setSpacing(4)

        self._macro_editor = QWidget()
        self._macro_editor.setEnabled(False)
        el = QVBoxLayout(self._macro_editor)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(4)

        # Nome + ativo + cooldown
        nr = QHBoxLayout()
        nr.addWidget(QLabel("Nome:"))
        self.inp_name = QLineEdit()
        self.inp_name.setPlaceholderText("Nome do macro")
        self.inp_name.textChanged.connect(self._on_name_changed)
        nr.addWidget(self.inp_name, 1)
        self.chk_enabled = QCheckBox("Ativo")
        self.chk_enabled.setChecked(True)
        self.chk_enabled.toggled.connect(self._on_enabled_changed)
        nr.addWidget(self.chk_enabled)
        nr.addWidget(QLabel("Cooldown:"))
        self.spin_cooldown = QSpinBox()
        self.spin_cooldown.setRange(0, 60000)
        self.spin_cooldown.setValue(500)
        self.spin_cooldown.setSuffix(" ms")
        self.spin_cooldown.valueChanged.connect(self._on_cooldown_changed)
        nr.addWidget(self.spin_cooldown)
        self._btn_save = QPushButton("💾 Salvar")
        self._btn_save.setFixedWidth(80)
        self._btn_save.clicked.connect(self._save_now)
        nr.addWidget(self._btn_save)
        el.addLayout(nr)

        # Segurança
        grp_safe = QGroupBox("Segurança")
        grp_safe.setStyleSheet("QGroupBox { color: #e8a020; font-weight: bold; }")
        sf = QFormLayout(grp_safe)
        sf.setSpacing(4)

        self.spin_min_frames = QSpinBox()
        self.spin_min_frames.setRange(1, 999)
        self.spin_min_frames.setValue(1)
        self.spin_min_frames.setToolTip(
            "Quantos polls consecutivos os triggers devem bater antes de disparar.\n"
            "Valor maior = menos falsos positivos por pixels transitórios."
        )
        self.spin_min_frames.valueChanged.connect(self._on_safety_changed)
        sf.addRow("Frames mínimos estáveis:", self.spin_min_frames)

        self.chk_require_window = QCheckBox("Exigir janela correspondida")
        self.chk_require_window.setChecked(True)
        self.chk_require_window.setToolTip(
            "Bloqueia execução se o perfil de janela não encontrou hwnd correspondente.\n"
            "Protege contra execução em janela fechada/substituída."
        )
        self.chk_require_window.toggled.connect(self._on_safety_changed)
        sf.addRow("", self.chk_require_window)

        self.spin_confirm_ms = QSpinBox()
        self.spin_confirm_ms.setRange(0, 10000)
        self.spin_confirm_ms.setValue(0)
        self.spin_confirm_ms.setSuffix(" ms")
        self.spin_confirm_ms.setToolTip(
            "Pausa antes de executar (0 = executa imediatamente).\n"
            "Durante esse tempo, Shift+Backspace aborta."
        )
        self.spin_confirm_ms.valueChanged.connect(self._on_safety_changed)
        sf.addRow("Pausa de confirmação:", self.spin_confirm_ms)

        el.addWidget(grp_safe)

        # Triggers
        grp_trig = QGroupBox("Triggers (todos devem bater)")
        tl = QVBoxLayout(grp_trig)
        self.trig_table = QTableWidget(0, 9)
        self.trig_table.setHorizontalHeaderLabels(
            ["X", "Y", "R", "G", "B", "Tol.", "Esperado", "Atual", "✓"]
        )
        hh = self.trig_table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        for col in (6, 7, 8):
            hh.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.trig_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.trig_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.trig_table.setMaximumHeight(150)
        tl.addWidget(self.trig_table)
        tb = QHBoxLayout()
        btn_add_t = QPushButton("+ Trigger")
        btn_add_t.clicked.connect(self._add_trigger)
        tb.addWidget(btn_add_t)
        btn_del_t = QPushButton("Remover")
        btn_del_t.clicked.connect(self._remove_trigger)
        tb.addWidget(btn_del_t)
        tb.addStretch()
        tl.addLayout(tb)
        el.addWidget(grp_trig)

        # Image Triggers
        grp_img = QGroupBox("Image Triggers")
        il = QVBoxLayout(grp_img)
        self.img_trig_list = QListWidget()
        self.img_trig_list.setMaximumHeight(120)
        self.img_trig_list.setSelectionMode(QAbstractItemView.SingleSelection)
        il.addWidget(self.img_trig_list)
        itb = QHBoxLayout()
        btn_add_it = QPushButton("+ Capturar região…")
        btn_add_it.clicked.connect(self._add_image_trigger)
        itb.addWidget(btn_add_it)
        btn_edit_it = QPushButton("Editar threshold")
        btn_edit_it.clicked.connect(self._edit_image_trigger)
        itb.addWidget(btn_edit_it)
        btn_del_it = QPushButton("Remover")
        btn_del_it.clicked.connect(self._remove_image_trigger)
        itb.addWidget(btn_del_it)
        itb.addStretch()
        il.addLayout(itb)
        el.addWidget(grp_img)

        # Ações
        grp_act = QGroupBox("Sequência de Ações")
        al = QVBoxLayout(grp_act)
        self.action_list = QListWidget()
        self.action_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.action_list.itemDoubleClicked.connect(self._edit_action)
        al.addWidget(self.action_list, 1)
        ab = QHBoxLayout()
        btn_add_a = QPushButton("+ Ação")
        btn_add_a.clicked.connect(self._add_action)
        ab.addWidget(btn_add_a)
        btn_edit_a = QPushButton("Editar")
        btn_edit_a.clicked.connect(self._edit_action)
        ab.addWidget(btn_edit_a)
        btn_del_a = QPushButton("Remover")
        btn_del_a.clicked.connect(self._remove_action)
        ab.addWidget(btn_del_a)
        btn_up_a = QPushButton("↑")
        btn_up_a.clicked.connect(self._move_action_up)
        ab.addWidget(btn_up_a)
        btn_dn_a = QPushButton("↓")
        btn_dn_a.clicked.connect(self._move_action_down)
        ab.addWidget(btn_dn_a)
        ab.addStretch()
        al.addLayout(ab)
        el.addWidget(grp_act, 1)

        l3.addWidget(self._macro_editor)
        splitter.addWidget(col3)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 3)

    # ── Polling ───────────────────────────────────────────────────────────────

    def _toggle_poll(self, checked: bool):
        if checked:
            self.btn_poll.setText("Stop Polling")
            self._poll_timer.start(self.spin_interval.value())
        else:
            self.btn_poll.setText("Start Polling")
            self._poll_timer.stop()
            self._waiting = False

    def _poll(self):
        # ── Pixel triggers ──────────────────────────────────────────────────
        if not self._waiting:
            positions: list[dict] = []
            seen: set[tuple] = set()
            for profile in self._profiles:
                if not profile.enabled:
                    continue
                hwnd = profile._matched_hwnd
                for macro in profile.macros:
                    if not macro.enabled:
                        continue
                    for t in macro.triggers:
                        key = (t.x, t.y, hwnd)
                        if key not in seen:
                            seen.add(key)
                            pos: dict = {"x": t.x, "y": t.y}
                            if hwnd:
                                pos["hwnd"] = hwnd
                            positions.append(pos)
            if positions:
                self._waiting = True
                self.command_requested.emit("get_pixels", {"positions": positions})

        # ── Image triggers — um match_templates por perfil ──────────────────
        if not self._waiting_image:
            # Indexamos os templates como "profIdx:macroIdx:trigIdx"
            per_hwnd: dict[int, list[dict]] = {}
            for pi, profile in enumerate(self._profiles):
                if not profile.enabled:
                    continue
                hwnd = profile._matched_hwnd
                for mi, macro in enumerate(profile.macros):
                    if not macro.enabled:
                        continue
                    for ti, it in enumerate(macro.image_triggers):
                        entry = {
                            "id": f"{pi}:{mi}:{ti}",
                            "data": it.template_b64,
                            "threshold": it.threshold,
                        }
                        per_hwnd.setdefault(hwnd, []).append(entry)

            for hwnd, templates in per_hwnd.items():
                params: dict = {"templates": templates}
                if hwnd:
                    params["hwnd"] = hwnd
                self._waiting_image = True
                self.command_requested.emit("match_templates", params)
                break   # emite um por poll; próximo poll processa o resto

    def update_pixels(self, results: list[dict]):
        self._waiting = False
        pixel_map = {(r["x"], r["y"]): (r["r"], r["g"], r["b"]) for r in results}
        self._last_pixel_map = pixel_map
        self._update_trigger_table_live(pixel_map)
        # Só avalia macros que TÊM pixel triggers — os puramente de imagem são
        # avaliados por update_image_matches quando a resposta chegar.
        self._evaluate_macros(pixel_map, only_pixel_triggered=True)
        self._refresh_profile_list()

    def _evaluate_macros(self, pixel_map: dict, only_pixel_triggered: bool = False):
        """Avalia todos os macros e dispara os que satisfazem seus triggers."""
        import time
        now = time.monotonic() * 1000

        for profile in self._profiles:
            if not profile.enabled:
                for macro in profile.macros:
                    macro._was_active = False
                    macro._trigger_frame_count = 0
                continue

            hwnd = profile._matched_hwnd

            for macro in profile.macros:
                if not macro.enabled:
                    macro._was_active = False
                    macro._trigger_frame_count = 0
                    continue

                # Quando chamado de update_pixels, pula macros sem pixel triggers
                # (eles dependem de match_templates e serão avaliados lá).
                if only_pixel_triggered and not macro.triggers:
                    continue

                is_active = macro.check_triggers(pixel_map)

                if not is_active:
                    if self._loop_macro is macro:
                        self._action_timer.stop()
                        self._action_queue.clear()
                        self._loop_macro = None
                        self._loop_hwnd = 0
                        self.log_event.emit("macro",
                            f"[{profile.name} / {macro.name}] interrompido — triggers perdidos")
                    macro._was_active = False
                    macro._trigger_frame_count = 0
                    macro._confirm_armed = False
                    continue

                macro._trigger_frame_count += 1
                stable = macro._trigger_frame_count >= macro.safety.min_trigger_frames

                if self._loop_macro is None and not self._action_queue and stable and now >= macro._cooldown_until:
                    err = self._preflight_check(macro, profile)
                    if err:
                        if not macro._was_active:
                            self.log_event.emit("warn",
                                f"[{profile.name} / {macro.name}] BLOQUEADO — {err}")
                        macro._was_active = is_active
                        continue

                    if not macro._was_active:
                        all_trig = list(macro.triggers) + list(macro.image_triggers)
                        trig_info = ", ".join(t.label() for t in all_trig)
                        extra = (f" (estável por {macro._trigger_frame_count} frames)"
                                 if macro.safety.min_trigger_frames > 1 else "")
                        self.log_event.emit("trigger",
                            f"[{profile.name} / {macro.name}] triggers OK{extra} → {trig_info}")

                    if macro.safety.confirm_pause_ms > 0 and not macro._confirm_armed:
                        macro._confirm_armed = True
                        macro._cooldown_until = now + macro.safety.confirm_pause_ms
                        self.log_event.emit("warn",
                            f"[{profile.name} / {macro.name}] aguardando confirmação "
                            f"({macro.safety.confirm_pause_ms} ms) — Shift+Backspace para abortar")
                        macro._was_active = is_active
                        continue

                    macro._confirm_armed = False
                    macro._cooldown_until = now + macro.cooldown_ms
                    self._fire_macro(macro, hwnd)

                macro._was_active = is_active

    def _preflight_check(self, macro: Macro, profile: WindowProfile) -> str:
        """Retorna mensagem de erro se bloqueado, '' se ok."""
        if profile.title_pattern.strip() and profile._matched_hwnd == 0:
            if macro.safety.require_window_in_list:
                return f"janela com padrão '{profile.title_pattern}' não encontrada"
        return ""

    def _fire_macro(self, macro: Macro, hwnd: int):
        if self._action_queue:
            return
        self.log_event.emit("macro", f"[{macro.name}] disparando {len(macro.actions)} ação(ões)")
        self._loop_macro = macro
        self._loop_hwnd = hwnd
        self._action_queue = [(act, hwnd) for act in macro.actions]
        self._exec_next_action()

    def _exec_next_action(self):
        if not self._action_queue:
            self._loop_macro = None
            self._loop_hwnd = 0
            return
        act, hwnd = self._action_queue.pop(0)
        if act.type == "wait":
            self.log_event.emit("macro", f"  wait {act.params['ms']} ms")
            self._action_timer.start(act.params["ms"])
        elif act.type == "dynamic_input":
            self.log_event.emit("macro", f"  → {act.label()}")
            self._exec_dynamic_input(act, hwnd)
        else:
            self.log_event.emit("macro", f"  → {act.label()}")
            params = dict(act.params)
            if hwnd and act.type in ("click", "move_mouse"):
                params["hwnd"] = hwnd
            self.command_requested.emit(act.type, params)
            self._action_timer.start(0)

    def _exec_dynamic_input(self, act: MacroAction, hwnd: int):
        import pocketbase_client as _pb_mod
        client = _pb_mod.get_shared()
        if client is None:
            self.log_event.emit("error", "dynamic_input: PocketBase não configurado")
            self._action_timer.start(0)
            return
        collection = act.params.get("collection", "")
        filter_expr = act.params.get("filter", "")
        sort_expr = act.params.get("sort", "")
        column = act.params.get("column", "")
        record_index = int(act.params.get("index", 0))
        try:
            records = client.fetch_records(collection, filter_expr=filter_expr, sort=sort_expr)
            if not records:
                self.log_event.emit("error", f"dynamic_input: nenhum registro em '{collection}'")
                self._action_timer.start(0)
                return
            idx = min(record_index, len(records) - 1)
            value = str(records[idx].get(column, ""))
            self.log_event.emit("macro", f"  dynamic_input → {column}={value[:40]}")
            cmd_params: dict = {"text": value}
            if hwnd:
                cmd_params["hwnd"] = hwnd
            self.command_requested.emit("type_text", cmd_params)
        except Exception as exc:
            self.log_event.emit("error", f"dynamic_input: {exc}")
        self._action_timer.start(0)

    def update_image_matches(self, results: list[dict]):
        """Processa resposta de match_templates, atualiza _found e avalia macros."""
        self._waiting_image = False
        for r in results:
            tid = r.get("id", "")
            parts = tid.split(":")
            if len(parts) != 3:
                continue
            try:
                pi, mi, ti = int(parts[0]), int(parts[1]), int(parts[2])
                it = self._profiles[pi].macros[mi].image_triggers[ti]
                it._found = r.get("found", False)
                it._confidence = r.get("confidence", 0.0)
                it._match_x = r.get("x", 0)
                it._match_y = r.get("y", 0)
            except (IndexError, ValueError):
                continue
        self._update_image_trigger_list_live()
        # Avalia macros com image triggers (com ou sem pixel triggers combinados).
        # only_pixel_triggered=False para incluir todos que dependem de imagem.
        self._evaluate_macros(self._last_pixel_map, only_pixel_triggered=False)
        self._refresh_profile_list()

    def _update_image_trigger_list_live(self):
        """Atualiza a lista de image triggers do macro selecionado com status ao vivo."""
        macro = self._cur_macro()
        if macro is None or not hasattr(self, "img_trig_list"):
            return
        for row in range(self.img_trig_list.count()):
            item = self.img_trig_list.item(row)
            if item is None or row >= len(macro.image_triggers):
                continue
            it = macro.image_triggers[row]
            pct = int(it._confidence * 100)
            found_str = "✓" if it._found else "✗"
            item.setText(f"{found_str} {it.label()}  [{pct}%]")
            item.setForeground(QColor("#4ec94e") if it._found else QColor("#e06060"))

    # ── Remote windows ────────────────────────────────────────────────────────

    def update_remote_windows(self, windows: list[dict]):
        self._remote_windows = windows
        for profile in self._profiles:
            profile._matched_hwnd = profile.match_windows(windows)
        self._refresh_profile_list()
        self._update_profile_status_label()

    # ── Profile management ────────────────────────────────────────────────────

    def _add_profile(self):
        p = WindowProfile(name=f"Janela {len(self._profiles) + 1}")
        self._profiles.append(p)
        self._refresh_profile_list()
        self.profile_list.setCurrentRow(len(self._profiles) - 1)
        self._schedule_save()

    def _remove_profile(self):
        if self._sel_profile < 0:
            return
        del self._profiles[self._sel_profile]
        self._sel_profile = -1
        self._sel_macro = -1
        self._refresh_profile_list()
        new = min(self._sel_profile, len(self._profiles) - 1)
        if new >= 0:
            self.profile_list.setCurrentRow(new)
        else:
            self._grp_prof.setEnabled(False)
            self.macro_list.clear()
            self._macro_editor.setEnabled(False)
        self._schedule_save()

    def _on_profile_selected(self, row: int):
        self._sel_profile = row
        self._sel_macro = -1
        self._macro_editor.setEnabled(False)
        p = self._cur_profile()
        if p is None:
            self._grp_prof.setEnabled(False)
            self.macro_list.clear()
            return
        self._grp_prof.setEnabled(True)
        for w in (self.inp_prof_name, self.inp_prof_pattern, self.chk_prof_enabled):
            w.blockSignals(True)
        self.inp_prof_name.setText(p.name)
        self.inp_prof_pattern.setText(p.title_pattern)
        self.chk_prof_enabled.setChecked(p.enabled)
        for w in (self.inp_prof_name, self.inp_prof_pattern, self.chk_prof_enabled):
            w.blockSignals(False)
        self._update_profile_status_label()
        self._refresh_macro_list()

    def _refresh_profile_list(self):
        cur = self._sel_profile
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        for p in self._profiles:
            no_target = not p.title_pattern.strip()
            matched = p._matched_hwnd != 0
            if no_target:
                suffix = "  [global]"
                color = QColor("#aaa") if p.enabled else QColor("#666")
            elif matched:
                suffix = f"  ✓ hwnd={p._matched_hwnd}"
                color = QColor("#4ec94e") if p.enabled else QColor("#666")
            else:
                suffix = "  ✗ não encontrada"
                color = QColor("#e06060") if p.enabled else QColor("#666")
            item = QListWidgetItem(p.name + suffix)
            item.setForeground(color)
            self.profile_list.addItem(item)
        self.profile_list.blockSignals(False)
        if 0 <= cur < self.profile_list.count():
            self.profile_list.setCurrentRow(cur)
        self._update_profile_status_label()

    def _update_profile_status_label(self):
        p = self._cur_profile()
        if p is None:
            return
        if not p.title_pattern.strip():
            self.lbl_prof_status.setText("global (coordenadas absolutas)")
            self.lbl_prof_status.setStyleSheet("color:#888; font-size:11px;")
        elif p._matched_hwnd:
            self.lbl_prof_status.setText(f"correspondida — hwnd={p._matched_hwnd}")
            self.lbl_prof_status.setStyleSheet("color:#4ec94e; font-size:11px;")
        else:
            self.lbl_prof_status.setText(f"não encontrada (padrão: '{p.title_pattern}')")
            self.lbl_prof_status.setStyleSheet("color:#e06060; font-size:11px;")

    def _on_prof_name_changed(self, text: str):
        p = self._cur_profile()
        if p:
            p.name = text
            self._refresh_profile_list()
            self._schedule_save()

    def _on_prof_pattern_changed(self, text: str):
        p = self._cur_profile()
        if p:
            p.title_pattern = text
            p._matched_hwnd = p.match_windows(self._remote_windows)
            self._refresh_profile_list()
            self._update_profile_status_label()
            self._schedule_save()

    def _on_prof_enabled_changed(self, checked: bool):
        p = self._cur_profile()
        if p:
            p.enabled = checked
            self._refresh_profile_list()
            self._schedule_save()

    # ── Macro management ──────────────────────────────────────────────────────

    def _add_macro(self):
        p = self._cur_profile()
        if p is None:
            return
        macro = Macro(name=f"Macro {len(p.macros) + 1}")
        p.macros.append(macro)
        self._refresh_macro_list()
        self.macro_list.setCurrentRow(len(p.macros) - 1)
        self._schedule_save()

    def _duplicate_macro(self):
        p = self._cur_profile()
        if p is None or self._sel_macro < 0:
            return
        import copy
        src = p.macros[self._sel_macro]
        dup = copy.deepcopy(src)
        dup.name = src.name + " (cópia)"
        p.macros.append(dup)
        self._refresh_macro_list()
        self.macro_list.setCurrentRow(len(p.macros) - 1)
        self._schedule_save()

    def _remove_macro(self):
        p = self._cur_profile()
        if p is None or self._sel_macro < 0:
            return
        del p.macros[self._sel_macro]
        old = self._sel_macro
        self._sel_macro = -1
        self._refresh_macro_list()
        new = min(old, len(p.macros) - 1)
        if new >= 0:
            self.macro_list.setCurrentRow(new)
        else:
            self._macro_editor.setEnabled(False)
        self._schedule_save()

    def _move_macro_up(self):
        p = self._cur_profile()
        if p is None or self._sel_macro <= 0:
            return
        r = self._sel_macro
        p.macros[r - 1], p.macros[r] = p.macros[r], p.macros[r - 1]
        self._refresh_macro_list()
        self.macro_list.setCurrentRow(r - 1)
        self._schedule_save()

    def _move_macro_down(self):
        p = self._cur_profile()
        if p is None:
            return
        r = self._sel_macro
        if r < 0 or r >= len(p.macros) - 1:
            return
        p.macros[r], p.macros[r + 1] = p.macros[r + 1], p.macros[r]
        self._refresh_macro_list()
        self.macro_list.setCurrentRow(r + 1)
        self._schedule_save()

    def _on_macro_selected(self, row: int):
        self._sel_macro = row
        macro = self._cur_macro()
        if macro is None:
            self._macro_editor.setEnabled(False)
            return
        self._macro_editor.setEnabled(True)
        widgets = (self.inp_name, self.chk_enabled, self.spin_cooldown,
                   self.spin_min_frames, self.chk_require_window, self.spin_confirm_ms)
        for w in widgets:
            w.blockSignals(True)
        self.inp_name.setText(macro.name)
        self.chk_enabled.setChecked(macro.enabled)
        self.spin_cooldown.setValue(macro.cooldown_ms)
        self.spin_min_frames.setValue(macro.safety.min_trigger_frames)
        self.chk_require_window.setChecked(macro.safety.require_window_in_list)
        self.spin_confirm_ms.setValue(macro.safety.confirm_pause_ms)
        for w in widgets:
            w.blockSignals(False)
        self._reload_triggers()
        self._reload_image_triggers()
        self._reload_actions()
        if self._last_pixel_map:
            self._update_trigger_table_live(self._last_pixel_map)

    def _refresh_macro_list(self):
        p = self._cur_profile()
        cur = self._sel_macro
        self.macro_list.blockSignals(True)
        self.macro_list.clear()
        if p:
            for macro in p.macros:
                item = QListWidgetItem(macro.name)
                item.setForeground(QColor("#4ec94e") if macro.enabled else QColor("#888"))
                self.macro_list.addItem(item)
        self.macro_list.blockSignals(False)
        if 0 <= cur < self.macro_list.count():
            self.macro_list.setCurrentRow(cur)

    # ── Editor: name / enabled / cooldown / safety ────────────────────────────

    def _on_name_changed(self, text: str):
        macro = self._cur_macro()
        if macro:
            macro.name = text
            item = self.macro_list.item(self._sel_macro)
            if item:
                item.setText(text)
            self._schedule_save()

    def _on_enabled_changed(self, checked: bool):
        macro = self._cur_macro()
        if macro:
            macro.enabled = checked
            item = self.macro_list.item(self._sel_macro)
            if item:
                item.setForeground(QColor("#4ec94e") if checked else QColor("#888"))
            self._schedule_save()

    def _on_cooldown_changed(self, val: int):
        macro = self._cur_macro()
        if macro:
            macro.cooldown_ms = val
            self._schedule_save()

    def _on_safety_changed(self, _val=None):
        macro = self._cur_macro()
        if macro:
            macro.safety.min_trigger_frames = self.spin_min_frames.value()
            macro.safety.require_window_in_list = self.chk_require_window.isChecked()
            macro.safety.confirm_pause_ms = self.spin_confirm_ms.value()
            self._schedule_save()

    # ── Editor: image triggers ────────────────────────────────────────────────

    def _reload_image_triggers(self):
        macro = self._cur_macro()
        self.img_trig_list.clear()
        if macro:
            for it in macro.image_triggers:
                item = QListWidgetItem(it.label())
                item.setForeground(QColor("#aaa"))
                self.img_trig_list.addItem(item)

    def _add_image_trigger(self):
        macro = self._cur_macro()
        if macro is None:
            return
        px = pick_region_from_window(self)
        if px is None:
            return
        dlg = _ImageTriggerThresholdDialog(px, self)
        if dlg.exec() != QDialog.Accepted:
            return
        it = dlg.result()
        macro.image_triggers.append(it)
        item = QListWidgetItem(it.label())
        item.setForeground(QColor("#aaa"))
        self.img_trig_list.addItem(item)
        self._schedule_save()

    def _edit_image_trigger(self):
        macro = self._cur_macro()
        if macro is None:
            return
        row = self.img_trig_list.currentRow()
        if row < 0 or row >= len(macro.image_triggers):
            return
        it = macro.image_triggers[row]
        dlg = _ImageTriggerThresholdDialog(None, self, existing=it)
        if dlg.exec() != QDialog.Accepted:
            return
        updated = dlg.result()
        macro.image_triggers[row] = updated
        self.img_trig_list.item(row).setText(updated.label())
        self._schedule_save()

    def _remove_image_trigger(self):
        macro = self._cur_macro()
        if macro is None:
            return
        row = self.img_trig_list.currentRow()
        if row < 0:
            return
        self.img_trig_list.takeItem(row)
        del macro.image_triggers[row]
        self._schedule_save()

    # ── Editor: triggers ──────────────────────────────────────────────────────

    def _reload_triggers(self):
        macro = self._cur_macro()
        self.trig_table.setRowCount(0)
        if macro:
            for t in macro.triggers:
                self._insert_trigger_row(t)

    def _insert_trigger_row(self, t: TriggerCondition):
        row = self.trig_table.rowCount()
        self.trig_table.insertRow(row)
        for col, val in enumerate([t.x, t.y, t.exp_r, t.exp_g, t.exp_b, t.tolerance]):
            item = QTableWidgetItem(str(val))
            item.setTextAlignment(Qt.AlignCenter)
            self.trig_table.setItem(row, col, item)
        exp_color = QColor(t.exp_r, t.exp_g, t.exp_b)
        for col in (2, 3, 4):
            self.trig_table.item(row, col).setBackground(exp_color)
            self.trig_table.item(row, col).setForeground(
                QColor("white") if exp_color.lightness() < 128 else QColor("black"))
        item_exp = QTableWidgetItem(f"#{t.exp_r:02X}{t.exp_g:02X}{t.exp_b:02X}")
        item_exp.setTextAlignment(Qt.AlignCenter)
        item_exp.setBackground(exp_color)
        item_exp.setForeground(QColor("white") if exp_color.lightness() < 128 else QColor("black"))
        self.trig_table.setItem(row, 6, item_exp)
        item_cur = QTableWidgetItem("—")
        item_cur.setTextAlignment(Qt.AlignCenter)
        self.trig_table.setItem(row, 7, item_cur)
        item_st = QTableWidgetItem("?")
        item_st.setTextAlignment(Qt.AlignCenter)
        self.trig_table.setItem(row, 8, item_st)

    def _add_trigger(self):
        macro = self._cur_macro()
        if macro is None:
            return
        dlg = AddTriggerDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        t = dlg.result()
        macro.triggers.append(t)
        self._insert_trigger_row(t)
        self._schedule_save()

    def _remove_trigger(self):
        macro = self._cur_macro()
        if macro is None:
            return
        rows = sorted({idx.row() for idx in self.trig_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.trig_table.removeRow(row)
            del macro.triggers[row]
        self._schedule_save()

    # ── Editor: actions ───────────────────────────────────────────────────────

    def _reload_actions(self):
        macro = self._cur_macro()
        self.action_list.clear()
        if macro:
            for act in macro.actions:
                self.action_list.addItem(act.label())

    def _add_action(self):
        macro = self._cur_macro()
        if macro is None:
            return
        dlg = AddActionDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        act = dlg.result()
        macro.actions.append(act)
        self.action_list.addItem(act.label())
        self._schedule_save()

    def _edit_action(self, _item=None):
        macro = self._cur_macro()
        if macro is None:
            return
        row = self.action_list.currentRow()
        if row < 0:
            return
        dlg = AddActionDialog(self, existing=macro.actions[row])
        if dlg.exec() != QDialog.Accepted:
            return
        act = dlg.result()
        macro.actions[row] = act
        self.action_list.item(row).setText(act.label())
        self._schedule_save()

    def _remove_action(self):
        macro = self._cur_macro()
        if macro is None:
            return
        row = self.action_list.currentRow()
        if row < 0:
            return
        self.action_list.takeItem(row)
        del macro.actions[row]
        self._schedule_save()

    def _move_action_up(self):
        macro = self._cur_macro()
        if macro is None:
            return
        row = self.action_list.currentRow()
        if row <= 0:
            return
        macro.actions[row - 1], macro.actions[row] = macro.actions[row], macro.actions[row - 1]
        self._reload_actions()
        self.action_list.setCurrentRow(row - 1)
        self._schedule_save()

    def _move_action_down(self):
        macro = self._cur_macro()
        if macro is None:
            return
        row = self.action_list.currentRow()
        if row < 0 or row >= len(macro.actions) - 1:
            return
        macro.actions[row], macro.actions[row + 1] = macro.actions[row + 1], macro.actions[row]
        self._reload_actions()
        self.action_list.setCurrentRow(row + 1)
        self._schedule_save()

    # ── Trigger table live update ─────────────────────────────────────────────

    def _update_trigger_table_live(self, pixel_map: dict):
        macro = self._cur_macro()
        if macro is None:
            return
        for row, t in enumerate(macro.triggers):
            rgb = pixel_map.get((t.x, t.y))
            if rgb is None:
                continue
            r, g, b = rgb
            cur_color = QColor(r, g, b)
            matches = t.matches(r, g, b)
            item_cur = self.trig_table.item(row, 7)
            if item_cur:
                item_cur.setText(f"#{r:02X}{g:02X}{b:02X}")
                item_cur.setBackground(cur_color)
                item_cur.setForeground(
                    QColor("white") if cur_color.lightness() < 128 else QColor("black"))
            item_st = self.trig_table.item(row, 8)
            if item_st:
                item_st.setText("✓" if matches else "✗")
                item_st.setBackground(QColor("#2d6a2d") if matches else QColor("#6a2d2d"))
                item_st.setForeground(QColor("white"))

    # ── Persistência ──────────────────────────────────────────────────────────

    def _save_now(self):
        self._save_timer.stop()
        self._autosave()
        self._btn_save.setText("✓ Salvo!")
        QTimer.singleShot(1500, lambda: self._btn_save.setText("💾 Salvar"))

    def _schedule_save(self):
        self._save_timer.start()

    def _autosave(self):
        data = _cfg.load()
        data["macros"] = self.dump_state()
        _cfg.save(data)

    def _macro_to_dict(self, m: Macro) -> dict:
        return {
            "name": m.name,
            "enabled": m.enabled,
            "cooldown_ms": m.cooldown_ms,
            "safety": {
                "min_trigger_frames": m.safety.min_trigger_frames,
                "require_window_in_list": m.safety.require_window_in_list,
                "confirm_pause_ms": m.safety.confirm_pause_ms,
            },
            "triggers": [
                {"x": t.x, "y": t.y, "r": t.exp_r, "g": t.exp_g, "b": t.exp_b,
                 "tolerance": t.tolerance}
                for t in m.triggers
            ],
            "image_triggers": [
                {"template_b64": it.template_b64, "threshold": it.threshold}
                for it in m.image_triggers
            ],
            "actions": [
                {"type": a.type, "params": a.params}
                for a in m.actions
            ],
        }

    def _macro_from_dict(self, item: dict) -> Macro:
        triggers = [
            TriggerCondition(
                x=t["x"], y=t["y"],
                exp_r=t["r"], exp_g=t["g"], exp_b=t["b"],
                tolerance=t.get("tolerance", 10),
            )
            for t in item.get("triggers", [])
        ]
        actions = [
            MacroAction(type=a["type"], params=a["params"])
            for a in item.get("actions", [])
        ]
        s = item.get("safety", {})
        image_triggers = [
            ImageTriggerCondition(
                template_b64=it["template_b64"],
                threshold=float(it.get("threshold", 0.8)),
            )
            for it in item.get("image_triggers", [])
        ]
        return Macro(
            name=item.get("name", "Macro"),
            enabled=item.get("enabled", True),
            cooldown_ms=item.get("cooldown_ms", 500),
            safety=MacroSafetyConfig(
                min_trigger_frames=s.get("min_trigger_frames", 1),
                require_window_in_list=s.get("require_window_in_list", True),
                confirm_pause_ms=s.get("confirm_pause_ms", 0),
            ),
            triggers=triggers,
            image_triggers=image_triggers,
            actions=actions,
        )

    def dump_state(self) -> dict:
        return {
            "poll_interval_ms": self.spin_interval.value(),
            "polling_active": self.btn_poll.isChecked(),
            "profiles": [
                {
                    "name": p.name,
                    "title_pattern": p.title_pattern,
                    "enabled": p.enabled,
                    "macros": [self._macro_to_dict(m) for m in p.macros],
                }
                for p in self._profiles
            ],
        }

    def load_state(self, data: dict) -> None:
        self._profiles.clear()

        # Formato novo: profiles
        for pd in data.get("profiles", []):
            self._profiles.append(WindowProfile(
                name=pd.get("name", "Janela"),
                title_pattern=pd.get("title_pattern", ""),
                enabled=pd.get("enabled", True),
                macros=[self._macro_from_dict(m) for m in pd.get("macros", [])],
            ))

        # Migração do formato antigo (flat items sem profiles)
        if not self._profiles and data.get("items"):
            global_p = WindowProfile(name="Global", title_pattern="")
            for item in data["items"]:
                global_p.macros.append(self._macro_from_dict(item))
            self._profiles.append(global_p)
            self.log_event.emit("info", "Macros migrados para perfil 'Global'")

        interval = data.get("poll_interval_ms", 100)
        self.spin_interval.blockSignals(True)
        self.spin_interval.setValue(interval)
        self.spin_interval.blockSignals(False)
        self._poll_timer.setInterval(interval)

        self._sel_profile = -1
        self._sel_macro = -1
        self._refresh_profile_list()
        self.macro_list.clear()
        self._macro_editor.setEnabled(False)
        self._grp_prof.setEnabled(False)

        if data.get("polling_active", False):
            self.btn_poll.setChecked(True)
            self._toggle_poll(True)

    # ── PocketBase ────────────────────────────────────────────────────────────

    def _open_pb_settings(self):
        from ui.pocketbase_panel import PocketBaseSettingsDialog
        dlg = PocketBaseSettingsDialog(self)
        if dlg.exec():
            self._reconnect_pb()

    def _reconnect_pb(self):
        from PySide6.QtCore import QThread, Signal as _Signal
        pb_cfg = _cfg.load().get("pocketbase", {})
        url = pb_cfg.get("url", "").strip()
        email = pb_cfg.get("email", "").strip()
        password = pb_cfg.get("password", "")
        if not url or not email:
            return
        import pocketbase_client as _pb_mod

        class _AuthThread(QThread):
            done = _Signal(bool, str)
            def __init__(self, u, e, p):
                super().__init__()
                self._u, self._e, self._p = u, e, p
            def run(self):
                try:
                    c = _pb_mod.init_shared(self._u, self._e, self._p)
                    c.authenticate()
                    self.done.emit(True, "")
                except Exception as ex:
                    self.done.emit(False, str(ex))

        self._pb_reconnect_thread = _AuthThread(url, email, password)
        self._pb_reconnect_thread.done.connect(
            lambda ok, err: self.log_event.emit(
                "info" if ok else "error",
                "PocketBase: sessão reiniciada ✓" if ok else f"PocketBase: falha — {err}"
            )
        )
        self._pb_reconnect_thread.start()

    # ── Stop ──────────────────────────────────────────────────────────────────

    def stop(self):
        self._poll_timer.stop()
        self._action_timer.stop()
        self._waiting = False
        self._action_queue.clear()
        self._loop_macro = None
        self._loop_hwnd = 0
        self._waiting_image = False
        for p in self._profiles:
            for macro in p.macros:
                macro._trigger_frame_count = 0
                macro._confirm_armed = False
                for it in macro.image_triggers:
                    it._found = False
                    it._confidence = 0.0
        self.btn_poll.setChecked(False)
        self.btn_poll.setText("Start Polling")


# ── Dialogs ───────────────────────────────────────────────────────────────────

class _ImageTriggerThresholdDialog(QDialog):
    """Configura o threshold de um ImageTriggerCondition e mostra preview do template."""

    def __init__(self, pixmap: "QPixmap | None", parent=None,
                 existing: "ImageTriggerCondition | None" = None):
        from PySide6.QtWidgets import QDoubleSpinBox, QSlider
        from PySide6.QtCore import Qt as _Qt
        super().__init__(parent)
        self.setWindowTitle("Configurar Image Trigger")
        self._template_b64: str = ""

        lay = QVBoxLayout(self)

        # Preview do template
        self._lbl_preview = QLabel()
        self._lbl_preview.setAlignment(Qt.AlignCenter)
        self._lbl_preview.setMinimumHeight(80)
        self._lbl_preview.setStyleSheet("background:#222; border:1px solid #444;")
        lay.addWidget(self._lbl_preview)

        if pixmap is not None:
            import base64, io
            from PySide6.QtCore import QBuffer, QIODevice
            buf = QBuffer()
            buf.open(QIODevice.WriteOnly)
            pixmap.save(buf, "PNG")
            self._template_b64 = base64.b64encode(bytes(buf.data())).decode()
            scaled = pixmap.scaledToHeight(min(pixmap.height(), 200))
            self._lbl_preview.setPixmap(scaled)
        elif existing is not None:
            self._template_b64 = existing.template_b64
            try:
                import base64
                from PySide6.QtGui import QPixmap as _QPixmap
                px = _QPixmap()
                px.loadFromData(base64.b64decode(existing.template_b64))
                scaled = px.scaledToHeight(min(px.height(), 200))
                self._lbl_preview.setPixmap(scaled)
            except Exception:
                pass

        # Threshold
        th_row = QHBoxLayout()
        th_row.addWidget(QLabel("Confiança mínima:"))
        self._slider = QSlider(_Qt.Horizontal)
        self._slider.setRange(1, 100)
        self._slider.setValue(int((existing.threshold if existing else 0.8) * 100))
        th_row.addWidget(self._slider, 1)
        self._spin_th = QDoubleSpinBox()
        self._spin_th.setRange(0.01, 1.0)
        self._spin_th.setSingleStep(0.05)
        self._spin_th.setDecimals(2)
        self._spin_th.setValue(existing.threshold if existing else 0.80)
        self._spin_th.setFixedWidth(70)
        th_row.addWidget(self._spin_th)
        lay.addLayout(th_row)

        self._slider.valueChanged.connect(lambda v: self._spin_th.setValue(v / 100))
        self._spin_th.valueChanged.connect(lambda v: self._slider.setValue(int(v * 100)))

        lbl_hint = QLabel("Valores altos (≥0.90) exigem correspondência exata. Valores baixos (<0.70) aceitam variações.")
        lbl_hint.setStyleSheet("color:#888; font-size:10px;")
        lbl_hint.setWordWrap(True)
        lay.addWidget(lbl_hint)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        btns.button(QDialogButtonBox.Ok).setEnabled(bool(self._template_b64))
        lay.addWidget(btns)

    def result(self) -> "ImageTriggerCondition":
        return ImageTriggerCondition(
            template_b64=self._template_b64,
            threshold=self._spin_th.value(),
        )


class AddTriggerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Adicionar Trigger")
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


class AddActionDialog(QDialog):
    def __init__(self, parent=None, existing: "MacroAction | None" = None):
        super().__init__(parent)
        self.setWindowTitle("Editar Ação" if existing else "Adicionar Ação")
        self._lay = QGridLayout(self)

        self._lay.addWidget(QLabel("Tipo:"), 0, 0)
        self.combo = QComboBox()
        self.combo.addItems(["click", "move_mouse", "key_press", "wait", "dynamic_input"])
        self.combo.currentTextChanged.connect(self._refresh_params)
        self._lay.addWidget(self.combo, 0, 1, 1, 3)

        self._param_widgets: dict[str, QSpinBox | QComboBox | QLineEdit] = {}
        self._param_rows_start = 1

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

    def _clear_params(self):
        while self._lay.count() > 2:
            item = self._lay.takeAt(2)
            w = item.widget() if item else None
            if w and w is not self.btns:
                w.deleteLater()
        self._param_widgets.clear()

    def _add_spin(self, row: int, label: str, key: str, min_: int, max_: int, default: int):
        self._lay.addWidget(QLabel(label), row, 0)
        sp = QSpinBox(); sp.setRange(min_, max_); sp.setValue(default)
        self._lay.addWidget(sp, row, 1, 1, 3)
        self._param_widgets[key] = sp

    def _add_line(self, row: int, label: str, key: str, default: str = ""):
        self._lay.addWidget(QLabel(label), row, 0)
        le = QLineEdit(); le.setText(default)
        self._lay.addWidget(le, row, 1, 1, 3)
        self._param_widgets[key] = le

    def _fill_params(self, params: dict):
        for key, widget in self._param_widgets.items():
            if key not in params:
                continue
            val = params[key]
            if isinstance(widget, QSpinBox):
                widget.setValue(int(val))
            elif isinstance(widget, QComboBox):
                widget.setCurrentText(str(val))
            elif isinstance(widget, QLineEdit):
                widget.setText(str(val))

    def _refresh_params(self, type_: str):
        self._clear_params()
        row = self._param_rows_start
        if type_ in ("click", "move_mouse"):
            btn_pick = QPushButton("🖥 Selecionar da Janela…")
            btn_pick.clicked.connect(self._pick_from_window)
            self._lay.addWidget(btn_pick, row, 0, 1, 4); row += 1
            self._add_spin(row, "X:", "x", 0, 9999, 0); row += 1
            self._add_spin(row, "Y:", "y", 0, 9999, 0); row += 1
            if type_ == "click":
                self._lay.addWidget(QLabel("Botão:"), row, 0)
                cb = QComboBox(); cb.addItems(["left", "right", "middle"])
                self._lay.addWidget(cb, row, 1)
                self._param_widgets["button"] = cb
                row += 1
        elif type_ == "key_press":
            self._add_spin(row, "VK Code:", "vk", 0, 255, 13); row += 1
        elif type_ == "wait":
            self._add_spin(row, "ms:", "ms", 0, 60000, 500); row += 1
        elif type_ == "dynamic_input":
            self._add_line(row, "Collection:", "collection", "accounts"); row += 1
            self._lay.addWidget(QLabel("Filtro:"), row, 0)
            filter_edit = QLineEdit()
            filter_edit.setPlaceholderText('ex: status = "active" && created >= "2024-01-01"')
            filter_edit.setToolTip(
                "Sintaxe idêntica ao filtro do painel web do PocketBase.\n"
                "Operadores: = != > >= < <= ~ !~ ?= ?!= ?> ?>= ?< ?<= ?~\n"
                'Exemplo: username = "foo" || (banned = false && tag ~ "pro")'
            )
            self._lay.addWidget(filter_edit, row, 1, 1, 3)
            self._param_widgets["filter"] = filter_edit
            row += 1
            self._add_line(row, "Sort:", "sort", ""); row += 1
            self._param_widgets["sort"].setPlaceholderText("ex: -created,+username")
            self._add_line(row, "Coluna:", "column", "password"); row += 1
            self._add_spin(row, "Índice do registro:", "index", 0, 9999, 0); row += 1
            btn_preview = QPushButton("🔍 Pré-visualizar colunas…")
            btn_preview.clicked.connect(self._preview_columns)
            self._lay.addWidget(btn_preview, row, 0, 1, 4); row += 1
        self._lay.addWidget(self.btns, row, 0, 1, 4)

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
        import pocketbase_client as _pb_mod
        client = _pb_mod.get_shared()
        if client is None:
            QMessageBox.warning(self, "PocketBase", "Sessão não iniciada.\nConfigure em ⚙ PocketBase.")
            return
        collection_widget = self._param_widgets.get("collection")
        collection = collection_widget.text().strip() if isinstance(collection_widget, QLineEdit) else ""
        if not collection:
            QMessageBox.warning(self, "PocketBase", "Preencha 'Collection' primeiro.")
            return
        filter_widget = self._param_widgets.get("filter")
        filter_expr = filter_widget.text().strip() if isinstance(filter_widget, QLineEdit) else ""
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
        params = {}
        for key, widget in self._param_widgets.items():
            if isinstance(widget, QSpinBox):
                params[key] = widget.value()
            elif isinstance(widget, QComboBox):
                params[key] = widget.currentText()
            elif isinstance(widget, QLineEdit):
                params[key] = widget.text()
        return MacroAction(type=type_, params=params)
