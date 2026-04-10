"""Jobs editor tab — CRUD for the jobs catalog.

Jobs describe NPC professions: purpose, wage, stat requirements,
schedule template. They're used by the RL arena generator and
(eventually) by any NPC spawned into a game-world map.
"""
import json
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

from editor.db import get_con
from editor.tooltip import add_tooltip


# Must match the purpose list in src/classes/actions.py TILE_PURPOSES
_PURPOSES = (
    'trading', 'farming', 'hunting', 'worship', 'eating',
    'sleeping', 'pairing', 'crafting', 'mining', 'fishing',
    'gathering', 'training', 'healing', 'guarding',
    'socializing', 'gossiping', 'exploring',
)

_STATS = ('STR', 'VIT', 'AGL', 'PER', 'INT', 'CHR', 'LCK')
_SCHEDULE_TEMPLATES = ('day_worker', 'night_worker', 'wanderer')


class JobsTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()
        self.refresh_list()

    def _build_ui(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        left = ttk.Frame(pane, width=200)
        pane.add(left, weight=0)

        ttk.Label(left, text='Jobs').pack(anchor='w')
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
        add_tooltip(btn_new, 'Clear form to create a new job')
        btn_save = ttk.Button(btn_row, text='Save', command=self._save)
        btn_save.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_save, 'Save the current job to the database')
        btn_del = ttk.Button(btn_row, text='Delete', command=self._delete)
        btn_del.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_del, 'Delete the selected job')

        right = ttk.Frame(pane)
        pane.add(right, weight=1)

        f = right
        row = 0

        ttk.Label(f, text='Key').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_key = tk.StringVar()
        e = ttk.Entry(f, textvariable=self.v_key, width=24)
        e.grid(row=row, column=1, sticky='ew', padx=6, pady=4)
        add_tooltip(e, 'Unique job identifier (lowercase, e.g. farmer, guard_captain)')
        row += 1

        ttk.Label(f, text='Name').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_name = tk.StringVar()
        e = ttk.Entry(f, textvariable=self.v_name, width=24)
        e.grid(row=row, column=1, sticky='ew', padx=6, pady=4)
        add_tooltip(e, 'Display name (e.g. "Farmer")')
        row += 1

        ttk.Label(f, text='Description').grid(row=row, column=0, sticky='nw', padx=6, pady=4)
        self.v_description = tk.StringVar()
        e = ttk.Entry(f, textvariable=self.v_description, width=48)
        e.grid(row=row, column=1, sticky='ew', padx=6, pady=4)
        add_tooltip(e, 'Flavor text shown in the editor and tooltips')
        row += 1

        ttk.Label(f, text='Purpose').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_purpose = tk.StringVar()
        cb = ttk.Combobox(f, textvariable=self.v_purpose, values=_PURPOSES, width=20)
        cb.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(cb, 'Primary tile purpose this job aligns with')
        row += 1

        ttk.Label(f, text='Wage / tick').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_wage = tk.StringVar(value='1.0')
        e = ttk.Entry(f, textvariable=self.v_wage, width=10)
        e.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(e, 'Gold paid per successful JOB tick during work hours')
        row += 1

        ttk.Label(f, text='Required Stat').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_req_stat = tk.StringVar(value='STR')
        cb = ttk.Combobox(f, textvariable=self.v_req_stat, values=_STATS, width=8)
        cb.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(cb, 'Which stat gates qualification for this job')
        row += 1

        ttk.Label(f, text='Required Level').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_req_level = tk.StringVar(value='8')
        e = ttk.Entry(f, textvariable=self.v_req_level, width=10)
        e.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(e, 'Minimum required stat value to qualify')
        row += 1

        ttk.Label(f, text='Workplace Purposes').grid(row=row, column=0, sticky='nw', padx=6, pady=4)
        self.v_workplaces = tk.StringVar(value='[]')
        e = ttk.Entry(f, textvariable=self.v_workplaces, width=48)
        e.grid(row=row, column=1, sticky='ew', padx=6, pady=4)
        add_tooltip(e, 'JSON list of tile purposes counted as "at work", e.g. ["farming"] or ["farming","gathering"]')
        row += 1

        ttk.Label(f, text='Schedule').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_schedule = tk.StringVar(value='day_worker')
        cb = ttk.Combobox(f, textvariable=self.v_schedule,
                          values=_SCHEDULE_TEMPLATES, width=16)
        cb.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(cb, 'Daily schedule template: day_worker (08-17 + sleep), '
                        'night_worker (dusk-dawn shift), wanderer (no work)')
        row += 1

        f.columnconfigure(1, weight=1)

    def refresh_list(self):
        con = get_con()
        try:
            rows = con.execute(
                'SELECT key, name, purpose FROM jobs ORDER BY key'
            ).fetchall()
        finally:
            con.close()
        self.listbox.delete(0, tk.END)
        for r in rows:
            self.listbox.insert(tk.END, f"{r['key']}  ({r['purpose']})")

    def _clear_form(self):
        self.v_key.set('')
        self.v_name.set('')
        self.v_description.set('')
        self.v_purpose.set('')
        self.v_wage.set('1.0')
        self.v_req_stat.set('STR')
        self.v_req_level.set('8')
        self.v_workplaces.set('[]')
        self.v_schedule.set('day_worker')

    def _populate_form(self, key):
        con = get_con()
        try:
            row = con.execute('SELECT * FROM jobs WHERE key=?', (key,)).fetchone()
        finally:
            con.close()
        if row is None:
            return
        self.v_key.set(row['key'])
        self.v_name.set(row['name'] or '')
        self.v_description.set(row['description'] or '')
        self.v_purpose.set(row['purpose'] or '')
        self.v_wage.set(str(row['wage_per_tick'] or 1.0))
        self.v_req_stat.set(row['required_stat'] or 'STR')
        self.v_req_level.set(str(row['required_level'] or 8))
        self.v_workplaces.set(row['workplace_purposes'] or '[]')
        self.v_schedule.set(row['schedule_template'] or 'day_worker')

    def _on_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        key = self.listbox.get(sel[0]).split('  ')[0]
        self._populate_form(key)

    def _new(self):
        self.listbox.selection_clear(0, tk.END)
        self._clear_form()

    def _save(self):
        key = self.v_key.get().strip()
        if not key:
            messagebox.showerror('Validation', 'Key is required.')
            return
        purpose = self.v_purpose.get().strip()
        if not purpose:
            messagebox.showerror('Validation', 'Purpose is required.')
            return
        try:
            wage = float(self.v_wage.get())
            req_level = int(self.v_req_level.get())
        except ValueError:
            messagebox.showerror('Validation', 'Wage must be a number and level an integer.')
            return
        # Validate workplaces as JSON list
        try:
            workplaces = json.loads(self.v_workplaces.get() or '[]')
            if not isinstance(workplaces, list):
                raise ValueError()
        except (ValueError, json.JSONDecodeError):
            messagebox.showerror('Validation', 'Workplace Purposes must be a JSON list.')
            return
        con = get_con()
        try:
            con.execute(
                '''INSERT INTO jobs (key, name, description, purpose,
                   wage_per_tick, required_stat, required_level,
                   workplace_purposes, schedule_template)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(key) DO UPDATE SET
                   name=excluded.name, description=excluded.description,
                   purpose=excluded.purpose, wage_per_tick=excluded.wage_per_tick,
                   required_stat=excluded.required_stat,
                   required_level=excluded.required_level,
                   workplace_purposes=excluded.workplace_purposes,
                   schedule_template=excluded.schedule_template
                ''',
                (key, self.v_name.get().strip(),
                 self.v_description.get().strip(),
                 purpose, wage,
                 self.v_req_stat.get().strip() or 'STR',
                 req_level,
                 json.dumps(workplaces),
                 self.v_schedule.get().strip() or 'day_worker')
            )
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()

    def _delete(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning('Delete', 'Select a job first.')
            return
        key = self.listbox.get(sel[0]).split('  ')[0]
        if not messagebox.askyesno('Delete', f'Delete job "{key}"?'):
            return
        con = get_con()
        try:
            con.execute('DELETE FROM jobs WHERE key=?', (key,))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()
        self._clear_form()
