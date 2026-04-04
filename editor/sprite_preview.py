import tkinter as tk

from editor.db import fetch_sprite
from editor.constants import PREVIEW_SIZE


class SpritePreview(tk.Canvas):
    """
    A small canvas that renders a sprite at PREVIEW_SIZE × PREVIEW_SIZE pixels.
    Call load(sprite_name) to update.
    """
    TRANSPARENT = '#d0d0d0'

    def __init__(self, parent, size=PREVIEW_SIZE, **kwargs):
        super().__init__(parent, width=size, height=size,
                         bg=self.TRANSPARENT, highlightthickness=1,
                         highlightbackground='#999', **kwargs)
        self._size = size
        self._draw_empty()

    def _draw_empty(self):
        self.delete('all')
        cs = max(1, self._size // 8)
        for row in range(8):
            for col in range(8):
                x0 = col * cs
                y0 = row * cs
                color = '#cccccc' if (row + col) % 2 == 0 else '#aaaaaa'
                self.create_rectangle(x0, y0, x0+cs, y0+cs, fill=color, outline='')

    def load(self, sprite_name: str | None):
        self.delete('all')
        data = fetch_sprite(sprite_name) if sprite_name else None
        if data is None:
            self._draw_empty()
            return
        palette = data['palette']
        pixels  = data['pixels']
        rows = len(pixels)
        cols = len(pixels[0]) if rows else 1
        cs_w = self._size / cols
        cs_h = self._size / rows
        for row_idx, row_str in enumerate(pixels):
            for col_idx, ch in enumerate(row_str):
                x0 = col_idx * cs_w
                y0 = row_idx * cs_h
                x1 = x0 + cs_w
                y1 = y0 + cs_h
                if ch == '.' or ch not in palette:
                    color = '#cccccc' if (row_idx + col_idx) % 2 == 0 else '#aaaaaa'
                else:
                    color = palette[ch]
                self.create_rectangle(x0, y0, x1, y1, fill=color, outline='')
