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
        # Wrapped in a vertical scroll container so the growing pipeline
        # grid (8 phase rows + signals + actions + buttons) doesn't push
        # controls off the bottom of a small editor window.
        right = ttk.Frame(pane)
        pane.add(right, weight=1)

        _canvas = tk.Canvas(right, highlightthickness=0)
        _vsb = ttk.Scrollbar(right, orient=tk.VERTICAL, command=_canvas.yview)
        _canvas.configure(yscrollcommand=_vsb.set)
        _canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        _vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # The real form lives inside an inner frame placed into the
        # canvas via create_window. Size is re-measured whenever the
        # inner frame changes so the scrollregion stays correct.
        f = ttk.Frame(_canvas)
        _inner_id = _canvas.create_window((0, 0), window=f, anchor='nw')

        def _on_inner_configure(_event):
            _canvas.configure(scrollregion=_canvas.bbox('all'))
        f.bind('<Configure>', _on_inner_configure)

        def _on_canvas_configure(event):
            # Grow the inner frame to the canvas width so entries
            # stretching with sticky='ew' actually fill available space.
            _canvas.itemconfigure(_inner_id, width=event.width)
        _canvas.bind('<Configure>', _on_canvas_configure)

        # Mouse-wheel scrolling when the cursor is over the canvas.
        # Linux uses Button-4/5; macOS/Windows use MouseWheel.
        def _on_mousewheel(event):
            delta = 0
            if hasattr(event, 'delta') and event.delta:
                delta = int(-event.delta / 40)
            elif getattr(event, 'num', 0) == 4:
                delta = -3
            elif getattr(event, 'num', 0) == 5:
                delta = 3
            if delta:
                _canvas.yview_scroll(delta, 'units')

        for _seq in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            _canvas.bind_all(_seq, _on_mousewheel, add='+')

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

        # Pipeline — JSON dict editor. Each key is a phase name; each
        # value is a dict of that phase's parameters. Much cleaner to
        # scan and edit than the previous 16-row grid with misaligned
        # columns across phases. Phases with all-default/zero params
        # can be omitted from the JSON (they'll use DB defaults).
        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky='ew', pady=6)
        row += 1
        ttk.Label(f, text='Pipeline (JSON)', font=('TkDefaultFont', 9, 'bold')
                  ).grid(row=row, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        row += 1
        ttk.Label(f, text='Phases execute in run_order; params here override DB defaults.',
                  foreground='gray').grid(row=row, column=0, columnspan=2,
                                           sticky='w', padx=6)
        row += 1

        self.pipeline_text = tk.Text(f, width=60, height=14, wrap=tk.NONE,
                                      font=('monospace', 9))
        self.pipeline_text.grid(row=row, column=0, columnspan=2,
                                 sticky='ew', padx=6, pady=2)
        add_tooltip(self.pipeline_text,
                    'JSON dict of phase params. Keys: imitation, mappo, es, ppo, '
                    'league, pbt, curiosity, offline_replay.\n\n'
                    'Example:\n'
                    '{\n'
                    '  "imitation": {"epochs": 3, "teacher": "StatWeighted"},\n'
                    '  "mappo": {"steps": 20000, "creatures": 10, "cols": 20},\n'
                    '  "es": {"gens": 0, "variants": 20, "steps": 1000, "parallel": 4},\n'
                    '  "ppo": {"steps": 20000, "parallel": 4, "creatures": 16, "cols": 25}\n'
                    '}')
        row += 1

        # Run order + global hparams
        hp = ttk.Frame(f)
        hp.grid(row=row, column=0, columnspan=2, sticky='w', padx=6, pady=(2, 4))
        row += 1
        ttk.Label(hp, text='Run order:').pack(side=tk.LEFT)
        self.v_run_order = tk.StringVar(value='mappo,es,ppo')
        _ro_e = ttk.Entry(hp, textvariable=self.v_run_order, width=40)
        _ro_e.pack(side=tk.LEFT, padx=(2, 10))
        add_tooltip(_ro_e,
                    'Comma-separated phase execution order. '
                    'Available: imitation, mappo, es, ppo, league, pbt, '
                    'curiosity, offline_replay')

        hp2 = ttk.Frame(f)
        hp2.grid(row=row, column=0, columnspan=2, sticky='w', padx=6, pady=(0, 4))
        row += 1
        self.v_lr = tk.StringVar()
        self.v_ent = tk.StringVar()
        self.v_resume = tk.StringVar()
        self.v_episode_len = tk.StringVar(value='0')
        for lbl, var, w, tip in [
            ('LR:', self.v_lr, 8, 'Learning rate (Adam)'),
            ('Entropy:', self.v_ent, 8, 'Entropy bonus coefficient'),
            ('Episode len:', self.v_episode_len, 7, 'Creature lifespan per episode (0=legacy)'),
            ('Resume:', self.v_resume, 5, 'Resume from stage N (blank=no auto-resume)'),
        ]:
            ttk.Label(hp2, text=lbl).pack(side=tk.LEFT)
            e = ttk.Entry(hp2, textvariable=var, width=w)
            e.pack(side=tk.LEFT, padx=(2, 8))
            add_tooltip(e, tip)

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

        # Model name. Parallelism is now per-phase per-stage (see
        # Pipeline grid above) so the old global Parallel field has
        # been retired — each stage declares its own ES / PPO worker
        # count in the DB.
        cfg_row = ttk.Frame(f)
        cfg_row.grid(row=row, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        ttk.Label(cfg_row, text='Model name:').pack(side=tk.LEFT)
        self.v_model_name = tk.StringVar(value='curriculum')
        ttk.Entry(cfg_row, textvariable=self.v_model_name, width=20).pack(side=tk.LEFT, padx=4)
        row += 1

        # (Arena size + creatures + map now live on the Pipeline rows
        # above, per-phase. The old separate Arena section was merged
        # into the 3-row pipeline.)

        # Status line
        self.status = ttk.Label(f, text='ready', foreground='gray')
        self.status.grid(row=row, column=0, columnspan=2, sticky='w', padx=6, pady=4)
        row += 1

        f.columnconfigure(1, weight=1)

    # ------------------------------------------------------------------
    # Pipeline JSON ↔ flat DB column helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_pipeline_json(r) -> str:
        """Build a pretty-printed JSON dict from flat curriculum_stages row."""
        _cols = set(r.keys()) if hasattr(r, 'keys') else set()
        def _g(key, default=0):
            return r[key] if key in _cols and r[key] is not None else default

        d = {}
        # Only include phases that have non-zero/non-default params
        imit = {}
        if _g('imitation_epochs'):
            imit['epochs'] = _g('imitation_epochs')
            imit['batch_size'] = _g('imitation_batch_size', 256)
            imit['teacher'] = _g('imitation_teacher', 'StatWeighted')
        if imit:
            d['imitation'] = imit

        mappo = {}
        if _g('mappo_steps'):
            mappo['steps'] = _g('mappo_steps')
        if _g('mappo_creatures'):
            mappo['creatures'] = _g('mappo_creatures')
        if _g('mappo_cols'):
            mappo['cols'] = _g('mappo_cols')
        if _g('mappo_rows'):
            mappo['rows'] = _g('mappo_rows')
        if mappo:
            d['mappo'] = mappo

        es = {}
        if _g('es_generations'):
            es['gens'] = _g('es_generations')
        es['variants'] = _g('es_variants', 20)
        es['steps'] = _g('es_steps', 1000)
        if _g('es_parallel', 1) > 1:
            es['parallel'] = _g('es_parallel', 1)
        if es.get('gens'):
            d['es'] = es

        ppo = {}
        if _g('ppo_steps'):
            ppo['steps'] = _g('ppo_steps')
        if _g('ppo_parallel', 1) > 1:
            ppo['parallel'] = _g('ppo_parallel', 1)
        if _g('ppo_creatures'):
            ppo['creatures'] = _g('ppo_creatures')
        if _g('ppo_cols'):
            ppo['cols'] = _g('ppo_cols')
        if _g('ppo_rows'):
            ppo['rows'] = _g('ppo_rows')
        if ppo:
            d['ppo'] = ppo

        # Stubs — only include if non-default
        if _g('league_iterations'):
            d['league'] = {'iterations': _g('league_iterations'),
                           'pool_size': _g('league_pool_size', 4)}
        if _g('pbt_population'):
            d['pbt'] = {'population': _g('pbt_population'),
                        'mutation_rate': float(_g('pbt_mutation_rate', 0.2))}
        if float(_g('curiosity_weight', 0)) > 0:
            d['curiosity'] = {'weight': float(_g('curiosity_weight')),
                              'hidden': _g('curiosity_hidden', 64)}

        arena_map = _g('arena_map', '')
        if arena_map:
            d['arena_map'] = arena_map

        return json.dumps(d, indent=2)

    @staticmethod
    def _pipeline_json_to_flat(text: str) -> dict:
        """Parse the JSON pipeline text into a flat dict of DB column values."""
        d = json.loads(text or '{}')
        flat = {}
        imit = d.get('imitation', {})
        flat['imitation_epochs'] = int(imit.get('epochs', 0))
        flat['imitation_batch_size'] = int(imit.get('batch_size', 256))
        flat['imitation_teacher'] = imit.get('teacher', 'StatWeighted')
        flat['imitation_parallel'] = int(imit.get('parallel', 1))

        mappo = d.get('mappo', {})
        flat['mappo_steps'] = int(mappo.get('steps', 0))
        flat['mappo_creatures'] = int(mappo.get('creatures', 0))
        flat['mappo_cols'] = int(mappo.get('cols', 0))
        flat['mappo_rows'] = int(mappo.get('rows', 0))

        es = d.get('es', {})
        flat['es_generations'] = int(es.get('gens', 0))
        flat['es_variants'] = int(es.get('variants', 20))
        flat['es_steps'] = int(es.get('steps', 1000))
        flat['es_parallel'] = int(es.get('parallel', 1))

        ppo = d.get('ppo', {})
        flat['ppo_steps'] = int(ppo.get('steps', 0))
        flat['ppo_parallel'] = int(ppo.get('parallel', 1))
        flat['ppo_creatures'] = int(ppo.get('creatures', 0))
        flat['ppo_cols'] = int(ppo.get('cols', 0))
        flat['ppo_rows'] = int(ppo.get('rows', 0))

        league = d.get('league', {})
        flat['league_iterations'] = int(league.get('iterations', 0))
        flat['league_pool_size'] = int(league.get('pool_size', 4))
        flat['league_parallel'] = int(league.get('parallel', 1))

        pbt = d.get('pbt', {})
        flat['pbt_population'] = int(pbt.get('population', 0))
        flat['pbt_mutation_rate'] = float(pbt.get('mutation_rate', 0.2))
        flat['pbt_exploit_threshold'] = float(pbt.get('exploit_threshold', 0.25))

        cur = d.get('curiosity', {})
        flat['curiosity_weight'] = float(cur.get('weight', 0.0))
        flat['curiosity_hidden'] = int(cur.get('hidden', 64))

        off = d.get('offline_replay', {})
        flat['offline_replay_path'] = off.get('path', '')
        flat['offline_replay_epochs'] = int(off.get('epochs', 0))

        flat['arena_map'] = d.get('arena_map', '')
        return flat

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
        # Pipeline JSON — one compact view of all phase parameters
        self.pipeline_text.delete('1.0', tk.END)
        self.pipeline_text.insert('1.0', self._row_to_pipeline_json(r))

        # Global hparams + run_order
        self.v_lr.set(str(r['learning_rate']))
        self.v_ent.set(str(r['ent_coef']))
        self.v_resume.set(str(r['resume_from_stage']) if r['resume_from_stage'] is not None else '')
        _cols = set(r.keys())
        self.v_run_order.set(
            r['run_order'] if 'run_order' in _cols and r['run_order'] else 'mappo,es,ppo')
        self.v_episode_len.set(
            str(r['episode_len']) if 'episode_len' in _cols and r['episode_len'] is not None else '0')
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
            # Parse pipeline JSON → flat DB columns
            pipe_str = self.pipeline_text.get('1.0', tk.END).strip() or '{}'
            p = self._pipeline_json_to_flat(pipe_str)

            lr = float(self.v_lr.get() or 3e-4)
            ent = float(self.v_ent.get() or 0.05)
            resume_str = self.v_resume.get().strip()
            resume = int(resume_str) if resume_str else None
            run_order = (self.v_run_order.get().strip() or 'mappo,es,ppo')
            episode_len = int(self.v_episode_len.get() or 0)
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
                   offline_replay_path=?, offline_replay_epochs=?,
                   episode_len=?
                   WHERE stage_number=?''',
                (self.v_name.get().strip(),
                 self.desc_text.get('1.0', tk.END).strip(),
                 json.dumps(active_signals), json.dumps(scales),
                 1 if self.v_hunger.get() else 0,
                 1 if self.v_combat.get() else 0,
                 1 if self.v_gestation.get() else 0,
                 1 if self.v_fatigue.get() else 0,
                 p['mappo_steps'], p['es_generations'], p['es_variants'],
                 p['es_steps'], p['ppo_steps'], lr, ent, resume,
                 json.dumps(allowed_actions),
                 p['mappo_creatures'], p['ppo_creatures'],
                 p['es_parallel'], p['ppo_parallel'],
                 p['mappo_cols'], p['mappo_rows'],
                 p['ppo_cols'], p['ppo_rows'],
                 p['arena_map'],
                 run_order,
                 p['imitation_epochs'], p['imitation_batch_size'],
                 p['imitation_teacher'], p['imitation_parallel'],
                 p['league_iterations'], p['league_pool_size'],
                 p['league_parallel'],
                 p['pbt_population'], p['pbt_mutation_rate'],
                 p['pbt_exploit_threshold'],
                 p['curiosity_weight'], p['curiosity_hidden'],
                 p['offline_replay_path'], p['offline_replay_epochs'],
                 episode_len,
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
            # Per-stage values are read from the curriculum_stages DB
            # at run time. These CLI flags are kept as overrides only
            # when non-zero; default '0' means "use the DB value."
            '--mappo-cols', self.v_mappo_cols.get(),
            '--mappo-rows', self.v_mappo_rows.get(),
            '--mappo-creatures', self.v_mappo_creatures.get(),
            '--ppo-cols', self.v_ppo_cols.get(),
            '--ppo-rows', self.v_ppo_rows.get(),
            '--ppo-creatures', self.v_ppo_creatures.get(),
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
