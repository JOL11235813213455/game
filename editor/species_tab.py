import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

from editor.db import get_con, fetch_sprite_names, fetch_composite_names
from editor.constants import STATS, STAT_LABELS, PREVIEW_SIZE
from editor.sprite_preview import SpritePreview
from editor.tooltip import add_tooltip


class SpeciesTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()
        self.refresh_list()

    def _build_ui(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        left = ttk.Frame(pane, width=180)
        pane.add(left, weight=0)

        ttk.Label(left, text='Species').pack(anchor='w')
        list_frame = ttk.Frame(left)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.listbox = tk.Listbox(list_frame, exportselection=False, width=22)
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.bind('<<ListboxSelect>>', self._on_select)

        btn_row = ttk.Frame(left)
        btn_row.pack(fill=tk.X, pady=4)
        ttk.Button(btn_row, text='New',    command=self._new).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text='Save',   command=self._save).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text='Delete', command=self._delete).pack(side=tk.LEFT, padx=2)

        right = ttk.Frame(pane)
        pane.add(right, weight=1)

        f = right
        row = 0

        ttk.Label(f, text='Name').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_name = tk.StringVar()
        e_name = ttk.Entry(f, textvariable=self.v_name, width=30)
        e_name.grid(row=row, column=1, sticky='ew', padx=6, pady=4)
        add_tooltip(e_name, 'Unique species name')
        row += 1

        self.v_playable = tk.BooleanVar()
        cb_play = ttk.Checkbutton(f, text='Playable', variable=self.v_playable)
        cb_play.grid(row=row, column=0, columnspan=2, sticky='w', padx=6, pady=4)
        add_tooltip(cb_play, 'Whether the player can choose this species')
        row += 1

        ttk.Label(f, text='Sprite').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        sprite_frame = ttk.Frame(f)
        sprite_frame.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        row += 1

        self.v_sprite = tk.StringVar()
        self._sprite_names = [''] + fetch_sprite_names()
        self.sprite_cb = ttk.Combobox(sprite_frame, textvariable=self.v_sprite,
                                      values=self._sprite_names, state='readonly', width=18)
        self.sprite_cb.pack(side=tk.LEFT, padx=(0, 8))
        add_tooltip(self.sprite_cb, 'Default sprite used for creatures of this species')
        self.sprite_preview = SpritePreview(sprite_frame, size=PREVIEW_SIZE)
        self.sprite_preview.pack(side=tk.LEFT)
        self.sprite_cb.bind('<<ComboboxSelected>>', self._on_sprite_change)

        ttk.Label(f, text='Tile Scale').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_tile_scale = tk.StringVar(value='1.0')
        e_scale = ttk.Entry(f, textvariable=self.v_tile_scale, width=10)
        e_scale.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(e_scale, 'Visual scale on the tile (1.0 = normal)')
        row += 1

        ttk.Label(f, text='Composite').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_composite = tk.StringVar()
        self._composite_names = [''] + fetch_composite_names()
        self.composite_cb = ttk.Combobox(f, textvariable=self.v_composite,
                                          values=self._composite_names, state='readonly', width=18)
        self.composite_cb.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(self.composite_cb, 'Optional composite sprite (layered) — overrides simple sprite if set')
        row += 1

        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky='ew', padx=6, pady=6)
        row += 1

        ttk.Label(f, text='Stats (blank = not set)', font=('TkDefaultFont', 9, 'bold')).grid(
            row=row, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        row += 1

        stat_tips = {
            'strength': 'Physical power — affects melee damage',
            'constitution': 'Endurance — affects max HP',
            'intelligence': 'Mental acuity — affects skills and magic',
            'agility': 'Speed and reflexes — affects dodge and move speed',
            'perception': 'Awareness — affects detection and ranged accuracy',
            'charisma': 'Social influence — affects NPC interactions',
            'luck': 'Fortune — affects critical hits and loot',
            'hit dice': 'Base HP dice rolled per level',
        }
        self.stat_vars: dict[str, tk.StringVar] = {}
        for stat in STATS:
            ttk.Label(f, text=STAT_LABELS[stat]).grid(
                row=row, column=0, sticky='w', padx=6, pady=2)
            var = tk.StringVar()
            self.stat_vars[stat] = var
            e_stat = ttk.Entry(f, textvariable=var, width=8)
            e_stat.grid(row=row, column=1, sticky='w', padx=6, pady=2)
            add_tooltip(e_stat, stat_tips.get(stat, f'Base {stat} value'))
            row += 1

        f.columnconfigure(1, weight=1)

    def _on_sprite_change(self, event=None):
        self.sprite_preview.load(self.v_sprite.get() or None)

    def refresh_list(self):
        con = get_con()
        try:
            rows = con.execute('SELECT name FROM species ORDER BY name').fetchall()
        finally:
            con.close()
        self.listbox.delete(0, tk.END)
        for r in rows:
            self.listbox.insert(tk.END, r['name'])

    def refresh_sprite_dropdown(self):
        self._sprite_names = [''] + fetch_sprite_names()
        self.sprite_cb['values'] = self._sprite_names
        self._composite_names = [''] + fetch_composite_names()
        self.composite_cb['values'] = self._composite_names

    def _clear_form(self):
        self.v_name.set('')
        self.v_playable.set(False)
        self.v_sprite.set('')
        self.v_composite.set('')
        self.sprite_preview.load(None)
        self.v_tile_scale.set('1.0')
        for var in self.stat_vars.values():
            var.set('')

    def _populate_form(self, name: str):
        con = get_con()
        try:
            row = con.execute(
                'SELECT name, playable, sprite_name, tile_scale, composite_name FROM species WHERE name=?', (name,)
            ).fetchone()
            if row is None:
                return
            stat_rows = con.execute(
                'SELECT stat, value FROM species_stats WHERE species_name=?', (name,)
            ).fetchall()
        finally:
            con.close()

        self.v_name.set(row['name'])
        self.v_playable.set(bool(row['playable']))
        sprite = row['sprite_name'] or ''
        self.v_sprite.set(sprite)
        self.sprite_preview.load(sprite or None)
        self.v_tile_scale.set(str(row['tile_scale'] if row['tile_scale'] is not None else 1.0))
        self.v_composite.set(row['composite_name'] or '')

        stats = {r['stat']: r['value'] for r in stat_rows}
        for stat, var in self.stat_vars.items():
            val = stats.get(stat)
            var.set(str(val) if val is not None else '')

    def _on_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        self._populate_form(self.listbox.get(sel[0]))

    def _new(self):
        self.listbox.selection_clear(0, tk.END)
        self._clear_form()

    def _save(self):
        name = self.v_name.get().strip()
        if not name:
            messagebox.showerror('Validation', 'Name is required.')
            return

        sprite = self.v_sprite.get().strip() or None
        composite = self.v_composite.get().strip() or None
        playable = int(self.v_playable.get())

        stats = {}
        for stat, var in self.stat_vars.items():
            txt = var.get().strip()
            if txt:
                try:
                    stats[stat] = int(txt)
                except ValueError:
                    messagebox.showerror('Validation', f'Stat {stat}: must be an integer.')
                    return

        con = get_con()
        try:
            try:
                tile_scale = float(self.v_tile_scale.get())
            except ValueError:
                tile_scale = 1.0
            con.execute(
                '''INSERT INTO species (name, playable, sprite_name, tile_scale, composite_name)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                   playable=excluded.playable,
                   sprite_name=excluded.sprite_name,
                   tile_scale=excluded.tile_scale,
                   composite_name=excluded.composite_name
                ''',
                (name, playable, sprite, tile_scale, composite)
            )
            con.execute('DELETE FROM species_stats WHERE species_name=?', (name,))
            for stat, val in stats.items():
                con.execute(
                    'INSERT INTO species_stats VALUES (?, ?, ?)',
                    (name, stat, val)
                )
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()

        self.refresh_list()
        items = list(self.listbox.get(0, tk.END))
        if name in items:
            idx = items.index(name)
            self.listbox.selection_set(idx)
            self.listbox.see(idx)

    def _delete(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning('Delete', 'Select a species first.')
            return
        name = self.listbox.get(sel[0])
        if not messagebox.askyesno('Delete', f'Delete species "{name}"?'):
            return
        con = get_con()
        try:
            con.execute('DELETE FROM species_stats WHERE species_name=?', (name,))
            con.execute('DELETE FROM species WHERE name=?', (name,))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()
        self._clear_form()
