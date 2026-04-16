"""
Training Pairs tab.

A training pair binds specific versions of all four NN models together:
  - CreatureNet (creature action policy)
  - GoalNet     (creature goal selection)
  - MonsterNet  (monster action policy)
  - PackNet     (pack coordination)

Pairs are named (e.g. 'p001') and advance stage-by-stage through the
curriculum. At any point, the pair points to specific (name, version)
tuples in nn_models for each component. Training a stage advances only
the models that participate in that stage (creature stages advance
CreatureNet+GoalNet; monster stages advance MonsterNet+PackNet;
co-evolution advances all four).

This tab is a lightweight editor for the training_pairs table. Training
execution is handled by the curriculum/standard training tabs which
read the active pair.
"""
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

from editor.db import get_con
from editor.tooltip import add_tooltip


class TrainingPairsTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()
        self.refresh_list()

    def _build_ui(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        left = ttk.Frame(pane, width=180)
        pane.add(left, weight=0)
        ttk.Label(left, text='Training Pairs').pack(anchor='w')

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
        add_tooltip(btn_new, 'Clear form to create a new training pair')
        btn_save = ttk.Button(btn_row, text='Save', command=self._save)
        btn_save.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_save, 'Save pair to DB')
        btn_del = ttk.Button(btn_row, text='Delete', command=self._delete)
        btn_del.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_del, 'Delete selected pair')

        right = ttk.Frame(pane)
        pane.add(right, weight=1)
        f = right
        row = 0

        ttk.Label(f, text='Pair Name').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_name = tk.StringVar()
        ttk.Entry(f, textvariable=self.v_name, width=30).grid(
            row=row, column=1, sticky='w', padx=6, pady=4)
        row += 1

        ttk.Label(f, text='Current Stage').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_current_stage = tk.StringVar(value='1')
        e_cs = ttk.Entry(f, textvariable=self.v_current_stage, width=8)
        e_cs.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(e_cs, 'Next stage to run (1-25)')
        row += 1

        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky='ew', padx=6, pady=6)
        row += 1
        ttk.Label(f, text='Bound Models (nn_models refs)',
                  font=('TkDefaultFont', 9, 'bold')).grid(
            row=row, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        row += 1

        # Each component has a (name, version) pair
        self._model_vars = {}
        for component in ['creature_model', 'goal_model',
                          'monster_model', 'pack_model']:
            ttk.Label(f, text=component.replace('_', ' ').title()).grid(
                row=row, column=0, sticky='w', padx=6, pady=4)
            name_var = tk.StringVar()
            ver_var = tk.StringVar()
            self._model_vars[component] = (name_var, ver_var)
            entry_row = ttk.Frame(f)
            entry_row.grid(row=row, column=1, sticky='w', padx=6, pady=4)
            ttk.Entry(entry_row, textvariable=name_var, width=20).pack(side=tk.LEFT)
            ttk.Label(entry_row, text='  v').pack(side=tk.LEFT)
            ttk.Entry(entry_row, textvariable=ver_var, width=5).pack(side=tk.LEFT)
            row += 1

        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky='ew', padx=6, pady=6)
        row += 1
        ttk.Label(f, text='Notes').grid(row=row, column=0, sticky='nw', padx=6, pady=4)
        self.txt_notes = tk.Text(f, width=50, height=6, wrap=tk.WORD)
        self.txt_notes.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        row += 1

        f.columnconfigure(1, weight=1)

    def refresh_list(self):
        self.listbox.delete(0, tk.END)
        try:
            con = get_con()
            try:
                rows = con.execute(
                    'SELECT name, current_stage FROM training_pairs '
                    'ORDER BY name').fetchall()
            finally:
                con.close()
        except sqlite3.OperationalError:
            # Table may not exist yet on very old DBs
            return
        for r in rows:
            self.listbox.insert(
                tk.END, f'{r["name"]} (stage {r["current_stage"]})')
        self._ordered_names = [r['name'] for r in rows]

    def _on_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self._ordered_names):
            self._populate_form(self._ordered_names[idx])

    def _new(self):
        self.listbox.selection_clear(0, tk.END)
        self._clear_form()

    def _clear_form(self):
        self.v_name.set('')
        self.v_current_stage.set('1')
        for name_var, ver_var in self._model_vars.values():
            name_var.set('')
            ver_var.set('')
        self.txt_notes.delete('1.0', tk.END)

    def _populate_form(self, name: str):
        con = get_con()
        try:
            row = con.execute(
                'SELECT * FROM training_pairs WHERE name=?', (name,)
            ).fetchone()
        finally:
            con.close()
        if row is None:
            return
        self.v_name.set(row['name'])
        self.v_current_stage.set(str(row['current_stage']))
        for component, (name_var, ver_var) in self._model_vars.items():
            n_col = f'{component}_name'
            v_col = f'{component}_version'
            name_var.set(row[n_col] or '')
            ver_var.set(str(row[v_col]) if row[v_col] is not None else '')
        self.txt_notes.delete('1.0', tk.END)
        self.txt_notes.insert('1.0', row['notes'] or '')

    def _save(self):
        name = self.v_name.get().strip()
        if not name:
            messagebox.showerror('Validation', 'Pair name is required.')
            return
        try:
            current_stage = int(self.v_current_stage.get())
        except ValueError:
            messagebox.showerror('Validation', 'Current stage must be integer.')
            return

        model_values = {}
        for component, (name_var, ver_var) in self._model_vars.items():
            m_name = name_var.get().strip() or None
            v_text = ver_var.get().strip()
            m_ver = int(v_text) if v_text else None
            model_values[f'{component}_name'] = m_name
            model_values[f'{component}_version'] = m_ver

        notes = self.txt_notes.get('1.0', tk.END).strip()
        created_at = datetime.utcnow().isoformat()

        con = get_con()
        try:
            con.execute(
                '''INSERT OR REPLACE INTO training_pairs
                   (name, creature_model_name, creature_model_version,
                    goal_model_name, goal_model_version,
                    monster_model_name, monster_model_version,
                    pack_model_name, pack_model_version,
                    current_stage, created_at, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                (name,
                 model_values['creature_model_name'],
                 model_values['creature_model_version'],
                 model_values['goal_model_name'],
                 model_values['goal_model_version'],
                 model_values['monster_model_name'],
                 model_values['monster_model_version'],
                 model_values['pack_model_name'],
                 model_values['pack_model_version'],
                 current_stage, created_at, notes)
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
            return
        idx = sel[0]
        if idx >= len(self._ordered_names):
            return
        name = self._ordered_names[idx]
        if not messagebox.askyesno('Confirm', f'Delete training pair "{name}"?'):
            return
        con = get_con()
        try:
            con.execute('DELETE FROM training_pairs WHERE name=?', (name,))
            con.commit()
        finally:
            con.close()
        self.refresh_list()
        self._clear_form()
