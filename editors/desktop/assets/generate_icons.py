#!/usr/bin/env python3
"""Generate all desktop icon assets from logo-icon.png (the cat-only master).

Plan B: light rounded-rectangle background + scaled-up cat composite.

Reads logo-icon.png (512x512 transparent cat), composites it onto a light
rounded-rectangle background plate, then derives every required size for
the macOS iconset, app-icon.png, icon.ico, and icon.icns.

Dependencies: Pillow (pip install Pillow)
macOS only for icon.icns: built-in iconutil

Run:  python3 generate_icons.py   (from the assets/ directory)
"""

import io
import os
import struct
import subprocess
import sys

from PIL import Image, ImageDraw

ASSETS = os.path.dirname(os.path.abspath(__file__))
CAT_SOURCE = os.path.join(ASSETS, "logo-icon.png")
ICONSET = os.path.join(ASSETS, "icon.iconset")
MASTER_SIZE = 1024

# ---- Plan B design parameters ----

# Light rounded background plate
BG_TOP = (245, 247, 250)  # #f5f7fa – very light blue-gray (top)
BG_BOTTOM = (233, 236, 241)  # #e9ecf1 – slightly deeper (bottom)

# Corner radius as fraction of canvas (≈ macOS squircle at 0.225)
CORNER_RADIUS_FRAC = 0.225

# How much of the canvas the cat occupies (up from the original ~49%)
CAT_FILL = 0.72

# ---- macOS iconset spec ----
ICONSET_SIZES = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]

# ---- Windows .ico embedded sizes ----
ICO_SIZES = [16, 32, 48, 256]


# ---------------------------------------------------------------------------
# Gradient background
# ---------------------------------------------------------------------------


def create_gradient_bg(
    size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]
) -> Image.Image:
    """Return an RGBA `size×size` image filled with a vertical gradient."""
    # Build a 1-pixel-wide column with the gradient, then scale horizontally.
    grad = Image.new("RGBA", (1, size))
    for y in range(size):
        t = y / (size - 1) if size > 1 else 0.0
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        grad.putpixel((0, y), (r, g, b, 255))
    return grad.resize((size, size))


# ---------------------------------------------------------------------------
# Master compositing
# ---------------------------------------------------------------------------


def crop_to_content(img: Image.Image, padding_frac: float = 0.06) -> Image.Image:
    """Crop `img` to the bounding box of its non-transparent pixels.

    Adds `padding_frac` of the bbox dimensions on each side so the subject
    has breathing room (avoids clipping at small icon sizes).
    """
    bbox = img.getbbox()
    if bbox is None:
        return img  # fully transparent – return as-is
    left, top, right, bottom = bbox
    bw, bh = right - left, bottom - top
    pad_w, pad_h = int(bw * padding_frac), int(bh * padding_frac)
    left = max(0, left - pad_w)
    top = max(0, top - pad_h)
    right = min(img.width, right + pad_w)
    bottom = min(img.height, bottom + pad_h)
    return img.crop((left, top, right, bottom))


def create_master(size: int, cat_full: Image.Image) -> Image.Image:
    """Composite the cat onto a light rounded-rect background.

    1. Crop the cat to its visible content so it fills the icon properly.
    2. Fill canvas with a subtle vertical gradient.
    3. Apply a rounded-rect alpha mask so the plate has soft corners.
    4. Scale the cropped cat to `CAT_FILL` of the canvas.
    5. Paste the cat centred on top.
    """
    # 1. Crop cat to content
    cat = crop_to_content(cat_full)

    # 2. Gradient background
    bg = create_gradient_bg(size, BG_TOP, BG_BOTTOM)

    # 3. Rounded-rect mask – corners stay transparent so the plate shape is visible
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    radius = int(size * CORNER_RADIUS_FRAC)
    draw.rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=radius, fill=255)
    bg.putalpha(mask)

    # 4. Scale the cropped cat so its largest dimension fills CAT_FILL
    cw, ch = cat.size
    cat_fill_px = int(size * CAT_FILL)
    scale = cat_fill_px / max(cw, ch)
    new_w, new_h = int(cw * scale), int(ch * scale)
    cat_scaled = cat.resize((new_w, new_h), Image.LANCZOS)

    # 5. Paste cat centred onto the rounded-rect background
    ox = (size - new_w) // 2
    oy = (size - new_h) // 2
    bg.paste(cat_scaled, (ox, oy), cat_scaled)

    return bg


# ---------------------------------------------------------------------------
# ICO writer (raw binary – Pillow's multi-size ICO can be unreliable)
# ---------------------------------------------------------------------------


def write_ico(master: Image.Image, sizes: list[int], out_path: str) -> None:
    """Build a multi-resolution .ico file with PNG-encoded frames."""
    entries: list[tuple[int, int, bytes]] = []

    for sz in sizes:
        img = master.resize((sz, sz), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        data = buf.getvalue()
        w = 0 if sz >= 256 else sz  # 0 means 256 in ICO spec
        h = 0 if sz >= 256 else sz
        entries.append((w, h, data))

    dir_size = 6 + len(entries) * 16
    offsets: list[int] = []
    off = dir_size
    for _, _, data in entries:
        offsets.append(off)
        off += len(data)

    with open(out_path, "wb") as fh:
        fh.write(struct.pack("<HHH", 0, 1, len(entries)))
        for (w, h, data), o in zip(entries, offsets):
            fh.write(struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(data), o))
        for _, _, data in entries:
            fh.write(data)

    total = dir_size + sum(len(d) for _, _, d in entries)
    print(f"    ICO  → {out_path}  ({len(entries)} frames, {total:,} bytes)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    # Load cat source (512×512 transparent PNG)
    cat_full = Image.open(CAT_SOURCE).convert("RGBA")
    print(f"Cat source : {CAT_SOURCE}  ({cat_full.size[0]}×{cat_full.size[1]})")

    # Show cropped dimensions before compositing
    cat_cropped = crop_to_content(cat_full)
    print(
        f"Cat crop   : {cat_cropped.size[0]}×{cat_cropped.size[1]}  "
        f"(from bbox {cat_full.getbbox()}, +6% padding)"
    )

    # Build master composite
    master = create_master(MASTER_SIZE, cat_full)
    radius_px = int(MASTER_SIZE * CORNER_RADIUS_FRAC)
    cat_fill_px = int(MASTER_SIZE * CAT_FILL)
    print(
        f"Master     : {MASTER_SIZE}×{MASTER_SIZE}  "
        f"(cat fills {cat_fill_px}px / {CAT_FILL * 100:.0f}%, "
        f"corner radius {radius_px}px)"
    )

    # ---- 1. macOS iconset PNGs ----
    os.makedirs(ICONSET, exist_ok=True)
    for filename, size in ICONSET_SIZES:
        img = master.resize((size, size), Image.LANCZOS)
        out = os.path.join(ICONSET, filename)
        img.save(out, "PNG", optimize=True)
    print(f"  ✓ iconset  → {ICONSET}/  ({len(ICONSET_SIZES)} files)")

    # ---- 2. app-icon.png (1024×1024 hi-res tile for Electron / Linux) ----
    app_icon = os.path.join(ASSETS, "app-icon.png")
    master.save(app_icon, "PNG", optimize=True)
    print(f"  ✓ app-icon → {app_icon}  ({MASTER_SIZE}×{MASTER_SIZE})")

    # ---- 3. icon.ico (multi-resolution for Windows) ----
    ico_path = os.path.join(ASSETS, "icon.ico")
    write_ico(master, ICO_SIZES, ico_path)

    # ---- 4. icon.icns (via macOS iconutil) ----
    icns_path = os.path.join(ASSETS, "icon.icns")
    result = subprocess.run(
        ["iconutil", "-c", "icns", ICONSET, "-o", icns_path],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        icns_sz = os.path.getsize(icns_path)
        print(f"  ✓ icon.icns → {icns_path}  ({icns_sz:,} bytes)")
    else:
        print(f"  ⚠ icon.icns skipped – iconutil failed: {result.stderr.strip()}")
        print(f"    Run manually:  iconutil -c icns {ICONSET} -o {icns_path}")

    print("\nAll assets generated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
