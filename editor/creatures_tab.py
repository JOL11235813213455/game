import json
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

from editor.db import get_con, fetch_species_names
from editor.constants import STATS, STAT_LABELS
from editor.tooltip import add_tooltip


BEHAVIORS = ['', 'RandomWanderBehavior']


class CreaturesTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()
        self.refresh_list()

    def _build_ui(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        left = ttk.Frame(pane, width=200)
        pane.add(left, weight=0)

        ttk.Label(left, text='Creatures').pack(anchor='w')
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
        add_tooltip(btn_new, 'Clear form to create a new creature template')
        btn_save = ttk.Button(btn_row, text='Save', command=self._save)
        btn_save.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_save, 'Save the current creature template to the database')
        btn_del = ttk.Button(btn_row, text='Delete', command=self._delete)
        btn_del.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_del, 'Delete the selected creature template')

        right = ttk.Frame(pane)
        pane.add(right, weight=1)

        f = right
        row = 0

        # Key
        ttk.Label(f, text='Key').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_key = tk.StringVar()
        e_key = ttk.Entry(f, textvariable=self.v_key, width=30)
        e_key.grid(row=row, column=1, sticky='ew', padx=6, pady=4)
        add_tooltip(e_key, 'Unique identifier for this creature template')
        row += 1

        # Name
        ttk.Label(f, text='Name').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_name = tk.StringVar()
        e_name = ttk.Entry(f, textvariable=self.v_name, width=30)
        e_name.grid(row=row, column=1, sticky='ew', padx=6, pady=4)
        add_tooltip(e_name, 'Display name for this creature')
        row += 1

        # Species
        ttk.Label(f, text='Species').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_species = tk.StringVar()
        self._species_names = fetch_species_names()
        self.species_cb = ttk.Combobox(f, textvariable=self.v_species,
                                       values=self._species_names, state='readonly', width=18)
        self.species_cb.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(self.species_cb, 'Species template this creature is based on')
        row += 1

        # Level
        ttk.Label(f, text='Level').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_level = tk.StringVar()
        e_level = ttk.Entry(f, textvariable=self.v_level, width=8)
        e_level.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(e_level, 'Creature level (blank = default from species)')
        row += 1

        # Sex
        ttk.Label(f, text='Sex').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_sex = tk.StringVar()
        sex_cb = ttk.Combobox(f, textvariable=self.v_sex,
                              values=['', 'male', 'female'],
                              state='readonly', width=10)
        sex_cb.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(sex_cb, 'Creature sex (blank = randomly assigned at spawn)')
        row += 1

        # Age
        ttk.Label(f, text='Age (days)').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_age = tk.StringVar()
        e_age = ttk.Entry(f, textvariable=self.v_age, width=8)
        e_age.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(e_age, 'Age in days (blank = 0, hatched from egg starts at 0)')
        row += 1

        # Prudishness
        ttk.Label(f, text='Prudishness').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_prudishness = tk.StringVar()
        e_prud = ttk.Entry(f, textvariable=self.v_prudishness, width=10)
        e_prud.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(e_prud, 'Override prudishness (0.0-1.0, blank = species default)')
        row += 1

        # Behavior
        ttk.Label(f, text='Behavior').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_behavior = tk.StringVar()
        beh_cb = ttk.Combobox(f, textvariable=self.v_behavior,
                              values=BEHAVIORS, width=20)
        beh_cb.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(beh_cb, 'Behavior module for this creature (blank = none/player)')
        row += 1

        # Job
        ttk.Label(f, text='Job').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_job = tk.StringVar()
        self.job_cb = ttk.Combobox(f, textvariable=self.v_job, values=[], width=20)
        self.job_cb.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(self.job_cb, 'Profession from the jobs catalog (blank = wanderer)')
        row += 1

        # Items
        ttk.Label(f, text='Items (JSON)').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_items = tk.StringVar(value='[]')
        e_items = ttk.Entry(f, textvariable=self.v_items, width=40)
        e_items.grid(row=row, column=1, sticky='ew', padx=6, pady=4)
        add_tooltip(e_items, 'JSON list of item keys this creature starts with, e.g. ["sword", "shield"]')
        row += 1

        # Stat overrides
        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky='ew', padx=6, pady=6)
        row += 1

        ttk.Label(f, text='Stat Overrides (blank = species default)',
                  font=('TkDefaultFont', 9, 'bold')).grid(
            row=row, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        row += 1

        self.stat_vars: dict[str, tk.StringVar] = {}
        stat_tips = {
            'strength': 'Physical power — override species default',
            'vitality': 'Toughness — override species default',
            'intelligence': 'Mental acuity — override species default',
            'agility': 'Speed and reflexes — override species default',
            'perception': 'Awareness — override species default',
            'charisma': 'Social influence — override species default',
            'luck': 'Fortune — override species default',
            'hit dice': 'Base HP dice — override species default',
        }
        for stat in STATS:
            ttk.Label(f, text=STAT_LABELS[stat]).grid(
                row=row, column=0, sticky='w', padx=6, pady=2)
            var = tk.StringVar()
            self.stat_vars[stat] = var
            e_stat = ttk.Entry(f, textvariable=var, width=8)
            e_stat.grid(row=row, column=1, sticky='w', padx=6, pady=2)
            add_tooltip(e_stat, stat_tips.get(stat, f'Override {stat} value'))
            row += 1

        f.columnconfigure(1, weight=1)

    def refresh_list(self):
        con = get_con()
        try:
            rows = con.execute('SELECT key, name, species FROM creatures ORDER BY species, key').fetchall()
            job_rows = con.execute('SELECT key FROM jobs ORDER BY key').fetchall()
        finally:
            con.close()
        self.listbox.delete(0, tk.END)
        for r in rows:
            label = f"[{r['species']}] {r['key']}"
            if r['name']:
                label += f" ({r['name']})"
            self.listbox.insert(tk.END, label)
        # Populate the job dropdown (blank = wanderer)
        self.job_cb['values'] = [''] + [j['key'] for j in job_rows]

    def refresh_species_dropdown(self):
        self._species_names = fetch_species_names()
        self.species_cb['values'] = self._species_names

    def _clear_form(self):
        self.v_key.set('')
        self.v_name.set('')
        self.v_species.set('')
        self.v_level.set('')
        self.v_sex.set('')
        self.v_age.set('')
        self.v_prudishness.set('')
        self.v_behavior.set('')
        self.v_job.set('')
        self.v_items.set('[]')
        for var in self.stat_vars.values():
            var.set('')

    def _populate_form(self, key: str):
        con = get_con()
        try:
            row = con.execute('SELECT * FROM creatures WHERE key=?', (key,)).fetchone()
            if row is None:
                return
            stat_rows = con.execute(
                'SELECT stat, value FROM creature_stats WHERE creature_key=?', (key,)
            ).fetchall()
        finally:
            con.close()

        self.v_key.set(row['key'])
        self.v_name.set(row['name'] or '')
        self.v_species.set(row['species'] or '')
        self.v_level.set(str(row['level']) if row['level'] is not None else '')
        self.v_sex.set(row['sex'] or '')
        self.v_age.set(str(row['age']) if row['age'] is not None else '')
        self.v_prudishness.set(str(row['prudishness']) if row['prudishness'] is not None else '')
        self.v_behavior.set(row['behavior'] or '')
        try:
            self.v_job.set(row['job_key'] or '')
        except (KeyError, IndexError):
            self.v_job.set('')
        self.v_items.set(row['items'] or '[]')

        stats = {r['stat']: r['value'] for r in stat_rows}
        for stat, var in self.stat_vars.items():
            val = stats.get(stat)
            var.set(str(val) if val is not None else '')

    def _on_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        entry = self.listbox.get(sel[0])
        # Extract key from "[species] key" or "[species] key (name)"
        after_bracket = entry.split('] ', 1)[-1]
        key = after_bracket.split(' (')[0]
        self._populate_form(key)

    def _new(self):
        self.listbox.selection_clear(0, tk.END)
        self._clear_form()

    def _int_or_none(self, var):
        txt = var.get().strip()
        if not txt:
            return None
        try:
            return int(txt)
        except ValueError:
            return None

    def _float_or_none(self, var):
        txt = var.get().strip()
        if not txt:
            return None
        try:
            return float(txt)
        except ValueError:
            return None

    def _save(self):
        key = self.v_key.get().strip()
        if not key:
            messagebox.showerror('Validation', 'Key is required.')
            return
        species = self.v_species.get().strip()
        if not species:
            messagebox.showerror('Validation', 'Species is required.')
            return

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
                '''INSERT INTO creatures (key, name, species, level, sex, age, prudishness, behavior, items, job_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                   name=excluded.name, species=excluded.species,
                   level=excluded.level, sex=excluded.sex, age=excluded.age,
                   prudishness=excluded.prudishness, behavior=excluded.behavior,
                   items=excluded.items, job_key=excluded.job_key
                ''',
                (
                    key,
                    self.v_name.get().strip(),
                    species,
                    self._int_or_none(self.v_level),
                    self.v_sex.get().strip() or None,
                    self._int_or_none(self.v_age),
                    self._float_or_none(self.v_prudishness),
                    self.v_behavior.get().strip() or None,
                    self.v_items.get().strip() or '[]',
                    self.v_job.get().strip() or None,
                )
            )
            con.execute('DELETE FROM creature_stats WHERE creature_key=?', (key,))
            for stat, val in stats.items():
                con.execute(
                    'INSERT INTO creature_stats VALUES (?, ?, ?)',
                    (key, stat, val)
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
            if entry.split('] ', 1)[-1].split(' (')[0] == key:
                self.listbox.selection_set(i)
                self.listbox.see(i)
                break

    def _delete(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning('Delete', 'Select a creature first.')
            return
        entry = self.listbox.get(sel[0])
        key = entry.split('] ', 1)[-1].split(' (')[0]
        if not messagebox.askyesno('Delete', f'Delete creature "{key}"?'):
            return
        con = get_con()
        try:
            con.execute('DELETE FROM creature_stats WHERE creature_key=?', (key,))
            con.execute('DELETE FROM creatures WHERE key=?', (key,))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()
        self._clear_form()
