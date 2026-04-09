import json
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

from editor.db import get_con, fetch_creature_keys
from editor.tooltip import add_tooltip

QUEST_TYPES = ['quest', 'job']


class QuestsTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()
        self.refresh_list()

    def _build_ui(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # -- Left: quest list --
        left = ttk.Frame(pane, width=200)
        pane.add(left, weight=0)

        ttk.Label(left, text='Quests').pack(anchor='w')
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
        add_tooltip(btn_new, 'Clear form to create a new quest')
        btn_save = ttk.Button(btn_row, text='Save', command=self._save)
        btn_save.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_save, 'Save the current quest to the database')
        btn_del = ttk.Button(btn_row, text='Delete', command=self._delete)
        btn_del.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_del, 'Delete the selected quest and all its steps')

        # -- Right: form + steps --
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

        self.v_name = tk.StringVar()
        add_row('Name', lambda p: ttk.Entry(p, textvariable=self.v_name, width=30).pack(anchor='w'),
                'Unique quest name (primary key)')

        self.v_giver = tk.StringVar()
        self._creature_keys = fetch_creature_keys()
        add_row('Giver', lambda p: ttk.Combobox(p, textvariable=self.v_giver,
                values=self._creature_keys, width=20).pack(anchor='w'),
                'Creature key of the NPC who gives this quest')

        self.v_description = tk.StringVar()
        add_row('Description', lambda p: ttk.Entry(p, textvariable=self.v_description, width=40).pack(anchor='w'),
                'Quest description shown to the player')

        self.v_quest_type = tk.StringVar(value='quest')
        add_row('Type', lambda p: ttk.Combobox(p, textvariable=self.v_quest_type,
                values=QUEST_TYPES, state='readonly', width=10).pack(anchor='w'),
                'quest = one-time story, job = repeatable task')

        self.v_conditions = tk.StringVar(value='{}')
        add_row('Conditions', lambda p: ttk.Entry(p, textvariable=self.v_conditions, width=40).pack(anchor='w'),
                'Python expression: conditions to make quest available')

        self.v_reward = tk.StringVar()
        add_row('Reward Action', lambda p: ttk.Entry(p, textvariable=self.v_reward, width=40).pack(anchor='w'),
                'Python code executed on quest completion')

        self.v_fail_action = tk.StringVar()
        add_row('Fail Action', lambda p: ttk.Entry(p, textvariable=self.v_fail_action, width=40).pack(anchor='w'),
                'Python code executed on quest failure')

        self.v_time_limit = tk.StringVar()
        add_row('Time Limit (s)', lambda p: ttk.Entry(p, textvariable=self.v_time_limit, width=10).pack(anchor='w'),
                'Total quest time limit in seconds (blank = no limit)')

        self.v_repeatable = tk.BooleanVar()
        add_row('Repeatable', lambda p: ttk.Checkbutton(p, variable=self.v_repeatable).pack(anchor='w'),
                'Can this quest be accepted again after completion?')

        self.v_cooldown = tk.StringVar()
        add_row('Cooldown (days)', lambda p: ttk.Entry(p, textvariable=self.v_cooldown, width=10).pack(anchor='w'),
                'Days before repeatable quest can be accepted again')

        # -- Steps section --
        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky='ew', padx=6, pady=6)
        row += 1

        ttk.Label(f, text='Quest Steps', font=('TkDefaultFont', 9, 'bold')).grid(
            row=row, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        row += 1

        self._steps_frame = ttk.Frame(f)
        self._steps_frame.grid(row=row, column=0, columnspan=2, sticky='ew', padx=6, pady=2)
        row += 1

        btn_step_row = ttk.Frame(f)
        btn_step_row.grid(row=row, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        btn_add_step = ttk.Button(btn_step_row, text='+ Step', command=self._add_step)
        btn_add_step.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_add_step, 'Add a new quest step')
        row += 1

        f.columnconfigure(1, weight=1)
        self._steps = []
        self._rebuild_steps_display()

    def _rebuild_steps_display(self):
        for w in self._steps_frame.winfo_children():
            w.destroy()
        if not self._steps:
            ttk.Label(self._steps_frame, text='(no steps)', foreground='#888').pack(anchor='w')
            return
        for i, step in enumerate(self._steps):
            row = ttk.Frame(self._steps_frame)
            row.pack(fill=tk.X, pady=2)
            text = f"{step['step_no']}{step['step_sub']}: {step['description'][:40]}"
            ttk.Label(row, text=text, font=('TkFixedFont', 9)).pack(side=tk.LEFT)
            def _del(idx=i):
                self._steps.pop(idx)
                self._rebuild_steps_display()
            del_btn = ttk.Button(row, text='\u2715', width=2, command=_del)
            del_btn.pack(side=tk.LEFT, padx=4)
            add_tooltip(del_btn, 'Remove this step')

    def _add_step(self):
        d = _StepDialog(self)
        self.wait_window(d)
        if d.result:
            self._steps.append(d.result)
            self._steps.sort(key=lambda s: (s['step_no'], s['step_sub']))
            self._rebuild_steps_display()

    def _int_or_none(self, var):
        txt = var.get().strip()
        if not txt:
            return None
        try:
            return int(txt)
        except ValueError:
            return None

    def refresh_list(self):
        con = get_con()
        try:
            rows = con.execute('SELECT name, quest_type FROM quests ORDER BY name').fetchall()
        finally:
            con.close()
        self.listbox.delete(0, tk.END)
        for r in rows:
            self.listbox.insert(tk.END, f"[{r['quest_type']}] {r['name']}")

    def refresh_dropdowns(self):
        self._creature_keys = fetch_creature_keys()

    def _clear_form(self):
        self.v_name.set('')
        self.v_giver.set('')
        self.v_description.set('')
        self.v_quest_type.set('quest')
        self.v_conditions.set('{}')
        self.v_reward.set('')
        self.v_fail_action.set('')
        self.v_time_limit.set('')
        self.v_repeatable.set(False)
        self.v_cooldown.set('')
        self._steps = []
        self._rebuild_steps_display()

    def _populate_form(self, name):
        con = get_con()
        try:
            row = con.execute('SELECT * FROM quests WHERE name=?', (name,)).fetchone()
            if row is None:
                return
            step_rows = con.execute(
                'SELECT * FROM quest_steps WHERE quest_name=? ORDER BY step_no, step_sub',
                (name,)).fetchall()
        finally:
            con.close()

        self.v_name.set(row['name'])
        self.v_giver.set(row['giver'] or '')
        self.v_description.set(row['description'] or '')
        self.v_quest_type.set(row['quest_type'] or 'quest')
        self.v_conditions.set(row['conditions'] or '{}')
        self.v_reward.set(row['reward_action'] or '')
        self.v_fail_action.set(row['fail_action'] or '')
        self.v_time_limit.set(str(row['time_limit']) if row['time_limit'] is not None else '')
        self.v_repeatable.set(bool(row['repeatable']))
        self.v_cooldown.set(str(row['cooldown_days']) if row['cooldown_days'] is not None else '')

        self._steps = []
        for sr in step_rows:
            self._steps.append({
                'step_no': sr['step_no'], 'step_sub': sr['step_sub'],
                'description': sr['description'] or '',
                'success_condition': sr['success_condition'] or '',
                'fail_condition': sr['fail_condition'] or '',
                'success_action': sr['success_action'] or '',
                'fail_action': sr['fail_action'] or '',
                'step_map': sr['step_map'], 'step_npc': sr['step_npc'],
                'step_location_x': sr['step_location_x'],
                'step_location_y': sr['step_location_y'],
                'time_limit': sr['time_limit'],
            })
        self._rebuild_steps_display()

    def _on_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        entry = self.listbox.get(sel[0])
        name = entry.split('] ', 1)[-1]
        self._populate_form(name)

    def _new(self):
        self.listbox.selection_clear(0, tk.END)
        self._clear_form()

    def _save(self):
        name = self.v_name.get().strip()
        if not name:
            messagebox.showerror('Validation', 'Name is required.')
            return
        giver = self.v_giver.get().strip()
        if not giver:
            messagebox.showerror('Validation', 'Giver is required.')
            return

        con = get_con()
        try:
            con.execute(
                '''INSERT INTO quests (name, giver, description, quest_type, conditions,
                   reward_action, fail_action, time_limit, repeatable, cooldown_days)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(name) DO UPDATE SET
                   giver=excluded.giver, description=excluded.description,
                   quest_type=excluded.quest_type, conditions=excluded.conditions,
                   reward_action=excluded.reward_action, fail_action=excluded.fail_action,
                   time_limit=excluded.time_limit, repeatable=excluded.repeatable,
                   cooldown_days=excluded.cooldown_days
                ''',
                (name, giver, self.v_description.get().strip(),
                 self.v_quest_type.get(), self.v_conditions.get().strip() or '{}',
                 self.v_reward.get().strip(), self.v_fail_action.get().strip(),
                 self._int_or_none(self.v_time_limit),
                 int(self.v_repeatable.get()),
                 self._int_or_none(self.v_cooldown))
            )
            # Save steps
            con.execute('DELETE FROM quest_steps WHERE quest_name=?', (name,))
            for step in self._steps:
                con.execute(
                    '''INSERT INTO quest_steps (quest_name, step_no, step_sub, description,
                       success_condition, fail_condition, success_action, fail_action,
                       step_map, step_location_x, step_location_y, step_npc, time_limit)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (name, step['step_no'], step['step_sub'], step['description'],
                     step['success_condition'], step['fail_condition'],
                     step['success_action'], step['fail_action'],
                     step.get('step_map'), step.get('step_location_x'),
                     step.get('step_location_y'), step.get('step_npc'),
                     step.get('time_limit'))
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
            messagebox.showwarning('Delete', 'Select a quest first.')
            return
        entry = self.listbox.get(sel[0])
        name = entry.split('] ', 1)[-1]
        if not messagebox.askyesno('Delete', f'Delete quest "{name}" and all steps?'):
            return
        con = get_con()
        try:
            con.execute('DELETE FROM quest_steps WHERE quest_name=?', (name,))
            con.execute('DELETE FROM quests WHERE name=?', (name,))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()
        self._clear_form()


class _StepDialog(tk.Toplevel):
    """Dialog for adding/editing a quest step."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title('Add Quest Step')
        self.result = None
        self._build()
        self.grab_set()

    def _build(self):
        f = self
        row = 0

        ttk.Label(f, text='Step No:').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.v_no = tk.StringVar(value='1')
        ttk.Entry(f, textvariable=self.v_no, width=5).grid(row=row, column=1, sticky='w', padx=6)
        row += 1

        ttk.Label(f, text='Sub:').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.v_sub = tk.StringVar(value='a')
        ttk.Entry(f, textvariable=self.v_sub, width=5).grid(row=row, column=1, sticky='w', padx=6)
        row += 1

        ttk.Label(f, text='Description:').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.v_desc = tk.StringVar()
        ttk.Entry(f, textvariable=self.v_desc, width=30).grid(row=row, column=1, sticky='ew', padx=6)
        row += 1

        ttk.Label(f, text='Success Cond:').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.v_succ = tk.StringVar()
        ttk.Entry(f, textvariable=self.v_succ, width=30).grid(row=row, column=1, sticky='ew', padx=6)
        row += 1

        ttk.Label(f, text='Fail Cond:').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.v_fail_c = tk.StringVar()
        ttk.Entry(f, textvariable=self.v_fail_c, width=30).grid(row=row, column=1, sticky='ew', padx=6)
        row += 1

        ttk.Label(f, text='Success Action:').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.v_succ_a = tk.StringVar()
        ttk.Entry(f, textvariable=self.v_succ_a, width=30).grid(row=row, column=1, sticky='ew', padx=6)
        row += 1

        ttk.Label(f, text='Fail Action:').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.v_fail_a = tk.StringVar()
        ttk.Entry(f, textvariable=self.v_fail_a, width=30).grid(row=row, column=1, sticky='ew', padx=6)
        row += 1

        ttk.Label(f, text='Map:').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.v_map = tk.StringVar()
        ttk.Entry(f, textvariable=self.v_map, width=20).grid(row=row, column=1, sticky='w', padx=6)
        row += 1

        ttk.Label(f, text='NPC:').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.v_npc = tk.StringVar()
        ttk.Entry(f, textvariable=self.v_npc, width=20).grid(row=row, column=1, sticky='w', padx=6)
        row += 1

        ttk.Label(f, text='Time Limit (s):').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.v_time = tk.StringVar()
        ttk.Entry(f, textvariable=self.v_time, width=10).grid(row=row, column=1, sticky='w', padx=6)
        row += 1

        ttk.Button(f, text='Add', command=self._ok).grid(row=row, column=0, columnspan=2, pady=6)

    def _ok(self):
        try:
            no = int(self.v_no.get())
        except ValueError:
            no = 1
        time_limit = None
        if self.v_time.get().strip():
            try:
                time_limit = int(self.v_time.get())
            except ValueError:
                pass
        self.result = {
            'step_no': no,
            'step_sub': self.v_sub.get().strip() or 'a',
            'description': self.v_desc.get().strip(),
            'success_condition': self.v_succ.get().strip(),
            'fail_condition': self.v_fail_c.get().strip(),
            'success_action': self.v_succ_a.get().strip(),
            'fail_action': self.v_fail_a.get().strip(),
            'step_map': self.v_map.get().strip() or None,
            'step_npc': self.v_npc.get().strip() or None,
            'step_location_x': None,
            'step_location_y': None,
            'time_limit': time_limit,
        }
        self.destroy()
