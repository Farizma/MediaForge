"""Generate assets/icon.png and assets/icon.ico (the anvil + play logo) using only the standard library."""
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The logo, on a 120-unit grid: an orange anvil with a white play symbol above it, on a dark tile.
TOP, BOTTOM = (46, 46, 50), (28, 28, 30)       # tile: a soft top-down sheen, like Media Vault's icons
ORANGE, WHITE = (255, 159, 10), (255, 255, 255)
PLAY = [(52, 24), (52, 47), (72, 35.5)]
ANVIL = [(20, 54), (100, 54), (90, 68), (73, 70), (73, 85), (88, 99), (32, 99), (47, 85), (47, 70), (30, 68)]


def _inside(px, py, poly):
    """Even-odd point-in-polygon (the anvil is not convex)."""
    inside, j = False, len(poly) - 1
    for i, (xi, yi) in enumerate(poly):
        xj, yj = poly[j]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def render(size: int, ss: int = 3) -> bytes:
    """The logo as RGBA rows, anti-aliased by supersampling."""
    pad, radius, half = size * 0.04, size * 0.22, size / 2
    inner = half - pad - radius
    k = 120 / size
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
                    gx, gy = px * k, py * k
                    if _inside(gx, gy, PLAY):
                        col = WHITE
                    elif _inside(gx, gy, ANVIL):
                        col = ORANGE
                    else:
                        t = py / size
                        col = tuple(TOP[i] + (BOTTOM[i] - TOP[i]) * t for i in range(3))
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
