"""
Training control tab for the editor.

Launch/stop training, view live stats, open TensorBoard.
"""
import os
import signal
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
from pathlib import Path

from editor.tooltip import add_tooltip

EDITOR_DIR = Path(__file__).parent
MODELS_DIR = EDITOR_DIR / 'models'
RUNS_DIR = EDITOR_DIR / 'runs'


class TrainingTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._process = None
        self._tb_process = None
        self._log_thread = None
        self._running = False
        self._build_ui()

    def _build_ui(self):
        # -- Pipeline overview --
        ctrl = ttk.LabelFrame(self, text='Training Pipeline: MAPPO → ES → PPO', padding=8)
        ctrl.pack(fill=tk.X, padx=8, pady=4)

        # General settings row
        gen_row = ttk.Frame(ctrl)
        gen_row.pack(fill=tk.X, pady=2)

        ttk.Label(gen_row, text='Cycles:').pack(side=tk.LEFT, padx=4)
        self.v_cycles = tk.StringVar(value='1')
        e = ttk.Entry(gen_row, textvariable=self.v_cycles, width=5)
        e.pack(side=tk.LEFT, padx=2)
        add_tooltip(e, 'Number of full MAPPO → ES → PPO cycles to run')

        ttk.Label(gen_row, text='LR:').pack(side=tk.LEFT, padx=12)
        self.v_lr = tk.StringVar(value='0.0003')
        e = ttk.Entry(gen_row, textvariable=self.v_lr, width=8)
        e.pack(side=tk.LEFT, padx=2)
        add_tooltip(e, 'Learning rate for MAPPO and PPO optimizers')

        ttk.Label(gen_row, text='Seed:').pack(side=tk.LEFT, padx=12)
        self.v_seed = tk.StringVar(value='42')
        e = ttk.Entry(gen_row, textvariable=self.v_seed, width=6)
        e.pack(side=tk.LEFT, padx=2)
        add_tooltip(e, 'Random seed for reproducibility')

        # Arena settings row
        arena_row = ttk.Frame(ctrl)
        arena_row.pack(fill=tk.X, pady=2)

        ttk.Label(arena_row, text='Arena size:').pack(side=tk.LEFT, padx=4)
        self.v_arena_cols = tk.StringVar(value='25')
        e = ttk.Entry(arena_row, textvariable=self.v_arena_cols, width=4)
        e.pack(side=tk.LEFT, padx=2)
        add_tooltip(e, 'Arena width in tiles')
        ttk.Label(arena_row, text='x').pack(side=tk.LEFT)
        self.v_arena_rows = tk.StringVar(value='25')
        e = ttk.Entry(arena_row, textvariable=self.v_arena_rows, width=4)
        e.pack(side=tk.LEFT, padx=2)
        add_tooltip(e, 'Arena height in tiles')

        ttk.Label(arena_row, text='Creatures:').pack(side=tk.LEFT, padx=12)
        self.v_num_creatures = tk.StringVar(value='16')
        e = ttk.Entry(arena_row, textvariable=self.v_num_creatures, width=4)
        e.pack(side=tk.LEFT, padx=2)
        add_tooltip(e, 'Number of creatures to spawn per arena')

        # --- Phase 1: MAPPO ---
        mappo_frame = ttk.LabelFrame(ctrl, text='Phase 1: MAPPO (multi-agent shared weights)', padding=4)
        mappo_frame.pack(fill=tk.X, pady=(6, 2))

        ttk.Label(mappo_frame, text='Steps:').pack(side=tk.LEFT, padx=4)
        self.v_mappo = tk.StringVar(value='50000')
        e = ttk.Entry(mappo_frame, textvariable=self.v_mappo, width=8)
        e.pack(side=tk.LEFT, padx=2)
        add_tooltip(e, 'MAPPO training steps — all creatures share one net and learn together')

        # --- Phase 2: ES ---
        es_frame = ttk.LabelFrame(ctrl, text='Phase 2: ES (weight perturbation + fitness eval)', padding=4)
        es_frame.pack(fill=tk.X, pady=2)

        ttk.Label(es_frame, text='Generations:').pack(side=tk.LEFT, padx=4)
        self.v_es_gens = tk.StringVar(value='20')
        e = ttk.Entry(es_frame, textvariable=self.v_es_gens, width=5)
        e.pack(side=tk.LEFT, padx=2)
        add_tooltip(e, 'ES generations — each generation tests all variants and updates weights toward the best')

        ttk.Label(es_frame, text='Variants:').pack(side=tk.LEFT, padx=8)
        self.v_es_vars = tk.StringVar(value='20')
        e = ttk.Entry(es_frame, textvariable=self.v_es_vars, width=5)
        e.pack(side=tk.LEFT, padx=2)
        add_tooltip(e, 'ES variants per generation — each variant is a random noise perturbation of the weights')

        ttk.Label(es_frame, text='Steps/variant:').pack(side=tk.LEFT, padx=8)
        self.v_es_steps = tk.StringVar(value='500')
        e = ttk.Entry(es_frame, textvariable=self.v_es_steps, width=6)
        e.pack(side=tk.LEFT, padx=2)
        add_tooltip(e, 'Simulation steps to evaluate each variant (total ES work = gens x variants x this)')

        # --- Phase 3: PPO ---
        ppo_frame = ttk.LabelFrame(ctrl, text='Phase 3: PPO (single-agent vs diverse opponents)', padding=4)
        ppo_frame.pack(fill=tk.X, pady=(2, 6))

        ttk.Label(ppo_frame, text='Steps:').pack(side=tk.LEFT, padx=4)
        self.v_ppo = tk.StringVar(value='50000')
        e = ttk.Entry(ppo_frame, textvariable=self.v_ppo, width=8)
        e.pack(side=tk.LEFT, padx=2)
        add_tooltip(e, 'PPO training steps — one agent trains against a mix of saved checkpoints and StatWeighted AI')

        # Buttons
        btn_row = ttk.Frame(ctrl)
        btn_row.pack(fill=tk.X, pady=4)

        self.btn_start = ttk.Button(btn_row, text='▶ Start Training', command=self._start)
        self.btn_start.pack(side=tk.LEFT, padx=4)
        add_tooltip(self.btn_start, 'Launch training in background')

        self.btn_stop = ttk.Button(btn_row, text='■ Stop', command=self._stop, state='disabled')
        self.btn_stop.pack(side=tk.LEFT, padx=4)
        add_tooltip(self.btn_stop, 'Kill training process')

        self.btn_tb = ttk.Button(btn_row, text='📊 Open TensorBoard', command=self._open_tensorboard)
        self.btn_tb.pack(side=tk.LEFT, padx=4)
        add_tooltip(self.btn_tb, 'Launch TensorBoard in browser (http://localhost:6006)')

        self.btn_train_viewer = ttk.Button(btn_row, text='🔴 Watch Training', command=self._open_training_viewer)
        self.btn_train_viewer.pack(side=tk.LEFT, padx=4)
        add_tooltip(self.btn_train_viewer, 'Watch the LIVE training simulation (must be running)')

        # Model name + resume from DB
        model_row = ttk.Frame(ctrl)
        model_row.pack(fill=tk.X, pady=2)
        ttk.Label(model_row, text='Model name:').pack(side=tk.LEFT, padx=4)
        self.v_model_name = tk.StringVar(value='alpha')
        e = ttk.Entry(model_row, textvariable=self.v_model_name, width=20)
        e.pack(side=tk.LEFT, padx=2)
        add_tooltip(e, 'Model lineage name — versions auto-increment in the DB')

        ttk.Label(model_row, text='Resume from:').pack(side=tk.LEFT, padx=8)
        self.v_resume = tk.StringVar(value='(new)')
        self._checkpoint_list = ['(new)']
        self._refresh_checkpoints()
        self.resume_cb = ttk.Combobox(model_row, textvariable=self.v_resume,
                                      values=self._checkpoint_list, width=35)
        self.resume_cb.pack(side=tk.LEFT, padx=2)
        add_tooltip(self.resume_cb, 'Start fresh or resume from a saved model version (name:version)')
        btn_refresh = ttk.Button(model_row, text='↻', width=3, command=self._refresh_checkpoints)
        btn_refresh.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_refresh, 'Refresh model list from DB')

        # Status
        self.v_status = tk.StringVar(value='Idle')
        ttk.Label(ctrl, textvariable=self.v_status, font=('TkDefaultFont', 10, 'bold')).pack(anchor='w', pady=2)

        # -- Log output --
        log_frame = ttk.LabelFrame(self, text='Training Log', padding=4)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self.log_text = tk.Text(log_frame, wrap=tk.WORD, height=25,
                                bg='#1e1e1e', fg='#cccccc',
                                font=('Consolas', 9), state='disabled')
        log_sb = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_sb.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_sb.pack(side=tk.RIGHT, fill=tk.Y)

        # -- Saved models (from DB) --
        models_frame = ttk.LabelFrame(self, text='Model Versions (game.db)', padding=4)
        models_frame.pack(fill=tk.X, padx=8, pady=4)

        self.models_list = tk.Listbox(models_frame, height=5, width=80,
                                       font=('Consolas', 9))
        self.models_list.pack(fill=tk.X)
        self._refresh_models()

    def _refresh_checkpoints(self):
        self._checkpoint_list = ['(new)']
        try:
            from editor.simulation.train import _list_models_from_db
            for m in _list_models_from_db():
                label = f'{m["name"]}:{m["version"]}'
                secs = m.get('training_seconds', 0)
                mins = secs / 60 if secs else 0
                extra = f' ({mins:.0f}min, obs={m["observation_size"]}, act={m["num_actions"]})'
                self._checkpoint_list.append(label + extra)
        except Exception:
            pass
        if hasattr(self, 'resume_cb'):
            self.resume_cb['values'] = self._checkpoint_list

    def _log(self, text):
        self.log_text.configure(state='normal')
        self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)
        self.log_text.configure(state='disabled')

    def _start(self):
        if self._running:
            messagebox.showwarning('Training', 'Training is already running.')
            return

        # Wrap in systemd-inhibit to prevent sleep during training
        cmd = [
            'systemd-inhibit', '--what=idle:sleep',
            '--who=RPGTraining', '--why=Training',
            sys.executable, '-u', '-m', 'editor.simulation.train',
            '--cycles', self.v_cycles.get(),
            '--mappo-steps', self.v_mappo.get(),
            '--ppo-steps', self.v_ppo.get(),
            '--es-generations', self.v_es_gens.get(),
            '--es-variants', self.v_es_vars.get(),
            '--es-steps', self.v_es_steps.get(),
            '--lr', self.v_lr.get(),
            '--seed', self.v_seed.get(),
            '--arena-cols', self.v_arena_cols.get(),
            '--arena-rows', self.v_arena_rows.get(),
            '--num-creatures', self.v_num_creatures.get(),
        ]
        model_name = self.v_model_name.get().strip()
        if model_name:
            cmd.extend(['--model', model_name])
        resume = self.v_resume.get()
        if resume and resume != '(new)':
            # Extract "name:version" from the display string (before the parenthetical)
            resume_key = resume.split(' (')[0]
            cmd.extend(['--resume', resume_key])

        self._log(f'Starting: {" ".join(cmd)}\n\n')
        self._process = subprocess.Popen(
            cmd, cwd=str(EDITOR_DIR.parent),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        self._running = True
        self.v_status.set('Training...')
        self.btn_start.configure(state='disabled')
        self.btn_stop.configure(state='normal')

        # Read output in background thread
        self._log_thread = threading.Thread(target=self._read_output, daemon=True)
        self._log_thread.start()

    def _read_output(self):
        try:
            for line in self._process.stdout:
                self.after(0, self._log, line)
        except Exception:
            pass
        finally:
            self._process.wait()
            self.after(0, self._on_training_done)

    def _on_training_done(self):
        self._running = False
        rc = self._process.returncode if self._process else -1
        self.v_status.set(f'Done (exit {rc})')
        self.btn_start.configure(state='normal')
        self.btn_stop.configure(state='disabled')
        self._refresh_models()
        self._refresh_checkpoints()
        self._log(f'\n--- Training finished (exit {rc}) ---\n')

    def _stop(self):
        if self._process:
            self._process.terminate()
            self._log('\n--- Training stopped by user ---\n')

    def _open_tensorboard(self):
        if self._tb_process and self._tb_process.poll() is None:
            # Already running
            import webbrowser
            webbrowser.open('http://localhost:6006')
            return

        self._tb_process = subprocess.Popen(
            ['tensorboard', '--logdir', str(RUNS_DIR), '--port', '6006', '--bind_all'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._log('TensorBoard started at http://localhost:6006\n')
        # Open browser after short delay
        self.after(2000, lambda: __import__('webbrowser').open('http://localhost:6006'))

    def _open_training_viewer(self):
        """Launch the LIVE training viewer — shows what training is doing right now."""
        cmd = [
            sys.executable, '-m', 'editor.simulation.viewer',
            '--scenario', 'training',
        ]
        self._log('Launching live training viewer\n')
        subprocess.Popen(cmd, cwd=str(EDITOR_DIR.parent))

    def _refresh_models(self):
        self.models_list.delete(0, tk.END)
        try:
            from editor.simulation.train import _list_models_from_db
            for m in _list_models_from_db():
                secs = m.get('training_seconds', 0)
                mins = secs / 60 if secs else 0
                notes = m.get('notes', '')[:30]
                line = (f'{m["name"]:15s} v{m["version"]:<4d} '
                        f'obs={m["observation_size"]}  act={m["num_actions"]}  '
                        f'{mins:5.0f}min  {m["created_at"]}')
                if notes:
                    line += f'  {notes}'
                self.models_list.insert(tk.END, line)
        except Exception:
            self.models_list.insert(tk.END, '(no models in DB)')
