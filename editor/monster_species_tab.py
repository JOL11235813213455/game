"""
Monster Species editor tab.

Parallel to SpeciesTab but for the monster_species table. Edits the
monster-specific fields: diet, compatible_tile, split_size,
territory_size + scaling toggle, dominance_type,
collapse_on_alpha_death, active_hours, swimming, ambush_tactics,
protect_young, natural_weapon_key.

Stats (STR/AGL/PER/VIT/INT/LCK + CHR=10) stored in
monster_species_stats just like species_stats.
"""
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

from editor.db import get_con, fetch_sprite_names
from editor.constants import STATS, STAT_LABELS
from editor.sprite_preview import SpritePreview
from editor.tooltip import add_tooltip


_SIZE_OPTIONS = ['tiny', 'small', 'medium', 'large', 'huge', 'colossal']
_DIET_OPTIONS = ['carnivore', 'herbivore', 'omnivore']
_DOMINANCE_OPTIONS = ['contest', 'fixed', 'none']
_ACTIVE_HOURS_OPTIONS = ['diurnal', 'nocturnal', 'crepuscular']


class MonsterSpeciesTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()
        self.refresh_list()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        left = ttk.Frame(pane, width=180)
        pane.add(left, weight=0)
        ttk.Label(left, text='Monster Species').pack(anchor='w')
        list_frame = ttk.Frame(left)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(list_frame, exportselection=False, width=22)
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL,
                           command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.bind('<<ListboxSelect>>', self._on_select)
        self.listbox.bind('<Shift-Delete>', lambda e: self._delete())

        btn_row = ttk.Frame(left)
        btn_row.pack(fill=tk.X, pady=4)
        btn_new = ttk.Button(btn_row, text='New', command=self._new)
        btn_new.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_new, 'Clear form to create a new monster species')
        btn_save = ttk.Button(btn_row, text='Save', command=self._save)
        btn_save.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_save, 'Save the current monster species')
        btn_del = ttk.Button(btn_row, text='Delete', command=self._delete)
        btn_del.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_del, 'Delete the selected monster species')

        right = ttk.Frame(pane)
        pane.add(right, weight=1)
        f = right
        row = 0

        ttk.Label(f, text='Name').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_name = tk.StringVar()
        e_name = ttk.Entry(f, textvariable=self.v_name, width=30)
        e_name.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(e_name, 'Unique species key (e.g. grey_wolf)')
        row += 1

        ttk.Label(f, text='Description').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_description = tk.StringVar()
        ttk.Entry(f, textvariable=self.v_description, width=60).grid(
            row=row, column=1, sticky='w', padx=6, pady=4)
        row += 1

        ttk.Label(f, text='Sprite').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_sprite = tk.StringVar()
        self.sprite_cb = ttk.Combobox(f, textvariable=self.v_sprite,
                                      values=[], state='normal', width=30)
        self.sprite_cb.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        row += 1

        # Sprite preview
        self.sprite_preview = SpritePreview(f, size=64)
        self.sprite_preview.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        row += 1
        self.v_sprite.trace_add('write',
                                lambda *a: self.sprite_preview.load(
                                    self.v_sprite.get() or None))

        ttk.Label(f, text='Size').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_size = tk.StringVar(value='medium')
        size_cb = ttk.Combobox(f, textvariable=self.v_size,
                               values=_SIZE_OPTIONS, state='readonly', width=12)
        size_cb.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(size_cb, 'Size affects collision footprint and default meat value')
        row += 1

        ttk.Label(f, text='Meat Value').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_meat_value = tk.StringVar()
        e_meat = ttk.Entry(f, textvariable=self.v_meat_value, width=10)
        e_meat.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(e_meat, 'Hunger restored when eaten. Blank = auto from size')
        row += 1

        ttk.Label(f, text='Diet').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_diet = tk.StringVar(value='carnivore')
        diet_cb = ttk.Combobox(f, textvariable=self.v_diet, values=_DIET_OPTIONS,
                               state='readonly', width=12)
        diet_cb.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(diet_cb, 'carnivore=meat only; herbivore=plants only; omnivore=either')
        row += 1

        ttk.Label(f, text='Compatible Tile').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_compatible_tile = tk.StringVar()
        e_compat = ttk.Entry(f, textvariable=self.v_compatible_tile, width=20)
        e_compat.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(e_compat, 'Tile purpose/resource type for grazing (e.g. flower, garbage)')
        row += 1

        # Pack dynamics
        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky='ew', padx=6, pady=6)
        row += 1
        ttk.Label(f, text='Pack Dynamics',
                  font=('TkDefaultFont', 9, 'bold')).grid(
            row=row, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        row += 1

        ttk.Label(f, text='Split Size').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_split_size = tk.StringVar(value='4')
        e_split = ttk.Entry(f, textvariable=self.v_split_size, width=8)
        e_split.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(e_split, 'Pack splits when size reaches this value (1 = solitary)')
        row += 1

        ttk.Label(f, text='Territory Size').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_territory_size = tk.StringVar(value='8.0')
        e_terr = ttk.Entry(f, textvariable=self.v_territory_size, width=8)
        e_terr.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(e_terr,
                    'MAX std-dev roaming radius (at pack.size = split_size-1 if scaling)')
        row += 1

        ttk.Label(f, text='Territory Scales').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_territory_scales = tk.BooleanVar(value=True)
        cb_scales = ttk.Checkbutton(f, variable=self.v_territory_scales)
        cb_scales.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(cb_scales,
                    'If checked, territory shrinks with pack size (wolves True, bees False)')
        row += 1

        ttk.Label(f, text='Dominance Type').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_dominance_type = tk.StringVar(value='contest')
        dom_cb = ttk.Combobox(f, textvariable=self.v_dominance_type,
                              values=_DOMINANCE_OPTIONS,
                              state='readonly', width=12)
        dom_cb.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(dom_cb,
                    'contest=fight for rank; fixed=caste (queen+workers); none=solitary')
        row += 1

        ttk.Label(f, text='Collapse on Alpha Death').grid(
            row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_collapse = tk.BooleanVar(value=False)
        cb_coll = ttk.Checkbutton(f, variable=self.v_collapse)
        cb_coll.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(cb_coll,
                    'If checked, pack disbands when alpha dies (bees, ants). '
                    'Unchecked = beta promotes (wolves, orcs)')
        row += 1

        # Behavior toggles
        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky='ew', padx=6, pady=6)
        row += 1
        ttk.Label(f, text='Behavior',
                  font=('TkDefaultFont', 9, 'bold')).grid(
            row=row, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        row += 1

        ttk.Label(f, text='Active Hours').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_active_hours = tk.StringVar(value='diurnal')
        act_cb = ttk.Combobox(f, textvariable=self.v_active_hours,
                              values=_ACTIVE_HOURS_OPTIONS,
                              state='readonly', width=12)
        act_cb.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(act_cb, 'diurnal=active in day, nocturnal=night, crepuscular=dawn/dusk')
        row += 1

        ttk.Label(f, text='Swimming').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_swimming = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, variable=self.v_swimming).grid(
            row=row, column=1, sticky='w', padx=6, pady=4)
        row += 1

        ttk.Label(f, text='Ambush Tactics').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_ambush = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, variable=self.v_ambush).grid(
            row=row, column=1, sticky='w', padx=6, pady=4)
        row += 1

        ttk.Label(f, text='Protect Young').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_protect_young = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, variable=self.v_protect_young).grid(
            row=row, column=1, sticky='w', padx=6, pady=4)
        row += 1

        ttk.Label(f, text='Natural Weapon Key').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_natural_weapon_key = tk.StringVar()
        e_weap = ttk.Entry(f, textvariable=self.v_natural_weapon_key, width=25)
        e_weap.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(e_weap, 'items.key of the natural weapon dropped on death')
        row += 1

        # Stats
        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky='ew', padx=6, pady=6)
        row += 1
        ttk.Label(f, text='Stats (blank = not set; CHR auto-set to 10)',
                  font=('TkDefaultFont', 9, 'bold')).grid(
            row=row, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        row += 1

        self.stat_vars: dict[str, tk.StringVar] = {}
        # Skip charisma — monsters default to neutral CHR=10
        for stat in STATS:
            if stat == 'charisma':
                continue
            ttk.Label(f, text=STAT_LABELS[stat]).grid(
                row=row, column=0, sticky='w', padx=6, pady=2)
            var = tk.StringVar()
            self.stat_vars[stat] = var
            e_stat = ttk.Entry(f, textvariable=var, width=8)
            e_stat.grid(row=row, column=1, sticky='w', padx=6, pady=2)
            row += 1

        f.columnconfigure(1, weight=1)

    # ------------------------------------------------------------------
    # List management
    # ------------------------------------------------------------------

    def refresh_list(self):
        self.listbox.delete(0, tk.END)
        con = get_con()
        try:
            rows = con.execute(
                'SELECT name FROM monster_species ORDER BY name').fetchall()
        finally:
            con.close()
        for r in rows:
            self.listbox.insert(tk.END, r['name'])
        # Refresh sprite dropdown
        self.sprite_cb['values'] = fetch_sprite_names()

    def _on_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        self._populate_form(self.listbox.get(sel[0]))

    def _new(self):
        self.listbox.selection_clear(0, tk.END)
        self._clear_form()

    # ------------------------------------------------------------------
    # Form populate / clear / save / delete
    # ------------------------------------------------------------------

    def _clear_form(self):
        self.v_name.set('')
        self.v_description.set('')
        self.v_sprite.set('')
        self.sprite_preview.load(None)
        self.v_size.set('medium')
        self.v_meat_value.set('')
        self.v_diet.set('carnivore')
        self.v_compatible_tile.set('')
        self.v_split_size.set('4')
        self.v_territory_size.set('8.0')
        self.v_territory_scales.set(True)
        self.v_dominance_type.set('contest')
        self.v_collapse.set(False)
        self.v_active_hours.set('diurnal')
        self.v_swimming.set(False)
        self.v_ambush.set(False)
        self.v_protect_young.set(True)
        self.v_natural_weapon_key.set('')
        for var in self.stat_vars.values():
            var.set('')

    def _populate_form(self, name: str):
        con = get_con()
        try:
            row = con.execute(
                'SELECT * FROM monster_species WHERE name=?', (name,)
            ).fetchone()
            if row is None:
                return
            stat_rows = con.execute(
                'SELECT stat, value FROM monster_species_stats '
                'WHERE species_name=?', (name,)
            ).fetchall()
        finally:
            con.close()

        self.v_name.set(row['name'])
        self.v_description.set(row['description'] or '')
        self.v_sprite.set(row['sprite_name'] or '')
        self.sprite_preview.load(row['sprite_name'] or None)
        self.v_size.set(row['size'] or 'medium')
        self.v_meat_value.set(str(row['meat_value'])
                              if row['meat_value'] is not None else '')
        self.v_diet.set(row['diet'] or 'carnivore')
        self.v_compatible_tile.set(row['compatible_tile'] or '')
        self.v_split_size.set(str(row['split_size']))
        self.v_territory_size.set(str(row['territory_size']))
        self.v_territory_scales.set(bool(row['territory_scales']))
        self.v_dominance_type.set(row['dominance_type'] or 'contest')
        self.v_collapse.set(bool(row['collapse_on_alpha_death']))
        self.v_active_hours.set(row['active_hours'] or 'diurnal')
        self.v_swimming.set(bool(row['swimming']))
        self.v_ambush.set(bool(row['ambush_tactics']))
        self.v_protect_young.set(bool(row['protect_young']))
        self.v_natural_weapon_key.set(row['natural_weapon_key'] or '')

        stats = {r['stat']: r['value'] for r in stat_rows}
        for stat, var in self.stat_vars.items():
            v = stats.get(stat)
            var.set(str(v) if v is not None else '')

    def _save(self):
        name = self.v_name.get().strip()
        if not name:
            messagebox.showerror('Validation', 'Name is required.')
            return

        try:
            meat_value = (float(self.v_meat_value.get())
                          if self.v_meat_value.get().strip() else None)
        except ValueError:
            meat_value = None
        try:
            split_size = int(self.v_split_size.get())
        except ValueError:
            split_size = 4
        try:
            territory_size = float(self.v_territory_size.get())
        except ValueError:
            territory_size = 8.0

        stats = {'charisma': 10}  # always neutral CHR for monsters
        for stat, var in self.stat_vars.items():
            txt = var.get().strip()
            if txt:
                try:
                    stats[stat] = int(txt)
                except ValueError:
                    messagebox.showerror(
                        'Validation', f'Stat {stat}: must be an integer.')
                    return

        con = get_con()
        try:
            con.execute(
                '''INSERT OR REPLACE INTO monster_species
                   (name, sprite_name, composite_name, tile_scale, size,
                    description, meat_value, diet, compatible_tile,
                    split_size, territory_size, territory_scales,
                    dominance_type, collapse_on_alpha_death, active_hours,
                    swimming, ambush_tactics, protect_young,
                    natural_weapon_key, egg_sprite)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (name,
                 self.v_sprite.get().strip() or None,
                 None,   # composite_name
                 1.0,    # tile_scale
                 self.v_size.get() or 'medium',
                 self.v_description.get() or '',
                 meat_value,
                 self.v_diet.get() or 'carnivore',
                 self.v_compatible_tile.get().strip() or None,
                 split_size,
                 territory_size,
                 1 if self.v_territory_scales.get() else 0,
                 self.v_dominance_type.get() or 'contest',
                 1 if self.v_collapse.get() else 0,
                 self.v_active_hours.get() or 'diurnal',
                 1 if self.v_swimming.get() else 0,
                 1 if self.v_ambush.get() else 0,
                 1 if self.v_protect_young.get() else 0,
                 self.v_natural_weapon_key.get().strip() or None,
                 None,   # egg_sprite
                 )
            )
            con.execute('DELETE FROM monster_species_stats WHERE species_name=?',
                        (name,))
            for stat, val in stats.items():
                con.execute(
                    'INSERT INTO monster_species_stats VALUES (?,?,?)',
                    (name, stat, val)
                )
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()

        self.refresh_list()
        # Re-select
        try:
            idx = list(self.listbox.get(0, tk.END)).index(name)
            self.listbox.selection_set(idx)
        except ValueError:
            pass

    def _delete(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        name = self.listbox.get(sel[0])
        if not messagebox.askyesno(
                'Confirm', f'Delete monster species "{name}"?'):
            return
        con = get_con()
        try:
            con.execute('DELETE FROM monster_species_stats WHERE species_name=?',
                        (name,))
            con.execute('DELETE FROM monster_species WHERE name=?', (name,))
            con.commit()
        finally:
            con.close()
        self.refresh_list()
        self._clear_form()
