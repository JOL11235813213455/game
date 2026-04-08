import json
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

from editor.db import get_con
from editor.tooltip import add_tooltip


class GodsTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()
        self.refresh_list()

    def _build_ui(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        left = ttk.Frame(pane, width=180)
        pane.add(left, weight=0)

        ttk.Label(left, text='Gods').pack(anchor='w')
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
        btn_new = ttk.Button(btn_row, text='New', command=self._new)
        btn_new.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_new, 'Clear form to create a new god')
        btn_save = ttk.Button(btn_row, text='Save', command=self._save)
        btn_save.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_save, 'Save the current god to the database')
        btn_del = ttk.Button(btn_row, text='Delete', command=self._delete)
        btn_del.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_del, 'Delete the selected god')

        right = ttk.Frame(pane)
        pane.add(right, weight=1)

        f = right
        row = 0

        ttk.Label(f, text='Name').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_name = tk.StringVar()
        e = ttk.Entry(f, textvariable=self.v_name, width=20)
        e.grid(row=row, column=1, sticky='ew', padx=6, pady=4)
        add_tooltip(e, 'Unique god name')
        row += 1

        ttk.Label(f, text='Domain').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_domain = tk.StringVar()
        e = ttk.Entry(f, textvariable=self.v_domain, width=20)
        e.grid(row=row, column=1, sticky='ew', padx=6, pady=4)
        add_tooltip(e, 'Domain of influence (e.g. order, chaos, compassion, wrath)')
        row += 1

        ttk.Label(f, text='Opposed God').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_opposed = tk.StringVar()
        self.opposed_cb = ttk.Combobox(f, textvariable=self.v_opposed, values=[], width=18)
        self.opposed_cb.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(self.opposed_cb, 'The directly opposed god on the same axis')
        row += 1

        ttk.Label(f, text='Description').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_description = tk.StringVar()
        e = ttk.Entry(f, textvariable=self.v_description, width=40)
        e.grid(row=row, column=1, sticky='ew', padx=6, pady=4)
        add_tooltip(e, 'Description of this god')
        row += 1

        ttk.Label(f, text='Aligned Actions').grid(row=row, column=0, sticky='nw', padx=6, pady=4)
        self.v_aligned = tk.StringVar(value='[]')
        e = ttk.Entry(f, textvariable=self.v_aligned, width=40)
        e.grid(row=row, column=1, sticky='ew', padx=6, pady=4)
        add_tooltip(e, 'JSON list of action names that please this god, e.g. ["talk", "trade", "heal"]')
        row += 1

        ttk.Label(f, text='Opposed Actions').grid(row=row, column=0, sticky='nw', padx=6, pady=4)
        self.v_opposed_actions = tk.StringVar(value='[]')
        e = ttk.Entry(f, textvariable=self.v_opposed_actions, width=40)
        e.grid(row=row, column=1, sticky='ew', padx=6, pady=4)
        add_tooltip(e, 'JSON list of action names that displease this god')
        row += 1

        f.columnconfigure(1, weight=1)

    def refresh_list(self):
        con = get_con()
        try:
            rows = con.execute('SELECT name, domain FROM gods ORDER BY name').fetchall()
        finally:
            con.close()
        self.listbox.delete(0, tk.END)
        god_names = []
        for r in rows:
            self.listbox.insert(tk.END, f"{r['name']} ({r['domain']})")
            god_names.append(r['name'])
        self.opposed_cb['values'] = [''] + god_names

    def _clear_form(self):
        self.v_name.set('')
        self.v_domain.set('')
        self.v_opposed.set('')
        self.v_description.set('')
        self.v_aligned.set('[]')
        self.v_opposed_actions.set('[]')

    def _populate_form(self, name):
        con = get_con()
        try:
            row = con.execute('SELECT * FROM gods WHERE name=?', (name,)).fetchone()
        finally:
            con.close()
        if row is None:
            return
        self.v_name.set(row['name'])
        self.v_domain.set(row['domain'] or '')
        self.v_opposed.set(row['opposed_god'] or '')
        self.v_description.set(row['description'] or '')
        self.v_aligned.set(row['aligned_actions'] or '[]')
        self.v_opposed_actions.set(row['opposed_actions'] or '[]')

    def _on_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        entry = self.listbox.get(sel[0])
        name = entry.split(' (')[0]
        self._populate_form(name)

    def _new(self):
        self.listbox.selection_clear(0, tk.END)
        self._clear_form()

    def _save(self):
        name = self.v_name.get().strip()
        if not name:
            messagebox.showerror('Validation', 'Name is required.')
            return
        con = get_con()
        try:
            con.execute(
                '''INSERT INTO gods (name, domain, opposed_god, aligned_actions,
                   opposed_actions, description)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(name) DO UPDATE SET
                   domain=excluded.domain, opposed_god=excluded.opposed_god,
                   aligned_actions=excluded.aligned_actions,
                   opposed_actions=excluded.opposed_actions,
                   description=excluded.description
                ''',
                (name, self.v_domain.get().strip(),
                 self.v_opposed.get().strip() or None,
                 self.v_aligned.get().strip() or '[]',
                 self.v_opposed_actions.get().strip() or '[]',
                 self.v_description.get().strip())
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
            messagebox.showwarning('Delete', 'Select a god first.')
            return
        entry = self.listbox.get(sel[0])
        name = entry.split(' (')[0]
        if not messagebox.askyesno('Delete', f'Delete god "{name}"?'):
            return
        con = get_con()
        try:
            con.execute('DELETE FROM gods WHERE name=?', (name,))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()
        self._clear_form()
