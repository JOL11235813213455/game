import json
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

from editor.db import get_con, fetch_sprite_names, fetch_map_names
from editor.constants import ITEM_CLASSES, SLOTS, CLASS_FIELDS, PREVIEW_SIZE
from editor.sprite_preview import SpritePreview
from editor.tooltip import add_tooltip


class ItemsTab(ttk.Frame):

    _ALL_FIELDS = [
        'key', 'name', 'description', 'action_word', 'weight', 'value',
        'inventoriable', 'collision', 'tile_scale',
        'max_stack_size', 'quantity', 'duration', 'destroy_on_use_probability',
        'damage', 'slots', 'slot_count', 'durability_max', 'durability_current',
        'render_on_creature', 'requirements', 'attack_time_ms', 'directions',
        'range', 'ammunition_type',
        'footprint', 'collision_mask', 'entry_points', 'nested_map',
        'sprite',
    ]

    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()
        self.refresh_list()

    def _build_ui(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

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
        btn_new = ttk.Button(btn_row, text='New',    command=self._new); btn_new.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_new, 'Clear form to create a new item')
        btn_save = ttk.Button(btn_row, text='Save',   command=self._save); btn_save.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_save, 'Save the current item to the database')
        btn_del = ttk.Button(btn_row, text='Delete', command=self._delete); btn_del.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_del, 'Delete the selected item')

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
        self._rows = {}
        self._tooltips = {}

        def add_row(field, label_text, widget_fn, tip=None):
            lbl = ttk.Label(f, text=label_text)
            frm = ttk.Frame(f)
            widget_fn(frm)
            self._rows[field] = (lbl, frm)
            if tip:
                add_tooltip(frm, tip)

        ttk.Label(f, text='Class', font=('TkDefaultFont', 9, 'bold')).grid(
            row=0, column=0, sticky='w', padx=6, pady=4)
        self.v_class = tk.StringVar(value='item')
        cls_cb = ttk.Combobox(f, textvariable=self.v_class, values=ITEM_CLASSES,
                              state='readonly', width=18)
        cls_cb.grid(row=0, column=1, sticky='w', padx=6, pady=4)
        cls_cb.bind('<<ComboboxSelected>>', lambda e: self._refresh_visible_fields())
        add_tooltip(cls_cb, 'Item type: determines which fields are available')
        self._class_row_count = 1

        self.v_key         = tk.StringVar()
        self.v_name        = tk.StringVar()
        self.v_description = tk.StringVar()
        self.v_weight      = tk.StringVar(value='0')
        self.v_value       = tk.StringVar(value='0')
        self.v_inventoriable = tk.BooleanVar(value=True)
        self.v_collision     = tk.BooleanVar(value=False)

        add_row('key',         'Key',         lambda p: ttk.Entry(p, textvariable=self.v_key, width=30).pack(anchor='w'),
                'Unique identifier for this item (used in code and saves)')
        add_row('name',        'Name',        lambda p: ttk.Entry(p, textvariable=self.v_name, width=30).pack(anchor='w'),
                'Display name shown to the player')
        add_row('description', 'Description', lambda p: ttk.Entry(p, textvariable=self.v_description, width=40).pack(anchor='w'),
                'Flavour text or description shown in inventory')

        self.v_action_word = tk.StringVar()
        add_row('action_word', 'Action Word', lambda p: ttk.Entry(p, textvariable=self.v_action_word, width=20).pack(anchor='w'),
                'Verb for this item (e.g. "slash", "drink", "wear") — used to build action descriptions')

        add_row('weight',      'Weight',      lambda p: ttk.Entry(p, textvariable=self.v_weight, width=10).pack(anchor='w'),
                'Item weight for inventory/encumbrance')
        add_row('value',       'Value',       lambda p: ttk.Entry(p, textvariable=self.v_value, width=10).pack(anchor='w'),
                'Base trade value of this item')
        add_row('inventoriable', 'Inventoriable', lambda p: ttk.Checkbutton(p, variable=self.v_inventoriable).pack(anchor='w'),
                'Whether this item can be picked up and stored in inventory')
        add_row('collision',     'Collision',     lambda p: ttk.Checkbutton(p, variable=self.v_collision).pack(anchor='w'),
                'Whether this item blocks movement when placed in the world')

        self.v_tile_scale = tk.StringVar(value='1.0')
        add_row('tile_scale', 'Tile Scale', lambda p: ttk.Entry(p, textvariable=self.v_tile_scale, width=10).pack(anchor='w'),
                'Visual scale multiplier on the tile (1.0 = normal size)')

        self.v_max_stack   = tk.StringVar(value='99')
        self.v_quantity    = tk.StringVar(value='1')
        add_row('max_stack_size', 'Max Stack',  lambda p: ttk.Entry(p, textvariable=self.v_max_stack, width=10).pack(anchor='w'),
                'Maximum number of items per inventory stack')
        add_row('quantity',       'Quantity',   lambda p: ttk.Entry(p, textvariable=self.v_quantity, width=10).pack(anchor='w'),
                'Default starting quantity when spawned')

        self.v_duration = tk.StringVar(value='0')
        add_row('duration', 'Duration', lambda p: ttk.Entry(p, textvariable=self.v_duration, width=10).pack(anchor='w'),
                'Effect duration in seconds when consumed')

        self.v_destroy_prob = tk.StringVar(value='1.0')
        add_row('destroy_on_use_probability', 'Destroy Prob.', lambda p: ttk.Entry(p, textvariable=self.v_destroy_prob, width=10).pack(anchor='w'),
                'Chance (0.0-1.0) that ammunition is destroyed on use')

        self.v_slot_count       = tk.StringVar(value='1')
        self.v_durability_max   = tk.StringVar(value='100')
        self.v_durability_cur   = tk.StringVar(value='100')
        self.v_render_on_creature = tk.BooleanVar(value=False)

        self.slot_vars: dict[str, tk.BooleanVar] = {s: tk.BooleanVar() for s in SLOTS}
        def _build_slots(p):
            cols = 3
            for i, slot in enumerate(SLOTS):
                ttk.Checkbutton(p, text=slot, variable=self.slot_vars[slot]).grid(
                    row=i // cols, column=i % cols, sticky='w', padx=4)
        add_row('slots',             'Slots',             _build_slots,
                'Equipment slots this item can be equipped in')
        add_row('slot_count',        'Slot Count',        lambda p: ttk.Entry(p, textvariable=self.v_slot_count, width=10).pack(anchor='w'),
                'Number of equipment slots this item occupies')
        add_row('durability_max',    'Durability Max',    lambda p: ttk.Entry(p, textvariable=self.v_durability_max, width=10).pack(anchor='w'),
                'Maximum durability when fully repaired')
        add_row('durability_current','Durability Cur.',   lambda p: ttk.Entry(p, textvariable=self.v_durability_cur, width=10).pack(anchor='w'),
                'Current durability (degrades with use)')
        add_row('render_on_creature','Render on Creature',lambda p: ttk.Checkbutton(p, variable=self.v_render_on_creature).pack(anchor='w'),
                'Whether to visually display this item on the creature sprite')

        self.v_requirements = tk.StringVar(value='{}')
        add_row('requirements', 'Requirements', lambda p: ttk.Entry(p, textvariable=self.v_requirements, width=40).pack(anchor='w'),
                'JSON stat requirements to equip, e.g. {"strength": 12, "agility": 10}')

        self.v_damage         = tk.StringVar(value='0')
        self.v_attack_time    = tk.StringVar(value='500')
        self.v_directions     = tk.StringVar(value='["front"]')
        self.v_range          = tk.StringVar(value='1')
        self.v_ammo_type      = tk.StringVar()
        add_row('damage',         'Damage',         lambda p: ttk.Entry(p, textvariable=self.v_damage, width=10).pack(anchor='w'),
                'Base damage dealt per hit')
        add_row('attack_time_ms', 'Attack Time ms', lambda p: ttk.Entry(p, textvariable=self.v_attack_time, width=10).pack(anchor='w'),
                'Milliseconds between attacks (lower = faster)')
        add_row('directions',     'Directions',     lambda p: ttk.Entry(p, textvariable=self.v_directions, width=30).pack(anchor='w'),
                'JSON list of attack directions, e.g. ["front", "back"]')
        add_row('range',          'Range',          lambda p: ttk.Entry(p, textvariable=self.v_range, width=10).pack(anchor='w'),
                'Attack range in tiles (1 = melee)')
        add_row('ammunition_type','Ammo Type',      lambda p: ttk.Entry(p, textvariable=self.v_ammo_type, width=20).pack(anchor='w'),
                'Name of required ammunition item (blank for no ammo)')

        self.v_footprint      = tk.StringVar(value='[[0,0]]')
        self.v_collision_mask = tk.StringVar(value='[[0,0]]')
        self.v_entry_points   = tk.StringVar(value='{}')
        self.v_nested_map     = tk.StringVar()
        add_row('footprint',      'Footprint (JSON)',      lambda p: ttk.Entry(p, textvariable=self.v_footprint, width=40).pack(anchor='w'),
                'Tile offsets this structure occupies, e.g. [[0,0],[1,0],[0,1],[1,1]]')
        add_row('collision_mask', 'Collision Mask (JSON)', lambda p: ttk.Entry(p, textvariable=self.v_collision_mask, width=40).pack(anchor='w'),
                'Subset of footprint that blocks movement (defaults to full footprint)')
        add_row('entry_points',   'Entry Points (JSON)',   lambda p: ttk.Entry(p, textvariable=self.v_entry_points, width=40).pack(anchor='w'),
                'Map offsets to interior entrances, e.g. {"0,1": [5, 10]}')
        self._map_names = [''] + fetch_map_names()
        def _build_nested_map(p):
            self.nested_map_cb = ttk.Combobox(p, textvariable=self.v_nested_map,
                                              values=self._map_names, state='readonly', width=18)
            self.nested_map_cb.pack(anchor='w')
        add_row('nested_map', 'Nested Map', _build_nested_map,
                'Interior map to enter when interacting with this structure')

        self.v_sprite = tk.StringVar()
        self._sprite_names = [''] + fetch_sprite_names()
        def _build_sprite(p):
            self.sprite_cb = ttk.Combobox(p, textvariable=self.v_sprite,
                                          values=self._sprite_names, state='readonly', width=18)
            self.sprite_cb.pack(side=tk.LEFT, padx=(0, 8))
            self.sprite_preview = SpritePreview(p, size=PREVIEW_SIZE)
            self.sprite_preview.pack(side=tk.LEFT)
            self.sprite_cb.bind('<<ComboboxSelected>>', self._on_sprite_change)
        add_row('sprite', 'Sprite', _build_sprite,
                'Sprite used to display this item in the world')

        f.columnconfigure(1, weight=1)
        self._refresh_visible_fields()

    def _refresh_visible_fields(self):
        cls = self.v_class.get()
        visible = {'key', 'name', 'description', 'weight', 'value', 'inventoriable', 'collision', 'tile_scale', 'sprite'}
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
        self._map_names = [''] + fetch_map_names()
        self.nested_map_cb['values'] = self._map_names

    def _clear_form(self):
        self.v_class.set('Item')
        self.v_key.set('')
        self.v_name.set('')
        self.v_description.set('')
        self.v_action_word.set('')
        self.v_weight.set('0')
        self.v_value.set('0')
        self.v_inventoriable.set(True)
        self.v_collision.set(False)
        self.v_tile_scale.set('1.0')
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
        self.v_requirements.set('{}')
        self.v_damage.set('0')
        self.v_attack_time.set('500')
        self.v_directions.set('["front"]')
        self.v_range.set('1')
        self.v_ammo_type.set('')
        self.v_footprint.set('[[0,0]]')
        self.v_collision_mask.set('[[0,0]]')
        self.v_entry_points.set('{}')
        self.v_nested_map.set('')
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

        self.v_class.set(row['class'] or 'Item')
        self.v_key.set(row['key'])
        self.v_name.set(row['name'] or '')
        self.v_description.set(row['description'] or '')
        self.v_action_word.set(row['action_word'] or '')
        self.v_weight.set(str(row['weight'] or 0))
        self.v_value.set(str(row['value'] or 0))
        self.v_inventoriable.set(bool(row['inventoriable']))
        self.v_collision.set(bool(row['collision']))
        self.v_tile_scale.set(str(row['tile_scale'] if row['tile_scale'] is not None else 1.0))
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
        self.v_requirements.set(row['requirements'] or '{}')
        self.v_damage.set(str(row['damage'] or 0))
        self.v_attack_time.set(str(row['attack_time_ms'] or 500))
        self.v_directions.set(row['directions'] or '["front"]')
        self.v_range.set(str(row['range'] or 1))
        self.v_ammo_type.set(row['ammunition_type'] or '')
        self.v_footprint.set(row['footprint'] or '[[0,0]]')
        self.v_collision_mask.set(row['collision_mask'] or '[[0,0]]')
        self.v_entry_points.set(row['entry_points'] or '{}')
        self.v_nested_map.set(row['nested_map'] or '')
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
                    collision, tile_scale, action_word, requirements,
                    max_stack_size, quantity, duration, destroy_on_use_probability,
                    slot_count, durability_max, durability_current, render_on_creature,
                    damage, attack_time_ms, directions, range, ammunition_type,
                    footprint, collision_mask, entry_points, nested_map)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(key) DO UPDATE SET
                   class=excluded.class, name=excluded.name, description=excluded.description,
                   weight=excluded.weight, value=excluded.value, sprite_name=excluded.sprite_name,
                   inventoriable=excluded.inventoriable, collision=excluded.collision,
                   tile_scale=excluded.tile_scale,
                   action_word=excluded.action_word, requirements=excluded.requirements,
                   max_stack_size=excluded.max_stack_size, quantity=excluded.quantity,
                   duration=excluded.duration,
                   destroy_on_use_probability=excluded.destroy_on_use_probability,
                   slot_count=excluded.slot_count, durability_max=excluded.durability_max,
                   durability_current=excluded.durability_current,
                   render_on_creature=excluded.render_on_creature,
                   damage=excluded.damage, attack_time_ms=excluded.attack_time_ms,
                   directions=excluded.directions, range=excluded.range,
                   ammunition_type=excluded.ammunition_type,
                   footprint=excluded.footprint, collision_mask=excluded.collision_mask,
                   entry_points=excluded.entry_points, nested_map=excluded.nested_map
                ''',
                (
                    cls, key,
                    self.v_name.get().strip(),
                    self.v_description.get().strip(),
                    self._float(self.v_weight),
                    self._float(self.v_value),
                    sprite,
                    int(self.v_inventoriable.get()),
                    int(self.v_collision.get()),
                    self._float(self.v_tile_scale, 1.0),
                    self.v_action_word.get().strip(),
                    self.v_requirements.get().strip() if cls in ('Weapon','Wearable') else '{}',
                    self._int(self.v_max_stack, 99) if cls in ('Consumable','Ammunition') else None,
                    self._int(self.v_quantity, 1)   if cls in ('Consumable','Ammunition') else None,
                    self._float(self.v_duration)    if cls == 'Consumable' else None,
                    self._float(self.v_destroy_prob, 1.0) if cls == 'Ammunition' else None,
                    self._int(self.v_slot_count, 1) if cls in ('Weapon','Wearable') else None,
                    self._int(self.v_durability_max, 100) if cls in ('Weapon','Wearable') else None,
                    self._int(self.v_durability_cur, 100) if cls in ('Weapon','Wearable') else None,
                    int(self.v_render_on_creature.get()) if cls in ('Weapon','Wearable') else None,
                    self._float(self.v_damage)      if cls in ('Weapon','Ammunition') else None,
                    self._int(self.v_attack_time, 500) if cls == 'Weapon' else None,
                    self.v_directions.get().strip() if cls == 'Weapon' else None,
                    self._int(self.v_range, 1)      if cls == 'Weapon' else None,
                    self.v_ammo_type.get().strip() or None if cls == 'Weapon' else None,
                    self.v_footprint.get().strip() if cls == 'Structure' else None,
                    self.v_collision_mask.get().strip() if cls == 'Structure' else None,
                    self.v_entry_points.get().strip() if cls == 'Structure' else None,
                    self.v_nested_map.get().strip() or None if cls == 'Structure' else None,
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
