import json
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

from editor.db import get_con, fetch_sprite_names, fetch_animation_names, fetch_species_names, fetch_creature_keys
from editor.sprite_preview import SpritePreview
from editor.tooltip import add_tooltip
from editor.constants import PREVIEW_SIZE

TARGET_TYPES = ['self', 'single', 'area']
EFFECT_TYPES = ['damage', 'heal', 'buff', 'debuff']
RESIST_TYPES = ['', 'poison resist', 'disease resist', 'fear resist', 'stagger resist']


class SpellsTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()
        self.refresh_list()

    def _build_ui(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        left = ttk.Frame(pane, width=200)
        pane.add(left, weight=0)

        ttk.Label(left, text='Spells').pack(anchor='w')
        list_frame = ttk.Frame(left)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.listbox = tk.Listbox(list_frame, exportselection=False, width=24)
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.bind('<<ListboxSelect>>', self._on_select)
        self.listbox.bind('<Shift-Delete>', lambda e: self._delete())

        btn_row = ttk.Frame(left)
        btn_row.pack(fill=tk.X, pady=4)
        btn_new = ttk.Button(btn_row, text='New', command=self._new)
        btn_new.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_new, 'Clear form to create a new spell')
        btn_save = ttk.Button(btn_row, text='Save', command=self._save)
        btn_save.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_save, 'Save the current spell to the database')
        btn_del = ttk.Button(btn_row, text='Delete', command=self._delete)
        btn_del.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_del, 'Delete the selected spell')

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
        row = 0

        def add_row(label, widget_fn, tip=None):
            nonlocal row
            ttk.Label(f, text=label).grid(row=row, column=0, sticky='w', padx=6, pady=2)
            frm = ttk.Frame(f)
            frm.grid(row=row, column=1, sticky='ew', padx=6, pady=2)
            widget_fn(frm)
            if tip:
                add_tooltip(frm, tip)
            row += 1

        self.v_key = tk.StringVar()
        add_row('Key', lambda p: ttk.Entry(p, textvariable=self.v_key, width=30).pack(anchor='w'),
                'Unique spell identifier')

        self.v_name = tk.StringVar()
        add_row('Name', lambda p: ttk.Entry(p, textvariable=self.v_name, width=30).pack(anchor='w'),
                'Display name')

        self.v_description = tk.StringVar()
        add_row('Description', lambda p: ttk.Entry(p, textvariable=self.v_description, width=40).pack(anchor='w'),
                'Flavour text shown to the player')

        self.v_action_word = tk.StringVar(value='cast')
        add_row('Action Word', lambda p: ttk.Entry(p, textvariable=self.v_action_word, width=20).pack(anchor='w'),
                'Verb for this spell (e.g. "conjure", "invoke", "channel")')

        self.v_target_type = tk.StringVar(value='single')
        add_row('Target Type', lambda p: ttk.Combobox(p, textvariable=self.v_target_type,
                values=TARGET_TYPES, state='readonly', width=10).pack(anchor='w'),
                'self = caster only, single = one target, area = radius around target')

        self.v_effect_type = tk.StringVar(value='damage')
        add_row('Effect Type', lambda p: ttk.Combobox(p, textvariable=self.v_effect_type,
                values=EFFECT_TYPES, state='readonly', width=10).pack(anchor='w'),
                'What the spell does: damage, heal, buff, or debuff')

        self.v_damage = tk.StringVar(value='0')
        add_row('Damage/Heal', lambda p: ttk.Entry(p, textvariable=self.v_damage, width=10).pack(anchor='w'),
                'Base damage or heal amount (+ MAGIC_DMG modifier)')

        self.v_mana_cost = tk.StringVar(value='0')
        add_row('Mana Cost', lambda p: ttk.Entry(p, textvariable=self.v_mana_cost, width=10).pack(anchor='w'),
                'Mana consumed per cast')

        self.v_stamina_cost = tk.StringVar(value='0')
        add_row('Stamina Cost', lambda p: ttk.Entry(p, textvariable=self.v_stamina_cost, width=10).pack(anchor='w'),
                'Stamina consumed per cast (0 for most spells)')

        self.v_range = tk.StringVar(value='5')
        add_row('Range', lambda p: ttk.Entry(p, textvariable=self.v_range, width=10).pack(anchor='w'),
                'Maximum cast range in tiles')

        self.v_radius = tk.StringVar(value='0')
        add_row('Radius', lambda p: ttk.Entry(p, textvariable=self.v_radius, width=10).pack(anchor='w'),
                'Area of effect radius (0 = single target only)')

        self.v_spell_dc = tk.StringVar(value='10')
        add_row('Spell DC', lambda p: ttk.Entry(p, textvariable=self.v_spell_dc, width=10).pack(anchor='w'),
                'Difficulty class vs MAGIC_RESIST')

        self.v_dodgeable = tk.BooleanVar(value=True)
        add_row('Dodgeable', lambda p: ttk.Checkbutton(p, variable=self.v_dodgeable).pack(anchor='w'),
                'Can the target dodge this spell? (accuracy vs dodge contest)')

        self.v_buffs = tk.StringVar(value='{}')
        add_row('Buffs/Debuffs', lambda p: ttk.Entry(p, textvariable=self.v_buffs, width=40).pack(anchor='w'),
                'JSON stat modifiers for buff/debuff spells, e.g. {"strength": 4, "agility": -2}')

        self.v_duration = tk.StringVar(value='0')
        add_row('Duration', lambda p: ttk.Entry(p, textvariable=self.v_duration, width=10).pack(anchor='w'),
                'Effect duration in seconds (0 = instant)')

        self.v_secondary_resist = tk.StringVar()
        add_row('Secondary Resist', lambda p: ttk.Combobox(p, textvariable=self.v_secondary_resist,
                values=RESIST_TYPES, width=18).pack(anchor='w'),
                'Secondary resist check (e.g. poison resist for a poison spell)')

        self.v_secondary_dc = tk.StringVar()
        add_row('Secondary DC', lambda p: ttk.Entry(p, textvariable=self.v_secondary_dc, width=10).pack(anchor='w'),
                'DC for secondary resist check')

        self.v_requirements = tk.StringVar(value='{}')
        add_row('Requirements', lambda p: ttk.Entry(p, textvariable=self.v_requirements, width=40).pack(anchor='w'),
                'JSON stat requirements to cast, e.g. {"intelligence": 14}')

        self.v_sprite = tk.StringVar()
        self._sprite_names = [''] + fetch_sprite_names()
        def _build_sprite(p):
            self.spell_sprite_cb = ttk.Combobox(p, textvariable=self.v_sprite,
                                                values=self._sprite_names, state='readonly', width=18)
            self.spell_sprite_cb.pack(side=tk.LEFT, padx=(0, 8))
            self.spell_sprite_preview = SpritePreview(p, size=PREVIEW_SIZE)
            self.spell_sprite_preview.pack(side=tk.LEFT)
            self.spell_sprite_cb.bind('<<ComboboxSelected>>',
                                      lambda e: self.spell_sprite_preview.load(self.v_sprite.get() or None))
        add_row('Sprite', _build_sprite, 'Projectile/effect sprite')

        self.v_animation = tk.StringVar()
        self._anim_names = [''] + fetch_animation_names()
        add_row('Animation', lambda p: ttk.Combobox(p, textvariable=self.v_animation,
                values=self._anim_names, state='readonly', width=18).pack(anchor='w'),
                'Spell cast animation')

        self.v_composite = tk.StringVar()
        add_row('Composite', lambda p: ttk.Entry(p, textvariable=self.v_composite, width=18).pack(anchor='w'),
                'Composite sprite for spell effect')

        f.columnconfigure(1, weight=1)

    def _float(self, var, default=0.0):
        try: return float(var.get())
        except (ValueError, TypeError): return default

    def _int(self, var, default=0):
        try: return int(var.get())
        except (ValueError, TypeError): return default

    def refresh_list(self):
        con = get_con()
        try:
            rows = con.execute('SELECT key, name FROM spells ORDER BY key').fetchall()
        finally:
            con.close()
        self.listbox.delete(0, tk.END)
        for r in rows:
            self.listbox.insert(tk.END, f"{r['key']} — {r['name']}" if r['name'] else r['key'])

    def refresh_sprite_dropdown(self):
        self._sprite_names = [''] + fetch_sprite_names()
        self.spell_sprite_cb['values'] = self._sprite_names
        self._anim_names = [''] + fetch_animation_names()

    def _clear_form(self):
        self.v_key.set(''); self.v_name.set(''); self.v_description.set('')
        self.v_action_word.set('cast'); self.v_target_type.set('single')
        self.v_effect_type.set('damage'); self.v_damage.set('0')
        self.v_mana_cost.set('0'); self.v_stamina_cost.set('0')
        self.v_range.set('5'); self.v_radius.set('0'); self.v_spell_dc.set('10')
        self.v_dodgeable.set(True); self.v_buffs.set('{}'); self.v_duration.set('0')
        self.v_secondary_resist.set(''); self.v_secondary_dc.set('')
        self.v_requirements.set('{}'); self.v_sprite.set('')
        self.v_animation.set(''); self.v_composite.set('')
        self.spell_sprite_preview.load(None)

    def _populate_form(self, key):
        con = get_con()
        try:
            row = con.execute('SELECT * FROM spells WHERE key=?', (key,)).fetchone()
        finally:
            con.close()
        if row is None:
            return
        self.v_key.set(row['key']); self.v_name.set(row['name'] or '')
        self.v_description.set(row['description'] or '')
        self.v_action_word.set(row['action_word'] or 'cast')
        self.v_target_type.set(row['target_type'] or 'single')
        self.v_effect_type.set(row['effect_type'] or 'damage')
        self.v_damage.set(str(row['damage'] or 0))
        self.v_mana_cost.set(str(row['mana_cost'] or 0))
        self.v_stamina_cost.set(str(row['stamina_cost'] or 0))
        self.v_range.set(str(row['range'] or 5))
        self.v_radius.set(str(row['radius'] or 0))
        self.v_spell_dc.set(str(row['spell_dc'] or 10))
        self.v_dodgeable.set(bool(row['dodgeable']))
        self.v_buffs.set(row['buffs'] or '{}')
        self.v_duration.set(str(row['duration'] or 0))
        self.v_secondary_resist.set(row['secondary_resist'] or '')
        self.v_secondary_dc.set(str(row['secondary_dc']) if row['secondary_dc'] is not None else '')
        self.v_requirements.set(row['requirements'] or '{}')
        self.v_sprite.set(row['sprite_name'] or '')
        self.spell_sprite_preview.load(row['sprite_name'] or None)
        self.v_animation.set(row['animation_name'] or '')
        self.v_composite.set(row['composite_name'] or '')

    def _on_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        entry = self.listbox.get(sel[0])
        key = entry.split(' — ')[0] if ' — ' in entry else entry
        self._populate_form(key)

    def _new(self):
        self.listbox.selection_clear(0, tk.END)
        self._clear_form()

    def _save(self):
        key = self.v_key.get().strip()
        if not key:
            messagebox.showerror('Validation', 'Key is required.')
            return
        con = get_con()
        try:
            con.execute(
                '''INSERT INTO spells
                   (key, name, description, action_word, damage, mana_cost, stamina_cost,
                    range, radius, spell_dc, dodgeable, target_type, effect_type,
                    buffs, duration, secondary_resist, secondary_dc, requirements,
                    sprite_name, animation_name, composite_name)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(key) DO UPDATE SET
                   name=excluded.name, description=excluded.description,
                   action_word=excluded.action_word, damage=excluded.damage,
                   mana_cost=excluded.mana_cost, stamina_cost=excluded.stamina_cost,
                   range=excluded.range, radius=excluded.radius, spell_dc=excluded.spell_dc,
                   dodgeable=excluded.dodgeable, target_type=excluded.target_type,
                   effect_type=excluded.effect_type, buffs=excluded.buffs,
                   duration=excluded.duration, secondary_resist=excluded.secondary_resist,
                   secondary_dc=excluded.secondary_dc, requirements=excluded.requirements,
                   sprite_name=excluded.sprite_name, animation_name=excluded.animation_name,
                   composite_name=excluded.composite_name
                ''',
                (
                    key, self.v_name.get().strip(), self.v_description.get().strip(),
                    self.v_action_word.get().strip() or 'cast',
                    self._float(self.v_damage), self._int(self.v_mana_cost),
                    self._int(self.v_stamina_cost), self._int(self.v_range, 5),
                    self._int(self.v_radius), self._int(self.v_spell_dc, 10),
                    int(self.v_dodgeable.get()), self.v_target_type.get(),
                    self.v_effect_type.get(), self.v_buffs.get().strip() or '{}',
                    self._float(self.v_duration),
                    self.v_secondary_resist.get().strip() or None,
                    self._int(self.v_secondary_dc) if self.v_secondary_dc.get().strip() else None,
                    self.v_requirements.get().strip() or '{}',
                    self.v_sprite.get().strip() or None,
                    self.v_animation.get().strip() or None,
                    self.v_composite.get().strip() or None,
                )
            )
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()
        entries = list(self.listbox.get(0, tk.END))
        for i, entry in enumerate(entries):
            if entry.startswith(key):
                self.listbox.selection_set(i)
                self.listbox.see(i)
                break

    def _delete(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning('Delete', 'Select a spell first.')
            return
        entry = self.listbox.get(sel[0])
        key = entry.split(' — ')[0] if ' — ' in entry else entry
        if not messagebox.askyesno('Delete', f'Delete spell "{key}"?'):
            return
        con = get_con()
        try:
            con.execute('DELETE FROM creature_spells WHERE spell_key=?', (key,))
            con.execute('DELETE FROM species_spells WHERE spell_key=?', (key,))
            con.execute('DELETE FROM spells WHERE key=?', (key,))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()
        self._clear_form()
