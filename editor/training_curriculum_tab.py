"""
Curriculum sub-tab — edit and run staged training plans.

A list of curriculum stages on the left, a per-stage config form on
the right, and Run buttons at the bottom. Stages live in the
``curriculum_stages`` DB table; this tab is the canonical editor for
that table.

Two run modes:
  * Run This Stage    — run only the selected stage, optionally
                        from a chosen starting checkpoint
  * Run Full Curriculum — run every stage from the selected one
                          forward, in order
"""
import json
import os
import sqlite3
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

from editor.db import get_con
from editor.tooltip import add_tooltip


# All possible reward signals — keep in sync with classes/reward.py
_ALL_SIGNALS = [
    'hp', 'gold', 'debt', 'inventory', 'equipment', 'reputation',
    'allies', 'kills', 'exploration', 'piety', 'quests', 'life_goals',
    'xp', 'failed_actions', 'fatigue', 'crowding', 'wage', 'trade',
    'hunger', 'goal_progress', 'goal_completed', 'purpose_proximity',
]


class TrainingCurriculumTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._selected_stage = None
        self._process = None
        self._build_ui()
        self.refresh_list()

    def _build_ui(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # ---- Left: stage list ----
        left = ttk.Frame(pane, width=220)
        pane.add(left, weight=0)

        ttk.Label(left, text='Curriculum stages').pack(anchor='w')
        list_frame = ttk.Frame(left)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(list_frame, exportselection=False, width=28)
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL,
                           command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.bind('<<ListboxSelect>>', self._on_select)

        # ---- Right: stage config form ----
        right = ttk.Frame(pane)
        pane.add(right, weight=1)

        f = right
        row = 0

        # Identity
        ttk.Label(f, text='Stage', font=('TkDefaultFont', 9, 'bold')
                  ).grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.l_stage = ttk.Label(f, text='—')
        self.l_stage.grid(row=row, column=1, sticky='w', padx=6, pady=2)
        row += 1

        ttk.Label(f, text='Name').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.v_name = tk.StringVar()
        ttk.Entry(f, textvariable=self.v_name, width=30).grid(
            row=row, column=1, sticky='ew', padx=6, pady=2)
        row += 1

        ttk.Label(f, text='Description').grid(row=row, column=0, sticky='nw', padx=6, pady=2)
        self.desc_text = tk.Text(f, width=50, height=3, wrap=tk.WORD)
        self.desc_text.grid(row=row, column=1, sticky='ew', padx=6, pady=2)
        row += 1

        # Env toggles
        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky='ew', pady=6)
        row += 1
        ttk.Label(f, text='Environment toggles', font=('TkDefaultFont', 9, 'bold')
                  ).grid(row=row, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        row += 1

        toggles_row = ttk.Frame(f)
        toggles_row.grid(row=row, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        self.v_hunger = tk.BooleanVar()
        self.v_combat = tk.BooleanVar()
        self.v_gestation = tk.BooleanVar()
        cb1 = ttk.Checkbutton(toggles_row, text='Hunger drain', variable=self.v_hunger)
        cb1.pack(side=tk.LEFT, padx=4)
        add_tooltip(cb1, 'When off, creatures never starve in this stage')
        cb2 = ttk.Checkbutton(toggles_row, text='Combat', variable=self.v_combat)
        cb2.pack(side=tk.LEFT, padx=4)
        add_tooltip(cb2, 'When off, MELEE/RANGED/GRAPPLE/CAST_SPELL short-circuit to noop')
        cb3 = ttk.Checkbutton(toggles_row, text='Gestation', variable=self.v_gestation)
        cb3.pack(side=tk.LEFT, padx=4)
        add_tooltip(cb3, 'When off, eggs never gestate or hatch — population stays static')
        row += 1

        # Pipeline shape
        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky='ew', pady=6)
        row += 1
        ttk.Label(f, text='Pipeline', font=('TkDefaultFont', 9, 'bold')
                  ).grid(row=row, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        row += 1

        for label, attr, tooltip in [
            ('MAPPO steps',     'v_mappo',    'Multi-agent PPO step count for this stage'),
            ('ES generations',  'v_es_gens',  'Evolutionary strategies generations (0 = skip ES)'),
            ('ES variants',     'v_es_vars',  'Variants per generation'),
            ('ES sim steps',    'v_es_steps', 'Sim steps per ES variant evaluation'),
            ('PPO steps',       'v_ppo',      'Single-agent PPO step count for this stage'),
            ('Learning rate',   'v_lr',       'Optimizer learning rate'),
            ('Entropy coef',    'v_ent',      'Entropy bonus weight (higher = more exploration)'),
            ('Resume from stage', 'v_resume', 'Stage number to load weights from at start (blank = fresh)'),
        ]:
            ttk.Label(f, text=label).grid(row=row, column=0, sticky='w', padx=6, pady=2)
            var = tk.StringVar()
            setattr(self, attr, var)
            entry = ttk.Entry(f, textvariable=var, width=12)
            entry.grid(row=row, column=1, sticky='w', padx=6, pady=2)
            add_tooltip(entry, tooltip)
            row += 1

        # Signals
        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky='ew', pady=6)
        row += 1
        ttk.Label(f, text='Reward signal scales', font=('TkDefaultFont', 9, 'bold')
                  ).grid(row=row, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        row += 1
        ttk.Label(f, text='(0 = silenced; soft fade keeps old signals at 0.3-0.5)',
                  foreground='gray').grid(row=row, column=0, columnspan=2,
                                           sticky='w', padx=6)
        row += 1

        # Single Text widget for the JSON dict — simplest editable form
        self.scales_text = tk.Text(f, width=50, height=6, wrap=tk.NONE,
                                    font=('monospace', 9))
        self.scales_text.grid(row=row, column=0, columnspan=2,
                               sticky='ew', padx=6, pady=2)
        add_tooltip(self.scales_text,
                    'JSON dict mapping signal name to scale, e.g. {"exploration": 1.0, "hp": 0.5}')
        row += 1

        # Action buttons
        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky='ew', pady=6)
        row += 1
        btn_row = ttk.Frame(f)
        btn_row.grid(row=row, column=0, columnspan=2, sticky='w', padx=6, pady=4)

        btn_save = ttk.Button(btn_row, text='Save Stage', command=self._save_stage)
        btn_save.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_save, 'Persist this stage\'s config back to the DB')

        btn_run_one = ttk.Button(btn_row, text='Run This Stage',
                                  command=self._run_one)
        btn_run_one.pack(side=tk.LEFT, padx=8)
        add_tooltip(btn_run_one, 'Run only the selected stage')

        btn_run_full = ttk.Button(btn_row, text='Run Full Curriculum',
                                   command=self._run_full)
        btn_run_full.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_run_full, 'Run from the selected stage forward through all later stages')

        btn_stop = ttk.Button(btn_row, text='Stop', command=self._stop)
        btn_stop.pack(side=tk.LEFT, padx=8)
        add_tooltip(btn_stop, 'Kill any running curriculum process')
        row += 1

        # Model name + arena config
        cfg_row = ttk.Frame(f)
        cfg_row.grid(row=row, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        ttk.Label(cfg_row, text='Model name:').pack(side=tk.LEFT)
        self.v_model_name = tk.StringVar(value='curriculum')
        ttk.Entry(cfg_row, textvariable=self.v_model_name, width=20).pack(side=tk.LEFT, padx=4)
        ttk.Label(cfg_row, text='Cols:').pack(side=tk.LEFT, padx=4)
        self.v_cols = tk.StringVar(value='25')
        ttk.Entry(cfg_row, textvariable=self.v_cols, width=5).pack(side=tk.LEFT)
        ttk.Label(cfg_row, text='Rows:').pack(side=tk.LEFT, padx=4)
        self.v_rows = tk.StringVar(value='25')
        ttk.Entry(cfg_row, textvariable=self.v_rows, width=5).pack(side=tk.LEFT)
        ttk.Label(cfg_row, text='Creatures:').pack(side=tk.LEFT, padx=4)
        self.v_creatures = tk.StringVar(value='12')
        ttk.Entry(cfg_row, textvariable=self.v_creatures, width=5).pack(side=tk.LEFT)
        row += 1

        # Status line
        self.status = ttk.Label(f, text='ready', foreground='gray')
        self.status.grid(row=row, column=0, columnspan=2, sticky='w', padx=6, pady=4)
        row += 1

        f.columnconfigure(1, weight=1)

    def refresh_list(self):
        con = get_con()
        try:
            rows = con.execute(
                'SELECT stage_number, name FROM curriculum_stages '
                'ORDER BY stage_number'
            ).fetchall()
        finally:
            con.close()
        self.listbox.delete(0, tk.END)
        self._stage_numbers = []
        for r in rows:
            self.listbox.insert(tk.END, f'  S{r["stage_number"]}  {r["name"]}')
            self._stage_numbers.append(r['stage_number'])

    def _on_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        self._selected_stage = self._stage_numbers[sel[0]]
        self._populate_form(self._selected_stage)

    def _populate_form(self, stage_number: int):
        con = get_con()
        try:
            r = con.execute(
                'SELECT * FROM curriculum_stages WHERE stage_number=?',
                (stage_number,)
            ).fetchone()
        finally:
            con.close()
        if r is None:
            return
        self.l_stage.config(text=str(r['stage_number']))
        self.v_name.set(r['name'] or '')
        self.desc_text.delete('1.0', tk.END)
        self.desc_text.insert('1.0', r['description'] or '')
        self.v_hunger.set(bool(r['hunger_drain']))
        self.v_combat.set(bool(r['combat_enabled']))
        self.v_gestation.set(bool(r['gestation_enabled']))
        self.v_mappo.set(str(r['mappo_steps']))
        self.v_es_gens.set(str(r['es_generations']))
        self.v_es_vars.set(str(r['es_variants']))
        self.v_es_steps.set(str(r['es_steps']))
        self.v_ppo.set(str(r['ppo_steps']))
        self.v_lr.set(str(r['learning_rate']))
        self.v_ent.set(str(r['ent_coef']))
        self.v_resume.set(str(r['resume_from_stage']) if r['resume_from_stage'] is not None else '')
        # Pretty-print signal scales for editing
        try:
            scales = json.loads(r['signal_scales'] or '{}')
        except Exception:
            scales = {}
        self.scales_text.delete('1.0', tk.END)
        self.scales_text.insert('1.0', json.dumps(scales, indent=2))

    def _save_stage(self):
        if self._selected_stage is None:
            messagebox.showwarning('Save', 'Select a stage first.')
            return
        try:
            scales_str = self.scales_text.get('1.0', tk.END).strip() or '{}'
            scales = json.loads(scales_str)
            if not isinstance(scales, dict):
                raise ValueError('signal_scales must be a JSON object')
            active_signals = list(scales.keys())
            mappo = int(self.v_mappo.get() or 0)
            es_gens = int(self.v_es_gens.get() or 0)
            es_vars = int(self.v_es_vars.get() or 20)
            es_steps = int(self.v_es_steps.get() or 1000)
            ppo = int(self.v_ppo.get() or 0)
            lr = float(self.v_lr.get() or 3e-4)
            ent = float(self.v_ent.get() or 0.05)
            resume_str = self.v_resume.get().strip()
            resume = int(resume_str) if resume_str else None
        except (ValueError, json.JSONDecodeError) as e:
            messagebox.showerror('Validation', f'Invalid input: {e}')
            return

        con = get_con()
        try:
            con.execute(
                '''UPDATE curriculum_stages SET
                   name=?, description=?,
                   active_signals=?, signal_scales=?,
                   hunger_drain=?, combat_enabled=?, gestation_enabled=?,
                   mappo_steps=?, es_generations=?, es_variants=?, es_steps=?,
                   ppo_steps=?, learning_rate=?, ent_coef=?,
                   resume_from_stage=?
                   WHERE stage_number=?''',
                (self.v_name.get().strip(),
                 self.desc_text.get('1.0', tk.END).strip(),
                 json.dumps(active_signals), json.dumps(scales),
                 1 if self.v_hunger.get() else 0,
                 1 if self.v_combat.get() else 0,
                 1 if self.v_gestation.get() else 0,
                 mappo, es_gens, es_vars, es_steps, ppo, lr, ent, resume,
                 self._selected_stage)
            )
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.status.config(text=f'stage {self._selected_stage} saved', foreground='green')

    def _run_one(self):
        if self._selected_stage is None:
            messagebox.showwarning('Run', 'Select a stage first.')
            return
        if self._process and self._process.poll() is None:
            messagebox.showwarning('Run', 'A training process is already running.')
            return
        self._launch([
            '--curriculum-stage', str(self._selected_stage),
        ])

    def _run_full(self):
        if self._selected_stage is None:
            messagebox.showwarning('Run', 'Select a stage first to use as the start point.')
            return
        if self._process and self._process.poll() is None:
            messagebox.showwarning('Run', 'A training process is already running.')
            return
        if not messagebox.askyesno(
                'Run Full Curriculum',
                f'Run all stages from S{self._selected_stage} forward?\n\n'
                f'This will produce a new model version per stage.'):
            return
        self._launch([
            '--curriculum-full',
            '--curriculum-start', str(self._selected_stage),
        ])

    def _launch(self, extra_args: list):
        model_name = self.v_model_name.get().strip() or 'curriculum'
        cmd = [
            sys.executable, '-u', '-m', 'editor.simulation.train',
            '--model', model_name,
            '--arena-cols', self.v_cols.get(),
            '--arena-rows', self.v_rows.get(),
            '--num-creatures', self.v_creatures.get(),
        ] + extra_args
        try:
            self._process = subprocess.Popen(
                cmd,
                cwd=str(Path(__file__).parent.parent),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                bufsize=1, universal_newlines=True,
            )
        except Exception as e:
            messagebox.showerror('Launch failed', str(e))
            return
        self.status.config(text=f'running pid={self._process.pid}',
                            foreground='blue')
        # Drain output in a background thread so the GUI stays responsive
        threading.Thread(target=self._drain_output, daemon=True).start()

    def _drain_output(self):
        if self._process is None:
            return
        for line in self._process.stdout:
            print(line, end='')
        self._process.wait()
        self.status.config(text=f'finished (exit {self._process.returncode})',
                            foreground='gray')

    def _stop(self):
        if self._process is None or self._process.poll() is not None:
            self.status.config(text='not running', foreground='gray')
            return
        try:
            self._process.terminate()
            self.status.config(text='stopped', foreground='red')
        except Exception as e:
            messagebox.showerror('Stop', str(e))
