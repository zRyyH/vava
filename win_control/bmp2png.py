"""Convert raw BGR bitmap data to JPEG/PNG using Pillow (fast) or stdlib fallback."""
import io

try:
    from PIL import Image as _Image
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


def raw_bgr_to_jpeg(width, height, bgr_data, quality=60):
    """Convert raw BGR24 bitmap to JPEG bytes using Pillow."""
    stride = (width * 3 + 3) & ~3
    img = _Image.frombuffer('RGB', (width, height), bgr_data, 'raw', 'BGR', stride, 1)
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=quality, optimize=False)
    return buf.getvalue()


def raw_bgr_to_png(width, height, bgr_data):
    """Convert raw BGR24 bitmap to PNG bytes. Uses Pillow if available, stdlib otherwise."""
    if _PIL_AVAILABLE:
        stride = (width * 3 + 3) & ~3
        img = _Image.frombuffer('RGB', (width, height), bgr_data, 'raw', 'BGR', stride, 1)
        buf = io.BytesIO()
        img.save(buf, 'PNG', compress_level=1)
        return buf.getvalue()

    import struct, zlib
    stride = (width * 3 + 3) & ~3
    raw_rows = []
    for y in range(height):
        offset = y * stride
        row = bytearray(width * 3)
        for x in range(width):
            src = offset + x * 3
            dst = x * 3
            row[dst] = bgr_data[src + 2]
            row[dst + 1] = bgr_data[src + 1]
            row[dst + 2] = bgr_data[src]
        raw_rows.append(b'\x00' + bytes(row))
    raw = b''.join(raw_rows)
    compressed = zlib.compress(raw, 1)

    def chunk(ctype, data):
        c = ctype + data
        crc = struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack('>I', len(data)) + c + crc

    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    return sig + chunk(b'IHDR', ihdr) + chunk(b'IDAT', compressed) + chunk(b'IEND', b'')
