"""
Creatures master tab — sub-tabs for Species and NPCs.

Species tab: defines species templates with stats, size, behavior baselines,
  age thresholds, fecundity, and composite animation bindings.

NPCs tab: defines individual creature templates. Auto-populates species
  defaults when a species is selected.
"""
import json
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

from editor.db import (
    get_con, fetch_sprite_names, fetch_composite_names,
    fetch_species_names, fetch_map_names, fetch_conversation_names,
)
from editor.constants import STATS, STAT_LABELS, PREVIEW_SIZE
from editor.sprite_preview import SpritePreview
from editor.tooltip import add_tooltip

SIZES = ['tiny', 'small', 'medium', 'large', 'huge', 'colossal']
BEHAVIORS = ['', 'RandomWanderBehavior', 'StatWeightedBehavior', 'NeuralBehavior']
MASKS = ['', 'socially_deaf', 'socially_impaired', 'blind', 'deaf',
         'amnesiac', 'impulsive', 'fearless', 'greedy', 'zealot', 'feral',
         'nearsighted', 'paranoid', 'antisocial']
COMP_BEHAVIORS = [
    'idle', 'idle_combat',
    'walk_north', 'walk_south', 'walk_east', 'walk_west',
    'attack_north', 'attack_south', 'attack_east', 'attack_west',
    'hurt', 'block', 'death',
]


# ============================================================================
# Species Sub-Tab
# ============================================================================

class _SpeciesSubTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._build()
        self.refresh_list()

    def _build(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Left: listbox
        left = ttk.Frame(pane, width=180)
        pane.add(left, weight=0)
        ttk.Label(left, text='Species').pack(anchor='w')
        lf = ttk.Frame(left)
        lf.pack(fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(lf, exportselection=False, width=20)
        sb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.bind('<<ListboxSelect>>', self._on_select)
        self.listbox.bind('<Shift-Delete>', lambda e: self._delete())

        btn = ttk.Frame(left)
        btn.pack(fill=tk.X, pady=4)
        for txt, cmd in [('New', self._new), ('Save', self._save), ('Delete', self._delete)]:
            b = ttk.Button(btn, text=txt, command=cmd); b.pack(side=tk.LEFT, padx=2)

        # Right: scrollable form
        right = ttk.Frame(pane)
        pane.add(right, weight=1)
        canvas = tk.Canvas(right, highlightthickness=0)
        vsb = ttk.Scrollbar(right, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.form = ttk.Frame(canvas)
        self._fw = canvas.create_window((0,0), window=self.form, anchor='nw')
        self.form.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfig(self._fw, width=e.width))

        self._build_form()

    def _add(self, label, widget_fn, tip=None, row=None):
        if row is None:
            row = self._row; self._row += 1
        ttk.Label(self.form, text=label).grid(row=row, column=0, sticky='w', padx=6, pady=2)
        frm = ttk.Frame(self.form)
        frm.grid(row=row, column=1, sticky='ew', padx=6, pady=2)
        widget_fn(frm)
        if tip: add_tooltip(frm, tip)

    def _build_form(self):
        f = self.form
        self._row = 0

        # -- Identity --
        self.v_name = tk.StringVar()
        self._add('Name', lambda p: ttk.Entry(p, textvariable=self.v_name, width=20).pack(anchor='w'), 'Unique species name')
        self.v_playable = tk.BooleanVar()
        self._add('Playable', lambda p: ttk.Checkbutton(p, variable=self.v_playable).pack(anchor='w'), 'Player-selectable')
        self.v_description = tk.StringVar()
        self._add('Description', lambda p: ttk.Entry(p, textvariable=self.v_description, width=40).pack(anchor='w'), 'Lore text')
        self.v_size = tk.StringVar(value='medium')
        self._add('Size', lambda p: ttk.Combobox(p, textvariable=self.v_size, values=SIZES, state='readonly', width=10).pack(anchor='w'), 'Creature size category')

        # -- Visuals --
        self.v_sprite = tk.StringVar()
        self._sprite_names = [''] + fetch_sprite_names()
        def _sp(p):
            self.sprite_cb = ttk.Combobox(p, textvariable=self.v_sprite, values=self._sprite_names, state='readonly', width=18)
            self.sprite_cb.pack(side=tk.LEFT, padx=(0,8))
            self.sprite_preview = SpritePreview(p, size=PREVIEW_SIZE)
            self.sprite_preview.pack(side=tk.LEFT)
            self.sprite_cb.bind('<<ComboboxSelected>>', lambda e: self.sprite_preview.load(self.v_sprite.get() or None))
        self._add('Sprite', _sp, 'Default sprite')
        self.v_tile_scale = tk.StringVar(value='1.0')
        self._add('Tile Scale', lambda p: ttk.Entry(p, textvariable=self.v_tile_scale, width=10).pack(anchor='w'), 'Visual scale')
        self.v_composite = tk.StringVar()
        self._composite_names = [''] + fetch_composite_names()
        self._add('Composite', lambda p: ttk.Combobox(p, textvariable=self.v_composite, values=self._composite_names, state='readonly', width=18).pack(anchor='w'), 'Layered sprite')
        self.v_egg_sprite = tk.StringVar()
        self._add('Egg Sprite', lambda p: ttk.Combobox(p, textvariable=self.v_egg_sprite, values=self._sprite_names, state='readonly', width=18).pack(anchor='w'), 'Sprite used for this species\' eggs')

        # -- Behavior Baselines --
        ttk.Separator(self.form, orient=tk.HORIZONTAL).grid(row=self._row, column=0, columnspan=2, sticky='ew', padx=6, pady=6); self._row += 1
        ttk.Label(self.form, text='Behavior Baselines', font=('TkDefaultFont', 9, 'bold')).grid(row=self._row, column=0, columnspan=2, sticky='w', padx=6); self._row += 1

        self.v_prudishness = tk.StringVar(value='0.5')
        self._add('Prudishness', lambda p: ttk.Entry(p, textvariable=self.v_prudishness, width=8).pack(anchor='w'), '0.0-1.0')
        self.v_aggression = tk.StringVar(value='0.3')
        self._add('Aggression', lambda p: ttk.Entry(p, textvariable=self.v_aggression, width=8).pack(anchor='w'), 'Baseline aggression 0-1')
        self.v_sociability = tk.StringVar(value='0.5')
        self._add('Sociability', lambda p: ttk.Entry(p, textvariable=self.v_sociability, width=8).pack(anchor='w'), 'Baseline sociability 0-1')
        self.v_territoriality = tk.StringVar(value='0.3')
        self._add('Territoriality', lambda p: ttk.Entry(p, textvariable=self.v_territoriality, width=8).pack(anchor='w'), 'Baseline territoriality 0-1')
        self.v_curiosity = tk.StringVar(value='0.0')
        self._add('Curiosity Mod', lambda p: ttk.Entry(p, textvariable=self.v_curiosity, width=8).pack(anchor='w'), 'Species curiosity bias')
        self.v_base_speed = tk.StringVar(value='4.0')
        self._add('Base Move Speed', lambda p: ttk.Entry(p, textvariable=self.v_base_speed, width=8).pack(anchor='w'), 'TPS before AGL modifier')
        self.v_preferred_deity = tk.StringVar()
        self._add('Preferred Deity', lambda p: ttk.Entry(p, textvariable=self.v_preferred_deity, width=18).pack(anchor='w'), 'Default deity tendency')

        # -- Age Thresholds --
        ttk.Separator(self.form, orient=tk.HORIZONTAL).grid(row=self._row, column=0, columnspan=2, sticky='ew', padx=6, pady=6); self._row += 1
        ttk.Label(self.form, text='Age Thresholds (game days)', font=('TkDefaultFont', 9, 'bold')).grid(row=self._row, column=0, columnspan=2, sticky='w', padx=6); self._row += 1

        self.v_young_max = tk.StringVar(value='30')
        self._add('Young Max', lambda p: ttk.Entry(p, textvariable=self.v_young_max, width=8).pack(anchor='w'), 'Days until no longer young')
        self.v_maturity = tk.StringVar(value='18')
        self._add('Maturity Age', lambda p: ttk.Entry(p, textvariable=self.v_maturity, width=8).pack(anchor='w'), 'Days until can pair')
        self.v_fecundity_peak = tk.StringVar(value='100')
        self._add('Fecundity Peak', lambda p: ttk.Entry(p, textvariable=self.v_fecundity_peak, width=8).pack(anchor='w'), 'Day fecundity starts declining')
        self.v_fecundity_end = tk.StringVar(value='300')
        self._add('Fecundity End', lambda p: ttk.Entry(p, textvariable=self.v_fecundity_end, width=8).pack(anchor='w'), 'Day fecundity reaches 0')
        self.v_lifespan = tk.StringVar(value='365')
        self._add('Lifespan', lambda p: ttk.Entry(p, textvariable=self.v_lifespan, width=8).pack(anchor='w'), 'Old age threshold (game days)')

        # -- Base Stats --
        ttk.Separator(self.form, orient=tk.HORIZONTAL).grid(row=self._row, column=0, columnspan=2, sticky='ew', padx=6, pady=6); self._row += 1
        ttk.Label(self.form, text='Base Stats (blank = not set)', font=('TkDefaultFont', 9, 'bold')).grid(row=self._row, column=0, columnspan=2, sticky='w', padx=6); self._row += 1

        self.stat_vars = {}
        for stat in STATS:
            var = tk.StringVar()
            self.stat_vars[stat] = var
            self._add(STAT_LABELS[stat], lambda p, v=var: ttk.Entry(p, textvariable=v, width=8).pack(anchor='w'), f'Base {stat} value')

        f.columnconfigure(1, weight=1)

    def _float(self, var, default=0.0):
        try: return float(var.get())
        except: return default

    def _int(self, var, default=0):
        try: return int(var.get())
        except: return default

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

    def _clear(self):
        self.v_name.set(''); self.v_playable.set(False); self.v_description.set('')
        self.v_size.set('medium'); self.v_sprite.set(''); self.v_tile_scale.set('1.0')
        self.v_composite.set(''); self.v_egg_sprite.set(''); self.v_prudishness.set('0.5')
        self.v_aggression.set('0.3'); self.v_sociability.set('0.5')
        self.v_territoriality.set('0.3'); self.v_curiosity.set('0.0')
        self.v_base_speed.set('4.0'); self.v_preferred_deity.set('')
        self.v_young_max.set('30'); self.v_maturity.set('18')
        self.v_fecundity_peak.set('100'); self.v_fecundity_end.set('300')
        self.v_lifespan.set('365')
        self.sprite_preview.load(None)
        for var in self.stat_vars.values(): var.set('')

    def _populate(self, name):
        con = get_con()
        try:
            row = con.execute('SELECT * FROM species WHERE name=?', (name,)).fetchone()
            if not row: return
            stats = con.execute('SELECT stat, value FROM species_stats WHERE species_name=?', (name,)).fetchall()
        finally:
            con.close()
        self.v_name.set(row['name'])
        self.v_playable.set(bool(row['playable']))
        self.v_description.set(row['description'] or '')
        self.v_size.set(row['size'] or 'medium')
        self.v_sprite.set(row['sprite_name'] or '')
        self.sprite_preview.load(row['sprite_name'] or None)
        self.v_tile_scale.set(str(row['tile_scale'] or 1.0))
        self.v_composite.set(row['composite_name'] or '')
        self.v_egg_sprite.set(row['egg_sprite'] or '' if 'egg_sprite' in row.keys() else '')
        self.v_prudishness.set(str(row['prudishness'] if row['prudishness'] is not None else 0.5))
        self.v_aggression.set(str(row['aggression'] if row['aggression'] is not None else 0.3))
        self.v_sociability.set(str(row['sociability'] if row['sociability'] is not None else 0.5))
        self.v_territoriality.set(str(row['territoriality'] if row['territoriality'] is not None else 0.3))
        self.v_curiosity.set(str(row['curiosity_modifier'] if row['curiosity_modifier'] is not None else 0.0))
        self.v_base_speed.set(str(row['base_move_speed'] if row['base_move_speed'] is not None else 4.0))
        self.v_preferred_deity.set(row['preferred_deity'] or '')
        self.v_young_max.set(str(row['young_max'] if row['young_max'] is not None else 30))
        self.v_maturity.set(str(row['maturity_age'] if row['maturity_age'] is not None else 18))
        self.v_fecundity_peak.set(str(row['fecundity_peak'] if row['fecundity_peak'] is not None else 100))
        self.v_fecundity_end.set(str(row['fecundity_end'] if row['fecundity_end'] is not None else 300))
        self.v_lifespan.set(str(row['lifespan'] if row['lifespan'] is not None else 365))
        stat_map = {r['stat']: r['value'] for r in stats}
        for stat, var in self.stat_vars.items():
            var.set(str(stat_map[stat]) if stat in stat_map else '')

    def _on_select(self, event=None):
        sel = self.listbox.curselection()
        if sel: self._populate(self.listbox.get(sel[0]))

    def _new(self):
        self.listbox.selection_clear(0, tk.END); self._clear()

    def _save(self):
        name = self.v_name.get().strip()
        if not name:
            messagebox.showerror('Validation', 'Name required.'); return
        con = get_con()
        try:
            con.execute(
                '''INSERT INTO species (name, playable, sprite_name, composite_name, tile_scale,
                   size, description, prudishness, base_move_speed, lifespan, maturity_age,
                   young_max, fecundity_peak, fecundity_end, aggression, sociability,
                   territoriality, curiosity_modifier, preferred_deity, egg_sprite)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(name) DO UPDATE SET
                   playable=excluded.playable, sprite_name=excluded.sprite_name,
                   composite_name=excluded.composite_name, tile_scale=excluded.tile_scale,
                   size=excluded.size, description=excluded.description,
                   prudishness=excluded.prudishness, base_move_speed=excluded.base_move_speed,
                   lifespan=excluded.lifespan, maturity_age=excluded.maturity_age,
                   young_max=excluded.young_max, fecundity_peak=excluded.fecundity_peak,
                   fecundity_end=excluded.fecundity_end, aggression=excluded.aggression,
                   sociability=excluded.sociability, territoriality=excluded.territoriality,
                   curiosity_modifier=excluded.curiosity_modifier,
                   preferred_deity=excluded.preferred_deity,
                   egg_sprite=excluded.egg_sprite
                ''',
                (name, int(self.v_playable.get()), self.v_sprite.get().strip() or None,
                 self.v_composite.get().strip() or None, self._float(self.v_tile_scale, 1.0),
                 self.v_size.get(), self.v_description.get().strip(),
                 self._float(self.v_prudishness, 0.5), self._float(self.v_base_speed, 4.0),
                 self._int(self.v_lifespan, 365), self._int(self.v_maturity, 18),
                 self._int(self.v_young_max, 30), self._int(self.v_fecundity_peak, 100),
                 self._int(self.v_fecundity_end, 300), self._float(self.v_aggression, 0.3),
                 self._float(self.v_sociability, 0.5), self._float(self.v_territoriality, 0.3),
                 self._float(self.v_curiosity, 0.0),
                 self.v_preferred_deity.get().strip() or None,
                 self.v_egg_sprite.get().strip() or None))
            # Stats
            con.execute('DELETE FROM species_stats WHERE species_name=?', (name,))
            for stat, var in self.stat_vars.items():
                txt = var.get().strip()
                if txt:
                    try:
                        con.execute('INSERT INTO species_stats VALUES (?,?,?)', (name, stat, int(txt)))
                    except ValueError: pass
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e)); return
        finally:
            con.close()
        self.refresh_list()

    def _delete(self):
        sel = self.listbox.curselection()
        if not sel: return
        name = self.listbox.get(sel[0])
        if not messagebox.askyesno('Delete', f'Delete species "{name}"?'): return
        con = get_con()
        try:
            con.execute('DELETE FROM species_stats WHERE species_name=?', (name,))
            con.execute('DELETE FROM species WHERE name=?', (name,))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e)); return
        finally:
            con.close()
        self.refresh_list(); self._clear()


# ============================================================================
# NPC Sub-Tab
# ============================================================================

class _NPCSubTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._build()
        self.refresh_list()

    def _build(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        left = ttk.Frame(pane, width=200)
        pane.add(left, weight=0)
        ttk.Label(left, text='NPCs').pack(anchor='w')
        lf = ttk.Frame(left)
        lf.pack(fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(lf, exportselection=False, width=24)
        sb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.bind('<<ListboxSelect>>', self._on_select)
        self.listbox.bind('<Shift-Delete>', lambda e: self._delete())

        btn = ttk.Frame(left)
        btn.pack(fill=tk.X, pady=4)
        for txt, cmd in [('New', self._new), ('Save', self._save), ('Delete', self._delete)]:
            b = ttk.Button(btn, text=txt, command=cmd); b.pack(side=tk.LEFT, padx=2)

        right = ttk.Frame(pane)
        pane.add(right, weight=1)
        canvas = tk.Canvas(right, highlightthickness=0)
        vsb = ttk.Scrollbar(right, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.form = ttk.Frame(canvas)
        self._fw = canvas.create_window((0,0), window=self.form, anchor='nw')
        self.form.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfig(self._fw, width=e.width))

        self._build_form()

    def _add(self, label, widget_fn, tip=None):
        row = self._row; self._row += 1
        ttk.Label(self.form, text=label).grid(row=row, column=0, sticky='w', padx=6, pady=2)
        frm = ttk.Frame(self.form)
        frm.grid(row=row, column=1, sticky='ew', padx=6, pady=2)
        widget_fn(frm)
        if tip: add_tooltip(frm, tip)

    def _build_form(self):
        self._row = 0

        self.v_key = tk.StringVar()
        self._add('Key', lambda p: ttk.Entry(p, textvariable=self.v_key, width=20).pack(anchor='w'), 'Unique NPC identifier')
        self.v_name = tk.StringVar()
        self._add('Name', lambda p: ttk.Entry(p, textvariable=self.v_name, width=20).pack(anchor='w'), 'Display name')
        self.v_title = tk.StringVar()
        self._add('Title', lambda p: ttk.Entry(p, textvariable=self.v_title, width=20).pack(anchor='w'), 'Role (e.g. Blacksmith, Guard)')
        self.v_description = tk.StringVar()
        self._add('Description', lambda p: ttk.Entry(p, textvariable=self.v_description, width=40).pack(anchor='w'), 'Lore text')

        # Species selector — auto-populates defaults
        self.v_species = tk.StringVar()
        self._species_names = fetch_species_names()
        def _sp_sel(p):
            self.species_cb = ttk.Combobox(p, textvariable=self.v_species, values=self._species_names, state='readonly', width=18)
            self.species_cb.pack(anchor='w')
            self.species_cb.bind('<<ComboboxSelected>>', self._on_species_changed)
        self._add('Species', _sp_sel, 'Species template — populates defaults')

        self.v_level = tk.StringVar()
        self._add('Level', lambda p: ttk.Entry(p, textvariable=self.v_level, width=8).pack(anchor='w'), 'Starting level')
        self.v_sex = tk.StringVar()
        self._add('Sex', lambda p: ttk.Combobox(p, textvariable=self.v_sex, values=['', 'male', 'female'], state='readonly', width=10).pack(anchor='w'), 'Blank = random')
        self.v_age = tk.StringVar()
        self._add('Age (days)', lambda p: ttk.Entry(p, textvariable=self.v_age, width=8).pack(anchor='w'), 'Starting age')
        self.v_prudishness = tk.StringVar()
        self._add('Prudishness', lambda p: ttk.Entry(p, textvariable=self.v_prudishness, width=8).pack(anchor='w'), 'Override species default')
        self.v_gold = tk.StringVar()
        self._add('Gold', lambda p: ttk.Entry(p, textvariable=self.v_gold, width=10).pack(anchor='w'), 'Starting gold')

        self.v_deity = tk.StringVar()
        self._add('Deity', lambda p: ttk.Entry(p, textvariable=self.v_deity, width=18).pack(anchor='w'), 'Assigned deity name')
        self.v_piety = tk.StringVar()
        self._add('Piety', lambda p: ttk.Entry(p, textvariable=self.v_piety, width=8).pack(anchor='w'), 'Starting piety 0-1')

        self.v_behavior = tk.StringVar()
        self._add('Behavior', lambda p: ttk.Combobox(p, textvariable=self.v_behavior, values=BEHAVIORS, width=20).pack(anchor='w'), 'AI module')
        self.v_mask = tk.StringVar()
        self._add('Observation Mask', lambda p: ttk.Combobox(p, textvariable=self.v_mask, values=MASKS, width=18).pack(anchor='w'), 'NN input mask (socially_deaf, blind, etc.)')

        self.v_unique = tk.BooleanVar(value=True)
        self._add('Unique', lambda p: ttk.Checkbutton(p, variable=self.v_unique).pack(anchor='w'), 'One-of-a-kind NPC')
        self.v_cumulative_limit = tk.StringVar(value='-1')
        self._add('Cumulative Limit', lambda p: ttk.Entry(p, textvariable=self.v_cumulative_limit, width=8).pack(anchor='w'),
                  'Lifetime spawn limit (-1 = infinite, 1 = unique)')
        self.v_concurrent_limit = tk.StringVar(value='-1')
        self._add('Concurrent Limit', lambda p: ttk.Entry(p, textvariable=self.v_concurrent_limit, width=8).pack(anchor='w'),
                  'Max alive at once (-1 = no limit)')

        self.v_dialogue = tk.StringVar()
        self._add('Dialogue Tree', lambda p: ttk.Entry(p, textvariable=self.v_dialogue, width=20).pack(anchor='w'), 'Default conversation name')

        self.v_spawn_map = tk.StringVar()
        self._map_names = [''] + fetch_map_names()
        self._add('Spawn Map', lambda p: ttk.Combobox(p, textvariable=self.v_spawn_map, values=self._map_names, width=18).pack(anchor='w'), 'Starting map')
        self.v_spawn_x = tk.StringVar()
        self.v_spawn_y = tk.StringVar()
        self._add('Spawn X, Y', lambda p: (
            ttk.Entry(p, textvariable=self.v_spawn_x, width=5).pack(side=tk.LEFT, padx=(0,4)),
            ttk.Entry(p, textvariable=self.v_spawn_y, width=5).pack(side=tk.LEFT),
        ), 'Starting position')

        self.v_items = tk.StringVar(value='[]')
        self._add('Items (JSON)', lambda p: ttk.Entry(p, textvariable=self.v_items, width=40).pack(anchor='w'), 'Starting inventory item keys')

        # Stats
        ttk.Separator(self.form, orient=tk.HORIZONTAL).grid(row=self._row, column=0, columnspan=2, sticky='ew', padx=6, pady=6); self._row += 1
        ttk.Label(self.form, text='Stat Overrides (blank = species default)', font=('TkDefaultFont', 9, 'bold')).grid(row=self._row, column=0, columnspan=2, sticky='w', padx=6); self._row += 1

        self.stat_vars = {}
        for stat in STATS:
            var = tk.StringVar()
            self.stat_vars[stat] = var
            self._add(STAT_LABELS[stat], lambda p, v=var: ttk.Entry(p, textvariable=v, width=8).pack(anchor='w'), f'Override {stat}')

        self.form.columnconfigure(1, weight=1)

    def _on_species_changed(self, event=None):
        """Auto-populate defaults from species when selected."""
        species = self.v_species.get().strip()
        if not species: return
        con = get_con()
        try:
            row = con.execute('SELECT * FROM species WHERE name=?', (species,)).fetchone()
            if not row: return
            stats = con.execute('SELECT stat, value FROM species_stats WHERE species_name=?', (species,)).fetchall()
        finally:
            con.close()

        # Only populate BLANK fields — don't overwrite user input
        if not self.v_prudishness.get().strip():
            self.v_prudishness.set(str(row['prudishness'] if row['prudishness'] is not None else ''))
        if not self.v_deity.get().strip() and row['preferred_deity']:
            self.v_deity.set(row['preferred_deity'])

        # Populate stats only if blank
        stat_map = {r['stat']: r['value'] for r in stats}
        for stat, var in self.stat_vars.items():
            if not var.get().strip() and stat in stat_map:
                var.set(str(stat_map[stat]))

    def _float(self, var, default=None):
        txt = var.get().strip()
        if not txt: return default
        try: return float(txt)
        except: return default

    def _int(self, var, default=None):
        txt = var.get().strip()
        if not txt: return default
        try: return int(txt)
        except: return default

    def refresh_list(self):
        con = get_con()
        try:
            rows = con.execute('SELECT key, name, species, title FROM creatures ORDER BY species, key').fetchall()
        finally:
            con.close()
        self.listbox.delete(0, tk.END)
        for r in rows:
            label = f"[{r['species']}] {r['key']}"
            if r['title']: label += f" ({r['title']})"
            elif r['name']: label += f" ({r['name']})"
            self.listbox.insert(tk.END, label)

    def refresh_species_dropdown(self):
        self._species_names = fetch_species_names()
        self.species_cb['values'] = self._species_names
        self._map_names = [''] + fetch_map_names()

    def _clear(self):
        self.v_key.set(''); self.v_name.set(''); self.v_title.set('')
        self.v_description.set(''); self.v_species.set(''); self.v_level.set('')
        self.v_sex.set(''); self.v_age.set(''); self.v_prudishness.set('')
        self.v_gold.set(''); self.v_deity.set(''); self.v_piety.set('')
        self.v_behavior.set(''); self.v_mask.set(''); self.v_unique.set(True)
        self.v_cumulative_limit.set('-1'); self.v_concurrent_limit.set('-1')
        self.v_dialogue.set(''); self.v_spawn_map.set('')
        self.v_spawn_x.set(''); self.v_spawn_y.set(''); self.v_items.set('[]')
        for var in self.stat_vars.values(): var.set('')

    def _populate(self, key):
        con = get_con()
        try:
            row = con.execute('SELECT * FROM creatures WHERE key=?', (key,)).fetchone()
            if not row: return
            stats = con.execute('SELECT stat, value FROM creature_stats WHERE creature_key=?', (key,)).fetchall()
        finally:
            con.close()
        self.v_key.set(row['key']); self.v_name.set(row['name'] or '')
        self.v_title.set(row['title'] or ''); self.v_description.set(row['description'] or '')
        self.v_species.set(row['species'] or ''); self.v_level.set(str(row['level']) if row['level'] is not None else '')
        self.v_sex.set(row['sex'] or ''); self.v_age.set(str(row['age']) if row['age'] is not None else '')
        self.v_prudishness.set(str(row['prudishness']) if row['prudishness'] is not None else '')
        self.v_gold.set(str(row['gold']) if row['gold'] is not None else '')
        self.v_deity.set(row['deity'] or ''); self.v_piety.set(str(row['piety']) if row['piety'] is not None else '')
        self.v_behavior.set(row['behavior'] or ''); self.v_mask.set(row['observation_mask'] or '')
        self.v_unique.set(bool(row['is_unique']))
        self.v_cumulative_limit.set(str(row['cumulative_limit'] if row['cumulative_limit'] is not None else -1))
        self.v_concurrent_limit.set(str(row['concurrent_limit'] if row['concurrent_limit'] is not None else -1))
        self.v_dialogue.set(row['dialogue_tree'] or '')
        self.v_spawn_map.set(row['spawn_map'] or '')
        self.v_spawn_x.set(str(row['spawn_x']) if row['spawn_x'] is not None else '')
        self.v_spawn_y.set(str(row['spawn_y']) if row['spawn_y'] is not None else '')
        self.v_items.set(row['items'] or '[]')
        stat_map = {r['stat']: r['value'] for r in stats}
        for stat, var in self.stat_vars.items():
            var.set(str(stat_map[stat]) if stat in stat_map else '')

    def _on_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel: return
        entry = self.listbox.get(sel[0])
        key = entry.split('] ', 1)[-1].split(' (')[0]
        self._populate(key)

    def _new(self):
        self.listbox.selection_clear(0, tk.END); self._clear()

    def _save(self):
        key = self.v_key.get().strip()
        if not key: messagebox.showerror('Validation', 'Key required.'); return
        species = self.v_species.get().strip()
        if not species: messagebox.showerror('Validation', 'Species required.'); return
        con = get_con()
        try:
            con.execute(
                '''INSERT INTO creatures (key, name, title, species, level, sex, age,
                   prudishness, behavior, items, deity, piety, gold, observation_mask,
                   is_unique, spawn_map, spawn_x, spawn_y, dialogue_tree, description,
                   cumulative_limit, concurrent_limit)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(key) DO UPDATE SET
                   name=excluded.name, title=excluded.title, species=excluded.species,
                   level=excluded.level, sex=excluded.sex, age=excluded.age,
                   prudishness=excluded.prudishness, behavior=excluded.behavior,
                   items=excluded.items, deity=excluded.deity, piety=excluded.piety,
                   gold=excluded.gold, observation_mask=excluded.observation_mask,
                   is_unique=excluded.is_unique, spawn_map=excluded.spawn_map,
                   spawn_x=excluded.spawn_x, spawn_y=excluded.spawn_y,
                   dialogue_tree=excluded.dialogue_tree, description=excluded.description,
                   cumulative_limit=excluded.cumulative_limit,
                   concurrent_limit=excluded.concurrent_limit
                ''',
                (key, self.v_name.get().strip(), self.v_title.get().strip(),
                 species, self._int(self.v_level), self.v_sex.get().strip() or None,
                 self._int(self.v_age), self._float(self.v_prudishness),
                 self.v_behavior.get().strip() or None, self.v_items.get().strip() or '[]',
                 self.v_deity.get().strip() or None, self._float(self.v_piety),
                 self._int(self.v_gold), self.v_mask.get().strip() or None,
                 int(self.v_unique.get()), self.v_spawn_map.get().strip() or None,
                 self._int(self.v_spawn_x), self._int(self.v_spawn_y),
                 self.v_dialogue.get().strip() or None, self.v_description.get().strip(),
                 self._int(self.v_cumulative_limit, -1),
                 self._int(self.v_concurrent_limit, -1)))
            # Stats
            con.execute('DELETE FROM creature_stats WHERE creature_key=?', (key,))
            for stat, var in self.stat_vars.items():
                txt = var.get().strip()
                if txt:
                    try: con.execute('INSERT INTO creature_stats VALUES (?,?,?)', (key, stat, int(txt)))
                    except ValueError: pass
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e)); return
        finally:
            con.close()
        self.refresh_list()

    def _delete(self):
        sel = self.listbox.curselection()
        if not sel: return
        entry = self.listbox.get(sel[0])
        key = entry.split('] ', 1)[-1].split(' (')[0]
        if not messagebox.askyesno('Delete', f'Delete NPC "{key}"?'): return
        con = get_con()
        try:
            con.execute('DELETE FROM creature_stats WHERE creature_key=?', (key,))
            con.execute('DELETE FROM creatures WHERE key=?', (key,))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e)); return
        finally:
            con.close()
        self.refresh_list(); self._clear()


# ============================================================================
# Master Tab
# ============================================================================

class CreaturesMasterTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True)

        self.species_tab = _SpeciesSubTab(nb)
        self.npc_tab = _NPCSubTab(nb)

        nb.add(self.species_tab, text='  Species  ')
        nb.add(self.npc_tab, text='  NPCs  ')

    def refresh_list(self):
        self.species_tab.refresh_list()
        self.npc_tab.refresh_list()

    def refresh_sprite_dropdown(self):
        self.species_tab.refresh_sprite_dropdown()

    def refresh_species_dropdown(self):
        self.npc_tab.refresh_species_dropdown()
