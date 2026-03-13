"""
Utilitários para selecionar coordenada X/Y e cor RGB a partir de uma janela.

Fluxo público:
  pick_from_window()      → dict {x, y, r, g, b} ou None
  pick_region_from_window() → QPixmap recortada ou None
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as _w

from PySide6.QtCore import Qt, QPoint, QRect, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

# ── Win32 structs ─────────────────────────────────────────────────────────────

_user32 = ctypes.windll.user32
_gdi32  = ctypes.windll.gdi32

_DIB_RGB_COLORS = 0
_SRCCOPY        = 0x00CC0020


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize",          _w.DWORD), ("biWidth",         _w.LONG),
        ("biHeight",        _w.LONG),  ("biPlanes",        _w.WORD),
        ("biBitCount",      _w.WORD),  ("biCompression",   _w.DWORD),
        ("biSizeImage",     _w.DWORD), ("biXPelsPerMeter", _w.LONG),
        ("biYPelsPerMeter", _w.LONG),  ("biClrUsed",       _w.DWORD),
        ("biClrImportant",  _w.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", _w.DWORD * 3)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


# ── Win32 helpers ─────────────────────────────────────────────────────────────

def _enum_visible_windows() -> list[tuple[int, str]]:
    results: list[tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, _w.HWND, _w.LPARAM)
    def _cb(hwnd, _lParam):
        if _user32.IsWindowVisible(hwnd):
            length = _user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                _user32.GetWindowTextW(hwnd, buf, length + 1)
                if title := buf.value.strip():
                    results.append((hwnd, title))
        return True

    _user32.EnumWindows(_cb, 0)
    return results


def _capture_window(hwnd: int) -> QPixmap | None:
    """Captura a área cliente da janela (sem título/bordas)."""
    win_rect = _w.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(win_rect))
    ww = win_rect.right - win_rect.left
    wh = win_rect.bottom - win_rect.top
    if ww <= 0 or wh <= 0:
        return None

    cli_rect = _w.RECT()
    _user32.GetClientRect(hwnd, ctypes.byref(cli_rect))
    cw, ch = cli_rect.right, cli_rect.bottom
    if cw <= 0 or ch <= 0:
        return None

    pt = _POINT(0, 0)
    _user32.ClientToScreen(hwnd, ctypes.byref(pt))
    dx = pt.x - win_rect.left
    dy = pt.y - win_rect.top

    hwnd_dc  = _user32.GetDC(hwnd)
    full_dc  = _gdi32.CreateCompatibleDC(hwnd_dc)
    full_bmp = _gdi32.CreateCompatibleBitmap(hwnd_dc, ww, wh)
    _gdi32.SelectObject(full_dc, full_bmp)
    _user32.PrintWindow(hwnd, full_dc, 2)

    cli_dc  = _gdi32.CreateCompatibleDC(hwnd_dc)
    cli_bmp = _gdi32.CreateCompatibleBitmap(hwnd_dc, cw, ch)
    _gdi32.SelectObject(cli_dc, cli_bmp)
    _gdi32.BitBlt(cli_dc, 0, 0, cw, ch, full_dc, dx, dy, _SRCCOPY)

    bmi = _BITMAPINFO()
    bmi.bmiHeader.biSize     = ctypes.sizeof(_BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth    = cw
    bmi.bmiHeader.biHeight   = -ch
    bmi.bmiHeader.biPlanes   = 1
    bmi.bmiHeader.biBitCount = 24

    stride = (cw * 3 + 3) & ~3
    buf = ctypes.create_string_buffer(stride * ch)
    _gdi32.GetDIBits(cli_dc, cli_bmp, 0, ch, buf, ctypes.byref(bmi), _DIB_RGB_COLORS)

    _gdi32.DeleteObject(cli_bmp); _gdi32.DeleteDC(cli_dc)
    _gdi32.DeleteObject(full_bmp); _gdi32.DeleteDC(full_dc)
    _user32.ReleaseDC(hwnd, hwnd_dc)

    img = QImage(bytes(buf), cw, ch, stride, QImage.Format.Format_BGR888)
    return QPixmap.fromImage(img)


# ── WindowPickerDialog ────────────────────────────────────────────────────────

class WindowPickerDialog(QDialog):
    """Lista janelas abertas; retorna (hwnd, título) ao confirmar."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Selecionar janela")
        self.resize(420, 360)
        self._hwnd: int = 0
        self._title: str = ""

        layout = QVBoxLayout(self)
        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._accept)
        layout.addWidget(self._list)

        btn_refresh = QPushButton("↺ Atualizar lista")
        btn_refresh.clicked.connect(self._refresh)
        layout.addWidget(btn_refresh)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._refresh()

    def _refresh(self):
        self._list.clear()
        for hwnd, title in sorted(_enum_visible_windows(), key=lambda t: t[1].lower()):
            item = QListWidgetItem(f"{title}  [hwnd={hwnd}]")
            item.setData(Qt.UserRole, (hwnd, title))
            self._list.addItem(item)

    def _accept(self, _item=None):
        item = self._list.currentItem()
        if item is None:
            return
        self._hwnd, self._title = item.data(Qt.UserRole)
        self.accept()

    def selected(self) -> tuple[int, str]:
        return self._hwnd, self._title


# ── _ClickableLabel ───────────────────────────────────────────────────────────

class _ClickableLabel(QLabel):
    mouse_moved   = Signal(QPoint)
    mouse_clicked = Signal(QPoint)

    def mouseMoveEvent(self, event):
        self.mouse_moved.emit(event.position().toPoint())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.mouse_clicked.emit(event.position().toPoint())


# ── WindowMirrorDialog ────────────────────────────────────────────────────────

class WindowMirrorDialog(QDialog):
    """
    Exibe espelho interativo de uma janela.
    Após clique: .picked_x, .picked_y, .picked_r, .picked_g, .picked_b.
    """

    def __init__(self, hwnd: int, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Espelho — {title}")
        self._hwnd = hwnd
        self._pixmap: QPixmap | None = None
        self.picked_x = self.picked_y = 0
        self.picked_r = self.picked_g = self.picked_b = 0

        self._build_ui()
        self._refresh_capture()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_capture)
        self._timer.start(500)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        bar = QHBoxLayout()
        self._lbl_coords = QLabel("X: –  Y: –")
        self._lbl_rgb    = QLabel("RGB: –")
        self._lbl_color  = QLabel("   ")
        self._lbl_color.setAutoFillBackground(True)
        self._lbl_color.setFixedWidth(28)
        bar.addWidget(self._lbl_coords)
        bar.addSpacing(16)
        bar.addWidget(self._lbl_rgb)
        bar.addWidget(self._lbl_color)
        bar.addStretch()
        btn_refresh = QPushButton("↺")
        btn_refresh.setFixedWidth(28)
        btn_refresh.clicked.connect(self._refresh_capture)
        bar.addWidget(btn_refresh)
        layout.addLayout(bar)

        self._img_label = _ClickableLabel()
        self._img_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._img_label.setMouseTracking(True)
        self._img_label.mouse_moved.connect(self._on_hover)
        self._img_label.mouse_clicked.connect(self._on_click)

        scroll = QScrollArea()
        scroll.setWidget(self._img_label)
        scroll.setWidgetResizable(False)
        layout.addWidget(scroll, 1)

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(self.reject)
        layout.addWidget(btn_cancel)

    def _refresh_capture(self):
        px = _capture_window(self._hwnd)
        if px is None:
            return
        first = self._pixmap is None
        self._pixmap = px
        self._img_label.setPixmap(px)
        self._img_label.resize(px.size())
        if first:
            screen = (self.screen()
                      or (self.windowHandle() and self.windowHandle().screen())
                      or QApplication.primaryScreen())
            max_w = max_h = 0
            if screen:
                geom = screen.availableGeometry()
                max_w, max_h = geom.width() - 40, geom.height() - 80
            w = px.width()  if not max_w else min(px.width(), max_w)
            h = px.height() + 80 if not max_h else min(px.height() + 80, max_h)
            self.resize(w, h)

    def _pixel_rgb(self, x: int, y: int) -> tuple[int, int, int] | None:
        if self._pixmap is None:
            return None
        img = self._pixmap.toImage()
        if x < 0 or y < 0 or x >= img.width() or y >= img.height():
            return None
        c = QColor(img.pixel(x, y))
        return c.red(), c.green(), c.blue()

    def _on_hover(self, pos: QPoint):
        rgb = self._pixel_rgb(pos.x(), pos.y())
        if rgb is None:
            return
        r, g, b = rgb
        self._lbl_coords.setText(f"X: {pos.x()}  Y: {pos.y()}")
        self._lbl_rgb.setText(f"RGB: ({r}, {g}, {b})  #{r:02X}{g:02X}{b:02X}")
        pal = self._lbl_color.palette()
        pal.setColor(self._lbl_color.backgroundRole(), QColor(r, g, b))
        self._lbl_color.setPalette(pal)

    def _on_click(self, pos: QPoint):
        rgb = self._pixel_rgb(pos.x(), pos.y())
        if rgb is None:
            return
        self.picked_x = pos.x()
        self.picked_y = pos.y()
        self.picked_r, self.picked_g, self.picked_b = rgb
        self._timer.stop()
        self.accept()

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)


# ── _RegionLabel ──────────────────────────────────────────────────────────────

class _RegionLabel(QLabel):
    region_selected = Signal(QRect)

    def __init__(self, pixmap: QPixmap):
        super().__init__()
        self.setPixmap(pixmap)
        self.resize(pixmap.size())
        self.setMouseTracking(True)
        self._start: QPoint | None = None
        self._current: QPoint | None = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._start = event.position().toPoint()
            self._current = self._start
            self.update()

    def mouseMoveEvent(self, event):
        if self._start is not None:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._start is not None:
            rect = QRect(self._start, event.position().toPoint()).normalized()
            self._start = self._current = None
            self.update()
            if rect.width() > 4 and rect.height() > 4:
                self.region_selected.emit(rect)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._start and self._current:
            painter = QPainter(self)
            painter.setPen(QPen(QColor(255, 80, 80), 2, Qt.DashLine))
            painter.setBrush(QBrush(QColor(255, 80, 80, 40)))
            painter.drawRect(QRect(self._start, self._current).normalized())
            painter.end()


# ── RegionSelectDialog ────────────────────────────────────────────────────────

class RegionSelectDialog(QDialog):
    """Mostra espelho da janela e permite selecionar uma região."""

    def __init__(self, hwnd: int, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Selecionar região — {title}")
        self._hwnd = hwnd
        self.selected_pixmap: QPixmap | None = None
        self._full_pixmap: QPixmap | None = None
        self._sized = False

        lay = QVBoxLayout(self)
        lay.setSpacing(4)

        hint = QLabel("Clique e arraste para selecionar a região do template.")
        hint.setStyleSheet("color:#aaa; font-size:11px;")
        lay.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        self._region_label = _RegionLabel(QPixmap())
        self._region_label.region_selected.connect(self._on_region_selected)
        scroll.setWidget(self._region_label)
        lay.addWidget(scroll, 1)

        bar = QHBoxLayout()
        self._lbl_preview = QLabel("Nenhuma região selecionada.")
        self._lbl_preview.setStyleSheet("color:#aaa;")
        bar.addWidget(self._lbl_preview, 1)
        btn_refresh = QPushButton("↺ Recapturar")
        btn_refresh.clicked.connect(self._refresh)
        bar.addWidget(btn_refresh)
        lay.addLayout(bar)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        self._btn_ok = btns.button(QDialogButtonBox.Ok)
        self._btn_ok.setEnabled(False)
        lay.addWidget(btns)

        self._refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(1000)

    def _refresh(self):
        px = _capture_window(self._hwnd)
        if not px:
            return
        self._full_pixmap = px
        self._region_label.setPixmap(px)
        self._region_label.resize(px.size())
        if not self._sized:
            self._sized = True
            screen = self.screen().availableGeometry()
            w = min(px.width(), screen.width() - 40)
            h = min(px.height() + 120, screen.height() - 40)
            self.resize(w, h)
            self.move(
                screen.x() + (screen.width()  - w) // 2,
                screen.y() + (screen.height() - h) // 2,
            )

    def _on_region_selected(self, rect: QRect):
        if self._full_pixmap is None:
            return
        self.selected_pixmap = self._full_pixmap.copy(rect)
        self._lbl_preview.setText(
            f"Região selecionada: {rect.width()}×{rect.height()} px — confirme com OK."
        )
        self._lbl_preview.setStyleSheet("color:#4ec94e;")
        self._btn_ok.setEnabled(True)

    def _on_accept(self):
        if self.selected_pixmap is not None:
            self._timer.stop()
            self.accept()

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)


# ── Funções públicas ──────────────────────────────────────────────────────────

def pick_from_window(parent: QWidget | None = None) -> dict | None:
    """Picker de janela → espelho interativo. Retorna {x, y, r, g, b} ou None."""
    picker = WindowPickerDialog(parent)
    if picker.exec() != QDialog.Accepted:
        return None
    hwnd, title = picker.selected()
    if not hwnd:
        return None
    mirror = WindowMirrorDialog(hwnd, title, parent)
    if mirror.exec() != QDialog.Accepted:
        return None
    return {
        "x": mirror.picked_x, "y": mirror.picked_y,
        "r": mirror.picked_r, "g": mirror.picked_g, "b": mirror.picked_b,
    }


def pick_region_from_window(parent: QWidget | None = None) -> QPixmap | None:
    """Picker de janela → seleção de região. Retorna QPixmap recortada ou None."""
    picker = WindowPickerDialog(parent)
    if picker.exec() != QDialog.Accepted:
        return None
    hwnd, title = picker.selected()
    if not hwnd:
        return None
    dlg = RegionSelectDialog(hwnd, title, parent)
    if dlg.exec() != QDialog.Accepted:
        return None
    return dlg.selected_pixmap
