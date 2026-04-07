"""Convert sprite DB data to tkinter PhotoImage via PIL, with caching."""
from PIL import Image, ImageTk
import tkinter as tk

from editor.db import fetch_sprite

# Cache: (sprite_name, width, height) → PhotoImage
# Must hold references to prevent GC of PhotoImages
_cache: dict[tuple, ImageTk.PhotoImage] = {}


def sprite_to_image(sprite_name: str) -> Image.Image | None:
    """Build a PIL RGBA Image from a sprite's palette + pixels at native resolution."""
    data = fetch_sprite(sprite_name)
    if data is None:
        return None
    palette = data['palette']
    pixels = data['pixels']
    rows = len(pixels)
    cols = data.get('width', len(pixels[0]) if rows else 1)

    img = Image.new('RGBA', (cols, rows), (0, 0, 0, 0))
    for ri, row_str in enumerate(pixels):
        for ci, ch in enumerate(row_str):
            if ci >= cols:
                break
            if ch == '.' or ch not in palette:
                continue
            hex_color = palette[ch]
            try:
                r = int(hex_color[1:3], 16)
                g = int(hex_color[3:5], 16)
                b = int(hex_color[5:7], 16)
                img.putpixel((ci, ri), (r, g, b, 255))
            except (ValueError, IndexError):
                continue
    return img


def sprite_to_photoimage(sprite_name: str, width: int, height: int) -> ImageTk.PhotoImage | None:
    """Get a cached PhotoImage for a sprite at the requested display size.

    Uses nearest-neighbor scaling to preserve pixel art.
    """
    if not sprite_name:
        return None
    key = (sprite_name, width, height)
    if key in _cache:
        return _cache[key]

    img = sprite_to_image(sprite_name)
    if img is None:
        return None

    scaled = img.resize((width, height), Image.NEAREST)
    photo = ImageTk.PhotoImage(scaled)
    _cache[key] = photo
    return photo


def invalidate_cache():
    """Clear all cached PhotoImages (e.g. on zoom change)."""
    _cache.clear()


def make_default_tile_photo(width: int, height: int,
                             color: tuple = (60, 90, 60, 255)) -> ImageTk.PhotoImage:
    """Create a solid-color PhotoImage for the default tile fill."""
    key = ('__default__', width, height, color)
    if key in _cache:
        return _cache[key]
    img = Image.new('RGBA', (width, height), color)
    photo = ImageTk.PhotoImage(img)
    _cache[key] = photo
    return photo


def make_empty_tile_photo(width: int, height: int) -> ImageTk.PhotoImage:
    """Create a dark checkerboard PhotoImage for tiles with no sprite."""
    key = ('__empty__', width, height)
    if key in _cache:
        return _cache[key]
    img = Image.new('RGBA', (width, height), (40, 40, 40, 255))
    cs = max(1, width // 4)
    for y in range(height):
        for x in range(width):
            if (x // cs + y // cs) % 2 == 0:
                img.putpixel((x, y), (50, 50, 50, 255))
    photo = ImageTk.PhotoImage(img)
    _cache[key] = photo
    return photo
