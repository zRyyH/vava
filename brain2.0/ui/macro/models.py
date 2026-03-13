"""
Modelos de dados para macros e perfis de janela.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── VK helpers ────────────────────────────────────────────────────────────────

_VK_NAMES: dict[int, str] = {
    0x08: "Backspace", 0x09: "Tab",      0x0D: "Enter",     0x10: "Shift",
    0x11: "Ctrl",      0x12: "Alt",      0x13: "Pause",     0x14: "CapsLock",
    0x1B: "Esc",       0x20: "Space",    0x21: "PageUp",    0x22: "PageDown",
    0x23: "End",       0x24: "Home",     0x25: "Left",      0x26: "Up",
    0x27: "Right",     0x28: "Down",     0x2C: "PrintScr",  0x2D: "Insert",
    0x2E: "Delete",    0x5B: "Win",      0x5C: "RWin",
    0x70: "F1",  0x71: "F2",  0x72: "F3",  0x73: "F4",  0x74: "F5",
    0x75: "F6",  0x76: "F7",  0x77: "F8",  0x78: "F9",  0x79: "F10",
    0x7A: "F11", 0x7B: "F12",
    0x90: "NumLock",   0x91: "ScrollLock",
    0xA0: "LShift",    0xA1: "RShift",   0xA2: "LCtrl",     0xA3: "RCtrl",
    0xA4: "LAlt",      0xA5: "RAlt",
    0xBB: "=+", 0xBC: ",<", 0xBD: "-_", 0xBE: ".>", 0xBF: "/?",
    0xC0: "`~", 0xDB: "[{", 0xDC: "\\|", 0xDD: "]}", 0xDE: "'\"",
}

MODIFIER_VKS: frozenset[int] = frozenset({
    0x10, 0x11, 0x12, 0x5B, 0x5C,
    0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5,
})


def vk_name(vk: int) -> str:
    if vk in _VK_NAMES:
        return _VK_NAMES[vk]
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    return f"VK{vk:#04x}"


def format_combo(vk: int, modifiers: list[int]) -> str:
    parts = []
    if any(m in (0x11, 0xA2, 0xA3) for m in modifiers):
        parts.append("Ctrl")
    if any(m in (0x10, 0xA0, 0xA1) for m in modifiers):
        parts.append("Shift")
    if any(m in (0x12, 0xA4, 0xA5) for m in modifiers):
        parts.append("Alt")
    if any(m in (0x5B, 0x5C) for m in modifiers):
        parts.append("Win")
    parts.append(vk_name(vk))
    return "+".join(parts)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class MacroSafetyConfig:
    """Travas de segurança para execução de macros."""
    min_trigger_frames: int = 1
    require_window_in_list: bool = True


@dataclass
class TriggerCondition:
    """Trigger por cor de pixel em uma coordenada."""
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
class ImageTriggerCondition:
    """Trigger por correspondência de imagem (template matching)."""
    template_b64: str
    threshold: float = 0.80

    # estado de runtime — não serializado
    _found:      bool  = field(default=False, init=False, repr=False, compare=False)
    _confidence: float = field(default=0.0,   init=False, repr=False, compare=False)
    _match_x:    int   = field(default=0,     init=False, repr=False, compare=False)
    _match_y:    int   = field(default=0,     init=False, repr=False, compare=False)

    def label(self) -> str:
        return f"Image {self._template_size()} ≥{int(self.threshold * 100)}%"

    def thumbnail(self, max_h: int = 32) -> "QPixmap":
        from PySide6.QtGui import QPixmap
        import base64
        try:
            px = QPixmap()
            px.loadFromData(base64.b64decode(self.template_b64))
            return px.scaledToHeight(max_h) if px.height() > max_h else px
        except Exception:
            return QPixmap()

    def _template_size(self) -> str:
        import base64
        from PySide6.QtGui import QImage
        try:
            img = QImage.fromData(base64.b64decode(self.template_b64))
            return f"{img.width()}×{img.height()}"
        except Exception:
            return "?"


_WIN_TRIG_LABELS: dict[str, str] = {
    "found":     "Janela encontrada",
    "not_found": "Janela não encontrada",
    "minimized": "Minimizada",
    "maximized": "Maximizada",
    "normal":    "Normal (restaurada)",
    "width":     "Largura",
    "height":    "Altura",
    "pos_x":     "Posição X",
    "pos_y":     "Posição Y",
}
_WIN_TRIG_NEEDS_VALUE: frozenset[str] = frozenset({"width", "height", "pos_x", "pos_y"})
_WIN_FIELD_MAP: dict[str, str] = {"width": "width", "height": "height", "pos_x": "x", "pos_y": "y"}


@dataclass
class WindowTriggerCondition:
    """Trigger baseado no estado da janela."""
    condition: str          # found | not_found | minimized | maximized | normal | width | height | pos_x | pos_y
    operator:  str = "=="   # == != > < >= <=
    value:     int = 0

    def check(self, hwnd: int, window_state: dict | None) -> bool:
        if self.condition == "found":
            return hwnd != 0
        if self.condition == "not_found":
            return hwnd == 0
        if window_state is None:
            return False
        if self.condition == "minimized":
            return bool(window_state.get("minimized"))
        if self.condition == "maximized":
            return bool(window_state.get("maximized"))
        if self.condition == "normal":
            return not window_state.get("minimized") and not window_state.get("maximized")
        key = _WIN_FIELD_MAP.get(self.condition)
        if key is None:
            return False
        actual = int(window_state.get(key, 0))
        ops = {"==": actual == self.value, "!=": actual != self.value,
               ">":  actual >  self.value, "<":  actual <  self.value,
               ">=": actual >= self.value, "<=": actual <= self.value}
        return ops.get(self.operator, False)

    def label(self) -> str:
        lbl = _WIN_TRIG_LABELS.get(self.condition, self.condition)
        return f"{lbl} {self.operator} {self.value}" if self.condition in _WIN_TRIG_NEEDS_VALUE else lbl


@dataclass
class MacroAction:
    type:   str
    params: dict[str, Any]

    def label(self) -> str:
        p = self.params
        if self.type == "click":
            return f"Click ({p['x']},{p['y']}) {p.get('button','left')}"
        if self.type == "key_press":
            vk = p.get("vk", 0)
            return f"Key {format_combo(vk, p.get('modifiers', []))}" if vk else "Key (vazio)"
        if self.type == "move_mouse":
            return f"Move ({p['x']},{p['y']})"
        if self.type == "wait":
            return f"Wait {p['ms']} ms"
        if self.type == "dynamic_input":
            lbl = f"DynamicInput [{p.get('collection','?')}] col={p.get('column','?')}"
            if p.get("filter"):
                lbl += f" | filter: {p['filter']}"
            if p.get("sort"):
                lbl += f" | sort: {p['sort']}"
            return lbl
        if self.type == "window_action":
            act = p.get("action", "?")
            if act in ("resize", "set_size"):
                return f"Window: resize {p.get('width','?')}×{p.get('height','?')}"
            if act == "move":
                return f"Window: move ({p.get('x','?')},{p.get('y','?')})"
            if act == "open_window":
                return f"Window: open {p.get('path','?').split(chr(92))[-1]}"
            return f"Window: {act}"
        return self.type


@dataclass
class Macro:
    name:    str
    enabled: bool = True
    triggers:        list[TriggerCondition]      = field(default_factory=list)
    image_triggers:  list[ImageTriggerCondition] = field(default_factory=list)
    window_triggers: list[WindowTriggerCondition] = field(default_factory=list)
    actions: list[MacroAction]   = field(default_factory=list)
    safety:  MacroSafetyConfig   = field(default_factory=MacroSafetyConfig)

    # estado de runtime — não serializado
    _was_active:          bool = field(default=False, init=False, repr=False, compare=False)
    _trigger_frame_count: int  = field(default=0,     init=False, repr=False, compare=False)
    _confirm_armed:       bool = field(default=False, init=False, repr=False, compare=False)

    def has_any_trigger(self) -> bool:
        return bool(self.triggers or self.image_triggers or self.window_triggers)

    def check_triggers(
        self,
        pixel_map: dict[tuple, tuple],
        hwnd: int = 0,
        window_state: dict | None = None,
    ) -> bool:
        if not self.has_any_trigger():
            return False
        if self.triggers and not all(
            t.matches(*pixel_map.get((t.x, t.y), (0, 0, 0))) for t in self.triggers
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
    """Agrupa macros para uma janela específica."""
    name:          str
    title_pattern: str = ""
    exe_path:      str = ""
    macros:        list[Macro] = field(default_factory=list)
    enabled:       bool = True

    # estado de runtime — não serializado
    _matched_hwnd: int = field(default=0, init=False, repr=False, compare=False)

    def match_windows(self, windows: list[dict]) -> int:
        """Retorna hwnd da primeira janela cujo título contenha title_pattern, ou 0."""
        pat = self.title_pattern.strip().lower()
        if not pat:
            return 0
        for w in windows:
            if pat in w.get("title", "").lower():
                return w["hwnd"]
        return 0


# ── Serialização ──────────────────────────────────────────────────────────────

def macro_to_dict(m: Macro) -> dict:
    return {
        "name":    m.name,
        "enabled": m.enabled,
        "safety": {
            "min_trigger_frames":     m.safety.min_trigger_frames,
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
        "actions": [{"type": a.type, "params": a.params} for a in m.actions],
    }


def macro_from_dict(item: dict) -> Macro:
    s = item.get("safety", {})
    return Macro(
        name=item.get("name", "Macro"),
        enabled=item.get("enabled", True),
        safety=MacroSafetyConfig(
            min_trigger_frames=s.get("min_trigger_frames", 1),
            require_window_in_list=s.get("require_window_in_list", True),
        ),
        triggers=[
            TriggerCondition(x=t["x"], y=t["y"],
                             exp_r=t["r"], exp_g=t["g"], exp_b=t["b"],
                             tolerance=t.get("tolerance", 10))
            for t in item.get("triggers", [])
        ],
        image_triggers=[
            ImageTriggerCondition(
                template_b64=it["template_b64"],
                threshold=float(it.get("threshold", 0.8)),
            )
            for it in item.get("image_triggers", [])
        ],
        window_triggers=[
            WindowTriggerCondition(
                condition=wt["condition"],
                operator=wt.get("operator", "=="),
                value=int(wt.get("value", 0)),
            )
            for wt in item.get("window_triggers", [])
        ],
        actions=[
            MacroAction(type=a["type"], params=a["params"])
            for a in item.get("actions", [])
        ],
    )
