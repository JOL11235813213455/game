import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

from editor.db import get_con, fetch_sprite_names, fetch_animation_names
from editor.constants import PREVIEW_SIZE
from editor.sprite_preview import SpritePreview
from editor.tooltip import add_tooltip


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
        btn_new = ttk.Button(br, text='New',    command=self._new); btn_new.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_new, 'Clear form to create a new tile template')
        btn_save = ttk.Button(br, text='Save',   command=self._save); btn_save.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_save, 'Save the current tile template to the database')
        btn_del = ttk.Button(br, text='Delete', command=self._delete); btn_del.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_del, 'Delete the selected tile template')

        right = ttk.Frame(pane)
        pane.add(right, weight=1)
        f = right
        r = 0

        ttk.Label(f, text='Key').grid(row=r, column=0, sticky='w', padx=6, pady=4)
        self.v_key = tk.StringVar()
        e_key = ttk.Entry(f, textvariable=self.v_key, width=24)
        e_key.grid(row=r, column=1, sticky='ew', padx=6, pady=4)
        add_tooltip(e_key, 'Unique identifier for this tile template')
        r += 1

        ttk.Label(f, text='Name').grid(row=r, column=0, sticky='w', padx=6, pady=4)
        self.v_name = tk.StringVar()
        e_name = ttk.Entry(f, textvariable=self.v_name, width=24)
        e_name.grid(row=r, column=1, sticky='ew', padx=6, pady=4)
        add_tooltip(e_name, 'Display name for this tile type')
        r += 1

        self.v_walkable = tk.BooleanVar(value=True)
        cb_walk = ttk.Checkbutton(f, text='Walkable', variable=self.v_walkable)
        cb_walk.grid(row=r, column=0, columnspan=2, sticky='w', padx=6, pady=4)
        add_tooltip(cb_walk, 'Whether creatures can walk on this tile')
        r += 1

        self.v_covered = tk.BooleanVar(value=False)
        cb_cov = ttk.Checkbutton(f, text='Covered', variable=self.v_covered)
        cb_cov.grid(row=r, column=0, columnspan=2, sticky='w', padx=6, pady=4)
        add_tooltip(cb_cov, 'Whether this tile acts as a roof/ceiling')
        r += 1

        ttk.Label(f, text='Tile Scale').grid(row=r, column=0, sticky='w', padx=6, pady=4)
        self.v_tile_scale = tk.StringVar(value='1.0')
        e_scale = ttk.Entry(f, textvariable=self.v_tile_scale, width=10)
        e_scale.grid(row=r, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(e_scale, 'Visual scale multiplier (1.0 = normal size)')
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
        add_tooltip(self.sprite_cb, 'Sprite used to draw this tile')
        self.sprite_preview = SpritePreview(sf, size=PREVIEW_SIZE)
        self.sprite_preview.pack(side=tk.LEFT)
        self.sprite_cb.bind('<<ComboboxSelected>>', lambda e: self.sprite_preview.load(self.v_sprite.get() or None))

        ttk.Label(f, text='Animation').grid(row=r, column=0, sticky='w', padx=6, pady=4)
        self.v_animation = tk.StringVar()
        self._anim_names = [''] + fetch_animation_names()
        self.anim_cb = ttk.Combobox(f, textvariable=self.v_animation,
                                    values=self._anim_names, state='readonly', width=18)
        self.anim_cb.grid(row=r, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(self.anim_cb, 'Animation to play on this tile (overrides static sprite)')
        r += 1

        ttk.Label(f, text='Speed Modifier').grid(row=r, column=0, sticky='w', padx=6, pady=4)
        self.v_speed_modifier = tk.StringVar(value='1.0')
        e_speed = ttk.Entry(f, textvariable=self.v_speed_modifier, width=10)
        e_speed.grid(row=r, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(e_speed, 'Movement speed multiplier (1.0 = normal, 0.5 = half speed, 2.0 = double)')
        r += 1

        ttk.Label(f, text='BG Color').grid(row=r, column=0, sticky='w', padx=6, pady=4)
        self.v_bg_color = tk.StringVar()
        e_bg = ttk.Entry(f, textvariable=self.v_bg_color, width=10)
        e_bg.grid(row=r, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(e_bg, 'Background fill color as hex RGB (e.g. #3a7a3a). Empty = transparent')
        r += 1

        f.columnconfigure(1, weight=1)

    def refresh_list(self):
        con = get_con()
        try:
            rows = con.execute('SELECT key FROM tile_templates ORDER BY key').fetchall()
        finally:
            con.close()
        self.listbox.delete(0, tk.END)
        self._list_keys = [r['key'] for r in rows]
        for k in self._list_keys:
            self.listbox.insert(tk.END, k)

    def refresh_sprite_dropdown(self):
        self._sprite_names = [''] + fetch_sprite_names()
        self.sprite_cb['values'] = self._sprite_names
        self._anim_names = [''] + fetch_animation_names()
        self.anim_cb['values'] = self._anim_names

    def _clear_form(self):
        self.v_key.set('')
        self.v_name.set('')
        self.v_walkable.set(True)
        self.v_covered.set(False)
        self.v_tile_scale.set('1.0')
        self.v_sprite.set('')
        self.v_animation.set('')
        self.v_speed_modifier.set('1.0')
        self.v_bg_color.set('')
        self.sprite_preview.load(None)

    def _populate_form(self, key: str):
        con = get_con()
        try:
            row = con.execute('SELECT * FROM tile_templates WHERE key=?', (key,)).fetchone()
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
        self.v_animation.set(row['animation_name'] or '')
        self.v_speed_modifier.set(str(row['speed_modifier'] if row['speed_modifier'] is not None else 1.0))
        self.v_bg_color.set(row['bg_color'] or '')
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
            name = self.v_name.get().strip()
            if not name:
                messagebox.showerror('Validation', 'Key or Name is required.')
                return
            parts = name.split()
            base = parts[0].lower() + ''.join(w.capitalize() for w in parts[1:])
            key = base
            if key in self._list_keys:
                i = 2
                while f'{base}{i}' in self._list_keys:
                    i += 1
                key = f'{base}{i}'
            self.v_key.set(key)
        try:
            ts = float(self.v_tile_scale.get())
        except ValueError:
            ts = 1.0
        try:
            sm = float(self.v_speed_modifier.get())
        except ValueError:
            sm = 1.0
        con = get_con()
        try:
            bg = self.v_bg_color.get().strip() or None
            con.execute(
                '''INSERT INTO tile_templates (key, name, walkable, covered, sprite_name,
                   tile_scale, animation_name, speed_modifier, bg_color)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                   name=excluded.name, walkable=excluded.walkable,
                   covered=excluded.covered, sprite_name=excluded.sprite_name,
                   tile_scale=excluded.tile_scale, animation_name=excluded.animation_name,
                   speed_modifier=excluded.speed_modifier, bg_color=excluded.bg_color''',
                (key, self.v_name.get().strip(), int(self.v_walkable.get()),
                 int(self.v_covered.get()), self.v_sprite.get().strip() or None, ts,
                 self.v_animation.get().strip() or None, sm, bg)
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
            con.execute('DELETE FROM tile_templates WHERE key=?', (key,))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()
        self._clear_form()
