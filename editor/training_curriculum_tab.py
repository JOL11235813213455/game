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
        self.v_fatigue = tk.BooleanVar()
        cb1 = ttk.Checkbutton(toggles_row, text='Hunger drain', variable=self.v_hunger)
        cb1.pack(side=tk.LEFT, padx=4)
        add_tooltip(cb1, 'When off, creatures never starve in this stage')
        cb2 = ttk.Checkbutton(toggles_row, text='Combat', variable=self.v_combat)
        cb2.pack(side=tk.LEFT, padx=4)
        add_tooltip(cb2, 'When off, MELEE/RANGED/GRAPPLE/CAST_SPELL short-circuit to noop (advisory — action mask is authoritative)')
        cb3 = ttk.Checkbutton(toggles_row, text='Gestation', variable=self.v_gestation)
        cb3.pack(side=tk.LEFT, padx=4)
        add_tooltip(cb3, 'When off, eggs never gestate or hatch — population stays static')
        cb4 = ttk.Checkbutton(toggles_row, text='Fatigue', variable=self.v_fatigue)
        cb4.pack(side=tk.LEFT, padx=4)
        add_tooltip(cb4, 'When off, creatures never accumulate sleep debt or fatigue')
        row += 1

        # Pipeline shape — one row per phase (MAPPO / ES / PPO), each
        # row carrying the knobs that phase actually uses. Built for
        # extension: adding a 4th phase (DAgger / imitation / PBT) is
        # a matter of appending another _phase_row(...) block.
        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky='ew', pady=6)
        row += 1
        ttk.Label(f, text='Pipeline', font=('TkDefaultFont', 9, 'bold')
                  ).grid(row=row, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        row += 1

        pipe_grid = ttk.Frame(f)
        pipe_grid.grid(row=row, column=0, columnspan=2, sticky='ew', padx=6, pady=2)
        row += 1

        def _grid_label(parent, text, r, c, width=8, anchor='center'):
            ttk.Label(parent, text=text, width=width, anchor=anchor).grid(
                row=r, column=c, padx=2, pady=1, sticky='w')

        def _grid_entry(parent, var, r, c, width=7, tip=''):
            e = ttk.Entry(parent, textvariable=var, width=width)
            e.grid(row=r, column=c, padx=2, pady=1, sticky='w')
            if tip:
                add_tooltip(e, tip)
            return e

        # --- MAPPO row ---
        # Columns: label | Steps | Creatures | Cols | Rows | Map
        # NOTE: MAPPO is always sequential (per train.py: per-creature
        # obs cost is the bottleneck, parallelism doesn't help).
        # No Parallel column on this row.
        _grid_label(pipe_grid, 'MAPPO', 0, 0, width=7, anchor='w')
        _grid_label(pipe_grid, 'Steps',    0, 1)
        _grid_label(pipe_grid, 'Creatures',0, 2)
        _grid_label(pipe_grid, 'Cols',     0, 3, width=5)
        _grid_label(pipe_grid, 'Rows',     0, 4, width=5)
        _grid_label(pipe_grid, 'Map',      0, 5, width=14, anchor='w')
        self.v_mappo = tk.StringVar()
        self.v_mappo_creatures = tk.StringVar(value='0')
        self.v_mappo_cols = tk.StringVar(value='0')
        self.v_mappo_rows = tk.StringVar(value='0')
        self.v_mappo_map = tk.StringVar(value='')
        ttk.Label(pipe_grid, text='MAPPO:', width=7, anchor='w').grid(
            row=1, column=0, padx=2, pady=1, sticky='w')
        _grid_entry(pipe_grid, self.v_mappo,          1, 1, tip='MAPPO steps (0=skip)')
        _grid_entry(pipe_grid, self.v_mappo_creatures,1, 2, tip='Creatures in MAPPO arena (0=inherit)')
        _grid_entry(pipe_grid, self.v_mappo_cols,     1, 3, width=5, tip='Arena cols (0=inherit)')
        _grid_entry(pipe_grid, self.v_mappo_rows,     1, 4, width=5, tip='Arena rows (0=inherit)')
        _grid_entry(pipe_grid, self.v_mappo_map,      1, 5, width=14,
                     tip='Named map (optional; blank=procedural)')

        # --- ES row ---
        _grid_label(pipe_grid, 'ES',       2, 0, width=7, anchor='w')
        _grid_label(pipe_grid, 'Gens',     2, 1)
        _grid_label(pipe_grid, 'Variants', 2, 2)
        _grid_label(pipe_grid, 'Steps',    2, 3)
        _grid_label(pipe_grid, 'Parallel', 2, 4, width=5)
        self.v_es_gens = tk.StringVar()
        self.v_es_vars = tk.StringVar()
        self.v_es_steps = tk.StringVar()
        self.v_es_parallel = tk.StringVar(value='1')
        ttk.Label(pipe_grid, text='ES:', width=7, anchor='w').grid(
            row=3, column=0, padx=2, pady=1, sticky='w')
        _grid_entry(pipe_grid, self.v_es_gens,     3, 1, tip='ES generations (0=skip)')
        _grid_entry(pipe_grid, self.v_es_vars,     3, 2, tip='Variants per generation')
        _grid_entry(pipe_grid, self.v_es_steps,    3, 3, tip='Steps per variant evaluation')
        _grid_entry(pipe_grid, self.v_es_parallel, 3, 4, width=5, tip='ES worker count')

        # --- PPO row ---
        _grid_label(pipe_grid, 'PPO', 4, 0, width=7, anchor='w')
        _grid_label(pipe_grid, 'Steps',    4, 1)
        _grid_label(pipe_grid, 'Parallel', 4, 2)
        _grid_label(pipe_grid, 'Creatures',4, 3)
        _grid_label(pipe_grid, 'Cols',     4, 4, width=5)
        _grid_label(pipe_grid, 'Rows',     4, 5, width=5)
        _grid_label(pipe_grid, 'Map',      4, 6, width=14, anchor='w')
        self.v_ppo = tk.StringVar()
        self.v_ppo_parallel = tk.StringVar(value='1')
        self.v_ppo_creatures = tk.StringVar(value='0')
        self.v_ppo_cols = tk.StringVar(value='0')
        self.v_ppo_rows = tk.StringVar(value='0')
        self.v_ppo_map = tk.StringVar(value='')
        ttk.Label(pipe_grid, text='PPO:', width=7, anchor='w').grid(
            row=5, column=0, padx=2, pady=1, sticky='w')
        _grid_entry(pipe_grid, self.v_ppo,          5, 1, tip='PPO steps (0=skip)')
        _grid_entry(pipe_grid, self.v_ppo_parallel, 5, 2, tip='PPO worker count (1=sequential)')
        _grid_entry(pipe_grid, self.v_ppo_creatures,5, 3, tip='Creatures in PPO arena (0=inherit)')
        _grid_entry(pipe_grid, self.v_ppo_cols,     5, 4, width=5, tip='Arena cols (0=inherit)')
        _grid_entry(pipe_grid, self.v_ppo_rows,     5, 5, width=5, tip='Arena rows (0=inherit)')
        _grid_entry(pipe_grid, self.v_ppo_map,      5, 6, width=14,
                     tip='Named map (optional; blank=procedural)')

        # --- Imitation / DAgger row (new technique, fully wired) ---
        _grid_label(pipe_grid, 'Imitation', 6, 0, width=9, anchor='w')
        _grid_label(pipe_grid, 'Epochs',    6, 1)
        _grid_label(pipe_grid, 'Batch',     6, 2)
        _grid_label(pipe_grid, 'Teacher',   6, 3, width=12)
        _grid_label(pipe_grid, 'Parallel',  6, 4, width=5)
        self.v_imit_epochs = tk.StringVar(value='0')
        self.v_imit_batch = tk.StringVar(value='256')
        self.v_imit_teacher = tk.StringVar(value='StatWeighted')
        self.v_imit_parallel = tk.StringVar(value='1')
        ttk.Label(pipe_grid, text='Imit:', width=9, anchor='w').grid(
            row=7, column=0, padx=2, pady=1, sticky='w')
        _grid_entry(pipe_grid, self.v_imit_epochs,   7, 1, tip='DAgger epochs (0=skip)')
        _grid_entry(pipe_grid, self.v_imit_batch,    7, 2, tip='Supervised minibatch size')
        _grid_entry(pipe_grid, self.v_imit_teacher,  7, 3, width=12,
                     tip='Teacher behavior module (currently: StatWeighted)')
        _grid_entry(pipe_grid, self.v_imit_parallel, 7, 4, width=5,
                     tip='Parallel workers (reserved)')

        # --- League row (stub — schema + UI only) ---
        _grid_label(pipe_grid, 'League', 8, 0, width=9, anchor='w')
        _grid_label(pipe_grid, 'Iters',  8, 1)
        _grid_label(pipe_grid, 'Pool',   8, 2)
        _grid_label(pipe_grid, 'Parallel', 8, 3, width=5)
        self.v_league_iter = tk.StringVar(value='0')
        self.v_league_pool = tk.StringVar(value='4')
        self.v_league_parallel = tk.StringVar(value='1')
        ttk.Label(pipe_grid, text='Lg:', width=9, anchor='w').grid(
            row=9, column=0, padx=2, pady=1, sticky='w')
        _grid_entry(pipe_grid, self.v_league_iter,     9, 1, tip='League self-play iterations (0=skip)')
        _grid_entry(pipe_grid, self.v_league_pool,     9, 2, tip='Opponent pool size')
        _grid_entry(pipe_grid, self.v_league_parallel, 9, 3, width=5, tip='Parallel workers')

        # --- PBT row (stub) ---
        _grid_label(pipe_grid, 'PBT',       10, 0, width=9, anchor='w')
        _grid_label(pipe_grid, 'Population',10, 1)
        _grid_label(pipe_grid, 'Mutation',  10, 2)
        _grid_label(pipe_grid, 'Exploit',   10, 3)
        self.v_pbt_pop = tk.StringVar(value='0')
        self.v_pbt_mut = tk.StringVar(value='0.2')
        self.v_pbt_thr = tk.StringVar(value='0.25')
        ttk.Label(pipe_grid, text='PBT:', width=9, anchor='w').grid(
            row=11, column=0, padx=2, pady=1, sticky='w')
        _grid_entry(pipe_grid, self.v_pbt_pop, 11, 1, tip='PBT population size (0=skip)')
        _grid_entry(pipe_grid, self.v_pbt_mut, 11, 2, tip='Hparam mutation rate (0-1)')
        _grid_entry(pipe_grid, self.v_pbt_thr, 11, 3, tip='Exploit threshold (fraction)')

        # --- Curiosity row (stub) ---
        _grid_label(pipe_grid, 'Curiosity', 12, 0, width=9, anchor='w')
        _grid_label(pipe_grid, 'Weight',    12, 1)
        _grid_label(pipe_grid, 'Hidden',    12, 2)
        self.v_cur_weight = tk.StringVar(value='0.0')
        self.v_cur_hidden = tk.StringVar(value='64')
        ttk.Label(pipe_grid, text='Curios:', width=9, anchor='w').grid(
            row=13, column=0, padx=2, pady=1, sticky='w')
        _grid_entry(pipe_grid, self.v_cur_weight, 13, 1, tip='Novelty reward weight (0=disabled)')
        _grid_entry(pipe_grid, self.v_cur_hidden, 13, 2, tip='Novelty net hidden size')

        # --- Offline replay row (stub) ---
        _grid_label(pipe_grid, 'OfflineReplay', 14, 0, width=13, anchor='w')
        _grid_label(pipe_grid, 'Path',   14, 1, width=18)
        _grid_label(pipe_grid, 'Epochs', 14, 2)
        self.v_off_path = tk.StringVar(value='')
        self.v_off_epochs = tk.StringVar(value='0')
        ttk.Label(pipe_grid, text='Off:', width=13, anchor='w').grid(
            row=15, column=0, padx=2, pady=1, sticky='w')
        _grid_entry(pipe_grid, self.v_off_path,   15, 1, width=18, tip='Trajectory file path')
        _grid_entry(pipe_grid, self.v_off_epochs, 15, 2, tip='Replay epochs (0=skip)')

        # --- Run order editor ---
        ro = ttk.Frame(f)
        ro.grid(row=row, column=0, columnspan=2, sticky='w', padx=6, pady=(4, 2))
        row += 1
        ttk.Label(ro, text='Run order:').pack(side=tk.LEFT)
        self.v_run_order = tk.StringVar(value='mappo,es,ppo')
        _ro_e = ttk.Entry(ro, textvariable=self.v_run_order, width=50)
        _ro_e.pack(side=tk.LEFT, padx=(4, 4))
        add_tooltip(_ro_e,
                    'Comma-separated phase names. Phases run in order; '
                    'unknown names skip silently with a warning. '
                    'Available: imitation, mappo, es, ppo, league, pbt, '
                    'curiosity, offline_replay')

        # --- Global hparams row: LR, Entropy, Resume ---
        hp = ttk.Frame(f)
        hp.grid(row=row, column=0, columnspan=2, sticky='w', padx=6, pady=(2, 4))
        row += 1
        self.v_lr = tk.StringVar()
        self.v_ent = tk.StringVar()
        self.v_resume = tk.StringVar()
        ttk.Label(hp, text='LR:').pack(side=tk.LEFT)
        _lr_e = ttk.Entry(hp, textvariable=self.v_lr, width=8)
        _lr_e.pack(side=tk.LEFT, padx=(2, 10))
        add_tooltip(_lr_e, 'Learning rate (Adam)')
        ttk.Label(hp, text='Entropy:').pack(side=tk.LEFT)
        _ent_e = ttk.Entry(hp, textvariable=self.v_ent, width=8)
        _ent_e.pack(side=tk.LEFT, padx=(2, 10))
        add_tooltip(_ent_e, 'Entropy bonus coefficient')
        ttk.Label(hp, text='Resume from stage:').pack(side=tk.LEFT)
        _res_e = ttk.Entry(hp, textvariable=self.v_resume, width=5)
        _res_e.pack(side=tk.LEFT, padx=2)
        add_tooltip(_res_e, 'Resume from stage N (blank=no auto-resume)')

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
        self.scales_text = tk.Text(f, width=50, height=4, wrap=tk.NONE,
                                    font=('monospace', 9))
        self.scales_text.grid(row=row, column=0, columnspan=2,
                               sticky='ew', padx=6, pady=2)
        add_tooltip(self.scales_text,
                    'JSON dict mapping signal name to scale, e.g. {"exploration": 1.0, "hp": 0.5}')
        row += 1

        # Allowed actions (progressive action masking)
        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky='ew', pady=6)
        row += 1
        ttk.Label(f, text='Allowed actions (mask)', font=('TkDefaultFont', 9, 'bold')
                  ).grid(row=row, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        row += 1
        ttk.Label(f, text='(JSON list of action indices, empty = all allowed)',
                  foreground='gray').grid(row=row, column=0, columnspan=2,
                                           sticky='w', padx=6)
        row += 1

        self.actions_text = tk.Text(f, width=50, height=2, wrap=tk.NONE,
                                     font=('monospace', 9))
        self.actions_text.grid(row=row, column=0, columnspan=2,
                                sticky='ew', padx=6, pady=2)
        add_tooltip(self.actions_text,
                    'JSON list of allowed action indices, e.g. [0,1,2,3,4,5,6,7,38,40]. '
                    'Empty list [] means all actions are allowed.')
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

        btn_watch = ttk.Button(btn_row, text='🔴 Watch Live',
                                command=self._open_viewer)
        btn_watch.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_watch, 'Open the live training viewer in a separate window')
        row += 1

        # Model name + arena config
        cfg_row = ttk.Frame(f)
        cfg_row.grid(row=row, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        ttk.Label(cfg_row, text='Model name:').pack(side=tk.LEFT)
        self.v_model_name = tk.StringVar(value='curriculum')
        ttk.Entry(cfg_row, textvariable=self.v_model_name, width=20).pack(side=tk.LEFT, padx=4)
        ttk.Label(cfg_row, text='Parallel:').pack(side=tk.LEFT, padx=(8, 0))
        self.v_parallel = tk.StringVar(value='1')
        ttk.Entry(cfg_row, textvariable=self.v_parallel, width=3).pack(side=tk.LEFT)
        row += 1

        # (Arena size + creatures + map now live on the Pipeline rows
        # above, per-phase. The old separate Arena section was merged
        # into the 3-row pipeline.)

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
        self.v_fatigue.set(bool(r['fatigue_enabled']) if r['fatigue_enabled'] is not None else True)
        self.v_mappo.set(str(r['mappo_steps']))
        self.v_es_gens.set(str(r['es_generations']))
        self.v_es_vars.set(str(r['es_variants']))
        self.v_es_steps.set(str(r['es_steps']))
        self.v_ppo.set(str(r['ppo_steps']))
        self.v_lr.set(str(r['learning_rate']))
        self.v_ent.set(str(r['ent_coef']))
        self.v_resume.set(str(r['resume_from_stage']) if r['resume_from_stage'] is not None else '')

        # Per-phase parallelism / creatures / arena / map. Guarded
        # by ``keys()`` check so pre-migration DBs don't throw.
        _cols = set(r.keys())
        def _set(var, key, default=''):
            if key in _cols and r[key] is not None:
                var.set(str(r[key]))
            else:
                var.set(str(default))
        _set(self.v_ppo_parallel,    'ppo_parallel',    1)
        _set(self.v_es_parallel,     'es_parallel',     1)
        _set(self.v_mappo_creatures, 'mappo_creatures', 0)
        _set(self.v_ppo_creatures,   'ppo_creatures',   0)
        _set(self.v_mappo_cols,      'mappo_cols',      0)
        _set(self.v_mappo_rows,      'mappo_rows',      0)
        _set(self.v_ppo_cols,        'ppo_cols',        0)
        _set(self.v_ppo_rows,        'ppo_rows',        0)
        # arena_map is shared (single column) — populate both UI
        # fields with the same value so either can be edited
        _set(self.v_mappo_map, 'arena_map', '')
        _set(self.v_ppo_map,   'arena_map', '')

        # Run order + new phase params (imitation/league/pbt/curiosity/offline)
        _set(self.v_run_order,     'run_order',            'mappo,es,ppo')
        _set(self.v_imit_epochs,   'imitation_epochs',     0)
        _set(self.v_imit_batch,    'imitation_batch_size', 256)
        _set(self.v_imit_teacher,  'imitation_teacher',    'StatWeighted')
        _set(self.v_imit_parallel, 'imitation_parallel',   1)
        _set(self.v_league_iter,     'league_iterations', 0)
        _set(self.v_league_pool,     'league_pool_size',  4)
        _set(self.v_league_parallel, 'league_parallel',   1)
        _set(self.v_pbt_pop, 'pbt_population',        0)
        _set(self.v_pbt_mut, 'pbt_mutation_rate',     0.2)
        _set(self.v_pbt_thr, 'pbt_exploit_threshold', 0.25)
        _set(self.v_cur_weight, 'curiosity_weight', 0.0)
        _set(self.v_cur_hidden, 'curiosity_hidden', 64)
        _set(self.v_off_path,   'offline_replay_path',   '')
        _set(self.v_off_epochs, 'offline_replay_epochs', 0)
        # Pretty-print signal scales for editing
        try:
            scales = json.loads(r['signal_scales'] or '{}')
        except Exception:
            scales = {}
        self.scales_text.delete('1.0', tk.END)
        self.scales_text.insert('1.0', json.dumps(scales, indent=2))
        # Pretty-print allowed actions for editing
        try:
            allowed = json.loads(r['allowed_actions'] or '[]')
        except Exception:
            allowed = []
        self.actions_text.delete('1.0', tk.END)
        self.actions_text.insert('1.0', json.dumps(allowed))

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
            actions_str = self.actions_text.get('1.0', tk.END).strip() or '[]'
            allowed_actions = json.loads(actions_str)
            if not isinstance(allowed_actions, list):
                raise ValueError('allowed_actions must be a JSON list')
            mappo = int(self.v_mappo.get() or 0)
            es_gens = int(self.v_es_gens.get() or 0)
            es_vars = int(self.v_es_vars.get() or 20)
            es_steps = int(self.v_es_steps.get() or 1000)
            ppo = int(self.v_ppo.get() or 0)
            lr = float(self.v_lr.get() or 3e-4)
            ent = float(self.v_ent.get() or 0.05)
            resume_str = self.v_resume.get().strip()
            resume = int(resume_str) if resume_str else None
            ppo_parallel = int(self.v_ppo_parallel.get() or 1)
            es_parallel = int(self.v_es_parallel.get() or 1)
            mappo_creatures = int(self.v_mappo_creatures.get() or 0)
            ppo_creatures = int(self.v_ppo_creatures.get() or 0)
            mappo_cols = int(self.v_mappo_cols.get() or 0)
            mappo_rows = int(self.v_mappo_rows.get() or 0)
            ppo_cols = int(self.v_ppo_cols.get() or 0)
            ppo_rows = int(self.v_ppo_rows.get() or 0)
            # Either map field authoritative; prefer non-empty mappo_map.
            arena_map = (self.v_mappo_map.get().strip()
                         or self.v_ppo_map.get().strip() or '')
            run_order = (self.v_run_order.get().strip() or 'mappo,es,ppo')
            imit_epochs = int(self.v_imit_epochs.get() or 0)
            imit_batch = int(self.v_imit_batch.get() or 256)
            imit_teacher = (self.v_imit_teacher.get().strip() or 'StatWeighted')
            imit_parallel = int(self.v_imit_parallel.get() or 1)
            league_iter = int(self.v_league_iter.get() or 0)
            league_pool = int(self.v_league_pool.get() or 4)
            league_parallel = int(self.v_league_parallel.get() or 1)
            pbt_pop = int(self.v_pbt_pop.get() or 0)
            pbt_mut = float(self.v_pbt_mut.get() or 0.2)
            pbt_thr = float(self.v_pbt_thr.get() or 0.25)
            cur_w = float(self.v_cur_weight.get() or 0.0)
            cur_h = int(self.v_cur_hidden.get() or 64)
            off_path = self.v_off_path.get().strip()
            off_ep = int(self.v_off_epochs.get() or 0)
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
                   fatigue_enabled=?,
                   mappo_steps=?, es_generations=?, es_variants=?, es_steps=?,
                   ppo_steps=?, learning_rate=?, ent_coef=?,
                   resume_from_stage=?, allowed_actions=?,
                   mappo_creatures=?, ppo_creatures=?,
                   es_parallel=?, ppo_parallel=?,
                   mappo_cols=?, mappo_rows=?, ppo_cols=?, ppo_rows=?,
                   arena_map=?,
                   run_order=?,
                   imitation_epochs=?, imitation_batch_size=?,
                   imitation_teacher=?, imitation_parallel=?,
                   league_iterations=?, league_pool_size=?, league_parallel=?,
                   pbt_population=?, pbt_mutation_rate=?, pbt_exploit_threshold=?,
                   curiosity_weight=?, curiosity_hidden=?,
                   offline_replay_path=?, offline_replay_epochs=?
                   WHERE stage_number=?''',
                (self.v_name.get().strip(),
                 self.desc_text.get('1.0', tk.END).strip(),
                 json.dumps(active_signals), json.dumps(scales),
                 1 if self.v_hunger.get() else 0,
                 1 if self.v_combat.get() else 0,
                 1 if self.v_gestation.get() else 0,
                 1 if self.v_fatigue.get() else 0,
                 mappo, es_gens, es_vars, es_steps, ppo, lr, ent, resume,
                 json.dumps(allowed_actions),
                 mappo_creatures, ppo_creatures,
                 es_parallel, ppo_parallel,
                 mappo_cols, mappo_rows, ppo_cols, ppo_rows,
                 arena_map,
                 run_order,
                 imit_epochs, imit_batch, imit_teacher, imit_parallel,
                 league_iter, league_pool, league_parallel,
                 pbt_pop, pbt_mut, pbt_thr,
                 cur_w, cur_h,
                 off_path, off_ep,
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
            '--mappo-cols', self.v_mappo_cols.get(),
            '--mappo-rows', self.v_mappo_rows.get(),
            '--mappo-creatures', self.v_mappo_creatures.get(),
            '--ppo-cols', self.v_ppo_cols.get(),
            '--ppo-rows', self.v_ppo_rows.get(),
            '--ppo-creatures', self.v_ppo_creatures.get(),
            '--parallel', self.v_parallel.get(),
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

    def _open_viewer(self):
        """Launch the live training viewer in a separate process.

        The viewer reads from editor/simulation/_live_state.json which
        is written by run_mappo / run_ppo regardless of which sub-tab
        launched the training. So opening it from here works whether
        the running training was kicked off via Standard, Curriculum,
        or even the CLI.
        """
        try:
            subprocess.Popen([
                sys.executable, '-m', 'editor.simulation.viewer',
                '--scenario', 'training',
            ], cwd=str(Path(__file__).parent.parent))
        except Exception as e:
            messagebox.showerror('Viewer', str(e))
