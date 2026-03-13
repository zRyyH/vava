from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSpinBox,
    QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
    QHeaderView, QDialog, QDialogButtonBox, QLineEdit, QGridLayout,
    QAbstractItemView, QComboBox, QSplitter, QGroupBox, QCheckBox,
    QFormLayout, QFrame,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QKeyEvent

from ui.window_picker import pick_from_window, pick_region_from_window
import config as _cfg


# ── VK helpers ────────────────────────────────────────────────────────────────

_VK_NAMES: dict[int, str] = {
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x10: "Shift",
    0x11: "Ctrl", 0x12: "Alt", 0x13: "Pause", 0x14: "CapsLock",
    0x1B: "Esc", 0x20: "Space", 0x21: "PageUp", 0x22: "PageDown",
    0x23: "End", 0x24: "Home", 0x25: "Left", 0x26: "Up",
    0x27: "Right", 0x28: "Down", 0x2C: "PrintScr", 0x2D: "Insert",
    0x2E: "Delete", 0x5B: "Win", 0x5C: "RWin",
    0x70: "F1", 0x71: "F2", 0x72: "F3", 0x73: "F4", 0x74: "F5",
    0x75: "F6", 0x76: "F7", 0x77: "F8", 0x78: "F9", 0x79: "F10",
    0x7A: "F11", 0x7B: "F12",
    0x90: "NumLock", 0x91: "ScrollLock",
    0xA0: "LShift", 0xA1: "RShift", 0xA2: "LCtrl", 0xA3: "RCtrl",
    0xA4: "LAlt", 0xA5: "RAlt",
    0xBB: "=+", 0xBC: ",<", 0xBD: "-_", 0xBE: ".>", 0xBF: "/?",
    0xC0: "`~", 0xDB: "[{", 0xDC: "\\|", 0xDD: "]}", 0xDE: "'\"",
}
_MODIFIER_VKS = {0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}


def _vk_name(vk: int) -> str:
    if vk in _VK_NAMES:
        return _VK_NAMES[vk]
    if 0x30 <= vk <= 0x39:
        return chr(vk)
    if 0x41 <= vk <= 0x5A:
        return chr(vk)
    return f"VK{vk:#04x}"


def _format_combo(vk: int, modifiers: list[int]) -> str:
    parts = []
    if any(m in (0x11, 0xA2, 0xA3) for m in modifiers):
        parts.append("Ctrl")
    if any(m in (0x10, 0xA0, 0xA1) for m in modifiers):
        parts.append("Shift")
    if any(m in (0x12, 0xA4, 0xA5) for m in modifiers):
        parts.append("Alt")
    if any(m in (0x5B, 0x5C) for m in modifiers):
        parts.append("Win")
    parts.append(_vk_name(vk))
    return "+".join(parts)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class MacroSafetyConfig:
    """Travas de segurança para execução de macros."""
    min_trigger_frames: int = 1          # polls consecutivos antes de disparar
    require_window_in_list: bool = True  # bloqueia se perfil não tiver hwnd correspondido


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


_WIN_TRIG_LABELS = {
    "found": "Janela encontrada",
    "not_found": "Janela não encontrada",
    "minimized": "Minimizada",
    "maximized": "Maximizada",
    "normal": "Normal (restaurada)",
    "width": "Largura",
    "height": "Altura",
    "pos_x": "Posição X",
    "pos_y": "Posição Y",
}
_WIN_TRIG_NEEDS_VALUE = {"width", "height", "pos_x", "pos_y"}


@dataclass
class WindowTriggerCondition:
    """Trigger baseado no estado da janela (minimizada, maximizada, tamanho, posição)."""
    condition: str   # found | not_found | minimized | maximized | normal | width | height | pos_x | pos_y
    operator: str = "=="   # == != > < >= <=  (relevante para width/height/pos_x/pos_y)
    value: int = 0

    def check(self, hwnd: int, window_state: "dict | None") -> bool:
        if self.condition == "found":
            return hwnd != 0
        if self.condition == "not_found":
            return hwnd == 0
        if window_state is None:
            return False
        if self.condition == "minimized":
            return bool(window_state.get("minimized", False))
        if self.condition == "maximized":
            return bool(window_state.get("maximized", False))
        if self.condition == "normal":
            return not window_state.get("minimized", False) and not window_state.get("maximized", False)
        field_map = {"width": "width", "height": "height", "pos_x": "x", "pos_y": "y"}
        key = field_map.get(self.condition)
        if key is None:
            return False
        actual = int(window_state.get(key, 0))
        if self.operator == "==": return actual == self.value
        if self.operator == "!=": return actual != self.value
        if self.operator == ">":  return actual > self.value
        if self.operator == "<":  return actual < self.value
        if self.operator == ">=": return actual >= self.value
        if self.operator == "<=": return actual <= self.value
        return False

    def label(self) -> str:
        lbl = _WIN_TRIG_LABELS.get(self.condition, self.condition)
        if self.condition in _WIN_TRIG_NEEDS_VALUE:
            return f"{lbl} {self.operator} {self.value}"
        return lbl


@dataclass
class MacroAction:
    type: str   # click | key_press | move_mouse | wait | dynamic_input
    params: dict[str, Any]

    def label(self) -> str:
        p = self.params
        if self.type == "click":
            return f"Click ({p['x']},{p['y']}) {p.get('button','left')}"
        if self.type == "key_press":
            vk = p.get("vk", 0)
            mods = p.get("modifiers", [])
            return f"Key {_format_combo(vk, mods)}" if vk else "Key (vazio)"
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
        if self.type == "window_action":
            act = p.get("action", "?")
            if act in ("resize", "set_size"):
                return f"Window: resize {p.get('width','?')}×{p.get('height','?')}"
            if act == "move":
                return f"Window: move ({p.get('x','?')},{p.get('y','?')})"
            if act == "open_window":
                path = p.get("path", "?")
                return f"Window: open {path.split(chr(92))[-1]}"
            return f"Window: {act}"
        return self.type


@dataclass
class Macro:
    name: str
    enabled: bool = True
    triggers: list[TriggerCondition] = field(default_factory=list)
    image_triggers: list[ImageTriggerCondition] = field(default_factory=list)
    window_triggers: list[WindowTriggerCondition] = field(default_factory=list)
    actions: list[MacroAction] = field(default_factory=list)
    safety: MacroSafetyConfig = field(default_factory=MacroSafetyConfig)
    # runtime (não serializado)
    _was_active: bool = field(default=False, init=False, repr=False, compare=False)
    _trigger_frame_count: int = field(default=0, init=False, repr=False, compare=False)
    _confirm_armed: bool = field(default=False, init=False, repr=False, compare=False)

    def has_any_trigger(self) -> bool:
        return bool(self.triggers or self.image_triggers or self.window_triggers)

    def check_triggers(self, pixel_map: dict[tuple, tuple],
                       hwnd: int = 0, window_state: "dict | None" = None) -> bool:
        """Verifica todos os triggers (pixel E imagem E janela devem ser satisfeitos)."""
        if not self.has_any_trigger():
            return False
        if self.triggers and not all(
            t.matches(*pixel_map.get((t.x, t.y), (0, 0, 0)))
            for t in self.triggers
        ):
            return False
        if self.image_triggers and not all(t._found for t in self.image_triggers):
            return False
        if self.window_triggers and not all(
            t.check(hwnd, window_state) for t in self.window_triggers
        ):
            return False
        return True


@dataclass
class WindowProfile:
    """Perfil de janela: agrupa macros que rodam em uma janela específica."""
    name: str
    title_pattern: str = ""   # substring case-insensitive do título (vazio = global/absoluto)
    exe_path: str = ""        # caminho do executável para monitoramento e open_window
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
        self._window_states: dict[int, dict] = {}

        self._action_queue: list[tuple[MacroAction, int]] = []
        self._loop_macro: Macro | None = None
        self._loop_hwnd: int = 0

        self._action_timer = QTimer(self)
        self._action_timer.setSingleShot(True)
        self._action_timer.timeout.connect(self._exec_next_action)

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)
        self._waiting_image = False   # flag para match_templates in-flight
        self._process_status: dict[str, dict] = {}

        self._process_poll_timer = QTimer(self)
        self._process_poll_timer.setInterval(500)
        self._process_poll_timer.timeout.connect(self._poll_processes)

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

        exe_row = QHBoxLayout()
        self.inp_prof_path = QLineEdit()
        self.inp_prof_path.setPlaceholderText(r"C:\...\app.exe")
        self.inp_prof_path.textChanged.connect(self._on_prof_path_changed)
        exe_row.addWidget(self.inp_prof_path, 1)
        btn_prof_browse = QPushButton("Browse…")
        btn_prof_browse.setFixedWidth(70)
        btn_prof_browse.clicked.connect(self._browse_profile_exe)
        exe_row.addWidget(btn_prof_browse)
        pe.addRow("Executável:", exe_row)

        self.lbl_prof_exe_status = QLabel("—")
        self.lbl_prof_exe_status.setStyleSheet("color:#888; font-size:11px;")
        pe.addRow("Exe:", self.lbl_prof_exe_status)

        self.chk_prof_enabled = QCheckBox("Perfil ativo")
        self.chk_prof_enabled.setChecked(True)
        self.chk_prof_enabled.toggled.connect(self._on_prof_enabled_changed)
        pe.addRow("", self.chk_prof_enabled)

        self.lbl_prof_status = QLabel("—")
        self.lbl_prof_status.setStyleSheet("color:#888; font-size:11px;")
        pe.addRow("Status:", self.lbl_prof_status)

        l1.addWidget(self._grp_prof)

        # ── Info em tempo real ────────────────────────────────────────────────
        sep_info = QFrame()
        sep_info.setFrameShape(QFrame.HLine)
        sep_info.setFrameShadow(QFrame.Sunken)
        l1.addWidget(sep_info)

        lbl_info_hdr = QLabel("Janela em tempo real")
        lbl_info_hdr.setStyleSheet("font-weight:bold; font-size:11px; color:#888;")
        l1.addWidget(lbl_info_hdr)

        info_grid = QGridLayout()
        info_grid.setSpacing(3)
        info_grid.setContentsMargins(0, 0, 0, 0)

        self._win_info_fields: dict[str, QLabel] = {}
        _info_rows = [
            ("status",  "Status"),
            ("focused", "Foco"),
            ("title",   "Título"),
            ("hwnd",    "HWND"),
            ("pid",     "PID"),
            ("pos",     "Posição"),
            ("size",    "Tamanho"),
        ]
        for row, (key, label) in enumerate(_info_rows):
            lk = QLabel(f"{label}:")
            lk.setStyleSheet("color:#666; font-size:10px;")
            lv = QLabel("—")
            lv.setStyleSheet("font-size:10px;")
            lv.setWordWrap(True)
            info_grid.addWidget(lk, row, 0, Qt.AlignTop)
            info_grid.addWidget(lv, row, 1, Qt.AlignTop)
            self._win_info_fields[key] = lv

        l1.addLayout(info_grid)

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
        self._btn_save = QPushButton("💾 Salvar")
        self._btn_save.setFixedWidth(80)
        self._btn_save.clicked.connect(self._save_now)
        nr.addWidget(self._btn_save)
        el.addLayout(nr)

        # Triggers unificados
        grp_trig = QGroupBox("Triggers (todos devem bater)")
        tl = QVBoxLayout(grp_trig)
        self.trig_list = QListWidget()
        self.trig_list.setMaximumHeight(180)
        self.trig_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.trig_list.itemDoubleClicked.connect(self._edit_trigger)
        tl.addWidget(self.trig_list)
        tb = QHBoxLayout()
        btn_add_px = QPushButton("+ Pixel")
        btn_add_px.clicked.connect(self._add_pixel_trigger)
        tb.addWidget(btn_add_px)
        btn_add_img = QPushButton("+ Imagem")
        btn_add_img.clicked.connect(self._add_image_trigger)
        tb.addWidget(btn_add_img)
        btn_add_win = QPushButton("+ Janela")
        btn_add_win.clicked.connect(self._add_window_trigger)
        tb.addWidget(btn_add_win)
        btn_edit_t = QPushButton("Editar")
        btn_edit_t.clicked.connect(self._edit_trigger)
        tb.addWidget(btn_edit_t)
        btn_del_t = QPushButton("Remover")
        btn_del_t.clicked.connect(self._remove_trigger_unified)
        tb.addWidget(btn_del_t)
        tb.addStretch()
        tl.addLayout(tb)
        el.addWidget(grp_trig)

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
            self._poll_timer.start(100)
        else:
            self.btn_poll.setText("Start Polling")
            self._poll_timer.stop()
            self._waiting = False

    def _poll(self):
        # Pausa quando a janela principal está minimizada (evita loop descontrolado)
        from PySide6.QtCore import Qt as _Qt
        win = self.window()
        if win and win.windowState() & _Qt.WindowMinimized:
            return

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

        # ── Window triggers ──────────────────────────────────────────────────
        hwnds_needing_state: set[int] = set()
        for profile in self._profiles:
            if not profile.enabled:
                continue
            for macro in profile.macros:
                if not macro.enabled:
                    continue
                for wt in macro.window_triggers:
                    if wt.condition not in ("found", "not_found"):
                        hwnds_needing_state.add(profile._matched_hwnd)
        for hwnd in hwnds_needing_state:
            if hwnd:
                self.command_requested.emit("get_window_state", {"hwnd": hwnd})

        # Macros com apenas window triggers (found/not_found) não dependem de dados
        # assíncronos — avalia imediatamente a cada poll.
        has_window_only = any(
            macro.window_triggers and not macro.triggers and not macro.image_triggers
            for profile in self._profiles if profile.enabled
            for macro in profile.macros if macro.enabled
        )
        if has_window_only:
            self._evaluate_macros(self._last_pixel_map, only_pixel_triggered=False)

    def update_pixels(self, results: list[dict]):
        self._waiting = False
        pixel_map = {(r["x"], r["y"]): (r["r"], r["g"], r["b"]) for r in results}
        self._last_pixel_map = pixel_map
        self._update_triggers_live(pixel_map)
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
                # nem window triggers (os puramente de imagem esperam match_templates).
                if only_pixel_triggered and not macro.triggers and not macro.window_triggers:
                    continue

                window_state = self._window_states.get(hwnd)
                is_active = macro.check_triggers(pixel_map, hwnd=hwnd, window_state=window_state)

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

                if self._loop_macro is None and not self._action_queue and stable and not macro._was_active:
                    err = self._preflight_check(macro, profile)
                    if err:
                        self.log_event.emit("warn",
                            f"[{profile.name} / {macro.name}] BLOQUEADO — {err}")
                        macro._was_active = is_active
                        continue

                    all_trig = list(macro.triggers) + list(macro.image_triggers) + list(macro.window_triggers)
                    trig_info = ", ".join(t.label() for t in all_trig)
                    extra = (f" (estável por {macro._trigger_frame_count} frames)"
                             if macro.safety.min_trigger_frames > 1 else "")
                    self.log_event.emit("trigger",
                        f"[{profile.name} / {macro.name}] triggers OK{extra} → {trig_info}")

                    macro._confirm_armed = False
                    self._fire_macro(macro, hwnd)

                macro._was_active = is_active

    def _preflight_check(self, macro: Macro, profile: WindowProfile) -> str:
        """Retorna mensagem de erro se bloqueado, '' se ok."""
        # Se o macro tem trigger 'not_found', a janela ausente é esperada — não bloquear.
        has_not_found = any(wt.condition == "not_found" for wt in macro.window_triggers)
        if has_not_found:
            return ""
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
            if self._loop_macro:
                self._loop_macro._was_active = False  # permite re-disparo imediato no próximo poll
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
            if hwnd and act.type in ("click", "move_mouse", "window_action"):
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
        self._update_triggers_live(self._last_pixel_map)
        self._evaluate_macros(self._last_pixel_map, only_pixel_triggered=False)
        self._refresh_profile_list()

    def update_window_state(self, state: dict):
        """Processa resposta de get_window_state {hwnd, minimized, maximized, width, height, x, y}."""
        hwnd = state.get("hwnd", 0)
        if hwnd:
            self._window_states[hwnd] = state
        self._update_triggers_live(self._last_pixel_map)
        self._evaluate_macros(self._last_pixel_map, only_pixel_triggered=False)

    # ── Process monitoring ────────────────────────────────────────────────────

    def start_monitoring(self):
        self._process_poll_timer.start()
        self._poll_processes()

    def stop_monitoring(self):
        self._process_poll_timer.stop()

    def _poll_processes(self):
        paths = [p.exe_path for p in self._profiles if p.exe_path]
        if paths:
            self.command_requested.emit("check_processes", {"paths": paths})
        # Atualiza lista de janelas abertas para hwnd matching e status de minimizado/maximizado
        self.command_requested.emit("list_windows", {"_silent": True})

    def update_process_status(self, results: list[dict]):
        for r in results:
            path = r.get("path", "")
            if path:
                self._process_status[path] = r
        self._refresh_profile_list()
        self._update_profile_status_label()

    def update_browser(self, entries: list[dict], path: str):
        if hasattr(self, "_browse_dlg") and self._browse_dlg and self._browse_dlg.isVisible():
            self._browse_dlg.update_browser(entries, path)

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
        for w in (self.inp_prof_name, self.inp_prof_pattern, self.inp_prof_path, self.chk_prof_enabled):
            w.blockSignals(True)
        self.inp_prof_name.setText(p.name)
        self.inp_prof_pattern.setText(p.title_pattern)
        self.inp_prof_path.setText(p.exe_path)
        self.chk_prof_enabled.setChecked(p.enabled)
        for w in (self.inp_prof_name, self.inp_prof_pattern, self.inp_prof_path, self.chk_prof_enabled):
            w.blockSignals(False)
        self._update_profile_status_label()
        self._refresh_macro_list()

    def _refresh_profile_list(self):
        cur = self._sel_profile
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        for p in self._profiles:
            # Exe running status
            proc = self._process_status.get(p.exe_path) if p.exe_path else None
            if proc is None:
                exe_badge = ""
            elif proc.get("running"):
                exe_badge = " [▶]"
            else:
                exe_badge = " [✗]"

            # Window match status
            no_target = not p.title_pattern.strip()
            matched = p._matched_hwnd != 0
            if no_target:
                win_suffix = ""
                color = QColor("#aaa") if p.enabled else QColor("#666")
            elif matched:
                win_suffix = f"  hwnd={p._matched_hwnd}"
                color = QColor("#4ec94e") if p.enabled else QColor("#666")
            else:
                win_suffix = "  ✗ janela"
                color = QColor("#e06060") if p.enabled else QColor("#666")

            # Exe color overrides if exe defined
            if p.exe_path and proc is not None:
                if proc.get("running"):
                    color = QColor("#4ec94e") if p.enabled else QColor("#666")
                else:
                    color = QColor("#e06060") if p.enabled else QColor("#666")

            item = QListWidgetItem(p.name + exe_badge + win_suffix)
            item.setForeground(color)
            self.profile_list.addItem(item)
        if 0 <= cur < self.profile_list.count():
            self.profile_list.setCurrentRow(cur)
        self.profile_list.blockSignals(False)
        self._update_profile_status_label()

    def _update_profile_status_label(self):
        p = self._cur_profile()
        if p is None:
            for v in self._win_info_fields.values():
                v.setText("—")
                v.setStyleSheet("font-size:10px;")
            return
        # Exe status
        if p.exe_path:
            proc = self._process_status.get(p.exe_path)
            if proc is None:
                exe_txt = "exe: aguardando…"
                exe_style = "color:#888;"
            elif proc.get("running"):
                wins = proc.get("windows", [])
                if wins:
                    states = []
                    for w in wins:
                        if w.get("minimized"):
                            states.append("minimizado")
                        elif w.get("maximized"):
                            states.append("maximizado")
                        else:
                            states.append("normal")
                    exe_txt = f"exe: rodando ({', '.join(states)})"
                else:
                    exe_txt = "exe: rodando"
                exe_style = "color:#4ec94e;"
            else:
                exe_txt = "exe: fechado"
                exe_style = "color:#e06060;"
            self.lbl_prof_exe_status.setText(exe_txt)
            self.lbl_prof_exe_status.setStyleSheet(exe_style + " font-size:11px;")
        else:
            self.lbl_prof_exe_status.setText("—")
            self.lbl_prof_exe_status.setStyleSheet("color:#888; font-size:11px;")

        # Window match status
        if not p.title_pattern.strip():
            self.lbl_prof_status.setText("global (coordenadas absolutas)")
            self.lbl_prof_status.setStyleSheet("color:#888; font-size:11px;")
        elif p._matched_hwnd:
            self.lbl_prof_status.setText(f"correspondida — hwnd={p._matched_hwnd}")
            self.lbl_prof_status.setStyleSheet("color:#4ec94e; font-size:11px;")
        else:
            self.lbl_prof_status.setText(f"não encontrada (padrão: '{p.title_pattern}')")
            self.lbl_prof_status.setStyleSheet("color:#e06060; font-size:11px;")

        self._update_win_info(p)

    def _update_win_info(self, p):
        f = self._win_info_fields

        def _clear():
            for v in f.values():
                v.setText("—")
                v.setStyleSheet("font-size:10px;")

        # Tenta obter a janela via exe_path primeiro, depois via hwnd matched
        win = None
        if p.exe_path:
            proc = self._process_status.get(p.exe_path)
            if proc and proc.get("running"):
                wins = proc.get("windows", [])
                if wins:
                    win = next((w for w in wins if w.get("focused")), wins[0])

        if win is None and p._matched_hwnd:
            # Fallback: busca nos remote_windows pelo hwnd
            rw = next((w for w in self._remote_windows if w.get("hwnd") == p._matched_hwnd), None)
            if rw:
                rect = rw.get("rect", {})
                win = {
                    "hwnd": rw["hwnd"],
                    "title": rw.get("title", ""),
                    "x": rect.get("x"), "y": rect.get("y"),
                    "width": rect.get("w"), "height": rect.get("h"),
                }

        if win is None:
            if p.exe_path:
                proc = self._process_status.get(p.exe_path)
                if proc is None:
                    f["status"].setText("Aguardando…")
                    f["status"].setStyleSheet("font-size:10px; color:#888;")
                else:
                    f["status"].setText("Não encontrada")
                    f["status"].setStyleSheet("font-size:10px; color:#e06060;")
                for k in ("focused", "title", "hwnd", "pid", "pos", "size"):
                    f[k].setText("—")
                    f[k].setStyleSheet("font-size:10px;")
            elif not p.title_pattern.strip():
                f["status"].setText("Global")
                f["status"].setStyleSheet("font-size:10px; color:#888;")
                for k in ("focused", "title", "hwnd", "pid", "pos", "size"):
                    f[k].setText("—")
                    f[k].setStyleSheet("font-size:10px;")
            else:
                f["status"].setText("Não encontrada")
                f["status"].setStyleSheet("font-size:10px; color:#e06060;")
                for k in ("focused", "title", "hwnd", "pid", "pos", "size"):
                    f[k].setText("—")
                    f[k].setStyleSheet("font-size:10px;")
            return

        if win.get("minimized"):
            s_txt, s_col = "Minimizada", "#f0c040"
        elif win.get("maximized"):
            s_txt, s_col = "Maximizada", "#4ec94e"
        else:
            s_txt, s_col = "Aberta", "#4ec94e"

        f["status"].setText(s_txt)
        f["status"].setStyleSheet(f"font-size:10px; color:{s_col}; font-weight:bold;")

        focused = win.get("focused")
        f["focused"].setText("Sim" if focused else "Não")
        f["focused"].setStyleSheet("font-size:10px; color:#4ec94e;" if focused else "font-size:10px; color:#888;")

        f["title"].setText(win.get("title") or "—")
        f["hwnd"].setText(str(win.get("hwnd", "—")))
        f["pid"].setText(str(win.get("pid", "—")) if win.get("pid") else "—")

        x, y = win.get("x"), win.get("y")
        f["pos"].setText(f"x={x}  y={y}" if x is not None else "—")

        w_, h_ = win.get("width"), win.get("height")
        f["size"].setText(f"{w_} × {h_}" if w_ is not None else "—")

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

    def _on_prof_path_changed(self, text: str):
        p = self._cur_profile()
        if p:
            p.exe_path = text
            self._poll_processes()
            self._schedule_save()

    def _browse_profile_exe(self):
        from ui.windows_panel import _AddPathDialog
        self._browse_dlg = _AddPathDialog(self)
        self._browse_dlg.browse_requested.connect(
            lambda path: self.command_requested.emit("list_directory", {"path": path, "_browser": True})
        )
        if self._browse_dlg.exec() == QDialog.Accepted:
            path = self._browse_dlg.result_path()
            if path:
                self.inp_prof_path.setText(path)
        self._browse_dlg = None

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
        for w in (self.inp_name, self.chk_enabled):
            w.blockSignals(True)
        self.inp_name.setText(macro.name)
        self.chk_enabled.setChecked(macro.enabled)
        for w in (self.inp_name, self.chk_enabled):
            w.blockSignals(False)
        self._reload_triggers_unified()
        self._reload_actions()
        if self._last_pixel_map:
            self._update_triggers_live(self._last_pixel_map)

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

    # ── Editor: name / enabled / safety ──────────────────────────────────────

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


    # ── Editor: triggers unificados ───────────────────────────────────────────

    def _reload_triggers_unified(self):
        macro = self._cur_macro()
        self.trig_list.clear()
        if macro is None:
            return
        for i, t in enumerate(macro.triggers):
            item = QListWidgetItem(f"[PIXEL] {t.label()}")
            item.setData(Qt.UserRole, ("pixel", i))
            item.setForeground(QColor("#aaa"))
            self.trig_list.addItem(item)
        for i, it in enumerate(macro.image_triggers):
            item = QListWidgetItem(f"[IMAGE] {it.label()}")
            item.setData(Qt.UserRole, ("image", i))
            item.setForeground(QColor("#aaa"))
            self.trig_list.addItem(item)
        for i, wt in enumerate(macro.window_triggers):
            item = QListWidgetItem(f"[JANELA] {wt.label()}")
            item.setData(Qt.UserRole, ("window", i))
            item.setForeground(QColor("#aaa"))
            self.trig_list.addItem(item)

    def _add_pixel_trigger(self):
        macro = self._cur_macro()
        if macro is None:
            return
        dlg = AddTriggerDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        macro.triggers.append(dlg.result())
        self._reload_triggers_unified()
        self._schedule_save()

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
        macro.image_triggers.append(dlg.result())
        self._reload_triggers_unified()
        self._schedule_save()

    def _add_window_trigger(self):
        macro = self._cur_macro()
        if macro is None:
            return
        dlg = AddWindowTriggerDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        macro.window_triggers.append(dlg.result())
        self._reload_triggers_unified()
        self._schedule_save()

    def _edit_trigger(self, _item=None):
        macro = self._cur_macro()
        if macro is None:
            return
        item = self.trig_list.currentItem()
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        ttype, idx = data
        if ttype == "pixel":
            dlg = AddTriggerDialog(self, existing=macro.triggers[idx])
            if dlg.exec() == QDialog.Accepted:
                macro.triggers[idx] = dlg.result()
                self._reload_triggers_unified()
                self._schedule_save()
        elif ttype == "image":
            dlg = _ImageTriggerThresholdDialog(None, self, existing=macro.image_triggers[idx])
            if dlg.exec() == QDialog.Accepted:
                macro.image_triggers[idx] = dlg.result()
                self._reload_triggers_unified()
                self._schedule_save()
        elif ttype == "window":
            dlg = AddWindowTriggerDialog(self, existing=macro.window_triggers[idx])
            if dlg.exec() == QDialog.Accepted:
                macro.window_triggers[idx] = dlg.result()
                self._reload_triggers_unified()
                self._schedule_save()

    def _remove_trigger_unified(self):
        macro = self._cur_macro()
        if macro is None:
            return
        item = self.trig_list.currentItem()
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        ttype, idx = data
        if ttype == "pixel":
            del macro.triggers[idx]
        elif ttype == "image":
            del macro.image_triggers[idx]
        elif ttype == "window":
            del macro.window_triggers[idx]
        self._reload_triggers_unified()
        self._schedule_save()

    # ── Editor: actions ───────────────────────────────────────────────────────

    def _reload_actions(self):
        macro = self._cur_macro()
        self.action_list.clear()
        if macro:
            for act in macro.actions:
                self.action_list.addItem(act.label())

    def _get_saved_windows(self) -> list[dict]:
        return [{"path": p.exe_path, "alias": p.name}
                for p in self._profiles if p.exe_path]

    def _add_action(self):
        macro = self._cur_macro()
        if macro is None:
            return
        dlg = AddActionDialog(self, saved_windows=self._get_saved_windows())
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
        dlg = AddActionDialog(self, existing=macro.actions[row], saved_windows=self._get_saved_windows())
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

    # ── Trigger live update ───────────────────────────────────────────────────

    @staticmethod
    def _window_trigger_actual(wt: "WindowTriggerCondition", hwnd: int, state: "dict | None") -> str:
        if wt.condition in ("found", "not_found"):
            return "encontrada" if hwnd != 0 else "não encontrada"
        if state is None:
            return "?"
        if wt.condition == "minimized":
            return "sim" if state.get("minimized") else "não"
        if wt.condition == "maximized":
            return "sim" if state.get("maximized") else "não"
        if wt.condition == "normal":
            is_n = not state.get("minimized") and not state.get("maximized")
            return "sim" if is_n else "não"
        field_map = {"width": "width", "height": "height", "pos_x": "x", "pos_y": "y"}
        key = field_map.get(wt.condition, "")
        return str(state.get(key, "?")) if key else "?"

    def _update_triggers_live(self, pixel_map: dict):
        macro = self._cur_macro()
        if macro is None:
            return
        profile = self._cur_profile()
        hwnd = profile._matched_hwnd if profile else 0
        for row in range(self.trig_list.count()):
            item = self.trig_list.item(row)
            if item is None:
                continue
            data = item.data(Qt.UserRole)
            if not data:
                continue
            ttype, idx = data
            if ttype == "pixel" and idx < len(macro.triggers):
                t = macro.triggers[idx]
                rgb = pixel_map.get((t.x, t.y))
                if rgb:
                    r, g, b = rgb
                    matches = t.matches(r, g, b)
                    item.setText(f"[PIXEL] {t.label()}  {'✓' if matches else '✗'} #{r:02X}{g:02X}{b:02X}")
                    item.setForeground(QColor("#4ec94e") if matches else QColor("#e06060"))
            elif ttype == "image" and idx < len(macro.image_triggers):
                it = macro.image_triggers[idx]
                pct = int(it._confidence * 100)
                item.setText(f"[IMAGE] {'✓' if it._found else '✗'} {it.label()}  [{pct}%]")
                item.setForeground(QColor("#4ec94e") if it._found else QColor("#e06060"))
            elif ttype == "window" and idx < len(macro.window_triggers):
                wt = macro.window_triggers[idx]
                state = self._window_states.get(hwnd)
                matched = wt.check(hwnd, state)
                actual = self._window_trigger_actual(wt, hwnd, state)
                item.setText(f"[JANELA] {'✓' if matched else '✗'} {wt.label()}  (atual: {actual})")
                item.setForeground(QColor("#4ec94e") if matched else QColor("#e06060"))

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
            "safety": {
                "min_trigger_frames": m.safety.min_trigger_frames,
                "require_window_in_list": m.safety.require_window_in_list,
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
            "window_triggers": [
                {"condition": wt.condition, "operator": wt.operator, "value": wt.value}
                for wt in m.window_triggers
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
        window_triggers = [
            WindowTriggerCondition(
                condition=wt["condition"],
                operator=wt.get("operator", "=="),
                value=int(wt.get("value", 0)),
            )
            for wt in item.get("window_triggers", [])
        ]
        return Macro(
            name=item.get("name", "Macro"),
            enabled=item.get("enabled", True),
            safety=MacroSafetyConfig(
                min_trigger_frames=s.get("min_trigger_frames", 1),
                require_window_in_list=s.get("require_window_in_list", True),
            ),
            triggers=triggers,
            image_triggers=image_triggers,
            window_triggers=window_triggers,
            actions=actions,
        )

    def dump_state(self) -> dict:
        return {
            "polling_active": self.btn_poll.isChecked(),
            "profiles": [
                {
                    "name": p.name,
                    "title_pattern": p.title_pattern,
                    "exe_path": p.exe_path,
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
                exe_path=pd.get("exe_path", ""),
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

        self._poll_timer.setInterval(100)

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
        self._process_poll_timer.stop()
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
    def __init__(self, parent=None, existing: "TriggerCondition | None" = None):
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


class KeyCaptureWidget(QLineEdit):
    """Campo que captura uma combinação de teclas ao ser pressionado."""

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
            self.setText(_format_combo(vk, modifiers))

    def keyPressEvent(self, event: QKeyEvent):
        vk = event.nativeVirtualKey()
        if not vk or vk in _MODIFIER_VKS:
            return  # aguarda tecla principal
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
        self.setText(_format_combo(vk, mods))


class AddActionDialog(QDialog):
    def __init__(self, parent=None, existing: "MacroAction | None" = None,
                 saved_windows: "list[dict] | None" = None):
        super().__init__(parent)
        self.setWindowTitle("Editar Ação" if existing else "Adicionar Ação")
        self._saved_windows = saved_windows or []
        self._lay = QGridLayout(self)

        self._lay.addWidget(QLabel("Tipo:"), 0, 0)
        self.combo = QComboBox()
        self.combo.addItems(["click", "move_mouse", "key_press", "wait", "dynamic_input", "window_action"])
        self.combo.currentTextChanged.connect(self._refresh_params)
        self._lay.addWidget(self.combo, 0, 1, 1, 3)

        self._param_widgets: dict[str, QSpinBox | QComboBox | QLineEdit] = {}
        self._param_rows_start = 1
        self._wa_sub_container: "QWidget | None" = None
        self._wa_sub_layout = None

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
        # Migração: ações antigas usavam "action" como chave do sub-action de window_action
        if "wa" in self._param_widgets and "wa" not in params and "action" in params:
            params = dict(params)
            params["wa"] = params.pop("action")
        for key, widget in list(self._param_widgets.items()):
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
                # Find by stored data (exe path)
                for i in range(widget.count()):
                    if widget.itemData(i) == val:
                        widget.setCurrentIndex(i)
                        break
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
            self._lay.addWidget(QLabel("Tecla:"), row, 0)
            kw = KeyCaptureWidget()
            self._lay.addWidget(kw, row, 1, 1, 3)
            self._param_widgets["key_combo"] = kw
            row += 1
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
            from PySide6.QtWidgets import QFormLayout as _QFL
            self._wa_sub_layout = _QFL(self._wa_sub_container)
            self._wa_sub_layout.setContentsMargins(0, 0, 0, 0)
            self._lay.addWidget(self._wa_sub_container, row, 0, 1, 4)
            row += 1

            cb.currentTextChanged.connect(self._refresh_window_action_sub)
            self._refresh_window_action_sub(cb.currentText())
        self._lay.addWidget(self.btns, row, 0, 1, 4)

    def _refresh_window_action_sub(self, action: str):
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
            x = QSpinBox(); x.setRange(-9999, 9999); x.setValue(0)
            self._wa_sub_layout.addRow("X:", x)
            self._param_widgets["x"] = x
            y = QSpinBox(); y.setRange(-9999, 9999); y.setValue(0)
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


class AddWindowTriggerDialog(QDialog):
    """Configura um WindowTriggerCondition."""

    def __init__(self, parent=None, existing: "WindowTriggerCondition | None" = None):
        super().__init__(parent)
        self.setWindowTitle("Editar Trigger de Janela" if existing else "Adicionar Trigger de Janela")
        self._lay = QFormLayout(self)

        self.combo_cond = QComboBox()
        self.combo_cond.addItems([
            "found", "not_found", "minimized", "maximized", "normal",
            "width", "height", "pos_x", "pos_y",
        ])
        self.combo_cond.currentTextChanged.connect(self._refresh)
        self._lay.addRow("Condição:", self.combo_cond)

        self._lbl_op = QLabel("Operador:")
        self.combo_op = QComboBox()
        self.combo_op.addItems(["==", "!=", ">", "<", ">=", "<="])
        self._lay.addRow(self._lbl_op, self.combo_op)

        self._lbl_val = QLabel("Valor (px):")
        self.spin_val = QSpinBox()
        self.spin_val.setRange(0, 99999)
        self._lay.addRow(self._lbl_val, self.spin_val)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        self._lay.addRow(btns)

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
