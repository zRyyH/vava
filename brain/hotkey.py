"""Global hotkey listener using Win32 RegisterHotKey."""
import ctypes
import ctypes.wintypes
import threading

from PySide6.QtCore import QObject, Signal

MOD_SHIFT = 0x0004
VK_BACK = 0x08
WM_HOTKEY = 0x0312

_user32 = ctypes.windll.user32


class GlobalHotkey(QObject):
    """Registers a global hotkey and emits `triggered` when pressed."""
    triggered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread_id: int = 0

    def start(self):
        self._thread.start()

    def _run(self):
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        ok = _user32.RegisterHotKey(None, 1, MOD_SHIFT, VK_BACK)
        if not ok:
            return
        msg = ctypes.wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY:
                self.triggered.emit()
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))
        _user32.UnregisterHotKey(None, 1)

    def stop(self):
        if self._thread_id:
            # Post WM_QUIT to the listener thread to unblock GetMessageW
            _user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT
