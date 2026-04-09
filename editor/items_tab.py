"""
Items editor — sub-tabbed by item class.

Each item type gets its own sub-tab with a dedicated listbox,
save/delete/new buttons, and type-specific fields.
Equippables and consumables get per-stat modifier entry widgets.
"""
import json
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

from editor.db import get_con, fetch_sprite_names, fetch_map_names
from editor.constants import SLOTS, PREVIEW_SIZE, STATS, STAT_LABELS
from editor.sprite_preview import SpritePreview
from editor.tooltip import add_tooltip


# All stat values for the buff/modifier widgets
_BUFF_STATS = [
    ('strength', 'STR'), ('vitality', 'VIT'), ('intelligence', 'INT'),
    ('agility', 'AGL'), ('perception', 'PER'), ('charisma', 'CHR'),
    ('luck', 'LCK'),
    ('max health', 'HP_MAX'), ('max stamina', 'MAX_STAM'), ('max mana', 'MAX_MANA'),
    ('armor', 'ARMOR'), ('dodge', 'DODGE'), ('block', 'BLOCK'),
    ('melee damage', 'MELEE_DMG'), ('ranged damage', 'RANGED_DMG'),
    ('magic damage', 'MAGIC_DMG'), ('accuracy', 'ACCURACY'),
    ('critical chance', 'CRIT%'), ('critical damage', 'CRIT_DMG'),
    ('move speed', 'SPEED'), ('stealth', 'STEALTH'), ('detection', 'DETECT'),
    ('carry weight', 'CARRY'), ('sight range', 'SIGHT'),
    ('poison resist', 'P_RES'), ('magic resist', 'M_RES'),
    ('stagger resist', 'STA_RES'), ('fear resist', 'F_RES'),
    ('stamina regen', 'ST_REG'), ('mana regen', 'MA_REG'),
    ('persuasion', 'PERS'), ('intimidation', 'INTIM'), ('deception', 'DECEP'),
    ('loot gini', 'LOOT'), ('craft quality', 'CRAFT'),
]


class _ItemSubTab(ttk.Frame):
    """Base class for each item type sub-tab."""

    item_class = 'Item'  # override in subclasses

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._build()
        self.refresh_list()

    def _build(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # -- Left: listbox --
        left = ttk.Frame(pane, width=200)
        pane.add(left, weight=0)

        list_frame = ttk.Frame(left)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(list_frame, exportselection=False, width=22)
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.bind('<<ListboxSelect>>', self._on_select)
        self.listbox.bind('<Shift-Delete>', lambda e: self._delete())

        btn_row = ttk.Frame(left)
        btn_row.pack(fill=tk.X, pady=4)
        b = ttk.Button(btn_row, text='New', command=self._new)
        b.pack(side=tk.LEFT, padx=2); add_tooltip(b, 'Clear form for new item')
        b = ttk.Button(btn_row, text='Save', command=self._save)
        b.pack(side=tk.LEFT, padx=2); add_tooltip(b, 'Save to database')
        b = ttk.Button(btn_row, text='Delete', command=self._delete)
        b.pack(side=tk.LEFT, padx=2); add_tooltip(b, 'Delete selected item')

        # -- Right: scrollable form --
        right = ttk.Frame(pane)
        pane.add(right, weight=1)

        canvas = tk.Canvas(right, highlightthickness=0)
        vsb = ttk.Scrollbar(right, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.form = ttk.Frame(canvas)
        self._form_win = canvas.create_window((0, 0), window=self.form, anchor='nw')
        self.form.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfig(self._form_win, width=e.width))

        self._row = 0
        self._build_common()
        self._build_specific()
        self.form.columnconfigure(1, weight=1)

    # -- Common fields (all item types) --
    def _add(self, label, widget_fn, tip=None):
        ttk.Label(self.form, text=label).grid(row=self._row, column=0, sticky='w', padx=6, pady=2)
        frm = ttk.Frame(self.form)
        frm.grid(row=self._row, column=1, sticky='ew', padx=6, pady=2)
        widget_fn(frm)
        if tip:
            add_tooltip(frm, tip)
        self._row += 1

    def _build_common(self):
        self.v_key = tk.StringVar()
        self._add('Key', lambda p: ttk.Entry(p, textvariable=self.v_key, width=30).pack(anchor='w'),
                  'Unique identifier')
        self.v_name = tk.StringVar()
        self._add('Name', lambda p: ttk.Entry(p, textvariable=self.v_name, width=30).pack(anchor='w'),
                  'Display name')
        self.v_description = tk.StringVar()
        self._add('Description', lambda p: ttk.Entry(p, textvariable=self.v_description, width=40).pack(anchor='w'),
                  'Flavour text')
        self.v_action_word = tk.StringVar()
        self._add('Action Word', lambda p: ttk.Entry(p, textvariable=self.v_action_word, width=20).pack(anchor='w'),
                  'Verb (e.g. slash, drink, wear)')
        self.v_weight = tk.StringVar(value='0')
        self._add('Weight', lambda p: ttk.Entry(p, textvariable=self.v_weight, width=10).pack(anchor='w'),
                  'Item weight')
        self.v_value = tk.StringVar(value='0')
        self._add('Value', lambda p: ttk.Entry(p, textvariable=self.v_value, width=10).pack(anchor='w'),
                  'Base gold value')
        self.v_inventoriable = tk.BooleanVar(value=True)
        self._add('Inventoriable', lambda p: ttk.Checkbutton(p, variable=self.v_inventoriable).pack(anchor='w'),
                  'Can be picked up')
        self.v_collision = tk.BooleanVar(value=False)
        self._add('Collision', lambda p: ttk.Checkbutton(p, variable=self.v_collision).pack(anchor='w'),
                  'Blocks movement')
        self.v_tile_scale = tk.StringVar(value='1.0')
        self._add('Tile Scale', lambda p: ttk.Entry(p, textvariable=self.v_tile_scale, width=10).pack(anchor='w'),
                  'Visual scale')

        # Sprite
        self.v_sprite = tk.StringVar()
        self._sprite_names = [''] + fetch_sprite_names()
        def _build_sprite(p):
            self._sprite_cb = ttk.Combobox(p, textvariable=self.v_sprite,
                                           values=self._sprite_names, state='readonly', width=18)
            self._sprite_cb.pack(side=tk.LEFT, padx=(0, 8))
            self._sprite_preview = SpritePreview(p, size=PREVIEW_SIZE)
            self._sprite_preview.pack(side=tk.LEFT)
            self._sprite_cb.bind('<<ComboboxSelected>>',
                                 lambda e: self._sprite_preview.load(self.v_sprite.get() or None))
        self._add('Sprite', _build_sprite, 'Visual sprite')

    def _build_specific(self):
        """Override in subclasses to add type-specific fields."""
        pass

    def _build_buffs_section(self, title='Stat Modifiers', show_req=True):
        """Build per-stat [Req] [Mod] table. Used by equippables + consumables."""
        ttk.Separator(self.form, orient=tk.HORIZONTAL).grid(
            row=self._row, column=0, columnspan=2, sticky='ew', padx=6, pady=6)
        self._row += 1
        ttk.Label(self.form, text=title, font=('TkDefaultFont', 9, 'bold')).grid(
            row=self._row, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        self._row += 1

        self._buff_vars = {}
        self._req_vars = {}
        stat_frame = ttk.Frame(self.form)
        stat_frame.grid(row=self._row, column=0, columnspan=2, sticky='ew', padx=6, pady=2)
        self._row += 1

        # Header
        cols_per_group = 4 if show_req else 3
        ttk.Label(stat_frame, text='Stat', width=7, font=('TkDefaultFont', 8, 'bold')).grid(row=0, column=0, padx=2)
        if show_req:
            ttk.Label(stat_frame, text='Req', width=4, font=('TkDefaultFont', 8, 'bold')).grid(row=0, column=1, padx=2)
        ttk.Label(stat_frame, text='Mod', width=4, font=('TkDefaultFont', 8, 'bold')).grid(
            row=0, column=2 if show_req else 1, padx=2)
        # Duplicate headers for second column block
        col_offset = cols_per_group
        ttk.Label(stat_frame, text='Stat', width=7, font=('TkDefaultFont', 8, 'bold')).grid(row=0, column=col_offset, padx=(12,2))
        if show_req:
            ttk.Label(stat_frame, text='Req', width=4, font=('TkDefaultFont', 8, 'bold')).grid(row=0, column=col_offset+1, padx=2)
        ttk.Label(stat_frame, text='Mod', width=4, font=('TkDefaultFont', 8, 'bold')).grid(
            row=0, column=col_offset + (2 if show_req else 1), padx=2)

        half = (len(_BUFF_STATS) + 1) // 2
        for i, (stat_val, label) in enumerate(_BUFF_STATS):
            if i < half:
                r = i + 1
                base_c = 0
            else:
                r = i - half + 1
                base_c = col_offset

            ttk.Label(stat_frame, text=label, width=7).grid(row=r, column=base_c, sticky='w', padx=2)

            c = base_c + 1
            if show_req:
                req_var = tk.StringVar()
                e_req = ttk.Entry(stat_frame, textvariable=req_var, width=4)
                e_req.grid(row=r, column=c, sticky='w', padx=2, pady=1)
                add_tooltip(e_req, f'Minimum {stat_val} required to equip')
                self._req_vars[stat_val] = req_var
                c += 1

            mod_var = tk.StringVar()
            e_mod = ttk.Entry(stat_frame, textvariable=mod_var, width=4)
            e_mod.grid(row=r, column=c, sticky='w', padx=2, pady=1)
            add_tooltip(e_mod, f'Modifier to {stat_val} (e.g. 3, -1)')
            self._buff_vars[stat_val] = mod_var

    def _get_buffs_json(self) -> str:
        """Read buff modifier widgets into JSON string."""
        buffs = {}
        for stat_val, var in self._buff_vars.items():
            txt = var.get().strip()
            if txt:
                try:
                    val = int(txt) if '.' not in txt else float(txt)
                    if val != 0:
                        buffs[stat_val] = val
                except ValueError:
                    pass
        return json.dumps(buffs) if buffs else '{}'

    def _get_requirements_json(self) -> str:
        """Read requirement widgets into JSON string."""
        reqs = {}
        for stat_val, var in self._req_vars.items():
            txt = var.get().strip()
            if txt:
                try:
                    val = int(txt)
                    if val > 0:
                        reqs[stat_val] = val
                except ValueError:
                    pass
        return json.dumps(reqs) if reqs else '{}'

    def _set_buffs_from_json(self, buffs_str: str):
        """Populate buff modifier widgets from JSON string."""
        for var in self._buff_vars.values():
            var.set('')
        try:
            buffs = json.loads(buffs_str or '{}')
        except (json.JSONDecodeError, TypeError):
            return
        for stat_val, amount in buffs.items():
            if stat_val in self._buff_vars:
                self._buff_vars[stat_val].set(str(amount))

    def _set_requirements_from_json(self, req_str: str):
        """Populate requirement widgets from JSON string."""
        if not hasattr(self, '_req_vars'):
            return
        for var in self._req_vars.values():
            var.set('')
        try:
            reqs = json.loads(req_str or '{}')
        except (json.JSONDecodeError, TypeError):
            return
        for stat_val, amount in reqs.items():
            if stat_val in self._req_vars:
                self._req_vars[stat_val].set(str(amount))

    # -- Helpers --
    def _float(self, var, default=0.0):
        try: return float(var.get())
        except (ValueError, TypeError): return default

    def _int(self, var, default=0):
        try: return int(var.get())
        except (ValueError, TypeError): return default

    def _int_or_none(self, var):
        txt = var.get().strip()
        if not txt or txt == '0': return None
        try: return int(txt)
        except ValueError: return None

    # -- List management --
    def refresh_list(self):
        con = get_con()
        try:
            rows = con.execute('SELECT key, name FROM items WHERE class=? ORDER BY key',
                               (self.item_class,)).fetchall()
        finally:
            con.close()
        self.listbox.delete(0, tk.END)
        for r in rows:
            label = f"{r['key']}" + (f" — {r['name']}" if r['name'] else '')
            self.listbox.insert(tk.END, label)

    def refresh_sprite_dropdown(self):
        self._sprite_names = [''] + fetch_sprite_names()
        self._sprite_cb['values'] = self._sprite_names

    def _on_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel: return
        entry = self.listbox.get(sel[0])
        key = entry.split(' — ')[0] if ' — ' in entry else entry
        self._populate(key)

    def _new(self):
        self.listbox.selection_clear(0, tk.END)
        self._clear()

    def _clear(self):
        self.v_key.set(''); self.v_name.set(''); self.v_description.set('')
        self.v_action_word.set(''); self.v_weight.set('0'); self.v_value.set('0')
        self.v_inventoriable.set(True); self.v_collision.set(False)
        self.v_tile_scale.set('1.0'); self.v_sprite.set('')
        self._sprite_preview.load(None)
        if hasattr(self, '_buff_vars'):
            for var in self._buff_vars.values():
                var.set('')
        if hasattr(self, '_req_vars'):
            for var in self._req_vars.values():
                var.set('')
        self._clear_specific()

    def _clear_specific(self):
        """Override to clear type-specific fields."""
        pass

    def _populate(self, key: str):
        con = get_con()
        try:
            row = con.execute('SELECT * FROM items WHERE key=?', (key,)).fetchone()
            if row is None: return
            slot_rows = con.execute('SELECT slot FROM item_slots WHERE item_key=?', (key,)).fetchall()
        finally:
            con.close()
        self.v_key.set(row['key'])
        self.v_name.set(row['name'] or '')
        self.v_description.set(row['description'] or '')
        self.v_action_word.set(row['action_word'] or '')
        self.v_weight.set(str(row['weight'] or 0))
        self.v_value.set(str(row['value'] or 0))
        self.v_inventoriable.set(bool(row['inventoriable']))
        self.v_collision.set(bool(row['collision']))
        self.v_tile_scale.set(str(row['tile_scale'] if row['tile_scale'] is not None else 1.0))
        sprite = row['sprite_name'] or ''
        self.v_sprite.set(sprite)
        self._sprite_preview.load(sprite or None)
        if hasattr(self, '_buff_vars'):
            self._set_buffs_from_json(row['buffs'])
        if hasattr(self, '_req_vars'):
            self._set_requirements_from_json(row['requirements'])
        self._populate_specific(row, slot_rows)

    def _populate_specific(self, row, slot_rows):
        """Override to load type-specific fields."""
        pass

    def _build_save_vals(self, key, cls) -> dict:
        """Build base column values for saving."""
        vals = {
            'class': cls, 'key': key,
            'name': self.v_name.get().strip(),
            'description': self.v_description.get().strip(),
            'weight': self._float(self.v_weight),
            'value': self._float(self.v_value),
            'sprite_name': self.v_sprite.get().strip() or None,
            'inventoriable': int(self.v_inventoriable.get()),
            'collision': int(self.v_collision.get()),
            'tile_scale': self._float(self.v_tile_scale, 1.0),
            'action_word': self.v_action_word.get().strip(),
            'buffs': self._get_buffs_json() if hasattr(self, '_buff_vars') else '{}',
        }
        if hasattr(self, '_req_vars'):
            vals['requirements'] = self._get_requirements_json()
        return vals

    def _save(self):
        key = self.v_key.get().strip()
        if not key:
            messagebox.showerror('Validation', 'Key is required.')
            return
        vals = self._build_save_vals(key, self.item_class)
        self._add_specific_vals(vals)

        con = get_con()
        try:
            cols = list(vals.keys())
            placeholders = ','.join(['?'] * len(cols))
            updates = ','.join(f'{c}=excluded.{c}' for c in cols if c != 'key')
            sql = (f"INSERT INTO items ({','.join(cols)}) VALUES ({placeholders}) "
                   f"ON CONFLICT(key) DO UPDATE SET {updates}")
            con.execute(sql, tuple(vals.values()))
            self._save_slots(key, con)
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()

    def _add_specific_vals(self, vals: dict):
        """Override to add type-specific values to the save dict."""
        pass

    def _save_slots(self, key: str, con):
        """Override if this type uses item_slots."""
        pass

    def _delete(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning('Delete', 'Select an item first.')
            return
        entry = self.listbox.get(sel[0])
        key = entry.split(' — ')[0] if ' — ' in entry else entry
        if not messagebox.askyesno('Delete', f'Delete "{key}"?'):
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
        self._clear()


# ============================================================================
# Sub-tab implementations
# ============================================================================

class _ItemBasicTab(_ItemSubTab):
    item_class = 'Item'

class _StackableTab(_ItemSubTab):
    item_class = 'Stackable'
    def _build_specific(self):
        self.v_max_stack = tk.StringVar(value='99')
        self._add('Max Stack', lambda p: ttk.Entry(p, textvariable=self.v_max_stack, width=10).pack(anchor='w'),
                  'Maximum per stack')
        self.v_quantity = tk.StringVar(value='1')
        self._add('Quantity', lambda p: ttk.Entry(p, textvariable=self.v_quantity, width=10).pack(anchor='w'),
                  'Default quantity')
    def _add_specific_vals(self, v):
        v['max_stack_size'] = self._int(self.v_max_stack, 99)
        v['quantity'] = self._int(self.v_quantity, 1)
    def _populate_specific(self, row, slots):
        self.v_max_stack.set(str(row['max_stack_size'] or 99))
        self.v_quantity.set(str(row['quantity'] or 1))
    def _clear_specific(self):
        self.v_max_stack.set('99'); self.v_quantity.set('1')


class _WeaponTab(_ItemSubTab):
    item_class = 'Weapon'
    def _build_specific(self):
        self.v_damage = tk.StringVar(value='0')
        self._add('Damage', lambda p: ttk.Entry(p, textvariable=self.v_damage, width=10).pack(anchor='w'),
                  'Base damage per hit')
        self.v_hit_dice = tk.StringVar(value='0')
        self._add('Hit Dice (sides)', lambda p: ttk.Entry(p, textvariable=self.v_hit_dice, width=10).pack(anchor='w'),
                  'Damage die (e.g. 6 for d6)')
        self.v_hit_dice_count = tk.StringVar(value='0')
        self._add('Hit Dice Count', lambda p: ttk.Entry(p, textvariable=self.v_hit_dice_count, width=10).pack(anchor='w'),
                  'Number of dice (e.g. 2 for 2d6)')
        self.v_attack_time = tk.StringVar(value='500')
        self._add('Attack Time (ms)', lambda p: ttk.Entry(p, textvariable=self.v_attack_time, width=10).pack(anchor='w'),
                  'Milliseconds between attacks')
        self.v_range = tk.StringVar(value='1')
        self._add('Range', lambda p: ttk.Entry(p, textvariable=self.v_range, width=10).pack(anchor='w'),
                  'Tiles (1 = melee)')
        self.v_directions = tk.StringVar(value='["front"]')
        self._add('Directions', lambda p: ttk.Entry(p, textvariable=self.v_directions, width=30).pack(anchor='w'),
                  'JSON attack directions')
        self.v_ammo_type = tk.StringVar()
        self._add('Ammo Type', lambda p: ttk.Entry(p, textvariable=self.v_ammo_type, width=20).pack(anchor='w'),
                  'Required ammunition name')
        self.v_crit_chance_mod = tk.StringVar(value='0')
        self._add('Crit Chance Mod', lambda p: ttk.Entry(p, textvariable=self.v_crit_chance_mod, width=10).pack(anchor='w'),
                  '+/- to crit chance %')
        self.v_crit_damage_mod = tk.StringVar(value='0')
        self._add('Crit Damage Mod', lambda p: ttk.Entry(p, textvariable=self.v_crit_damage_mod, width=10).pack(anchor='w'),
                  '+/- to crit damage multiplier')
        self.v_stagger_dc = tk.StringVar(value='0')
        self._add('Stagger DC', lambda p: ttk.Entry(p, textvariable=self.v_stagger_dc, width=10).pack(anchor='w'),
                  'DC for stagger (0 = use base damage)')
        self.v_stamina_cost = tk.StringVar(value='0')
        self._add('Stamina Cost', lambda p: ttk.Entry(p, textvariable=self.v_stamina_cost, width=10).pack(anchor='w'),
                  'Per-swing cost (0 = default formula)')
        self.v_status_effect = tk.StringVar()
        self._add('Status Effect', lambda p: ttk.Entry(p, textvariable=self.v_status_effect, width=20).pack(anchor='w'),
                  'On-hit status (poison, bleed, stun)')
        self.v_status_dc = tk.StringVar(value='0')
        self._add('Status DC', lambda p: ttk.Entry(p, textvariable=self.v_status_dc, width=10).pack(anchor='w'),
                  'DC for status resist')

        # Equipment fields
        self.v_slot_count = tk.StringVar(value='1')
        self._add('Slot Count', lambda p: ttk.Entry(p, textvariable=self.v_slot_count, width=10).pack(anchor='w'),
                  'Slots occupied')
        self.v_durability_max = tk.StringVar(value='100')
        self._add('Durability Max', lambda p: ttk.Entry(p, textvariable=self.v_durability_max, width=10).pack(anchor='w'))
        self.v_durability_cur = tk.StringVar(value='100')
        self._add('Durability Cur', lambda p: ttk.Entry(p, textvariable=self.v_durability_cur, width=10).pack(anchor='w'))
        self.v_render_on_creature = tk.BooleanVar(value=False)
        self._add('Render on Creature', lambda p: ttk.Checkbutton(p, variable=self.v_render_on_creature).pack(anchor='w'))
        # Requirements are now in the stat table below (Req column)

        # Slots checkboxes
        self.slot_vars = {s: tk.BooleanVar() for s in SLOTS}
        def _build_slots(p):
            for i, slot in enumerate(SLOTS):
                ttk.Checkbutton(p, text=slot, variable=self.slot_vars[slot]).grid(
                    row=i // 3, column=i % 3, sticky='w', padx=4)
        self._add('Slots', _build_slots, 'Equipment slots')

        # Stat modifiers
        self._build_buffs_section('Weapon Stat Modifiers (on equip)')

    def _add_specific_vals(self, v):
        v['damage'] = self._float(self.v_damage)
        v['hit_dice'] = self._int_or_none(self.v_hit_dice)
        v['hit_dice_count'] = self._int_or_none(self.v_hit_dice_count)
        v['attack_time_ms'] = self._int(self.v_attack_time, 500)
        v['range'] = self._int(self.v_range, 1)
        v['directions'] = self.v_directions.get().strip()
        v['ammunition_type'] = self.v_ammo_type.get().strip() or None
        v['crit_chance_mod'] = self._int_or_none(self.v_crit_chance_mod)
        v['crit_damage_mod'] = self._float(self.v_crit_damage_mod) or None
        v['stagger_dc'] = self._int_or_none(self.v_stagger_dc)
        v['stamina_cost'] = self._int_or_none(self.v_stamina_cost)
        v['status_effect'] = self.v_status_effect.get().strip() or None
        v['status_dc'] = self._int_or_none(self.v_status_dc)
        v['slot_count'] = self._int(self.v_slot_count, 1)
        v['durability_max'] = self._int(self.v_durability_max, 100)
        v['durability_current'] = self._int(self.v_durability_cur, 100)
        v['render_on_creature'] = int(self.v_render_on_creature.get())
        # requirements handled by _build_save_vals via _req_vars

    def _save_slots(self, key, con):
        con.execute('DELETE FROM item_slots WHERE item_key=?', (key,))
        for slot, var in self.slot_vars.items():
            if var.get():
                con.execute('INSERT INTO item_slots VALUES (?, ?)', (key, slot))

    def _populate_specific(self, row, slot_rows):
        self.v_damage.set(str(row['damage'] or 0))
        self.v_hit_dice.set(str(row['hit_dice'] or 0))
        self.v_hit_dice_count.set(str(row['hit_dice_count'] or 0))
        self.v_attack_time.set(str(row['attack_time_ms'] or 500))
        self.v_range.set(str(row['range'] or 1))
        self.v_directions.set(row['directions'] or '["front"]')
        self.v_ammo_type.set(row['ammunition_type'] or '')
        self.v_crit_chance_mod.set(str(row['crit_chance_mod'] or 0))
        self.v_crit_damage_mod.set(str(row['crit_damage_mod'] or 0))
        self.v_stagger_dc.set(str(row['stagger_dc'] or 0))
        self.v_stamina_cost.set(str(row['stamina_cost'] or 0))
        self.v_status_effect.set(row['status_effect'] or '')
        self.v_status_dc.set(str(row['status_dc'] or 0))
        self.v_slot_count.set(str(row['slot_count'] or 1))
        self.v_durability_max.set(str(row['durability_max'] or 100))
        self.v_durability_cur.set(str(row['durability_current'] or 100))
        self.v_render_on_creature.set(bool(row['render_on_creature']))
        # requirements loaded via _set_requirements_from_json in _populate()
        item_slots = {r['slot'] for r in slot_rows}
        for slot, var in self.slot_vars.items():
            var.set(slot in item_slots)

    def _clear_specific(self):
        self.v_damage.set('0'); self.v_hit_dice.set('0'); self.v_hit_dice_count.set('0')
        self.v_attack_time.set('500'); self.v_range.set('1')
        self.v_directions.set('["front"]'); self.v_ammo_type.set('')
        self.v_crit_chance_mod.set('0'); self.v_crit_damage_mod.set('0')
        self.v_stagger_dc.set('0'); self.v_stamina_cost.set('0')
        self.v_status_effect.set(''); self.v_status_dc.set('0')
        self.v_slot_count.set('1'); self.v_durability_max.set('100')
        self.v_durability_cur.set('100'); self.v_render_on_creature.set(False)
        # requirements cleared via _clear() → _req_vars
        for v in self.slot_vars.values(): v.set(False)


class _WearableTab(_ItemSubTab):
    item_class = 'Wearable'
    def _build_specific(self):
        self.v_slot_count = tk.StringVar(value='1')
        self._add('Slot Count', lambda p: ttk.Entry(p, textvariable=self.v_slot_count, width=10).pack(anchor='w'))
        self.v_durability_max = tk.StringVar(value='100')
        self._add('Durability Max', lambda p: ttk.Entry(p, textvariable=self.v_durability_max, width=10).pack(anchor='w'))
        self.v_durability_cur = tk.StringVar(value='100')
        self._add('Durability Cur', lambda p: ttk.Entry(p, textvariable=self.v_durability_cur, width=10).pack(anchor='w'))
        self.v_render_on_creature = tk.BooleanVar(value=False)
        self._add('Render on Creature', lambda p: ttk.Checkbutton(p, variable=self.v_render_on_creature).pack(anchor='w'))
        self.v_requirements = tk.StringVar(value='{}')
        self._add('Requirements', lambda p: ttk.Entry(p, textvariable=self.v_requirements, width=40).pack(anchor='w'),
                  'JSON stat minimums')
        self.slot_vars = {s: tk.BooleanVar() for s in SLOTS}
        def _build_slots(p):
            for i, slot in enumerate(SLOTS):
                ttk.Checkbutton(p, text=slot, variable=self.slot_vars[slot]).grid(
                    row=i // 3, column=i % 3, sticky='w', padx=4)
        self._add('Slots', _build_slots)
        self._build_buffs_section('Armor Stat Modifiers (on equip)')

    def _add_specific_vals(self, v):
        v['slot_count'] = self._int(self.v_slot_count, 1)
        v['durability_max'] = self._int(self.v_durability_max, 100)
        v['durability_current'] = self._int(self.v_durability_cur, 100)
        v['render_on_creature'] = int(self.v_render_on_creature.get())
        # requirements handled by _build_save_vals via _req_vars

    def _save_slots(self, key, con):
        con.execute('DELETE FROM item_slots WHERE item_key=?', (key,))
        for slot, var in self.slot_vars.items():
            if var.get():
                con.execute('INSERT INTO item_slots VALUES (?, ?)', (key, slot))

    def _populate_specific(self, row, slot_rows):
        self.v_slot_count.set(str(row['slot_count'] or 1))
        self.v_durability_max.set(str(row['durability_max'] or 100))
        self.v_durability_cur.set(str(row['durability_current'] or 100))
        self.v_render_on_creature.set(bool(row['render_on_creature']))
        # requirements loaded via _set_requirements_from_json in _populate()
        item_slots = {r['slot'] for r in slot_rows}
        for slot, var in self.slot_vars.items():
            var.set(slot in item_slots)

    def _clear_specific(self):
        self.v_slot_count.set('1'); self.v_durability_max.set('100')
        self.v_durability_cur.set('100'); self.v_render_on_creature.set(False)
        # requirements cleared via _clear() → _req_vars
        for v in self.slot_vars.values(): v.set(False)


class _ConsumableTab(_ItemSubTab):
    item_class = 'Consumable'
    def _build_specific(self):
        self.v_max_stack = tk.StringVar(value='99')
        self._add('Max Stack', lambda p: ttk.Entry(p, textvariable=self.v_max_stack, width=10).pack(anchor='w'))
        self.v_quantity = tk.StringVar(value='1')
        self._add('Quantity', lambda p: ttk.Entry(p, textvariable=self.v_quantity, width=10).pack(anchor='w'))
        self.v_duration = tk.StringVar(value='0')
        self._add('Duration (s)', lambda p: ttk.Entry(p, textvariable=self.v_duration, width=10).pack(anchor='w'),
                  'Buff duration (0 = instant)')
        self.v_heal_amount = tk.StringVar(value='0')
        self._add('Heal Amount', lambda p: ttk.Entry(p, textvariable=self.v_heal_amount, width=10).pack(anchor='w'),
                  'Direct HP healed')
        self.v_mana_restore = tk.StringVar(value='0')
        self._add('Mana Restore', lambda p: ttk.Entry(p, textvariable=self.v_mana_restore, width=10).pack(anchor='w'))
        self.v_stamina_restore = tk.StringVar(value='0')
        self._add('Stamina Restore', lambda p: ttk.Entry(p, textvariable=self.v_stamina_restore, width=10).pack(anchor='w'))
        self._build_buffs_section('Consumable Buffs (temporary on use)', show_req=False)

    def _add_specific_vals(self, v):
        v['max_stack_size'] = self._int(self.v_max_stack, 99)
        v['quantity'] = self._int(self.v_quantity, 1)
        v['duration'] = self._float(self.v_duration)
        v['heal_amount'] = self._int(self.v_heal_amount)
        v['mana_restore'] = self._int(self.v_mana_restore)
        v['stamina_restore'] = self._int(self.v_stamina_restore)

    def _populate_specific(self, row, slots):
        self.v_max_stack.set(str(row['max_stack_size'] or 99))
        self.v_quantity.set(str(row['quantity'] or 1))
        self.v_duration.set(str(row['duration'] or 0))
        self.v_heal_amount.set(str(row['heal_amount'] or 0))
        self.v_mana_restore.set(str(row['mana_restore'] or 0))
        self.v_stamina_restore.set(str(row['stamina_restore'] or 0))

    def _clear_specific(self):
        self.v_max_stack.set('99'); self.v_quantity.set('1')
        self.v_duration.set('0'); self.v_heal_amount.set('0')
        self.v_mana_restore.set('0'); self.v_stamina_restore.set('0')


class _AmmunitionTab(_ItemSubTab):
    item_class = 'Ammunition'
    def _build_specific(self):
        self.v_max_stack = tk.StringVar(value='99')
        self._add('Max Stack', lambda p: ttk.Entry(p, textvariable=self.v_max_stack, width=10).pack(anchor='w'))
        self.v_quantity = tk.StringVar(value='1')
        self._add('Quantity', lambda p: ttk.Entry(p, textvariable=self.v_quantity, width=10).pack(anchor='w'))
        self.v_damage = tk.StringVar(value='0')
        self._add('Damage', lambda p: ttk.Entry(p, textvariable=self.v_damage, width=10).pack(anchor='w'),
                  'Per-projectile damage')
        self.v_destroy_prob = tk.StringVar(value='1.0')
        self._add('Destroy Prob', lambda p: ttk.Entry(p, textvariable=self.v_destroy_prob, width=10).pack(anchor='w'),
                  'Chance consumed on hit (0-1)')
        self.v_recoverable = tk.BooleanVar(value=True)
        self._add('Recoverable', lambda p: ttk.Checkbutton(p, variable=self.v_recoverable).pack(anchor='w'),
                  'Lands on tile on miss (arrows yes, bullets no)')
        self.v_status_effect = tk.StringVar()
        self._add('Status Effect', lambda p: ttk.Entry(p, textvariable=self.v_status_effect, width=20).pack(anchor='w'),
                  'On-hit status (poison, bleed)')
        self.v_status_dc = tk.StringVar(value='0')
        self._add('Status DC', lambda p: ttk.Entry(p, textvariable=self.v_status_dc, width=10).pack(anchor='w'))

    def _add_specific_vals(self, v):
        v['max_stack_size'] = self._int(self.v_max_stack, 99)
        v['quantity'] = self._int(self.v_quantity, 1)
        v['damage'] = self._float(self.v_damage)
        v['destroy_on_use_probability'] = self._float(self.v_destroy_prob, 1.0)
        v['recoverable'] = int(self.v_recoverable.get())
        v['status_effect'] = self.v_status_effect.get().strip() or None
        v['status_dc'] = self._int_or_none(self.v_status_dc)

    def _populate_specific(self, row, slots):
        self.v_max_stack.set(str(row['max_stack_size'] or 99))
        self.v_quantity.set(str(row['quantity'] or 1))
        self.v_damage.set(str(row['damage'] or 0))
        self.v_destroy_prob.set(str(row['destroy_on_use_probability'] or 1.0))
        self.v_recoverable.set(bool(row['recoverable']) if row['recoverable'] is not None else True)
        self.v_status_effect.set(row['status_effect'] or '')
        self.v_status_dc.set(str(row['status_dc'] or 0))

    def _clear_specific(self):
        self.v_max_stack.set('99'); self.v_quantity.set('1')
        self.v_damage.set('0'); self.v_destroy_prob.set('1.0')
        self.v_recoverable.set(True); self.v_status_effect.set('')
        self.v_status_dc.set('0')


class _StructureTab(_ItemSubTab):
    item_class = 'Structure'
    def _build_specific(self):
        self.v_footprint = tk.StringVar(value='[[0,0]]')
        self._add('Footprint', lambda p: ttk.Entry(p, textvariable=self.v_footprint, width=40).pack(anchor='w'),
                  'JSON tile offsets')
        self.v_collision_mask = tk.StringVar(value='[[0,0]]')
        self._add('Collision Mask', lambda p: ttk.Entry(p, textvariable=self.v_collision_mask, width=40).pack(anchor='w'))
        self.v_entry_points = tk.StringVar(value='{}')
        self._add('Entry Points', lambda p: ttk.Entry(p, textvariable=self.v_entry_points, width=40).pack(anchor='w'))
        self.v_nested_map = tk.StringVar()
        self._map_names = [''] + fetch_map_names()
        def _build_map(p):
            self._map_cb = ttk.Combobox(p, textvariable=self.v_nested_map,
                                        values=self._map_names, state='readonly', width=18)
            self._map_cb.pack(anchor='w')
        self._add('Nested Map', _build_map, 'Interior map when entering this structure')

    def _add_specific_vals(self, v):
        v['footprint'] = self.v_footprint.get().strip()
        v['collision_mask'] = self.v_collision_mask.get().strip()
        v['entry_points'] = self.v_entry_points.get().strip()
        v['nested_map'] = self.v_nested_map.get().strip() or None

    def _populate_specific(self, row, slots):
        self.v_footprint.set(row['footprint'] or '[[0,0]]')
        self.v_collision_mask.set(row['collision_mask'] or '[[0,0]]')
        self.v_entry_points.set(row['entry_points'] or '{}')
        self.v_nested_map.set(row['nested_map'] or '')

    def _clear_specific(self):
        self.v_footprint.set('[[0,0]]'); self.v_collision_mask.set('[[0,0]]')
        self.v_entry_points.set('{}'); self.v_nested_map.set('')


# ============================================================================
# Main Items Tab — sub-notebook container
# ============================================================================

class ItemsTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True)

        self._tabs = {
            'Item':       _ItemBasicTab(nb),
            'Stackable':  _StackableTab(nb),
            'Weapon':     _WeaponTab(nb),
            'Wearable':   _WearableTab(nb),
            'Consumable': _ConsumableTab(nb),
            'Ammunition': _AmmunitionTab(nb),
            'Structure':  _StructureTab(nb),
        }

        for label, tab in self._tabs.items():
            nb.add(tab, text=f'  {label}  ')

    def refresh_list(self):
        for tab in self._tabs.values():
            tab.refresh_list()

    def refresh_sprite_dropdown(self):
        for tab in self._tabs.values():
            tab.refresh_sprite_dropdown()
