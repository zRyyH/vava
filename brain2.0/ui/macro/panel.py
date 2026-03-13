"""
MacroPanel — painel principal de automação por janelas.
"""
from __future__ import annotations

import copy
import time

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QSplitter,
    QVBoxLayout, QWidget,
)

import config as _cfg
from ui.macro.models import (
    Macro, MacroAction, MacroSafetyConfig, WindowProfile,
    ImageTriggerCondition, TriggerCondition, WindowTriggerCondition,
    macro_to_dict, macro_from_dict,
)
from ui.macro.dialogs import (
    AddTriggerDialog, ImageTriggerDialog, AddWindowTriggerDialog, AddActionDialog,
)
from ui.window_picker import pick_region_from_window


class MacroPanel(QWidget):
    command_requested = Signal(str, dict)
    log_event         = Signal(str, str)   # (level, message)

    def __init__(self):
        super().__init__()
        self._profiles: list[WindowProfile] = []
        self._sel_profile = -1
        self._sel_macro   = -1

        self._waiting       = False
        self._waiting_image = False
        self._last_pixel_map: dict = {}
        self._remote_windows: list[dict] = []
        self._window_states: dict[int, dict] = {}
        self._process_status: dict[str, dict] = {}

        self._action_queue: list[tuple[MacroAction, int]] = []
        self._loop_macro: Macro | None = None
        self._loop_hwnd:  int = 0

        self._action_timer = QTimer(self)
        self._action_timer.setSingleShot(True)
        self._action_timer.timeout.connect(self._exec_next_action)

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)

        self._process_poll_timer = QTimer(self)
        self._process_poll_timer.setInterval(500)
        self._process_poll_timer.timeout.connect(self._poll_processes)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(1000)
        self._save_timer.timeout.connect(self._autosave)

        self._build_ui()

    # ── Helpers ───────────────────────────────────────────────────────────────

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

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        splitter.addWidget(self._build_col_profiles())
        splitter.addWidget(self._build_col_macros())
        splitter.addWidget(self._build_col_editor())

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 3)

    def _build_col_profiles(self) -> QWidget:
        col = QWidget()
        lay = QVBoxLayout(col)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        lbl = QLabel("Janelas")
        lbl.setStyleSheet("font-weight:bold; font-size:13px; color:#6ec6f5;")
        lay.addWidget(lbl)

        self.profile_list = QListWidget()
        self.profile_list.currentRowChanged.connect(self._on_profile_selected)
        lay.addWidget(self.profile_list, 1)

        btns = QHBoxLayout()
        btn_add = QPushButton("+ Janela")
        btn_add.clicked.connect(self._add_profile)
        btns.addWidget(btn_add)
        btn_del = QPushButton("Remover")
        btn_del.clicked.connect(self._remove_profile)
        btns.addWidget(btn_del)
        lay.addLayout(btns)

        # ── editor de perfil ──
        self._grp_prof = QGroupBox("Configurar Janela")
        self._grp_prof.setEnabled(False)
        form = QFormLayout(self._grp_prof)
        form.setSpacing(4)

        self.inp_prof_name = QLineEdit()
        self.inp_prof_name.setPlaceholderText("Nome do perfil")
        self.inp_prof_name.textChanged.connect(self._on_prof_name_changed)
        form.addRow("Nome:", self.inp_prof_name)

        self.inp_prof_pattern = QLineEdit()
        self.inp_prof_pattern.setPlaceholderText("ex: Notepad  (vazio = global)")
        self.inp_prof_pattern.setToolTip(
            "Substring do título da janela (case-insensitive).\n"
            "Vazio = perfil global (coordenadas absolutas, sem hwnd)."
        )
        self.inp_prof_pattern.textChanged.connect(self._on_prof_pattern_changed)
        form.addRow("Padrão de título:", self.inp_prof_pattern)

        exe_row = QHBoxLayout()
        self.inp_prof_path = QLineEdit()
        self.inp_prof_path.setPlaceholderText(r"C:\...\app.exe")
        self.inp_prof_path.textChanged.connect(self._on_prof_path_changed)
        exe_row.addWidget(self.inp_prof_path, 1)
        btn_browse = QPushButton("Browse…")
        btn_browse.setFixedWidth(70)
        btn_browse.clicked.connect(self._browse_profile_exe)
        exe_row.addWidget(btn_browse)
        form.addRow("Executável:", exe_row)

        self.lbl_prof_exe_status = QLabel("—")
        self.lbl_prof_exe_status.setStyleSheet("color:#888; font-size:11px;")
        form.addRow("Exe:", self.lbl_prof_exe_status)

        self.chk_prof_enabled = QCheckBox("Perfil ativo")
        self.chk_prof_enabled.setChecked(True)
        self.chk_prof_enabled.toggled.connect(self._on_prof_enabled_changed)
        form.addRow("", self.chk_prof_enabled)

        self.lbl_prof_status = QLabel("—")
        self.lbl_prof_status.setStyleSheet("color:#888; font-size:11px;")
        form.addRow("Status:", self.lbl_prof_status)

        lay.addWidget(self._grp_prof)

        # ── info em tempo real ──
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        lay.addWidget(sep)

        lbl_info = QLabel("Janela em tempo real")
        lbl_info.setStyleSheet("font-weight:bold; font-size:11px; color:#888;")
        lay.addWidget(lbl_info)

        info_grid = QGridLayout()
        info_grid.setSpacing(3)
        self._win_info_fields: dict[str, QLabel] = {}
        for row, (key, label) in enumerate([
            ("status", "Status"), ("focused", "Foco"), ("title", "Título"),
            ("hwnd", "HWND"), ("pid", "PID"), ("pos", "Posição"), ("size", "Tamanho"),
        ]):
            lk = QLabel(f"{label}:")
            lk.setStyleSheet("color:#666; font-size:10px;")
            lv = QLabel("—")
            lv.setStyleSheet("font-size:10px;")
            lv.setWordWrap(True)
            info_grid.addWidget(lk, row, 0, Qt.AlignTop)
            info_grid.addWidget(lv, row, 1, Qt.AlignTop)
            self._win_info_fields[key] = lv
        lay.addLayout(info_grid)

        return col

    def _build_col_macros(self) -> QWidget:
        col = QWidget()
        lay = QVBoxLayout(col)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        lbl = QLabel("Macros")
        lbl.setStyleSheet("font-weight:bold; font-size:13px; color:#6ec6f5;")
        lay.addWidget(lbl)

        self.macro_list = QListWidget()
        self.macro_list.currentRowChanged.connect(self._on_macro_selected)
        lay.addWidget(self.macro_list, 1)

        row1 = QHBoxLayout()
        btn_add = QPushButton("+ Macro")
        btn_add.clicked.connect(self._add_macro)
        row1.addWidget(btn_add)
        btn_dup = QPushButton("Dup")
        btn_dup.clicked.connect(self._duplicate_macro)
        row1.addWidget(btn_dup)
        btn_del = QPushButton("Remover")
        btn_del.clicked.connect(self._remove_macro)
        row1.addWidget(btn_del)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        btn_up = QPushButton("↑")
        btn_up.clicked.connect(self._move_macro_up)
        row2.addWidget(btn_up)
        btn_dn = QPushButton("↓")
        btn_dn.clicked.connect(self._move_macro_down)
        row2.addWidget(btn_dn)
        row2.addStretch()
        lay.addLayout(row2)

        return col

    def _build_col_editor(self) -> QWidget:
        col = QWidget()
        lay = QVBoxLayout(col)
        lay.setContentsMargins(4, 0, 0, 0)
        lay.setSpacing(4)

        self._macro_editor = QWidget()
        self._macro_editor.setEnabled(False)
        el = QVBoxLayout(self._macro_editor)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(4)

        # nome + ativo + salvar
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

        # triggers
        grp_trig = QGroupBox("Triggers (todos devem ser satisfeitos)")
        tl = QVBoxLayout(grp_trig)
        self.trig_list = QListWidget()
        self.trig_list.setMaximumHeight(180)
        self.trig_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.trig_list.itemDoubleClicked.connect(self._edit_trigger)
        tl.addWidget(self.trig_list)

        tb = QHBoxLayout()
        btn_add_px  = QPushButton("+ Pixel");  btn_add_px.clicked.connect(self._add_pixel_trigger)
        btn_add_img = QPushButton("+ Imagem"); btn_add_img.clicked.connect(self._add_image_trigger)
        btn_add_win = QPushButton("+ Janela"); btn_add_win.clicked.connect(self._add_window_trigger)
        btn_edit_t  = QPushButton("Editar");   btn_edit_t.clicked.connect(self._edit_trigger)
        btn_del_t   = QPushButton("Remover");  btn_del_t.clicked.connect(self._remove_trigger)
        for b in (btn_add_px, btn_add_img, btn_add_win, btn_edit_t, btn_del_t):
            tb.addWidget(b)
        tb.addStretch()
        tl.addLayout(tb)
        el.addWidget(grp_trig)

        # ações
        grp_act = QGroupBox("Sequência de Ações")
        al = QVBoxLayout(grp_act)
        self.action_list = QListWidget()
        self.action_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.action_list.itemDoubleClicked.connect(self._edit_action)
        al.addWidget(self.action_list, 1)

        ab = QHBoxLayout()
        btn_add_a = QPushButton("+ Ação");  btn_add_a.clicked.connect(self._add_action)
        btn_edit_a = QPushButton("Editar"); btn_edit_a.clicked.connect(self._edit_action)
        btn_del_a  = QPushButton("Remover"); btn_del_a.clicked.connect(self._remove_action)
        btn_up_a   = QPushButton("↑");      btn_up_a.clicked.connect(self._move_action_up)
        btn_dn_a   = QPushButton("↓");      btn_dn_a.clicked.connect(self._move_action_down)
        for b in (btn_add_a, btn_edit_a, btn_del_a, btn_up_a, btn_dn_a):
            ab.addWidget(b)
        ab.addStretch()
        al.addLayout(ab)
        el.addWidget(grp_act, 1)

        lay.addWidget(self._macro_editor)
        return col

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
        win = self.window()
        if win and win.windowState() & Qt.WindowMinimized:
            return

        # pixel triggers
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

        # image triggers
        if not self._waiting_image:
            per_hwnd: dict[int, list[dict]] = {}
            for pi, profile in enumerate(self._profiles):
                if not profile.enabled:
                    continue
                hwnd = profile._matched_hwnd
                for mi, macro in enumerate(profile.macros):
                    if not macro.enabled:
                        continue
                    for ti, it in enumerate(macro.image_triggers):
                        per_hwnd.setdefault(hwnd, []).append({
                            "id": f"{pi}:{mi}:{ti}",
                            "data": it.template_b64,
                            "threshold": it.threshold,
                        })
            for hwnd, templates in per_hwnd.items():
                params: dict = {"templates": templates}
                if hwnd:
                    params["hwnd"] = hwnd
                self._waiting_image = True
                self.command_requested.emit("match_templates", params)
                break

        # window state triggers
        hwnds: set[int] = set()
        for profile in self._profiles:
            if not profile.enabled:
                continue
            for macro in profile.macros:
                if not macro.enabled:
                    continue
                for wt in macro.window_triggers:
                    if wt.condition not in ("found", "not_found"):
                        hwnds.add(profile._matched_hwnd)
        for hwnd in hwnds:
            if hwnd:
                self.command_requested.emit("get_window_state", {"hwnd": hwnd})

        # macros com apenas window trigger found/not_found
        has_window_only = any(
            macro.window_triggers and not macro.triggers and not macro.image_triggers
            for profile in self._profiles if profile.enabled
            for macro in profile.macros if macro.enabled
        )
        if has_window_only:
            self._evaluate_macros(self._last_pixel_map, only_pixel_triggered=False)

    # ── Update handlers ───────────────────────────────────────────────────────

    def update_pixels(self, results: list[dict]):
        self._waiting = False
        pixel_map = {(r["x"], r["y"]): (r["r"], r["g"], r["b"]) for r in results}
        self._last_pixel_map = pixel_map
        self._update_triggers_live(pixel_map)
        self._evaluate_macros(pixel_map, only_pixel_triggered=True)
        self._refresh_profile_list()

    def update_image_matches(self, results: list[dict]):
        self._waiting_image = False
        for r in results:
            parts = r.get("id", "").split(":")
            if len(parts) != 3:
                continue
            try:
                pi, mi, ti = int(parts[0]), int(parts[1]), int(parts[2])
                it = self._profiles[pi].macros[mi].image_triggers[ti]
                it._found      = r.get("found", False)
                it._confidence = r.get("confidence", 0.0)
                it._match_x    = r.get("x", 0)
                it._match_y    = r.get("y", 0)
            except (IndexError, ValueError):
                continue
        self._update_triggers_live(self._last_pixel_map)
        self._evaluate_macros(self._last_pixel_map, only_pixel_triggered=False)
        self._refresh_profile_list()

    def update_window_state(self, state: dict):
        hwnd = state.get("hwnd", 0)
        if hwnd:
            self._window_states[hwnd] = state
        self._update_triggers_live(self._last_pixel_map)
        self._evaluate_macros(self._last_pixel_map, only_pixel_triggered=False)

    def update_remote_windows(self, windows: list[dict]):
        self._remote_windows = windows
        for profile in self._profiles:
            profile._matched_hwnd = profile.match_windows(windows)
        self._refresh_profile_list()
        self._update_profile_status_label()

    def update_process_status(self, results: list[dict]):
        for r in results:
            if path := r.get("path", ""):
                self._process_status[path] = r
        self._refresh_profile_list()
        self._update_profile_status_label()

    def update_browser(self, entries: list[dict], path: str):
        if hasattr(self, "_browse_dlg") and self._browse_dlg and self._browse_dlg.isVisible():
            self._browse_dlg.update_browser(entries, path)

    # ── Macro evaluation ──────────────────────────────────────────────────────

    def _evaluate_macros(self, pixel_map: dict, only_pixel_triggered: bool):
        for profile in self._profiles:
            if not profile.enabled:
                for m in profile.macros:
                    m._was_active = False
                    m._trigger_frame_count = 0
                continue

            hwnd = profile._matched_hwnd
            for macro in profile.macros:
                if not macro.enabled:
                    macro._was_active = False
                    macro._trigger_frame_count = 0
                    continue

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

                if (self._loop_macro is None and not self._action_queue
                        and stable and not macro._was_active):
                    err = self._preflight_check(macro, profile)
                    if err:
                        self.log_event.emit("warn",
                            f"[{profile.name} / {macro.name}] BLOQUEADO — {err}")
                        macro._was_active = is_active
                        continue
                    all_trigs = list(macro.triggers) + list(macro.image_triggers) + list(macro.window_triggers)
                    extra = (f" (estável por {macro._trigger_frame_count} frames)"
                             if macro.safety.min_trigger_frames > 1 else "")
                    self.log_event.emit("trigger",
                        f"[{profile.name} / {macro.name}] triggers OK{extra} → "
                        f"{', '.join(t.label() for t in all_trigs)}")
                    self._fire_macro(macro, hwnd)

                macro._was_active = is_active

    def _preflight_check(self, macro: Macro, profile: WindowProfile) -> str:
        if any(wt.condition == "not_found" for wt in macro.window_triggers):
            return ""
        if profile.title_pattern.strip() and profile._matched_hwnd == 0:
            if macro.safety.require_window_in_list:
                return f"janela '{profile.title_pattern}' não encontrada"
        return ""

    def _fire_macro(self, macro: Macro, hwnd: int):
        if self._action_queue:
            return
        self.log_event.emit("macro", f"[{macro.name}] disparando {len(macro.actions)} ação(ões)")
        self._loop_macro = macro
        self._loop_hwnd  = hwnd
        self._action_queue = [(act, hwnd) for act in macro.actions]
        self._exec_next_action()

    def _exec_next_action(self):
        if not self._action_queue:
            if self._loop_macro:
                self._loop_macro._was_active = False
            self._loop_macro = None
            self._loop_hwnd  = 0
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
        import pocketbase_client as _pb
        client = _pb.get_shared()
        if client is None:
            self.log_event.emit("error", "dynamic_input: PocketBase não configurado")
            self._action_timer.start(0)
            return
        collection = act.params.get("collection", "")
        filter_expr = act.params.get("filter", "")
        sort_expr   = act.params.get("sort", "")
        column      = act.params.get("column", "")
        idx         = int(act.params.get("index", 0))
        try:
            records = client.fetch_records(collection, filter_expr=filter_expr, sort=sort_expr)
            if not records:
                self.log_event.emit("error", f"dynamic_input: nenhum registro em '{collection}'")
                self._action_timer.start(0)
                return
            value = str(records[min(idx, len(records) - 1)].get(column, ""))
            self.log_event.emit("macro", f"  dynamic_input → {column}={value[:40]}")
            params: dict = {"text": value}
            if hwnd:
                params["hwnd"] = hwnd
            self.command_requested.emit("type_text", params)
        except Exception as exc:
            self.log_event.emit("error", f"dynamic_input: {exc}")
        self._action_timer.start(0)

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
        self.command_requested.emit("list_windows", {"_silent": True})

    def stop(self):
        self._poll_timer.stop()
        self._process_poll_timer.stop()
        self._action_timer.stop()
        self._waiting = False
        self._waiting_image = False
        self._action_queue.clear()
        self._loop_macro = None
        self._loop_hwnd  = 0
        for p in self._profiles:
            for macro in p.macros:
                macro._trigger_frame_count = 0
                macro._confirm_armed = False
                for it in macro.image_triggers:
                    it._found = False
                    it._confidence = 0.0
        self.btn_poll.setChecked(False)
        self.btn_poll.setText("Start Polling")

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
        self._sel_macro   = -1
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
        self._sel_macro   = -1
        self._macro_editor.setEnabled(False)
        p = self._cur_profile()
        if p is None:
            self._grp_prof.setEnabled(False)
            self.macro_list.clear()
            return
        self._grp_prof.setEnabled(True)
        for w in (self.inp_prof_name, self.inp_prof_pattern,
                  self.inp_prof_path, self.chk_prof_enabled):
            w.blockSignals(True)
        self.inp_prof_name.setText(p.name)
        self.inp_prof_pattern.setText(p.title_pattern)
        self.inp_prof_path.setText(p.exe_path)
        self.chk_prof_enabled.setChecked(p.enabled)
        for w in (self.inp_prof_name, self.inp_prof_pattern,
                  self.inp_prof_path, self.chk_prof_enabled):
            w.blockSignals(False)
        self._update_profile_status_label()
        self._refresh_macro_list()

    def _refresh_profile_list(self):
        cur = self._sel_profile
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        for p in self._profiles:
            proc = self._process_status.get(p.exe_path) if p.exe_path else None
            exe_badge = (" [▶]" if proc and proc.get("running") else
                         " [✗]" if proc else "")
            no_target = not p.title_pattern.strip()
            matched   = p._matched_hwnd != 0
            if no_target:
                suffix = ""
                color = QColor("#aaa") if p.enabled else QColor("#666")
            elif matched:
                suffix = f"  hwnd={p._matched_hwnd}"
                color = QColor("#4ec94e") if p.enabled else QColor("#666")
            else:
                suffix = "  ✗ janela"
                color = QColor("#e06060") if p.enabled else QColor("#666")
            if p.exe_path and proc is not None:
                color = (QColor("#4ec94e") if proc.get("running") else QColor("#e06060")) if p.enabled else QColor("#666")
            item = QListWidgetItem(p.name + exe_badge + suffix)
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

        if p.exe_path:
            proc = self._process_status.get(p.exe_path)
            if proc is None:
                exe_txt, exe_style = "exe: aguardando…", "color:#888;"
            elif proc.get("running"):
                wins = proc.get("windows", [])
                states = []
                for w in wins:
                    if w.get("minimized"):
                        states.append("minimizado")
                    elif w.get("maximized"):
                        states.append("maximizado")
                    else:
                        states.append("normal")
                exe_txt = f"exe: rodando ({', '.join(states)})" if states else "exe: rodando"
                exe_style = "color:#4ec94e;"
            else:
                exe_txt, exe_style = "exe: fechado", "color:#e06060;"
            self.lbl_prof_exe_status.setText(exe_txt)
            self.lbl_prof_exe_status.setStyleSheet(exe_style + " font-size:11px;")
        else:
            self.lbl_prof_exe_status.setText("—")
            self.lbl_prof_exe_status.setStyleSheet("color:#888; font-size:11px;")

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

    def _update_win_info(self, p: WindowProfile):
        f = self._win_info_fields

        def _clear(status: str, style: str):
            f["status"].setText(status)
            f["status"].setStyleSheet(f"font-size:10px; {style}")
            for k in ("focused", "title", "hwnd", "pid", "pos", "size"):
                f[k].setText("—")
                f[k].setStyleSheet("font-size:10px;")

        # tenta via exe_path primeiro, depois via hwnd matchado
        win = None
        if p.exe_path:
            proc = self._process_status.get(p.exe_path)
            if proc and proc.get("running"):
                wins = proc.get("windows", [])
                if wins:
                    win = next((w for w in wins if w.get("focused")), wins[0])

        if win is None and p._matched_hwnd:
            rw = next((w for w in self._remote_windows if w.get("hwnd") == p._matched_hwnd), None)
            if rw:
                rect = rw.get("rect", {})
                win = {
                    "hwnd": rw["hwnd"], "title": rw.get("title", ""),
                    "x": rect.get("x"), "y": rect.get("y"),
                    "width": rect.get("w"), "height": rect.get("h"),
                }

        if win is None:
            if p.exe_path:
                proc = self._process_status.get(p.exe_path)
                _clear("Aguardando…" if proc is None else "Não encontrada",
                       "color:#888;" if proc is None else "color:#e06060;")
            elif not p.title_pattern.strip():
                _clear("Global", "color:#888;")
            else:
                _clear("Não encontrada", "color:#e06060;")
            return

        s_txt, s_col = (
            ("Minimizada", "#f0c040") if win.get("minimized") else
            ("Maximizada", "#4ec94e") if win.get("maximized") else
            ("Aberta",     "#4ec94e")
        )
        f["status"].setText(s_txt)
        f["status"].setStyleSheet(f"font-size:10px; color:{s_col}; font-weight:bold;")

        focused = win.get("focused")
        f["focused"].setText("Sim" if focused else "Não")
        f["focused"].setStyleSheet("font-size:10px; color:#4ec94e;" if focused else "font-size:10px; color:#888;")
        f["title"].setText(win.get("title") or "—")
        f["hwnd"].setText(str(win.get("hwnd", "—")))
        f["pid"].setText(str(win.get("pid", "—")) if win.get("pid") else "—")
        x, y   = win.get("x"), win.get("y")
        w_, h_ = win.get("width"), win.get("height")
        f["pos"].setText(f"x={x}  y={y}" if x is not None else "—")
        f["size"].setText(f"{w_} × {h_}" if w_ is not None else "—")

    def _on_prof_name_changed(self, text: str):
        if p := self._cur_profile():
            p.name = text
            self._refresh_profile_list()
            self._schedule_save()

    def _on_prof_pattern_changed(self, text: str):
        if p := self._cur_profile():
            p.title_pattern = text
            p._matched_hwnd = p.match_windows(self._remote_windows)
            self._refresh_profile_list()
            self._update_profile_status_label()
            self._schedule_save()

    def _on_prof_enabled_changed(self, checked: bool):
        if p := self._cur_profile():
            p.enabled = checked
            self._refresh_profile_list()
            self._schedule_save()

    def _on_prof_path_changed(self, text: str):
        if p := self._cur_profile():
            p.exe_path = text
            self._poll_processes()
            self._schedule_save()

    def _browse_profile_exe(self):
        from ui.file_browser import AddPathDialog
        self._browse_dlg = AddPathDialog(self)
        self._browse_dlg.browse_requested.connect(
            lambda path: self.command_requested.emit("list_directory", {"path": path, "_browser": True})
        )
        if self._browse_dlg.exec() == QDialog.Accepted:
            if path := self._browse_dlg.result_path():
                self.inp_prof_path.setText(path)
        self._browse_dlg = None

    # ── Macro management ──────────────────────────────────────────────────────

    def _add_macro(self):
        if p := self._cur_profile():
            macro = Macro(name=f"Macro {len(p.macros) + 1}")
            p.macros.append(macro)
            self._refresh_macro_list()
            self.macro_list.setCurrentRow(len(p.macros) - 1)
            self._schedule_save()

    def _duplicate_macro(self):
        p = self._cur_profile()
        if p is None or self._sel_macro < 0:
            return
        dup = copy.deepcopy(p.macros[self._sel_macro])
        dup.name += " (cópia)"
        p.macros.append(dup)
        self._refresh_macro_list()
        self.macro_list.setCurrentRow(len(p.macros) - 1)
        self._schedule_save()

    def _remove_macro(self):
        p = self._cur_profile()
        if p is None or self._sel_macro < 0:
            return
        del p.macros[self._sel_macro]
        old, self._sel_macro = self._sel_macro, -1
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
        r = self._sel_macro
        if p is None or r < 0 or r >= len(p.macros) - 1:
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
        self._reload_triggers()
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

    def _on_name_changed(self, text: str):
        if macro := self._cur_macro():
            macro.name = text
            if item := self.macro_list.item(self._sel_macro):
                item.setText(text)
            self._schedule_save()

    def _on_enabled_changed(self, checked: bool):
        if macro := self._cur_macro():
            macro.enabled = checked
            if item := self.macro_list.item(self._sel_macro):
                item.setForeground(QColor("#4ec94e") if checked else QColor("#888"))
            self._schedule_save()

    # ── Triggers ──────────────────────────────────────────────────────────────

    def _reload_triggers(self):
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
        if (macro := self._cur_macro()) is None:
            return
        dlg = AddTriggerDialog(self)
        if dlg.exec() == QDialog.Accepted:
            macro.triggers.append(dlg.result())
            self._reload_triggers()
            self._schedule_save()

    def _add_image_trigger(self):
        if (macro := self._cur_macro()) is None:
            return
        px = pick_region_from_window(self)
        if px is None:
            return
        dlg = ImageTriggerDialog(px, self)
        if dlg.exec() == QDialog.Accepted:
            macro.image_triggers.append(dlg.result())
            self._reload_triggers()
            self._schedule_save()

    def _add_window_trigger(self):
        if (macro := self._cur_macro()) is None:
            return
        dlg = AddWindowTriggerDialog(self)
        if dlg.exec() == QDialog.Accepted:
            macro.window_triggers.append(dlg.result())
            self._reload_triggers()
            self._schedule_save()

    def _edit_trigger(self, _item=None):
        macro = self._cur_macro()
        if macro is None:
            return
        item = self.trig_list.currentItem()
        if item is None:
            return
        ttype, idx = item.data(Qt.UserRole)
        if ttype == "pixel":
            dlg = AddTriggerDialog(self, existing=macro.triggers[idx])
            if dlg.exec() == QDialog.Accepted:
                macro.triggers[idx] = dlg.result()
        elif ttype == "image":
            dlg = ImageTriggerDialog(None, self, existing=macro.image_triggers[idx])
            if dlg.exec() == QDialog.Accepted:
                macro.image_triggers[idx] = dlg.result()
        elif ttype == "window":
            dlg = AddWindowTriggerDialog(self, existing=macro.window_triggers[idx])
            if dlg.exec() == QDialog.Accepted:
                macro.window_triggers[idx] = dlg.result()
        self._reload_triggers()
        self._schedule_save()

    def _remove_trigger(self):
        macro = self._cur_macro()
        if macro is None:
            return
        item = self.trig_list.currentItem()
        if item is None:
            return
        ttype, idx = item.data(Qt.UserRole)
        if ttype == "pixel":
            del macro.triggers[idx]
        elif ttype == "image":
            del macro.image_triggers[idx]
        elif ttype == "window":
            del macro.window_triggers[idx]
        self._reload_triggers()
        self._schedule_save()

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
                    ok = t.matches(r, g, b)
                    item.setText(f"[PIXEL] {t.label()}  {'✓' if ok else '✗'} #{r:02X}{g:02X}{b:02X}")
                    item.setForeground(QColor("#4ec94e") if ok else QColor("#e06060"))
            elif ttype == "image" and idx < len(macro.image_triggers):
                it = macro.image_triggers[idx]
                pct = int(it._confidence * 100)
                item.setText(f"[IMAGE] {'✓' if it._found else '✗'} {it.label()}  [{pct}%]")
                item.setForeground(QColor("#4ec94e") if it._found else QColor("#e06060"))
            elif ttype == "window" and idx < len(macro.window_triggers):
                wt = macro.window_triggers[idx]
                state = self._window_states.get(hwnd)
                ok = wt.check(hwnd, state)
                actual = self._window_trigger_actual(wt, hwnd, state)
                item.setText(f"[JANELA] {'✓' if ok else '✗'} {wt.label()}  (atual: {actual})")
                item.setForeground(QColor("#4ec94e") if ok else QColor("#e06060"))

    @staticmethod
    def _window_trigger_actual(wt: WindowTriggerCondition, hwnd: int,
                                state: dict | None) -> str:
        if wt.condition in ("found", "not_found"):
            return "encontrada" if hwnd != 0 else "não encontrada"
        if state is None:
            return "?"
        if wt.condition == "minimized":
            return "sim" if state.get("minimized") else "não"
        if wt.condition == "maximized":
            return "sim" if state.get("maximized") else "não"
        if wt.condition == "normal":
            return "sim" if not state.get("minimized") and not state.get("maximized") else "não"
        from ui.macro.models import _WIN_FIELD_MAP
        key = _WIN_FIELD_MAP.get(wt.condition, "")
        return str(state.get(key, "?")) if key else "?"

    # ── Actions ───────────────────────────────────────────────────────────────

    def _reload_actions(self):
        self.action_list.clear()
        if macro := self._cur_macro():
            for act in macro.actions:
                self.action_list.addItem(act.label())

    def _saved_windows(self) -> list[dict]:
        return [{"path": p.exe_path, "alias": p.name}
                for p in self._profiles if p.exe_path]

    def _add_action(self):
        if (macro := self._cur_macro()) is None:
            return
        dlg = AddActionDialog(self, saved_windows=self._saved_windows())
        if dlg.exec() == QDialog.Accepted:
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
        dlg = AddActionDialog(self, existing=macro.actions[row],
                              saved_windows=self._saved_windows())
        if dlg.exec() == QDialog.Accepted:
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

    # ── Persistence ───────────────────────────────────────────────────────────

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

    def dump_state(self) -> dict:
        return {
            "polling_active": self.btn_poll.isChecked(),
            "profiles": [
                {
                    "name":          p.name,
                    "title_pattern": p.title_pattern,
                    "exe_path":      p.exe_path,
                    "enabled":       p.enabled,
                    "macros":        [macro_to_dict(m) for m in p.macros],
                }
                for p in self._profiles
            ],
        }

    def load_state(self, data: dict) -> None:
        self._profiles.clear()
        for pd in data.get("profiles", []):
            self._profiles.append(WindowProfile(
                name=pd.get("name", "Janela"),
                title_pattern=pd.get("title_pattern", ""),
                exe_path=pd.get("exe_path", ""),
                enabled=pd.get("enabled", True),
                macros=[macro_from_dict(m) for m in pd.get("macros", [])],
            ))

        # migração: formato antigo sem profiles
        if not self._profiles and data.get("items"):
            global_p = WindowProfile(name="Global", title_pattern="")
            for item in data["items"]:
                global_p.macros.append(macro_from_dict(item))
            self._profiles.append(global_p)
            self.log_event.emit("info", "Macros migrados para perfil 'Global'")

        self._poll_timer.setInterval(100)
        self._sel_profile = -1
        self._sel_macro   = -1
        self._refresh_profile_list()
        self.macro_list.clear()
        self._macro_editor.setEnabled(False)
        self._grp_prof.setEnabled(False)

        if data.get("polling_active", False):
            self.btn_poll.setChecked(True)
            self._toggle_poll(True)
