"""Generate assets/icon.png and assets/icon.ico using only the standard library."""
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
C1, C2 = (64, 140, 255), (132, 76, 255)     # gradient: blue -> violet
WHITE = (255, 255, 255)


def _inside_tri(px, py, a, b, c):
    def side(p, q, r):
        return (p[0] - r[0]) * (q[1] - r[1]) - (q[0] - r[0]) * (p[1] - r[1])
    d1, d2, d3 = side((px, py), a, b), side((px, py), b, c), side((px, py), c, a)
    return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))


def render(size: int, ss: int = 3) -> bytes:
    """Rounded gradient tile with a white 'play' triangle and an underline bar (RGBA rows)."""
    pad, radius, half = size * 0.04, size * 0.22, size / 2
    tri = [(size * 0.37, size * 0.24), (size * 0.37, size * 0.64), (size * 0.75, size * 0.44)]
    bar = (size * 0.25, size * 0.74, size * 0.75, size * 0.82)   # x0, y0, x1, y1
    inner = half - pad - radius
    out = bytearray()
    for y in range(size):
        for x in range(size):
            n_bg = 0
            acc = [0.0, 0.0, 0.0]
            for sy in range(ss):
                for sx in range(ss):
                    px, py = x + (sx + 0.5) / ss, y + (sy + 0.5) / ss
                    dx, dy = max(abs(px - half) - inner, 0.0), max(abs(py - half) - inner, 0.0)
                    if dx * dx + dy * dy > radius * radius:
                        continue
                    n_bg += 1
                    fg = _inside_tri(px, py, *tri) or (bar[0] <= px <= bar[2] and bar[1] <= py <= bar[3])
                    if fg:
                        col = WHITE
                    else:
                        t = (px + py) / (2 * size)
                        col = tuple(C1[i] + (C2[i] - C1[i]) * t for i in range(3))
                    for i in range(3):
                        acc[i] += col[i]
            if n_bg:
                out += bytes((round(acc[0] / n_bg), round(acc[1] / n_bg), round(acc[2] / n_bg),
                              round(255 * n_bg / (ss * ss))))
            else:
                out += b"\x00\x00\x00\x00"
    return bytes(out)


def png(size: int, rgba: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + rgba[y * size * 4:(y + 1) * size * 4] for y in range(size))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def ico(images: list[tuple[int, bytes]]) -> bytes:
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, data in images:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    return head + entries + blobs


def main() -> None:
    (ROOT / "assets").mkdir(exist_ok=True)
    sizes = [256, 64, 48, 32, 16]
    pngs = [(s, png(s, render(s, ss=3 if s >= 32 else 5))) for s in sizes]
    (ROOT / "assets" / "icon.png").write_bytes(pngs[0][1])
    (ROOT / "assets" / "icon.ico").write_bytes(ico(pngs))
    print("wrote assets/icon.png and assets/icon.ico")


if __name__ == "__main__":
    main()
