"""Tile template palette for the visual map editor."""
import tkinter as tk
from tkinter import ttk

from editor.db import get_con
from editor.sprite_to_photoimage import sprite_to_photoimage, make_empty_tile_photo
from editor.tooltip import add_tooltip

THUMB_SIZE = 32


class TilePalette(ttk.Frame):
    """Sidebar showing tile templates as a selectable list with sprite previews."""

    def __init__(self, parent, on_select=None, **kwargs):
        super().__init__(parent, **kwargs)
        self._on_select = on_select
        self._templates = []   # list of (key, sprite_name, walkable)
        self._photos = {}      # keep PhotoImage references
        self._selected_key = None

        self._build_ui()
        self.refresh()

    def _build_ui(self):
        ttk.Label(self, text='Tile Palette',
                   font=('TkDefaultFont', 9, 'bold')).pack(
            anchor='w', padx=4, pady=(4, 2))

        # Search filter
        filter_f = ttk.Frame(self)
        filter_f.pack(fill=tk.X, padx=4, pady=2)
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add('write', lambda *_: self._apply_filter())
        filter_entry = ttk.Entry(filter_f, textvariable=self._filter_var, width=16)
        filter_entry.pack(fill=tk.X)
        add_tooltip(filter_entry, 'Filter tile templates by name')

        # Eraser button
        eraser_f = ttk.Frame(self)
        eraser_f.pack(fill=tk.X, padx=4, pady=2)
        self._eraser_btn = ttk.Button(eraser_f, text='\u2716 Eraser',
                                       command=self._select_eraser)
        self._eraser_btn.pack(fill=tk.X)
        add_tooltip(self._eraser_btn, 'Click to select eraser tool — removes tiles (reverts to default)')

        # Template list with scrollbar
        list_f = ttk.Frame(self)
        list_f.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        self._listbox = tk.Listbox(list_f, exportselection=False,
                                    width=20, height=6,
                                    font=('Courier', 9))
        sb = ttk.Scrollbar(list_f, orient=tk.VERTICAL,
                            command=self._listbox.yview)
        self._listbox.configure(yscrollcommand=sb.set)
        self._listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._listbox.bind('<<ListboxSelect>>', self._on_listbox_select)

        # Preview of selected template
        self._preview_label = ttk.Label(self, text='')
        self._preview_label.pack(padx=4, pady=4)
        self._preview_canvas = tk.Canvas(self, width=64, height=48,
                                          bg='#2d2d2d', highlightthickness=1,
                                          highlightbackground='#555')
        self._preview_canvas.pack(padx=4, pady=(0, 4))

    def refresh(self):
        """Reload templates from DB."""
        con = get_con()
        try:
            rows = con.execute(
                'SELECT key, sprite_name, walkable FROM tile_templates ORDER BY key'
            ).fetchall()
            self._templates = [(r['key'], r['sprite_name'], r['walkable']) for r in rows]
        finally:
            con.close()
        self._apply_filter()

    def get_selected(self) -> str | None:
        """Return the selected tile template key, or None for eraser."""
        return self._selected_key

    def _apply_filter(self):
        """Filter and repopulate the listbox."""
        filt = self._filter_var.get().strip().lower()
        self._listbox.delete(0, tk.END)
        self._filtered = []
        for key, sprite, walkable in self._templates:
            if filt and filt not in key.lower():
                continue
            prefix = '\u2713' if walkable else '\u2717'
            self._listbox.insert(tk.END, f'{prefix} {key}')
            self._filtered.append((key, sprite, walkable))

    def _on_listbox_select(self, event=None):
        sel = self._listbox.curselection()
        if not sel:
            return
        key, sprite, walkable = self._filtered[sel[0]]
        self._selected_key = key
        self._preview_label.configure(text=key)
        self._update_preview(sprite)
        if self._on_select:
            self._on_select(key)

    def _select_eraser(self):
        self._selected_key = None
        self._listbox.selection_clear(0, tk.END)
        self._preview_label.configure(text='Eraser')
        self._preview_canvas.delete('all')
        self._preview_canvas.create_text(
            32, 24, text='\u2716', fill='#ff6666',
            font=('TkDefaultFont', 18))
        if self._on_select:
            self._on_select(None)

    def _update_preview(self, sprite_name: str | None):
        self._preview_canvas.delete('all')
        if sprite_name:
            photo = sprite_to_photoimage(sprite_name, 64, 48)
            if photo:
                self._photos['preview'] = photo
                self._preview_canvas.create_image(0, 0, image=photo, anchor='nw')
                return
        self._preview_canvas.create_text(
            32, 24, text='No sprite', fill='#666',
            font=('TkDefaultFont', 8))
