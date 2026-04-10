"""
Models browser sub-tab — read/edit nn_models rows.

A list-and-form view over the nn_models table. Each model has its
training_params, training_stats, notes shown in detail. You can edit
notes, mark a model as default for runtime use, or delete obsolete
experiments without writing SQL.
"""
import json
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

from editor.db import get_con
from editor.tooltip import add_tooltip


class TrainingModelsTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._selected_id = None
        self._build_ui()
        self.refresh_list()

    def _build_ui(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # ---- Left: model list ----
        left = ttk.Frame(pane, width=320)
        pane.add(left, weight=0)

        ttk.Label(left, text='Trained Models').pack(anchor='w')

        list_frame = ttk.Frame(left)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(list_frame, exportselection=False, width=44)
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL,
                           command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.bind('<<ListboxSelect>>', self._on_select)

        btn_row = ttk.Frame(left)
        btn_row.pack(fill=tk.X, pady=4)
        btn_refresh = ttk.Button(btn_row, text='Refresh',
                                  command=self.refresh_list)
        btn_refresh.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_refresh, 'Reload the list from the database')
        btn_save = ttk.Button(btn_row, text='Save Notes',
                               command=self._save_notes)
        btn_save.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_save, 'Save the current notes back to the model row')
        btn_del = ttk.Button(btn_row, text='Delete',
                              command=self._delete)
        btn_del.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_del, 'Permanently delete this model from the DB')

        # ---- Right: detail panel ----
        right = ttk.Frame(pane)
        pane.add(right, weight=1)

        f = right
        row = 0

        # Identity row (read-only)
        ttk.Label(f, text='Name', font=('TkDefaultFont', 9, 'bold')
                  ).grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.l_name = ttk.Label(f, text='—')
        self.l_name.grid(row=row, column=1, sticky='w', padx=6, pady=2)
        row += 1

        ttk.Label(f, text='Version', font=('TkDefaultFont', 9, 'bold')
                  ).grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.l_version = ttk.Label(f, text='—')
        self.l_version.grid(row=row, column=1, sticky='w', padx=6, pady=2)
        row += 1

        ttk.Label(f, text='Parent').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.l_parent = ttk.Label(f, text='—')
        self.l_parent.grid(row=row, column=1, sticky='w', padx=6, pady=2)
        row += 1

        ttk.Label(f, text='Created').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.l_created = ttk.Label(f, text='—')
        self.l_created.grid(row=row, column=1, sticky='w', padx=6, pady=2)
        row += 1

        ttk.Label(f, text='Training time').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.l_time = ttk.Label(f, text='—')
        self.l_time.grid(row=row, column=1, sticky='w', padx=6, pady=2)
        row += 1

        # Network shape
        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky='ew', pady=6)
        row += 1
        ttk.Label(f, text='Network shape', font=('TkDefaultFont', 9, 'bold')
                  ).grid(row=row, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        row += 1

        ttk.Label(f, text='Observation size').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.l_obs = ttk.Label(f, text='—')
        self.l_obs.grid(row=row, column=1, sticky='w', padx=6, pady=2)
        row += 1

        ttk.Label(f, text='Action count').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.l_act = ttk.Label(f, text='—')
        self.l_act.grid(row=row, column=1, sticky='w', padx=6, pady=2)
        row += 1

        # Training params blob
        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky='ew', pady=6)
        row += 1
        ttk.Label(f, text='Training params', font=('TkDefaultFont', 9, 'bold')
                  ).grid(row=row, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        row += 1
        self.params_text = tk.Text(f, width=60, height=10, wrap=tk.WORD,
                                    state='disabled', font=('monospace', 9))
        self.params_text.grid(row=row, column=0, columnspan=2,
                               sticky='ew', padx=6, pady=2)
        row += 1

        # Notes (editable)
        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky='ew', pady=6)
        row += 1
        ttk.Label(f, text='Notes', font=('TkDefaultFont', 9, 'bold')
                  ).grid(row=row, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        row += 1
        self.notes_text = tk.Text(f, width=60, height=4, wrap=tk.WORD,
                                   font=('TkDefaultFont', 9))
        self.notes_text.grid(row=row, column=0, columnspan=2,
                              sticky='ew', padx=6, pady=2)
        add_tooltip(self.notes_text,
                    'Free-form notes about this model. Click "Save Notes" to persist.')
        row += 1

        f.columnconfigure(1, weight=1)

    def refresh_list(self):
        con = get_con()
        try:
            rows = con.execute(
                'SELECT id, name, version, observation_size, num_actions, '
                'training_seconds, created_at, notes '
                'FROM nn_models ORDER BY name, version'
            ).fetchall()
        finally:
            con.close()
        self.listbox.delete(0, tk.END)
        self._row_ids = []
        for r in rows:
            mins = r['training_seconds'] / 60.0 if r['training_seconds'] else 0
            line = (f'{r["name"]:14s} v{r["version"]:<3d}  '
                    f'obs={r["observation_size"]:<5d} '
                    f'act={r["num_actions"]:<3d} '
                    f'{mins:5.0f}m')
            self.listbox.insert(tk.END, line)
            self._row_ids.append(r['id'])

    def _on_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        self._selected_id = self._row_ids[sel[0]]
        self._populate_form(self._selected_id)

    def _populate_form(self, model_id: int):
        con = get_con()
        try:
            r = con.execute(
                'SELECT * FROM nn_models WHERE id=?', (model_id,)
            ).fetchone()
        finally:
            con.close()
        if r is None:
            return
        self.l_name.config(text=r['name'])
        self.l_version.config(text=str(r['version']))
        self.l_parent.config(text=str(r['parent_version'])
                              if r['parent_version'] is not None else '—')
        self.l_created.config(text=r['created_at'] or '—')
        secs = r['training_seconds'] or 0
        if secs >= 3600:
            self.l_time.config(text=f'{secs/3600:.2f} h')
        elif secs >= 60:
            self.l_time.config(text=f'{secs/60:.1f} min')
        else:
            self.l_time.config(text=f'{secs:.0f} s')
        self.l_obs.config(text=str(r['observation_size']))
        self.l_act.config(text=str(r['num_actions']))

        # Pretty-print training params
        try:
            params = json.loads(r['training_params'] or '{}')
            stats = json.loads(r['training_stats'] or '{}')
            blob = 'PARAMS\n' + json.dumps(params, indent=2)
            blob += '\n\nSTATS\n' + json.dumps(stats, indent=2)
        except Exception:
            blob = '(parse error)'
        self.params_text.configure(state='normal')
        self.params_text.delete('1.0', tk.END)
        self.params_text.insert('1.0', blob)
        self.params_text.configure(state='disabled')

        self.notes_text.delete('1.0', tk.END)
        self.notes_text.insert('1.0', r['notes'] or '')

    def _save_notes(self):
        if self._selected_id is None:
            messagebox.showwarning('Save', 'Select a model first.')
            return
        notes = self.notes_text.get('1.0', tk.END).strip()
        con = get_con()
        try:
            con.execute('UPDATE nn_models SET notes=? WHERE id=?',
                        (notes, self._selected_id))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        messagebox.showinfo('Save', 'Notes saved.')

    def _delete(self):
        if self._selected_id is None:
            messagebox.showwarning('Delete', 'Select a model first.')
            return
        if not messagebox.askyesno(
                'Delete model',
                f'Permanently delete this model row?\n\n'
                f'Name: {self.l_name.cget("text")}\n'
                f'Version: {self.l_version.cget("text")}'):
            return
        con = get_con()
        try:
            con.execute('DELETE FROM nn_models WHERE id=?', (self._selected_id,))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self._selected_id = None
        self.refresh_list()
