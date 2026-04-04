import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

from editor.db import get_con, fetch_sprite_names
from editor.constants import PREVIEW_SIZE
from editor.sprite_preview import SpritePreview


class TilesTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._list_keys: list[str] = []
        self._build_ui()
        self.refresh_list()

    def _build_ui(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        left = ttk.Frame(pane, width=200)
        pane.add(left, weight=0)
        ttk.Label(left, text='Tile Templates').pack(anchor='w')
        lf = ttk.Frame(left)
        lf.pack(fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(lf, exportselection=False, width=24)
        sb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.bind('<<ListboxSelect>>', self._on_select)
        br = ttk.Frame(left)
        br.pack(fill=tk.X, pady=4)
        ttk.Button(br, text='New',    command=self._new).pack(side=tk.LEFT, padx=2)
        ttk.Button(br, text='Save',   command=self._save).pack(side=tk.LEFT, padx=2)
        ttk.Button(br, text='Delete', command=self._delete).pack(side=tk.LEFT, padx=2)

        right = ttk.Frame(pane)
        pane.add(right, weight=1)
        f = right
        r = 0

        ttk.Label(f, text='Key').grid(row=r, column=0, sticky='w', padx=6, pady=4)
        self.v_key = tk.StringVar()
        ttk.Entry(f, textvariable=self.v_key, width=24).grid(row=r, column=1, sticky='ew', padx=6, pady=4)
        r += 1

        ttk.Label(f, text='Name').grid(row=r, column=0, sticky='w', padx=6, pady=4)
        self.v_name = tk.StringVar()
        ttk.Entry(f, textvariable=self.v_name, width=24).grid(row=r, column=1, sticky='ew', padx=6, pady=4)
        r += 1

        self.v_walkable = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text='Walkable', variable=self.v_walkable).grid(
            row=r, column=0, columnspan=2, sticky='w', padx=6, pady=4)
        r += 1

        self.v_covered = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text='Covered', variable=self.v_covered).grid(
            row=r, column=0, columnspan=2, sticky='w', padx=6, pady=4)
        r += 1

        ttk.Label(f, text='Tile Scale').grid(row=r, column=0, sticky='w', padx=6, pady=4)
        self.v_tile_scale = tk.StringVar(value='1.0')
        ttk.Entry(f, textvariable=self.v_tile_scale, width=10).grid(row=r, column=1, sticky='w', padx=6, pady=4)
        r += 1

        ttk.Label(f, text='Sprite').grid(row=r, column=0, sticky='w', padx=6, pady=4)
        sf = ttk.Frame(f)
        sf.grid(row=r, column=1, sticky='w', padx=6, pady=4)
        r += 1
        self.v_sprite = tk.StringVar()
        self._sprite_names = [''] + fetch_sprite_names()
        self.sprite_cb = ttk.Combobox(sf, textvariable=self.v_sprite,
                                      values=self._sprite_names, state='readonly', width=18)
        self.sprite_cb.pack(side=tk.LEFT, padx=(0, 8))
        self.sprite_preview = SpritePreview(sf, size=PREVIEW_SIZE)
        self.sprite_preview.pack(side=tk.LEFT)
        self.sprite_cb.bind('<<ComboboxSelected>>', lambda e: self.sprite_preview.load(self.v_sprite.get() or None))
        f.columnconfigure(1, weight=1)

    def refresh_list(self):
        con = get_con()
        try:
            rows = con.execute('SELECT key FROM tiles ORDER BY key').fetchall()
        finally:
            con.close()
        self.listbox.delete(0, tk.END)
        self._list_keys = [r['key'] for r in rows]
        for k in self._list_keys:
            self.listbox.insert(tk.END, k)

    def refresh_sprite_dropdown(self):
        self._sprite_names = [''] + fetch_sprite_names()
        self.sprite_cb['values'] = self._sprite_names

    def _clear_form(self):
        self.v_key.set('')
        self.v_name.set('')
        self.v_walkable.set(True)
        self.v_covered.set(False)
        self.v_tile_scale.set('1.0')
        self.v_sprite.set('')
        self.sprite_preview.load(None)

    def _populate_form(self, key: str):
        con = get_con()
        try:
            row = con.execute('SELECT * FROM tiles WHERE key=?', (key,)).fetchone()
        finally:
            con.close()
        if row is None:
            return
        self.v_key.set(row['key'])
        self.v_name.set(row['name'] or '')
        self.v_walkable.set(bool(row['walkable']))
        self.v_covered.set(bool(row['covered']))
        self.v_tile_scale.set(str(row['tile_scale'] if row['tile_scale'] is not None else 1.0))
        self.v_sprite.set(row['sprite_name'] or '')
        self.sprite_preview.load(row['sprite_name'] or None)

    def _on_select(self, event=None):
        sel = self.listbox.curselection()
        if sel:
            self._populate_form(self._list_keys[sel[0]])

    def _new(self):
        self.listbox.selection_clear(0, tk.END)
        self._clear_form()

    def _save(self):
        key = self.v_key.get().strip()
        if not key:
            messagebox.showerror('Validation', 'Key is required.')
            return
        try:
            ts = float(self.v_tile_scale.get())
        except ValueError:
            ts = 1.0
        con = get_con()
        try:
            con.execute(
                '''INSERT INTO tiles (key, name, walkable, covered, sprite_name, tile_scale)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                   name=excluded.name, walkable=excluded.walkable,
                   covered=excluded.covered, sprite_name=excluded.sprite_name,
                   tile_scale=excluded.tile_scale''',
                (key, self.v_name.get().strip(), int(self.v_walkable.get()),
                 int(self.v_covered.get()), self.v_sprite.get().strip() or None, ts)
            )
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()
        if key in self._list_keys:
            idx = self._list_keys.index(key)
            self.listbox.selection_set(idx)
            self.listbox.see(idx)

    def _delete(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning('Delete', 'Select a tile first.')
            return
        key = self._list_keys[sel[0]]
        if not messagebox.askyesno('Delete', f'Delete tile "{key}"?'):
            return
        con = get_con()
        try:
            con.execute('DELETE FROM tiles WHERE key=?', (key,))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()
        self._clear_form()
