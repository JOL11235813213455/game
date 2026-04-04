#!/usr/bin/env python3
"""
Standalone tkinter editor for the pygame RPG game's SQLite database.
Run from any directory:  python editor.py
"""

import sys
import json
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox, colorchooser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

DB_PATH = str(Path(__file__).parent / 'src' / 'data' / 'game.db')

# ---------------------------------------------------------------------------
# Hardcoded enum values (keep editor self-contained)
# ---------------------------------------------------------------------------
ITEM_CLASSES = ['item', 'stackable', 'consumable', 'ammunition', 'equippable', 'weapon', 'wearable']
SLOTS        = ['head', 'neck', 'shoulders', 'chest', 'back', 'wrists', 'hands',
                'waist', 'legs', 'feet', 'ring_l', 'ring_r', 'hand_l', 'hand_r']
STATS        = ['strength', 'constitution', 'intelligence', 'agility',
                'perception', 'charisma', 'luck', 'hit dice']
STAT_LABELS  = {
    'strength':      'STR',
    'constitution':  'CON',
    'intelligence':  'INT',
    'agility':       'AGL',
    'perception':    'PER',
    'charisma':      'CHR',
    'luck':          'LCK',
    'hit dice':      'HD',
}

# Fields shown per item class (in addition to base fields shown for all)
CLASS_FIELDS = {
    'item':        [],
    'stackable':   ['max_stack_size', 'quantity'],
    'consumable':  ['max_stack_size', 'quantity', 'duration'],
    'ammunition':  ['max_stack_size', 'quantity', 'damage', 'destroy_on_use_probability'],
    'equippable':  ['slots', 'slot_count', 'durability_max', 'durability_current', 'render_on_creature'],
    'weapon':      ['slots', 'slot_count', 'durability_max', 'durability_current', 'render_on_creature',
                    'damage', 'attack_time_ms', 'directions', 'range', 'ammunition_type'],
    'wearable':    ['slots', 'slot_count', 'durability_max', 'durability_current', 'render_on_creature'],
}

GRID_COLS    = 8
GRID_ROWS    = 8
CELL_SIZE    = 40          # pixels per grid cell in the sprite editor
PREVIEW_SIZE = 64          # pixels for the small previews on Items/Species tabs
MAX_PALETTE  = 12


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_con() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    return con


def fetch_sprite_names() -> list[str]:
    con = get_con()
    try:
        rows = con.execute('SELECT name FROM sprites ORDER BY name').fetchall()
        return [r['name'] for r in rows]
    finally:
        con.close()


def fetch_sprite(name: str) -> dict | None:
    """Return {'palette': {char: '#rrggbb', ...}, 'pixels': [[...], ...]} or None."""
    if not name:
        return None
    con = get_con()
    try:
        row = con.execute('SELECT palette, pixels FROM sprites WHERE name=?', (name,)).fetchone()
        if row is None:
            return None
        raw_palette = json.loads(row['palette'])
        palette = {}
        for char, val in raw_palette.items():
            if isinstance(val, (list, tuple)):
                r, g, b = val
                palette[char] = f'#{r:02x}{g:02x}{b:02x}'
            else:
                palette[char] = val  # already a hex string
        return {
            'palette': palette,
            'pixels':  json.loads(row['pixels']),
        }
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Sprite preview widget (shared between Items and Species tabs)
# ---------------------------------------------------------------------------

class SpritePreview(tk.Canvas):
    """
    A small canvas that renders an 8×8 sprite at PREVIEW_SIZE × PREVIEW_SIZE pixels.
    Call load(sprite_name) to update.
    """
    TRANSPARENT = '#d0d0d0'   # shown for '.' cells

    def __init__(self, parent, size=PREVIEW_SIZE, **kwargs):
        super().__init__(parent, width=size, height=size,
                         bg=self.TRANSPARENT, highlightthickness=1,
                         highlightbackground='#999', **kwargs)
        self._size = size
        self._cell = size / GRID_COLS
        self._draw_empty()

    def _draw_empty(self):
        self.delete('all')
        # Draw checkerboard for transparent
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
        cs = self._cell
        for row_idx, row_str in enumerate(pixels):
            for col_idx, ch in enumerate(row_str):
                x0 = col_idx * cs
                y0 = row_idx * cs
                x1 = x0 + cs
                y1 = y0 + cs
                if ch == '.' or ch not in palette:
                    # checkerboard
                    color = '#cccccc' if (row_idx + col_idx) % 2 == 0 else '#aaaaaa'
                else:
                    color = palette[ch]
                self.create_rectangle(x0, y0, x1, y1, fill=color, outline='')


# ---------------------------------------------------------------------------
# Items Tab
# ---------------------------------------------------------------------------

class ItemsTab(ttk.Frame):

    # All possible field widgets; shown/hidden based on selected class
    _ALL_FIELDS = [
        'key', 'name', 'description', 'weight', 'value', 'inventoriable',
        'max_stack_size', 'quantity', 'duration', 'destroy_on_use_probability',
        'damage', 'slots', 'slot_count', 'durability_max', 'durability_current',
        'render_on_creature', 'attack_time_ms', 'directions', 'range',
        'ammunition_type', 'sprite',
    ]

    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()
        self.refresh_list()

    def _build_ui(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # --- Left list ---
        left = ttk.Frame(pane, width=200)
        pane.add(left, weight=0)

        ttk.Label(left, text='Items').pack(anchor='w')
        list_frame = ttk.Frame(left)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.listbox = tk.Listbox(list_frame, exportselection=False, width=24)
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

        # --- Right scrollable form ---
        right_outer = ttk.Frame(pane)
        pane.add(right_outer, weight=1)

        canvas = tk.Canvas(right_outer, highlightthickness=0)
        vsb = ttk.Scrollbar(right_outer, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.form = ttk.Frame(canvas)
        self._form_window = canvas.create_window((0, 0), window=self.form, anchor='nw')
        self.form.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfig(self._form_window, width=e.width))

        self._build_form()

    def _build_form(self):
        f = self.form
        self._rows = {}   # field_name → (label_widget, widget_frame)

        def add_row(field, label_text, widget_fn):
            lbl = ttk.Label(f, text=label_text)
            frm = ttk.Frame(f)
            widget_fn(frm)
            self._rows[field] = (lbl, frm)

        # Class selector always visible at top
        ttk.Label(f, text='Class', font=('TkDefaultFont', 9, 'bold')).grid(
            row=0, column=0, sticky='w', padx=6, pady=4)
        self.v_class = tk.StringVar(value='item')
        cls_cb = ttk.Combobox(f, textvariable=self.v_class, values=ITEM_CLASSES,
                              state='readonly', width=18)
        cls_cb.grid(row=0, column=1, sticky='w', padx=6, pady=4)
        cls_cb.bind('<<ComboboxSelected>>', lambda e: self._refresh_visible_fields())
        self._class_row_count = 1

        # Base fields
        self.v_key         = tk.StringVar()
        self.v_name        = tk.StringVar()
        self.v_description = tk.StringVar()
        self.v_weight      = tk.StringVar(value='0')
        self.v_value       = tk.StringVar(value='0')
        self.v_inventoriable = tk.BooleanVar(value=True)

        add_row('key',         'Key',         lambda p: ttk.Entry(p, textvariable=self.v_key, width=30).pack(anchor='w'))
        add_row('name',        'Name',        lambda p: ttk.Entry(p, textvariable=self.v_name, width=30).pack(anchor='w'))
        add_row('description', 'Description', lambda p: ttk.Entry(p, textvariable=self.v_description, width=40).pack(anchor='w'))
        add_row('weight',      'Weight',      lambda p: ttk.Entry(p, textvariable=self.v_weight, width=10).pack(anchor='w'))
        add_row('value',       'Value',       lambda p: ttk.Entry(p, textvariable=self.v_value, width=10).pack(anchor='w'))
        add_row('inventoriable', 'Inventoriable', lambda p: ttk.Checkbutton(p, variable=self.v_inventoriable).pack(anchor='w'))

        # Stackable fields
        self.v_max_stack   = tk.StringVar(value='99')
        self.v_quantity    = tk.StringVar(value='1')
        add_row('max_stack_size', 'Max Stack',  lambda p: ttk.Entry(p, textvariable=self.v_max_stack, width=10).pack(anchor='w'))
        add_row('quantity',       'Quantity',   lambda p: ttk.Entry(p, textvariable=self.v_quantity, width=10).pack(anchor='w'))

        # Consumable
        self.v_duration = tk.StringVar(value='0')
        add_row('duration', 'Duration', lambda p: ttk.Entry(p, textvariable=self.v_duration, width=10).pack(anchor='w'))

        # Ammunition
        self.v_destroy_prob = tk.StringVar(value='1.0')
        add_row('destroy_on_use_probability', 'Destroy Prob.', lambda p: ttk.Entry(p, textvariable=self.v_destroy_prob, width=10).pack(anchor='w'))

        # Equippable fields
        self.v_slot_count       = tk.StringVar(value='1')
        self.v_durability_max   = tk.StringVar(value='100')
        self.v_durability_cur   = tk.StringVar(value='100')
        self.v_render_on_creature = tk.BooleanVar(value=False)

        # Slots — checkboxes
        self.slot_vars: dict[str, tk.BooleanVar] = {s: tk.BooleanVar() for s in SLOTS}
        def _build_slots(p):
            cols = 3
            for i, slot in enumerate(SLOTS):
                ttk.Checkbutton(p, text=slot, variable=self.slot_vars[slot]).grid(
                    row=i // cols, column=i % cols, sticky='w', padx=4)
        add_row('slots',             'Slots',             _build_slots)
        add_row('slot_count',        'Slot Count',        lambda p: ttk.Entry(p, textvariable=self.v_slot_count, width=10).pack(anchor='w'))
        add_row('durability_max',    'Durability Max',    lambda p: ttk.Entry(p, textvariable=self.v_durability_max, width=10).pack(anchor='w'))
        add_row('durability_current','Durability Cur.',   lambda p: ttk.Entry(p, textvariable=self.v_durability_cur, width=10).pack(anchor='w'))
        add_row('render_on_creature','Render on Creature',lambda p: ttk.Checkbutton(p, variable=self.v_render_on_creature).pack(anchor='w'))

        # Weapon fields
        self.v_damage         = tk.StringVar(value='0')
        self.v_attack_time    = tk.StringVar(value='500')
        self.v_directions     = tk.StringVar(value='["front"]')
        self.v_range          = tk.StringVar(value='1')
        self.v_ammo_type      = tk.StringVar()
        add_row('damage',         'Damage',         lambda p: ttk.Entry(p, textvariable=self.v_damage, width=10).pack(anchor='w'))
        add_row('attack_time_ms', 'Attack Time ms', lambda p: ttk.Entry(p, textvariable=self.v_attack_time, width=10).pack(anchor='w'))
        add_row('directions',     'Directions',     lambda p: ttk.Entry(p, textvariable=self.v_directions, width=30).pack(anchor='w'))
        add_row('range',          'Range',          lambda p: ttk.Entry(p, textvariable=self.v_range, width=10).pack(anchor='w'))
        add_row('ammunition_type','Ammo Type',      lambda p: ttk.Entry(p, textvariable=self.v_ammo_type, width=20).pack(anchor='w'))

        # Sprite
        self.v_sprite = tk.StringVar()
        self._sprite_names = [''] + fetch_sprite_names()
        def _build_sprite(p):
            self.sprite_cb = ttk.Combobox(p, textvariable=self.v_sprite,
                                          values=self._sprite_names, state='readonly', width=18)
            self.sprite_cb.pack(side=tk.LEFT, padx=(0, 8))
            self.sprite_preview = SpritePreview(p, size=PREVIEW_SIZE)
            self.sprite_preview.pack(side=tk.LEFT)
            self.sprite_cb.bind('<<ComboboxSelected>>', self._on_sprite_change)
        add_row('sprite', 'Sprite', _build_sprite)

        f.columnconfigure(1, weight=1)
        self._refresh_visible_fields()

    def _refresh_visible_fields(self):
        cls = self.v_class.get()
        visible = {'key', 'name', 'description', 'weight', 'value', 'inventoriable', 'sprite'}
        visible.update(CLASS_FIELDS.get(cls, []))

        row = self._class_row_count
        for field in self._ALL_FIELDS:
            lbl, frm = self._rows[field]
            if field in visible:
                lbl.grid(row=row, column=0, sticky='nw', padx=6, pady=2)
                frm.grid(row=row, column=1, sticky='ew', padx=6, pady=2)
                row += 1
            else:
                lbl.grid_remove()
                frm.grid_remove()

    def _on_sprite_change(self, event=None):
        self.sprite_preview.load(self.v_sprite.get() or None)

    def _float(self, var, default=0.0):
        try:
            return float(var.get())
        except (ValueError, TypeError):
            return default

    def _int(self, var, default=0):
        try:
            return int(var.get())
        except (ValueError, TypeError):
            return default

    def refresh_list(self):
        con = get_con()
        try:
            rows = con.execute('SELECT key, class FROM items ORDER BY class, key').fetchall()
        finally:
            con.close()
        self.listbox.delete(0, tk.END)
        for r in rows:
            self.listbox.insert(tk.END, f"[{r['class']}] {r['key']}")

    def refresh_sprite_dropdown(self):
        self._sprite_names = [''] + fetch_sprite_names()
        self.sprite_cb['values'] = self._sprite_names

    def _clear_form(self):
        self.v_class.set('item')
        self.v_key.set('')
        self.v_name.set('')
        self.v_description.set('')
        self.v_weight.set('0')
        self.v_value.set('0')
        self.v_inventoriable.set(True)
        self.v_max_stack.set('99')
        self.v_quantity.set('1')
        self.v_duration.set('0')
        self.v_destroy_prob.set('1.0')
        for v in self.slot_vars.values():
            v.set(False)
        self.v_slot_count.set('1')
        self.v_durability_max.set('100')
        self.v_durability_cur.set('100')
        self.v_render_on_creature.set(False)
        self.v_damage.set('0')
        self.v_attack_time.set('500')
        self.v_directions.set('["front"]')
        self.v_range.set('1')
        self.v_ammo_type.set('')
        self.v_sprite.set('')
        self.sprite_preview.load(None)
        self._refresh_visible_fields()

    def _populate_form(self, key: str):
        con = get_con()
        try:
            row = con.execute('SELECT * FROM items WHERE key=?', (key,)).fetchone()
            if row is None:
                return
            slot_rows = con.execute('SELECT slot FROM item_slots WHERE item_key=?', (key,)).fetchall()
        finally:
            con.close()

        self.v_class.set(row['class'] or 'item')
        self.v_key.set(row['key'])
        self.v_name.set(row['name'] or '')
        self.v_description.set(row['description'] or '')
        self.v_weight.set(str(row['weight'] or 0))
        self.v_value.set(str(row['value'] or 0))
        self.v_inventoriable.set(bool(row['inventoriable']))
        self.v_max_stack.set(str(row['max_stack_size'] or 99))
        self.v_quantity.set(str(row['quantity'] or 1))
        self.v_duration.set(str(row['duration'] or 0))
        self.v_destroy_prob.set(str(row['destroy_on_use_probability'] or 1.0))
        item_slots = {r['slot'] for r in slot_rows}
        for slot, var in self.slot_vars.items():
            var.set(slot in item_slots)
        self.v_slot_count.set(str(row['slot_count'] or 1))
        self.v_durability_max.set(str(row['durability_max'] or 100))
        self.v_durability_cur.set(str(row['durability_current'] or 100))
        self.v_render_on_creature.set(bool(row['render_on_creature'] or False))
        self.v_damage.set(str(row['damage'] or 0))
        self.v_attack_time.set(str(row['attack_time_ms'] or 500))
        self.v_directions.set(row['directions'] or '["front"]')
        self.v_range.set(str(row['range'] or 1))
        self.v_ammo_type.set(row['ammunition_type'] or '')
        sprite = row['sprite_name'] or ''
        self.v_sprite.set(sprite)
        self.sprite_preview.load(sprite or None)
        self._refresh_visible_fields()

    def _on_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        entry = self.listbox.get(sel[0])
        key = entry.split('] ', 1)[-1]
        self._populate_form(key)

    def _new(self):
        self.listbox.selection_clear(0, tk.END)
        self._clear_form()

    def _save(self):
        key = self.v_key.get().strip()
        if not key:
            messagebox.showerror('Validation', 'Key is required.')
            return
        selected_slots = [s for s, v in self.slot_vars.items() if v.get()]
        sprite = self.v_sprite.get().strip() or None
        cls = self.v_class.get()
        con = get_con()
        try:
            con.execute(
                '''INSERT INTO items
                   (class, key, name, description, weight, value, sprite_name, inventoriable,
                    max_stack_size, quantity, duration, destroy_on_use_probability,
                    slot_count, durability_max, durability_current, render_on_creature,
                    damage, attack_time_ms, directions, range, ammunition_type)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(key) DO UPDATE SET
                   class=excluded.class, name=excluded.name, description=excluded.description,
                   weight=excluded.weight, value=excluded.value, sprite_name=excluded.sprite_name,
                   inventoriable=excluded.inventoriable,
                   max_stack_size=excluded.max_stack_size, quantity=excluded.quantity,
                   duration=excluded.duration,
                   destroy_on_use_probability=excluded.destroy_on_use_probability,
                   slot_count=excluded.slot_count, durability_max=excluded.durability_max,
                   durability_current=excluded.durability_current,
                   render_on_creature=excluded.render_on_creature,
                   damage=excluded.damage, attack_time_ms=excluded.attack_time_ms,
                   directions=excluded.directions, range=excluded.range,
                   ammunition_type=excluded.ammunition_type
                ''',
                (
                    cls, key,
                    self.v_name.get().strip(),
                    self.v_description.get().strip(),
                    self._float(self.v_weight),
                    self._float(self.v_value),
                    sprite,
                    int(self.v_inventoriable.get()),
                    self._int(self.v_max_stack, 99) if cls in ('stackable','consumable','ammunition') else None,
                    self._int(self.v_quantity, 1)   if cls in ('stackable','consumable','ammunition') else None,
                    self._float(self.v_duration)    if cls == 'consumable' else None,
                    self._float(self.v_destroy_prob, 1.0) if cls == 'ammunition' else None,
                    self._int(self.v_slot_count, 1) if cls in ('equippable','weapon','wearable') else None,
                    self._int(self.v_durability_max, 100) if cls in ('equippable','weapon','wearable') else None,
                    self._int(self.v_durability_cur, 100) if cls in ('equippable','weapon','wearable') else None,
                    int(self.v_render_on_creature.get()) if cls in ('equippable','weapon','wearable') else None,
                    self._float(self.v_damage)      if cls in ('weapon','ammunition') else None,
                    self._int(self.v_attack_time, 500) if cls == 'weapon' else None,
                    self.v_directions.get().strip() if cls == 'weapon' else None,
                    self._int(self.v_range, 1)      if cls == 'weapon' else None,
                    self.v_ammo_type.get().strip() or None if cls == 'weapon' else None,
                )
            )
            con.execute('DELETE FROM item_slots WHERE item_key=?', (key,))
            for slot in selected_slots:
                con.execute('INSERT INTO item_slots VALUES (?, ?)', (key, slot))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()

        self.refresh_list()
        entries = list(self.listbox.get(0, tk.END))
        target = f'[{cls}] {key}'
        if target in entries:
            idx = entries.index(target)
            self.listbox.selection_set(idx)
            self.listbox.see(idx)

    def _delete(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning('Delete', 'Select an item first.')
            return
        entry = self.listbox.get(sel[0])
        key = entry.split('] ', 1)[-1]
        if not messagebox.askyesno('Delete', f'Delete item "{key}"?'):
            return
        con = get_con()
        try:
            con.execute('DELETE FROM item_slots WHERE item_key=?', (key,))
            con.execute('DELETE FROM items WHERE key=?', (key,))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()
        self._clear_form()


# ---------------------------------------------------------------------------
# Species Tab
# ---------------------------------------------------------------------------

class SpeciesTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()
        self.refresh_list()

    def _build_ui(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # --- Left list ---
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

        # --- Right form ---
        right = ttk.Frame(pane)
        pane.add(right, weight=1)

        f = right
        row = 0

        # Name
        ttk.Label(f, text='Name').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_name = tk.StringVar()
        ttk.Entry(f, textvariable=self.v_name, width=30).grid(
            row=row, column=1, sticky='ew', padx=6, pady=4)
        row += 1

        # Playable
        self.v_playable = tk.BooleanVar()
        ttk.Checkbutton(f, text='Playable', variable=self.v_playable).grid(
            row=row, column=0, columnspan=2, sticky='w', padx=6, pady=4)
        row += 1

        # Sprite selector + preview
        ttk.Label(f, text='Sprite').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        sprite_frame = ttk.Frame(f)
        sprite_frame.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        row += 1

        self.v_sprite = tk.StringVar()
        self._sprite_names = [''] + fetch_sprite_names()
        self.sprite_cb = ttk.Combobox(sprite_frame, textvariable=self.v_sprite,
                                      values=self._sprite_names, state='readonly', width=18)
        self.sprite_cb.pack(side=tk.LEFT, padx=(0, 8))
        self.sprite_preview = SpritePreview(sprite_frame, size=PREVIEW_SIZE)
        self.sprite_preview.pack(side=tk.LEFT)
        self.sprite_cb.bind('<<ComboboxSelected>>', self._on_sprite_change)

        # Stats section
        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky='ew', padx=6, pady=6)
        row += 1

        ttk.Label(f, text='Stats (blank = not set)', font=('TkDefaultFont', 9, 'bold')).grid(
            row=row, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        row += 1

        self.stat_vars: dict[str, tk.StringVar] = {}
        for stat in STATS:
            ttk.Label(f, text=STAT_LABELS[stat]).grid(
                row=row, column=0, sticky='w', padx=6, pady=2)
            var = tk.StringVar()
            self.stat_vars[stat] = var
            ttk.Entry(f, textvariable=var, width=8).grid(
                row=row, column=1, sticky='w', padx=6, pady=2)
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

    def _clear_form(self):
        self.v_name.set('')
        self.v_playable.set(False)
        self.v_sprite.set('')
        self.sprite_preview.load(None)
        for var in self.stat_vars.values():
            var.set('')

    def _populate_form(self, name: str):
        con = get_con()
        try:
            row = con.execute(
                'SELECT name, playable, sprite_name FROM species WHERE name=?', (name,)
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
            con.execute(
                '''INSERT INTO species (name, playable, sprite_name)
                   VALUES (?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                   playable=excluded.playable,
                   sprite_name=excluded.sprite_name
                ''',
                (name, playable, sprite)
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


# ---------------------------------------------------------------------------
# Sprites Tab
# ---------------------------------------------------------------------------

class SpritesTab(ttk.Frame):
    """
    Full sprite editor: 8×8 pixel grid with a per-sprite palette.
    """

    TRANSPARENT_CHAR = '.'
    CHECKER_A        = '#cccccc'
    CHECKER_B        = '#aaaaaa'
    CELL_PX          = CELL_SIZE   # 40 px per cell → 320×320 grid

    def __init__(self, parent, on_sprites_changed=None):
        super().__init__(parent)
        self.on_sprites_changed = on_sprites_changed  # callback when sprite list changes

        # Working state
        self._pixels: list[list[str]] = self._empty_pixels()
        self._palette: dict[str, str] = {}          # char → '#rrggbb'
        self._selected_char: str | None = None       # currently active palette char
        self._palette_widgets: list[dict] = []       # list of widget dicts per entry

        self._build_ui()
        self.refresh_list()

    # ---- layout -----------------------------------------------------------

    def _build_ui(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # --- Left list ---
        left = ttk.Frame(pane, width=160)
        pane.add(left, weight=0)

        ttk.Label(left, text='Sprites').pack(anchor='w')
        list_frame = ttk.Frame(left)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.listbox = tk.Listbox(list_frame, exportselection=False, width=20)
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

        # --- Right panel ---
        right_outer = ttk.Frame(pane)
        pane.add(right_outer, weight=1)

        # Scrollable right panel
        right_canvas = tk.Canvas(right_outer, highlightthickness=0)
        right_sb = ttk.Scrollbar(right_outer, orient=tk.VERTICAL, command=right_canvas.yview)
        right_canvas.configure(yscrollcommand=right_sb.set)
        right_sb.pack(side=tk.RIGHT, fill=tk.Y)
        right_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right = ttk.Frame(right_canvas)
        self._right_win = right_canvas.create_window((0, 0), window=right, anchor='nw')

        def _on_right_configure(e):
            right_canvas.configure(scrollregion=right_canvas.bbox('all'))
        def _on_rc_configure(e):
            right_canvas.itemconfig(self._right_win, width=e.width)

        right.bind('<Configure>', _on_right_configure)
        right_canvas.bind('<Configure>', _on_rc_configure)

        # Bind mousewheel to scroll
        def _on_mousewheel(e):
            right_canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units')
        right_canvas.bind_all('<MouseWheel>', _on_mousewheel)

        # Name field
        name_row = ttk.Frame(right)
        name_row.pack(fill=tk.X, padx=6, pady=6)
        ttk.Label(name_row, text='Name:').pack(side=tk.LEFT)
        self.v_name = tk.StringVar()
        ttk.Entry(name_row, textvariable=self.v_name, width=24).pack(side=tk.LEFT, padx=6)

        # Grid + palette side by side
        editor_row = ttk.Frame(right)
        editor_row.pack(fill=tk.X, padx=6, pady=4)

        # Pixel grid canvas
        grid_size = self.CELL_PX * GRID_COLS
        self.grid_canvas = tk.Canvas(
            editor_row,
            width=grid_size,
            height=grid_size,
            bg='white',
            cursor='crosshair',
        )
        self.grid_canvas.pack(side=tk.LEFT, anchor='n')
        self.grid_canvas.bind('<Button-1>', self._on_grid_click)
        self.grid_canvas.bind('<B1-Motion>', self._on_grid_drag)
        self.grid_canvas.bind('<Button-3>', self._on_grid_erase)
        self.grid_canvas.bind('<B3-Motion>', self._on_grid_erase)

        # Draw initial empty grid
        self._draw_grid()

        # Palette panel (right of grid)
        palette_outer = ttk.Frame(editor_row)
        palette_outer.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0), anchor='n')

        ttk.Label(palette_outer, text='Palette', font=('TkDefaultFont', 10, 'bold')).pack(anchor='w')

        self._selected_label = ttk.Label(
            palette_outer, text='Selected: (none)', foreground='#555'
        )
        self._selected_label.pack(anchor='w', pady=(0, 4))

        # Palette entries container
        self.palette_frame = ttk.Frame(palette_outer)
        self.palette_frame.pack(fill=tk.X)

        ttk.Button(palette_outer, text='+ Add Palette Entry',
                   command=self._add_palette_entry).pack(anchor='w', pady=4)

    # ---- pixel grid -------------------------------------------------------

    def _empty_pixels(self) -> list[list[str]]:
        return [['.' for _ in range(GRID_COLS)] for _ in range(GRID_ROWS)]

    def _draw_grid(self):
        self.grid_canvas.delete('all')
        cp = self.CELL_PX
        for row in range(GRID_ROWS):
            for col in range(GRID_COLS):
                x0 = col * cp
                y0 = row * cp
                x1 = x0 + cp
                y1 = y0 + cp
                ch = self._pixels[row][col]
                if ch == self.TRANSPARENT_CHAR or ch not in self._palette:
                    # Checkerboard
                    color = self.CHECKER_A if (row + col) % 2 == 0 else self.CHECKER_B
                else:
                    color = self._palette[ch]
                tag = f'cell_{row}_{col}'
                self.grid_canvas.create_rectangle(
                    x0, y0, x1, y1,
                    fill=color, outline='#888888', width=1,
                    tags=tag,
                )

    def _cell_from_event(self, event) -> tuple[int, int] | None:
        col = event.x // self.CELL_PX
        row = event.y // self.CELL_PX
        if 0 <= row < GRID_ROWS and 0 <= col < GRID_COLS:
            return row, col
        return None

    def _paint_cell(self, row: int, col: int):
        """Assign the currently selected palette char to this cell and redraw it."""
        if self._selected_char is None:
            return
        self._pixels[row][col] = self._selected_char
        cp = self.CELL_PX
        x0 = col * cp
        y0 = row * cp
        x1 = x0 + cp
        y1 = y0 + cp
        tag = f'cell_{row}_{col}'
        self.grid_canvas.delete(tag)
        ch = self._selected_char
        if ch == self.TRANSPARENT_CHAR or ch not in self._palette:
            color = self.CHECKER_A if (row + col) % 2 == 0 else self.CHECKER_B
        else:
            color = self._palette[ch]
        self.grid_canvas.create_rectangle(
            x0, y0, x1, y1,
            fill=color, outline='#888888', width=1,
            tags=tag,
        )

    def _on_grid_click(self, event):
        cell = self._cell_from_event(event)
        if cell:
            self._paint_cell(*cell)

    def _on_grid_drag(self, event):
        cell = self._cell_from_event(event)
        if cell:
            self._paint_cell(*cell)

    def _on_grid_erase(self, event):
        cell = self._cell_from_event(event)
        if cell:
            row, col = cell
            self._pixels[row][col] = self.TRANSPARENT_CHAR
            cp = self.CELL_PX
            x0, y0 = col * cp, row * cp
            tag = f'cell_{row}_{col}'
            self.grid_canvas.delete(tag)
            color = self.CHECKER_A if (row + col) % 2 == 0 else self.CHECKER_B
            self.grid_canvas.create_rectangle(
                x0, y0, x0 + cp, y0 + cp,
                fill=color, outline='#888888', width=1,
                tags=tag,
            )

    # ---- palette ----------------------------------------------------------

    def _rebuild_palette_widgets(self):
        """Destroy and re-create all palette entry rows from self._palette."""
        for w in self._palette_widgets:
            w['frame'].destroy()
        self._palette_widgets = []

        for char, color in list(self._palette.items()):
            self._create_palette_row(char, color)

    def _create_palette_row(self, char: str, color: str):
        idx = len(self._palette_widgets)
        frame = ttk.Frame(self.palette_frame)
        frame.pack(fill=tk.X, pady=2)

        # "Selected" radio indicator — clicking the row selects it
        select_btn = tk.Button(
            frame, text='  ', relief=tk.RAISED, width=2,
            bg='#e0e0e0',
        )
        select_btn.pack(side=tk.LEFT, padx=(0, 4))

        # Letter input
        char_var = tk.StringVar(value=char)
        char_entry = ttk.Entry(frame, textvariable=char_var, width=3)
        char_entry.pack(side=tk.LEFT, padx=(0, 4))

        # Color swatch
        swatch = tk.Button(
            frame, bg=color, width=3, relief=tk.RAISED,
        )
        swatch.pack(side=tk.LEFT, padx=(0, 4))

        # Delete button
        del_btn = ttk.Button(frame, text='✕', width=2)
        del_btn.pack(side=tk.LEFT, padx=(0, 4))

        entry = {
            'frame':      frame,
            'char_var':   char_var,
            'color':      color,
            'select_btn': select_btn,
            'swatch':     swatch,
            'char':       char,        # original char key
        }
        self._palette_widgets.append(entry)
        local_idx = idx  # capture for closures

        def on_select(e=None, w=entry):
            self._select_palette_entry(w)

        def on_char_change(*args, w=entry, cv=char_var):
            new_char = cv.get()
            if len(new_char) == 1 and new_char != '.':
                old_char = w['char']
                if new_char != old_char and new_char not in self._palette:
                    # Rename key in palette and pixels
                    self._palette[new_char] = self._palette.pop(old_char)
                    for r in range(GRID_ROWS):
                        for c in range(GRID_COLS):
                            if self._pixels[r][c] == old_char:
                                self._pixels[r][c] = new_char
                    w['char'] = new_char
                    if self._selected_char == old_char:
                        self._selected_char = new_char
                        self._update_selected_label()

        def on_swatch_click(e=None, w=entry):
            initial = w['color']
            result = colorchooser.askcolor(color=initial, title='Choose color')
            if result and result[1]:
                new_color = result[1]
                w['color'] = new_color
                w['swatch'].configure(bg=new_color)
                ch = w['char']
                self._palette[ch] = new_color
                self._draw_grid()

        def on_delete(e=None, w=entry):
            ch = w['char']
            self._palette.pop(ch, None)
            if self._selected_char == ch:
                self._selected_char = None
                self._update_selected_label()
            # Replace pixels with transparent
            for r in range(GRID_ROWS):
                for c in range(GRID_COLS):
                    if self._pixels[r][c] == ch:
                        self._pixels[r][c] = '.'
            self._draw_grid()
            self._rebuild_palette_widgets()

        select_btn.configure(command=on_select)
        char_var.trace_add('write', on_char_change)
        swatch.configure(command=on_swatch_click)
        del_btn.configure(command=on_delete)

        # Make clicking anywhere on frame select it
        frame.bind('<Button-1>', on_select)

    def _select_palette_entry(self, entry: dict):
        self._selected_char = entry['char']
        self._update_selected_label()
        # Visually highlight
        for w in self._palette_widgets:
            w['select_btn'].configure(relief=tk.RAISED, bg='#e0e0e0')
        entry['select_btn'].configure(relief=tk.SUNKEN, bg='#a0c8f0')

    def _update_selected_label(self):
        if self._selected_char is None:
            self._selected_label.configure(text='Selected: (none)')
        elif self._selected_char == self.TRANSPARENT_CHAR:
            self._selected_label.configure(text='Selected: . (transparent)')
        else:
            color = self._palette.get(self._selected_char, '?')
            self._selected_label.configure(
                text=f'Selected: {self._selected_char}  {color}'
            )

    def _add_palette_entry(self):
        if len(self._palette) >= MAX_PALETTE:
            messagebox.showwarning('Palette', f'Maximum {MAX_PALETTE} palette entries.')
            return
        # Find an unused letter
        used = set(self._palette.keys()) | {self.TRANSPARENT_CHAR}
        new_char = None
        for ch in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789':
            if ch not in used:
                new_char = ch
                break
        if new_char is None:
            messagebox.showwarning('Palette', 'No available single characters.')
            return
        self._palette[new_char] = '#ffffff'
        self._create_palette_row(new_char, '#ffffff')

    # ---- list management --------------------------------------------------

    def refresh_list(self):
        con = get_con()
        try:
            rows = con.execute('SELECT name FROM sprites ORDER BY name').fetchall()
        finally:
            con.close()
        self.listbox.delete(0, tk.END)
        for r in rows:
            self.listbox.insert(tk.END, r['name'])

    def _clear_editor(self):
        self.v_name.set('')
        self._pixels = self._empty_pixels()
        self._palette = {}
        self._selected_char = None
        self._update_selected_label()
        self._draw_grid()
        self._rebuild_palette_widgets()

    def _load_sprite(self, name: str):
        con = get_con()
        try:
            row = con.execute(
                'SELECT name, palette, pixels FROM sprites WHERE name=?', (name,)
            ).fetchone()
            if row is None:
                return
        finally:
            con.close()

        self.v_name.set(row['name'])
        raw_palette = json.loads(row['palette'])
        self._palette = {}
        for char, val in raw_palette.items():
            if isinstance(val, (list, tuple)):
                r2, g2, b2 = val
                self._palette[char] = f'#{r2:02x}{g2:02x}{b2:02x}'
            else:
                self._palette[char] = val

        raw_pixels = json.loads(row['pixels'])
        self._pixels = [list(r) for r in raw_pixels]
        # Pad/trim to GRID_ROWS × GRID_COLS just in case
        while len(self._pixels) < GRID_ROWS:
            self._pixels.append(['.'] * GRID_COLS)
        for r in self._pixels:
            while len(r) < GRID_COLS:
                r.append('.')

        self._selected_char = None
        self._update_selected_label()
        self._draw_grid()
        self._rebuild_palette_widgets()

    def _on_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        self._load_sprite(self.listbox.get(sel[0]))

    def _new(self):
        self.listbox.selection_clear(0, tk.END)
        self._clear_editor()

    def _save(self):
        name = self.v_name.get().strip()
        if not name:
            messagebox.showerror('Validation', 'Sprite name is required.')
            return

        # Build palette JSON: store as {char: [r, g, b]}
        palette_out = {}
        for char, hexcolor in self._palette.items():
            hexcolor = hexcolor.lstrip('#')
            r = int(hexcolor[0:2], 16)
            g = int(hexcolor[2:4], 16)
            b = int(hexcolor[4:6], 16)
            palette_out[char] = [r, g, b]

        # Build pixels JSON: list of strings
        pixels_out = [''.join(row) for row in self._pixels]

        con = get_con()
        try:
            con.execute(
                '''INSERT INTO sprites (name, palette, pixels)
                   VALUES (?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                   palette=excluded.palette,
                   pixels=excluded.pixels
                ''',
                (name, json.dumps(palette_out), json.dumps(pixels_out))
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

        if self.on_sprites_changed:
            self.on_sprites_changed()

    def _delete(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning('Delete', 'Select a sprite first.')
            return
        name = self.listbox.get(sel[0])
        if not messagebox.askyesno('Delete', f'Delete sprite "{name}"?'):
            return
        con = get_con()
        try:
            con.execute('DELETE FROM sprites WHERE name=?', (name,))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()
        self._clear_editor()
        if self.on_sprites_changed:
            self.on_sprites_changed()


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class EditorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('RPG Database Editor')
        self.minsize(1000, 700)
        self.geometry('1200x800')

        style = ttk.Style(self)
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass

        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.items_tab   = ItemsTab(notebook)
        self.species_tab = SpeciesTab(notebook)
        self.sprites_tab = SpritesTab(notebook, on_sprites_changed=self._on_sprites_changed)

        notebook.add(self.items_tab,   text='  Items  ')
        notebook.add(self.species_tab, text='  Species  ')
        notebook.add(self.sprites_tab, text='  Sprites  ')

        # When the Sprites tab changes, update sprite dropdowns on other tabs
        notebook.bind('<<NotebookTabChanged>>', self._on_tab_changed)

    def _on_sprites_changed(self):
        """Called when sprites are added/renamed/deleted — refresh dropdowns."""
        self.items_tab.refresh_sprite_dropdown()
        self.species_tab.refresh_sprite_dropdown()

    def _on_tab_changed(self, event):
        # Refresh sprite dropdowns whenever user switches to Items or Species tabs,
        # in case sprites were edited in the meantime.
        tab = event.widget.tab(event.widget.select(), 'text').strip()
        if tab in ('Items', 'Species'):
            self.items_tab.refresh_sprite_dropdown()
            self.species_tab.refresh_sprite_dropdown()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    app = EditorApp()
    app.mainloop()
