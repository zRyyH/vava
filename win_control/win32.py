"""Win32 API bindings via ctypes for window management, pixel reading, and screenshots."""
import ctypes
import ctypes.wintypes as w

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

# --- Constants ---
SW_HIDE = 0
SW_NORMAL = 1
SW_MINIMIZE = 6
SW_MAXIMIZE = 3
SW_RESTORE = 9
SW_SHOW = 5

SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_SHOWWINDOW = 0x0040

GWL_STYLE = -16
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_POPUP = 0x80000000

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0

SM_CXSCREEN = 0
SM_CYSCREEN = 1


# --- Structures ---
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", w.DWORD), ("biWidth", w.LONG), ("biHeight", w.LONG),
        ("biPlanes", w.WORD), ("biBitCount", w.WORD), ("biCompression", w.DWORD),
        ("biSizeImage", w.DWORD), ("biXPelsPerMeter", w.LONG),
        ("biYPelsPerMeter", w.LONG), ("biClrUsed", w.DWORD), ("biClrImportant", w.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", w.DWORD * 3)]


# --- Window Functions ---

def list_windows():
    """Return list of {hwnd, title, rect} for all visible windows with titles."""
    results = []
    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                rect = w.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                results.append({
                    "hwnd": hwnd,
                    "title": buf.value,
                    "rect": {"x": rect.left, "y": rect.top, "w": rect.right - rect.left, "h": rect.bottom - rect.top},
                })
        return True
    WNDENUMPROC = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return results


def get_window_info(hwnd):
    """Get info for a single window."""
    rect = w.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    return {
        "hwnd": hwnd,
        "title": buf.value,
        "rect": {"x": rect.left, "y": rect.top, "w": rect.right - rect.left, "h": rect.bottom - rect.top},
        "visible": bool(user32.IsWindowVisible(hwnd)),
        "minimized": bool(user32.IsIconic(hwnd)),
        "maximized": bool(user32.IsZoomed(hwnd)),
        "style": style,
    }


def focus_window(hwnd):
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)


def close_window(hwnd):
    WM_CLOSE = 0x0010
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def minimize_window(hwnd):
    user32.ShowWindow(hwnd, SW_MINIMIZE)


def maximize_window(hwnd):
    user32.ShowWindow(hwnd, SW_MAXIMIZE)


def restore_window(hwnd):
    user32.ShowWindow(hwnd, SW_RESTORE)


def move_resize_window(hwnd, x, y, width, height):
    user32.MoveWindow(hwnd, x, y, width, height, True)


def set_windowed(hwnd):
    """Remove fullscreen, restore windowed mode with standard frame."""
    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    user32.SetWindowLongW(hwnd, GWL_STYLE, style | WS_OVERLAPPEDWINDOW)
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetWindowPos(hwnd, 0, 100, 100, 800, 600, SWP_NOZORDER | SWP_SHOWWINDOW)


def set_fullscreen(hwnd):
    """Make window borderless fullscreen."""
    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    user32.SetWindowLongW(hwnd, GWL_STYLE, style & ~WS_OVERLAPPEDWINDOW | WS_POPUP)
    cx = user32.GetSystemMetrics(SM_CXSCREEN)
    cy = user32.GetSystemMetrics(SM_CYSCREEN)
    user32.SetWindowPos(hwnd, 0, 0, 0, cx, cy, SWP_SHOWWINDOW)


# --- Pixel Reading ---

class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _client_offset(hwnd: int) -> tuple[int, int]:
    """Converte (0,0) da área-cliente do hwnd para coordenadas de tela."""
    pt = _POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


def get_pixels(positions):
    """Get RGB of multiple positions. Each position may have optional 'hwnd' for window-relative coords."""
    dc = user32.GetDC(0)
    _cache: dict[int, tuple[int, int]] = {}
    results = []
    for pos in positions:
        x, y = pos["x"], pos["y"]
        hwnd = pos.get("hwnd", 0)
        if hwnd:
            if hwnd not in _cache:
                _cache[hwnd] = _client_offset(hwnd)
            ox, oy = _cache[hwnd]
            x, y = x + ox, y + oy
        color = gdi32.GetPixel(dc, x, y)
        if color == 0xFFFFFFFF:  # CLR_INVALID
            results.append({"x": pos["x"], "y": pos["y"], "r": 0, "g": 0, "b": 0})
        else:
            results.append({
                "x": pos["x"], "y": pos["y"],
                "r": color & 0xFF,
                "g": (color >> 8) & 0xFF,
                "b": (color >> 16) & 0xFF,
            })
    user32.ReleaseDC(0, dc)
    return results


# --- Screenshot ---

def screenshot_window(hwnd):
    """Capture client area only. Returns (width, height, bmp_data_bytes, client_screen_rect) or None."""
    # Tamanho da janela completa (para PrintWindow)
    win_rect = w.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(win_rect))
    ww = win_rect.right  - win_rect.left
    wh = win_rect.bottom - win_rect.top
    if ww <= 0 or wh <= 0:
        return None

    # Área cliente
    cli_rect = w.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(cli_rect))
    cw = cli_rect.right
    ch = cli_rect.bottom
    if cw <= 0 or ch <= 0:
        return None

    pt = _POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    dx = pt.x - win_rect.left
    dy = pt.y - win_rect.top

    hwnd_dc  = user32.GetDC(hwnd)
    # 1. Renderiza janela completa
    full_dc  = gdi32.CreateCompatibleDC(hwnd_dc)
    full_bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, ww, wh)
    gdi32.SelectObject(full_dc, full_bmp)
    user32.PrintWindow(hwnd, full_dc, 2)  # PW_RENDERFULLCONTENT

    # 2. Extrai apenas a área cliente
    cli_dc  = gdi32.CreateCompatibleDC(hwnd_dc)
    cli_bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, cw, ch)
    gdi32.SelectObject(cli_dc, cli_bmp)
    gdi32.BitBlt(cli_dc, 0, 0, cw, ch, full_dc, dx, dy, SRCCOPY)

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize        = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth       = cw
    bmi.bmiHeader.biHeight      = -ch  # top-down
    bmi.bmiHeader.biPlanes      = 1
    bmi.bmiHeader.biBitCount    = 24
    bmi.bmiHeader.biCompression = 0

    stride = (cw * 3 + 3) & ~3
    buf = ctypes.create_string_buffer(stride * ch)
    gdi32.GetDIBits(cli_dc, cli_bmp, 0, ch, buf, ctypes.byref(bmi), DIB_RGB_COLORS)

    gdi32.DeleteObject(cli_bmp)
    gdi32.DeleteDC(cli_dc)
    gdi32.DeleteObject(full_bmp)
    gdi32.DeleteDC(full_dc)
    user32.ReleaseDC(hwnd, hwnd_dc)

    client_screen_rect = {"x": pt.x, "y": pt.y, "w": cw, "h": ch}
    return cw, ch, bytes(buf), client_screen_rect


def screenshot_screen():
    """Capture entire screen. Returns (width, height, bmp_data_bytes)."""
    cx = user32.GetSystemMetrics(SM_CXSCREEN)
    cy = user32.GetSystemMetrics(SM_CYSCREEN)
    hwnd_dc = user32.GetDC(0)
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, cx, cy)
    gdi32.SelectObject(mem_dc, bitmap)
    gdi32.BitBlt(mem_dc, 0, 0, cx, cy, hwnd_dc, 0, 0, SRCCOPY)

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = cx
    bmi.bmiHeader.biHeight = -cy
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 24
    bmi.bmiHeader.biCompression = 0

    buf_size = ((cx * 3 + 3) & ~3) * cy
    buf = ctypes.create_string_buffer(buf_size)
    gdi32.GetDIBits(mem_dc, bitmap, 0, cy, buf, ctypes.byref(bmi), DIB_RGB_COLORS)

    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(0, hwnd_dc)

    return cx, cy, bytes(buf)
