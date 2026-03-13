"""Win Control — WebSocket client that connects to a server and executes window commands.

All mouse/keyboard input is performed via the Arduino HID hardware controller.
"""

import asyncio
import json
import os
import sys
import subprocess
import websockets
import win32 as w
import arduino_hid

DEFAULT_URL = "ws://127.0.0.1:8765"


def dispatch(action, msg):
    if action == "list_com_ports":
        import serial.tools.list_ports
        ports = [
            {"device": info.device, "description": info.description or info.device}
            for info in serial.tools.list_ports.comports()
        ]
        return {"ports": ports}
    if action == "init_hid":
        port = msg.get("port") or None
        print(f"Reinitializing Arduino HID on port {port or 'auto-detect'}...")
        arduino_hid.init(port=port)
        print("Arduino HID ready.")
        return {"port": port or "auto-detect"}
    if action == "list_directory":
        path = msg.get("path", "")
        if not path:
            import string

            drives = []
            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    drives.append({"name": drive, "is_dir": True})
            return {"path": path, "entries": drives}
        entries = []
        try:
            for name in os.listdir(path):
                full = os.path.join(path, name)
                entries.append({"name": name, "is_dir": os.path.isdir(full)})
        except PermissionError:
            pass
        entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
        return {"path": path, "entries": entries}
    if action == "list_windows":
        return w.list_windows()
    if action == "get_window":
        return w.get_window_info(msg["hwnd"])
    if action == "get_window_state":
        hwnd = msg["hwnd"]
        info = w.get_window_info(hwnd)
        return {
            "hwnd": hwnd,
            "minimized": info["minimized"],
            "maximized": info["maximized"],
            "width": info["rect"]["w"],
            "height": info["rect"]["h"],
            "x": info["rect"]["x"],
            "y": info["rect"]["y"],
            "visible": info["visible"],
        }
    if action == "check_processes":
        paths = msg.get("paths", [])
        results = []
        for path in paths:
            windows = w.find_process_windows(path)
            results.append({"path": path, "running": len(windows) > 0, "windows": windows})
        return {"results": results}
    if action == "get_pixels":
        return w.get_pixels(msg["positions"])
    if action == "focus":
        w.focus_window(msg["hwnd"])
    elif action == "close":
        w.close_window(msg["hwnd"])
    elif action == "minimize":
        w.minimize_window(msg["hwnd"])
    elif action == "maximize":
        w.maximize_window(msg["hwnd"])
    elif action == "restore":
        w.restore_window(msg["hwnd"])
    elif action == "move_resize":
        w.move_resize_window(
            msg["hwnd"], msg["x"], msg["y"], msg["width"], msg["height"]
        )
    elif action == "set_windowed":
        w.set_windowed(msg["hwnd"])
    elif action == "set_fullscreen":
        w.set_fullscreen(msg["hwnd"])
    elif action == "open_process":
        path = msg["path"]
        args = msg.get("args", [])
        proc = subprocess.Popen([path] + args)
        return {"pid": proc.pid}
    elif action == "window_action":
        hwnd = msg.get("hwnd", 0)
        wa = msg.get("wa", "") or msg.get("action", "")
        if wa == "minimize":
            w.minimize_window(hwnd)
        elif wa == "maximize":
            w.maximize_window(hwnd)
        elif wa == "restore":
            w.restore_window(hwnd)
        elif wa == "close":
            w.close_window(hwnd)
        elif wa in ("focus", "bring_to_front"):
            w.focus_window(hwnd)
        elif wa == "resize":
            w.move_resize_window(hwnd, msg.get("x", 0), msg.get("y", 0),
                                 msg.get("width", 800), msg.get("height", 600))
        elif wa == "move":
            info = w.get_window_info(hwnd)
            w.move_resize_window(hwnd, msg.get("x", 0), msg.get("y", 0),
                                 info["rect"]["w"], info["rect"]["h"])
        elif wa == "set_fullscreen":
            w.set_fullscreen(hwnd)
        elif wa == "set_windowed":
            w.set_windowed(hwnd)
        elif wa == "open_window":
            path = msg.get("path", "")
            if path:
                args = msg.get("args", [])
                proc = subprocess.Popen([path] + args)
                return {"pid": proc.pid}
    elif action == "click":
        x, y = msg["x"], msg["y"]
        hwnd = msg.get("hwnd", 0)
        if hwnd:
            ox, oy = w._client_offset(hwnd)
            x, y = x + ox, y + oy
        arduino_hid.get().click(x, y, msg.get("button", "left"))
    elif action == "move_mouse":
        x, y = msg["x"], msg["y"]
        hwnd = msg.get("hwnd", 0)
        if hwnd:
            ox, oy = w._client_offset(hwnd)
            x, y = x + ox, y + oy
        arduino_hid.get().mouse_move_abs(x, y)
    elif action == "key_press":
        hid = arduino_hid.get()
        modifiers = msg.get("modifiers", [])
        mod_hids = [arduino_hid.vk_to_hid(m) for m in modifiers]
        mod_hids = [h for h in mod_hids if h is not None]
        for h in mod_hids:
            hid.key_press(h)
        hid.vk_press(msg["vk"])
        for h in reversed(mod_hids):
            hid.key_release(h)
    elif action == "type_text":
        arduino_hid.get().type_text(msg["text"])
    elif action == "match_templates":
        return _match_templates(msg)
    else:
        raise ValueError(f"unknown action: {action}")
    return None


def _match_templates(msg: dict) -> dict:
    """Captura screenshot e executa template matching para cada template enviado."""
    import base64, io

    hwnd = msg.get("hwnd", 0)
    templates = msg.get("templates", [])
    if not templates:
        return {"results": []}

    # Captura screenshot uma vez
    if hwnd:
        cap = w.screenshot_window(hwnd)
        if cap is None:
            return {
                "results": [
                    {"id": t["id"], "found": False, "confidence": 0.0, "x": 0, "y": 0}
                    for t in templates
                ]
            }
        src_w, src_h, bmp_data, win_rect = cap
        # Border offset: screenshot origin is window top-left, but click coords are
        # client-relative (brain adds _client_offset). Subtract the border so that
        # match results are returned in client-relative space.
        client_ox, client_oy = w._client_offset(hwnd)
        border_dx = client_ox - win_rect["x"]
        border_dy = client_oy - win_rect["y"]
    else:
        src_w, src_h, bmp_data = w.screenshot_screen()
        border_dx = border_dy = 0

    # Converte BMP BGR-24 para numpy (H, W, 3)
    import numpy as np

    row_stride = (src_w * 3 + 3) & ~3
    raw = np.frombuffer(bmp_data, dtype=np.uint8).reshape(src_h, row_stride)
    src_bgr = np.ascontiguousarray(raw[:, : src_w * 3].reshape(src_h, src_w, 3))

    results = []
    for tmpl in templates:
        tid = tmpl["id"]
        threshold = float(tmpl.get("threshold", 0.8))
        try:
            tdata = base64.b64decode(tmpl["data"])
            confidence, mx, my = _do_match(src_bgr, tdata)
            results.append(
                {
                    "id": tid,
                    "found": confidence >= threshold,
                    "confidence": round(float(confidence), 4),
                    "x": int(mx) - border_dx,
                    "y": int(my) - border_dy,
                }
            )
        except Exception as e:
            results.append(
                {
                    "id": tid,
                    "found": False,
                    "confidence": 0.0,
                    "x": 0,
                    "y": 0,
                    "error": str(e),
                }
            )
    return {"results": results}


def _do_match(src_bgr, template_png_bytes: bytes) -> tuple[float, int, int]:
    """Retorna (confidence, x, y). Usa OpenCV se disponível, senão numpy NCC."""
    import io, numpy as np
    from PIL import Image

    timg = Image.open(io.BytesIO(template_png_bytes)).convert("RGB")
    tmpl_rgb = np.array(timg, dtype=np.uint8)
    tmpl_bgr = tmpl_rgb[:, :, ::-1]

    try:
        import cv2

        # Match in color (BGR) so that differently-colored regions don't get
        # falsely high confidence scores when structure/luminance is similar.
        res = cv2.matchTemplate(src_bgr, tmpl_bgr, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        return float(max_val), max_loc[0], max_loc[1]
    except ImportError:
        pass

    return _ncc_numpy(src_bgr, tmpl_bgr)


def _ncc_numpy(src: "np.ndarray", tmpl: "np.ndarray") -> tuple[float, int, int]:
    """Normalized cross-correlation via FFT (numpy). Per-channel, averaged."""
    import math
    import numpy as np

    sh, sw = src.shape[:2]
    th, tw = tmpl.shape[:2]
    oh, ow = sh - th + 1, sw - tw + 1

    if oh <= 0 or ow <= 0:
        return 0.0, 0, 0

    fh = 2 ** math.ceil(math.log2(sh + th))
    fw = 2 ** math.ceil(math.log2(sw + tw))

    ncc_sum = np.zeros((oh, ow), dtype=np.float64)
    valid_channels = 0

    for ch in range(src.shape[2]):
        s = src[:, :, ch].astype(np.float32)
        t = tmpl[:, :, ch].astype(np.float32)

        t_mu = t.mean()
        t_c = t - t_mu
        t_norm = float(np.sqrt((t_c**2).sum()))
        if t_norm == 0:
            continue

        xcorr = np.fft.irfft2(
            np.fft.rfft2(s, s=(fh, fw)) * np.fft.rfft2(t_c[::-1, ::-1], s=(fh, fw)),
            s=(fh, fw),
        )[th - 1 : th - 1 + oh, tw - 1 : tw - 1 + ow]

        ii = np.zeros((sh + 1, sw + 1), dtype=np.float64)
        ii[1:, 1:] = np.cumsum(np.cumsum(s.astype(np.float64), 0), 1)
        ii2 = np.zeros((sh + 1, sw + 1), dtype=np.float64)
        ii2[1:, 1:] = np.cumsum(np.cumsum(s.astype(np.float64) ** 2, 0), 1)

        R = np.arange(oh)[:, None]
        C = np.arange(ow)[None, :]

        def box(A):
            return A[R + th, C + tw] - A[R, C + tw] - A[R + th, C] + A[R, C]

        n = th * tw
        p_sum = box(ii)
        p_sum2 = box(ii2)
        p_var = np.maximum(p_sum2 / n - (p_sum / n) ** 2, 0.0)
        p_std = np.sqrt(p_var * n)

        denom = p_std * t_norm
        ncc_sum += np.where(denom > 1e-8, xcorr / denom, 0.0)
        valid_channels += 1

    if valid_channels == 0:
        return 0.0, 0, 0

    ncc = ncc_sum / valid_channels
    idx = int(np.argmax(ncc))
    best_y, best_x = divmod(idx, ow)
    return float(ncc[best_y, best_x]), best_x, best_y


async def run(url):
    while True:
        try:
            async with websockets.connect(
                url,
                max_size=10 * 1024 * 1024,
                ping_interval=None,
            ) as ws:
                print(f"Connected to {url}")
                async for raw in ws:
                    msg = {}
                    try:
                        msg = json.loads(raw)
                        action = msg.get("action")
                        result = dispatch(action, msg)
                        resp = {"ok": True, "action": action, "data": result}
                    except Exception as e:
                        resp = {
                            "ok": False,
                            "action": msg.get("action"),
                            "error": str(e),
                        }
                    if "id" in msg:
                        resp["id"] = msg["id"]
                    try:
                        await ws.send(json.dumps(resp))
                    except websockets.exceptions.ConnectionClosed:
                        print(
                            "Connection closed while sending response; reconnecting..."
                        )
                        break
        except (websockets.exceptions.ConnectionClosed, OSError) as e:
            print(f"Disconnected ({e}); reconnecting in 3s...")
            await asyncio.sleep(3)


if __name__ == "__main__":
    args = sys.argv[1:]
    url = DEFAULT_URL
    port = None
    i = 0
    while i < len(args):
        if args[i] == "--hid-port" and i + 1 < len(args):
            port = args[i + 1]
            i += 2
        else:
            url = args[i]
            i += 1

    print(f"Initializing Arduino HID on port {port or 'auto-detect'}...")
    arduino_hid.init(port=port)
    print("Arduino HID ready.")

    asyncio.run(run(url))
