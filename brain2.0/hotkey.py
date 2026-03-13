"""Global hotkey listener usando Win32 RegisterHotKey."""
import ctypes
import ctypes.wintypes
import threading

from PySide6.QtCore import QObject, Signal

MOD_SHIFT = 0x0004
VK_BACK   = 0x08
WM_HOTKEY = 0x0312
WM_QUIT   = 0x0012

_user32 = ctypes.windll.user32


class GlobalHotkey(QObject):
    """Registra Shift+Backspace globalmente e emite `triggered` ao pressionar."""

    triggered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread_id: int = 0

    def start(self):
        self._thread.start()

    def stop(self):
        if self._thread_id:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def _run(self):
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        if not _user32.RegisterHotKey(None, 1, MOD_SHIFT, VK_BACK):
            return
        msg = ctypes.wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY:
                self.triggered.emit()
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))
        _user32.UnregisterHotKey(None, 1)
