"""Arduino HID Controller — serial communication layer.

Sends binary commands to the Arduino Micro (ATmega32U4) running hid_controller.ino.

Protocol:
    Request:  [0xAA] [CMD] [LEN] [PAYLOAD...] [CHK]
    Response: [0xAA] [TYPE] [DATA] [CHK]
    CHK = XOR of bytes between SOF and CHK (exclusive).
"""

import ctypes
import ctypes.wintypes as wt
import time
import serial
import serial.tools.list_ports

# ── Protocol constants ──────────────────────────────────────────────────────

SOF = 0xAA

CMD_PING         = 0x01
CMD_KEY_PRESS    = 0x10
CMD_KEY_RELEASE  = 0x11
CMD_KEY_REL_ALL  = 0x12
CMD_KEY_WRITE    = 0x13
CMD_MOUSE_MOVE   = 0x20
CMD_MOUSE_CLICK  = 0x21
CMD_MOUSE_PRESS  = 0x22
CMD_MOUSE_RELEASE = 0x23
CMD_MOUSE_SCROLL = 0x24

RSP_ACK  = 0x06
RSP_NACK = 0x15
RSP_PONG = 0x02

# Mouse button bitmask (matches Arduino firmware)
BTN_LEFT   = 0x01
BTN_RIGHT  = 0x02
BTN_MIDDLE = 0x04

# HID modifier keycodes (0xE0-0xE7)
HID_LCTRL  = 0xE0
HID_LSHIFT = 0xE1
HID_LALT   = 0xE2
HID_LMETA  = 0xE3
HID_RCTRL  = 0xE4
HID_RSHIFT = 0xE5
HID_RALT   = 0xE6
HID_RMETA  = 0xE7

# ── VK → HID keycode table (Windows Virtual Keys → USB HID Usage IDs) ──────

_VK_TO_HID = {
    0x08: 0x2A,  # VK_BACK → Backspace
    0x09: 0x2B,  # VK_TAB
    0x0D: 0x28,  # VK_RETURN → Enter
    0x1B: 0x29,  # VK_ESCAPE
    0x20: 0x2C,  # VK_SPACE
    0x21: 0x4B,  # VK_PRIOR → Page Up
    0x22: 0x4E,  # VK_NEXT  → Page Down
    0x23: 0x4D,  # VK_END
    0x24: 0x4A,  # VK_HOME
    0x25: 0x50,  # VK_LEFT
    0x26: 0x52,  # VK_UP
    0x27: 0x4F,  # VK_RIGHT
    0x28: 0x51,  # VK_DOWN
    0x2D: 0x49,  # VK_INSERT
    0x2E: 0x4C,  # VK_DELETE
    # 0-9
    0x30: 0x27,  # '0'
    0x31: 0x1E,  # '1'
    0x32: 0x1F,
    0x33: 0x20,
    0x34: 0x21,
    0x35: 0x22,
    0x36: 0x23,
    0x37: 0x24,
    0x38: 0x25,
    0x39: 0x26,  # '9'
    # A-Z
    **{0x41 + i: 0x04 + i for i in range(26)},
    # F1-F12
    **{0x70 + i: 0x3A + i for i in range(12)},
    # Modifiers
    0x10: 0xE1,  # VK_SHIFT → LShift
    0x11: 0xE0,  # VK_CONTROL → LCtrl
    0x12: 0xE2,  # VK_MENU → LAlt
    0xA0: 0xE1,  # VK_LSHIFT
    0xA1: 0xE5,  # VK_RSHIFT
    0xA2: 0xE0,  # VK_LCONTROL
    0xA3: 0xE4,  # VK_RCONTROL
    0xA4: 0xE2,  # VK_LMENU (LAlt)
    0xA5: 0xE6,  # VK_RMENU (RAlt)
    0x5B: 0xE3,  # VK_LWIN
    0x5C: 0xE7,  # VK_RWIN
    0x14: 0x39,  # VK_CAPITAL → Caps Lock
    0x90: 0x53,  # VK_NUMLOCK
    0x91: 0x47,  # VK_SCROLL
    # OEM keys (US layout)
    0xBD: 0x2D,  # VK_OEM_MINUS → -
    0xBB: 0x2E,  # VK_OEM_PLUS  → =
    0xDB: 0x2F,  # VK_OEM_4     → [
    0xDD: 0x30,  # VK_OEM_6     → ]
    0xDC: 0x31,  # VK_OEM_5     → backslash
    0xBA: 0x33,  # VK_OEM_1     → ;
    0xDE: 0x34,  # VK_OEM_7     → '
    0xC0: 0x35,  # VK_OEM_3     → `
    0xBC: 0x36,  # VK_OEM_COMMA → ,
    0xBE: 0x37,  # VK_OEM_PERIOD→ .
    0xBF: 0x38,  # VK_OEM_2     → /
}


def vk_to_hid(vk_code: int) -> int | None:
    """Convert a Windows VK code to a USB HID usage ID. Returns None if unknown."""
    return _VK_TO_HID.get(vk_code)


# ── Char → (hid_code, shift) table (US ANSI layout) ───────────────────────

def _build_char_map():
    m = {}
    # lowercase letters
    for i, ch in enumerate("abcdefghijklmnopqrstuvwxyz"):
        m[ch] = (0x04 + i, False)
    # uppercase letters
    for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        m[ch] = (0x04 + i, True)
    # digits
    m['1'] = (0x1E, False); m['!'] = (0x1E, True)
    m['2'] = (0x1F, False); m['@'] = (0x1F, True)
    m['3'] = (0x20, False); m['#'] = (0x20, True)
    m['4'] = (0x21, False); m['$'] = (0x21, True)
    m['5'] = (0x22, False); m['%'] = (0x22, True)
    m['6'] = (0x23, False); m['^'] = (0x23, True)
    m['7'] = (0x24, False); m['&'] = (0x24, True)
    m['8'] = (0x25, False); m['*'] = (0x25, True)
    m['9'] = (0x26, False); m['('] = (0x26, True)
    m['0'] = (0x27, False); m[')'] = (0x27, True)
    # whitespace / control
    m[' ']  = (0x2C, False)
    m['\n'] = (0x28, False)
    m['\t'] = (0x2B, False)
    # punctuation
    m['-']  = (0x2D, False); m['_']  = (0x2D, True)
    m['=']  = (0x2E, False); m['+']  = (0x2E, True)
    m['[']  = (0x2F, False); m['{']  = (0x2F, True)
    m[']']  = (0x30, False); m['}']  = (0x30, True)
    m['\\'] = (0x31, False); m['|']  = (0x31, True)
    m[';']  = (0x33, False); m[':']  = (0x33, True)
    m["'"]  = (0x34, False); m['"']  = (0x34, True)
    m['`']  = (0x35, False); m['~']  = (0x35, True)
    m[',']  = (0x36, False); m['<']  = (0x36, True)
    m['.']  = (0x37, False); m['>']  = (0x37, True)
    m['/']  = (0x38, False); m['?']  = (0x38, True)
    return m

_CHAR_MAP = _build_char_map()


# ── Win32 cursor position ───────────────────────────────────────────────────

class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

_user32 = ctypes.windll.user32


def _get_cursor_pos() -> tuple[int, int]:
    pt = _POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


# ── Arduino HID class ───────────────────────────────────────────────────────

class ArduinoHID:
    """Serial interface to the Arduino HID firmware."""

    ARDUINO_VIDS = {0x2341, 0x2A03, 0x1B4F, 0x239A}  # Arduino, Sparkfun, Adafruit

    def __init__(self, port: str | None = None, baudrate: int = 115200, timeout: float = 0.5):
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._ser: serial.Serial | None = None
        self._connect()

    # ── Connection ──────────────────────────────────────────────────────────

    def _connect(self):
        port = self._port or self._detect_port()
        if port is None:
            raise RuntimeError("Arduino HID not found. Specify port or check USB connection.")
        self._ser = serial.Serial(port, self._baudrate, timeout=self._timeout)
        time.sleep(2.0)  # let Arduino reset + bootloader settle
        self._ser.reset_input_buffer()
        self.ping()  # verify communication

    @classmethod
    def _detect_port(cls) -> str | None:
        """Auto-detect Arduino serial port by USB VID."""
        for info in serial.tools.list_ports.comports():
            if info.vid in cls.ARDUINO_VIDS:
                return info.device
        # Fallback: any port with 'Arduino' or 'CH340' in description
        for info in serial.tools.list_ports.comports():
            desc = (info.description or "").lower()
            if "arduino" in desc or "ch340" in desc or "usbserial" in desc:
                return info.device
        return None

    def close(self):
        if self._ser and self._ser.is_open:
            self._ser.close()

    # ── Low-level protocol ──────────────────────────────────────────────────

    def _send(self, cmd: int, payload: bytes = b"") -> tuple[int, int]:
        """Send a command and return (response_type, data_byte)."""
        length = len(payload)
        chk = cmd ^ length
        for b in payload:
            chk ^= b
        packet = bytes([SOF, cmd, length]) + payload + bytes([chk])
        self._ser.write(packet)
        return self._recv()

    def _recv(self) -> tuple[int, int]:
        """Read a 4-byte response packet. Returns (type, data)."""
        buf = self._ser.read(4)
        if len(buf) < 4 or buf[0] != SOF:
            raise IOError(f"Bad response: {buf.hex() if buf else 'timeout'}")
        rtype, data, chk = buf[1], buf[2], buf[3]
        if (rtype ^ data) != chk:
            raise IOError("Response checksum error")
        return rtype, data

    # ── Commands ────────────────────────────────────────────────────────────

    def ping(self) -> bool:
        rtype, _ = self._send(CMD_PING)
        return rtype == RSP_PONG

    def key_press(self, hid_code: int):
        self._send(CMD_KEY_PRESS, bytes([hid_code]))

    def key_release(self, hid_code: int):
        self._send(CMD_KEY_RELEASE, bytes([hid_code]))

    def key_release_all(self):
        self._send(CMD_KEY_REL_ALL)

    def key_write(self, hid_codes: list[int]):
        """Tap each key in sequence (press+release)."""
        for i in range(0, len(hid_codes), 8):
            chunk = hid_codes[i:i+8]
            self._send(CMD_KEY_WRITE, bytes(chunk))

    def mouse_move_rel(self, dx: int, dy: int):
        """Relative mouse move. dx/dy clamped to int8 (-128..127)."""
        dx = max(-128, min(127, dx))
        dy = max(-128, min(127, dy))
        self._send(CMD_MOUSE_MOVE, bytes([dx & 0xFF, dy & 0xFF]))

    def mouse_click(self, buttons: int = BTN_LEFT):
        self._send(CMD_MOUSE_CLICK, bytes([buttons]))

    def mouse_press(self, buttons: int):
        self._send(CMD_MOUSE_PRESS, bytes([buttons]))

    def mouse_release(self, buttons: int):
        self._send(CMD_MOUSE_RELEASE, bytes([buttons]))

    def mouse_scroll(self, amount: int):
        amount = max(-128, min(127, amount))
        self._send(CMD_MOUSE_SCROLL, bytes([amount & 0xFF]))

    # ── High-level helpers ──────────────────────────────────────────────────

    def mouse_move_abs(self, target_x: int, target_y: int):
        """Move cursor to absolute screen coordinates via incremental relative moves."""
        cur_x, cur_y = _get_cursor_pos()
        remaining_x = target_x - cur_x
        remaining_y = target_y - cur_y
        while remaining_x != 0 or remaining_y != 0:
            dx = max(-127, min(127, remaining_x))
            dy = max(-127, min(127, remaining_y))
            self.mouse_move_rel(dx, dy)
            remaining_x -= dx
            remaining_y -= dy

    def click(self, x: int, y: int, button: str = "left"):
        """Move to (x, y) and click."""
        self.mouse_move_abs(x, y)
        btn = {"left": BTN_LEFT, "right": BTN_RIGHT, "middle": BTN_MIDDLE}.get(button, BTN_LEFT)
        self.mouse_click(btn)

    def vk_press(self, vk_code: int):
        """Press and release a key given a Windows VK code."""
        hid = vk_to_hid(vk_code)
        if hid is None:
            raise ValueError(f"No HID mapping for VK 0x{vk_code:02X}")
        self.key_press(hid)
        self.key_release(hid)

    def type_text(self, text: str):
        """Type a string character by character using HID keycodes (US layout)."""
        for ch in text:
            mapping = _CHAR_MAP.get(ch)
            if mapping is None:
                continue  # skip unmappable characters
            hid_code, use_shift = mapping
            if use_shift:
                self.key_press(HID_LSHIFT)
            self.key_press(hid_code)
            self.key_release(hid_code)
            if use_shift:
                self.key_release(HID_LSHIFT)


# ── Module-level singleton ──────────────────────────────────────────────────

_hid: ArduinoHID | None = None


def init(port: str | None = None, baudrate: int = 115200) -> ArduinoHID:
    """Initialize (or reinitialize) the global Arduino HID instance."""
    global _hid
    if _hid is not None:
        try:
            _hid.close()
        except Exception:
            pass
    _hid = ArduinoHID(port=port, baudrate=baudrate)
    return _hid


def get() -> ArduinoHID:
    """Return the global instance. Raises RuntimeError if not initialized."""
    if _hid is None:
        raise RuntimeError("ArduinoHID not initialized. Call arduino_hid.init() first.")
    return _hid
