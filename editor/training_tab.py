"""
Training control tab for the editor.

Launch/stop training, view live stats, open TensorBoard.
"""
import os
import signal
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
from pathlib import Path

from editor.tooltip import add_tooltip

SRC_DIR = Path(__file__).parent.parent / 'src'
MODELS_DIR = SRC_DIR / 'models'
RUNS_DIR = SRC_DIR / 'runs'


class TrainingTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._process = None
        self._tb_process = None
        self._log_thread = None
        self._running = False
        self._build_ui()

    def _build_ui(self):
        # -- Controls --
        ctrl = ttk.LabelFrame(self, text='Training Controls', padding=8)
        ctrl.pack(fill=tk.X, padx=8, pady=4)

        row1 = ttk.Frame(ctrl)
        row1.pack(fill=tk.X, pady=2)

        ttk.Label(row1, text='Cycles:').pack(side=tk.LEFT, padx=4)
        self.v_cycles = tk.StringVar(value='1')
        e = ttk.Entry(row1, textvariable=self.v_cycles, width=5)
        e.pack(side=tk.LEFT, padx=2)
        add_tooltip(e, 'Number of MAPPO → ES → PPO cycles')

        ttk.Label(row1, text='MAPPO steps:').pack(side=tk.LEFT, padx=4)
        self.v_mappo = tk.StringVar(value='50000')
        e = ttk.Entry(row1, textvariable=self.v_mappo, width=8)
        e.pack(side=tk.LEFT, padx=2)
        add_tooltip(e, 'Steps per MAPPO phase')

        ttk.Label(row1, text='PPO steps:').pack(side=tk.LEFT, padx=4)
        self.v_ppo = tk.StringVar(value='50000')
        e = ttk.Entry(row1, textvariable=self.v_ppo, width=8)
        e.pack(side=tk.LEFT, padx=2)
        add_tooltip(e, 'Steps per PPO phase')

        row2 = ttk.Frame(ctrl)
        row2.pack(fill=tk.X, pady=2)

        ttk.Label(row2, text='ES gens:').pack(side=tk.LEFT, padx=4)
        self.v_es_gens = tk.StringVar(value='20')
        e = ttk.Entry(row2, textvariable=self.v_es_gens, width=5)
        e.pack(side=tk.LEFT, padx=2)
        add_tooltip(e, 'ES generations')

        ttk.Label(row2, text='ES variants:').pack(side=tk.LEFT, padx=4)
        self.v_es_vars = tk.StringVar(value='20')
        e = ttk.Entry(row2, textvariable=self.v_es_vars, width=5)
        e.pack(side=tk.LEFT, padx=2)
        add_tooltip(e, 'ES variants per generation')

        ttk.Label(row2, text='LR:').pack(side=tk.LEFT, padx=4)
        self.v_lr = tk.StringVar(value='0.0003')
        e = ttk.Entry(row2, textvariable=self.v_lr, width=8)
        e.pack(side=tk.LEFT, padx=2)
        add_tooltip(e, 'Learning rate')

        ttk.Label(row2, text='Seed:').pack(side=tk.LEFT, padx=4)
        self.v_seed = tk.StringVar(value='42')
        e = ttk.Entry(row2, textvariable=self.v_seed, width=6)
        e.pack(side=tk.LEFT, padx=2)
        add_tooltip(e, 'Random seed for reproducibility')

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

        # Run name + resume
        name_row = ttk.Frame(ctrl)
        name_row.pack(fill=tk.X, pady=2)
        ttk.Label(name_row, text='Run name:').pack(side=tk.LEFT, padx=4)
        self.v_run_name = tk.StringVar(value='')
        e = ttk.Entry(name_row, textvariable=self.v_run_name, width=20)
        e.pack(side=tk.LEFT, padx=2)
        add_tooltip(e, 'Name for this training run (blank = auto timestamp)')

        ttk.Label(name_row, text='Resume from:').pack(side=tk.LEFT, padx=8)
        self.v_resume = tk.StringVar(value='(new)')
        self._checkpoint_list = ['(new)']
        self._refresh_checkpoints()
        self.resume_cb = ttk.Combobox(name_row, textvariable=self.v_resume,
                                      values=self._checkpoint_list, width=25)
        self.resume_cb.pack(side=tk.LEFT, padx=2)
        add_tooltip(self.resume_cb, 'Start fresh or resume from a saved .pt checkpoint')
        btn_refresh = ttk.Button(name_row, text='↻', width=3, command=self._refresh_checkpoints)
        btn_refresh.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_refresh, 'Refresh checkpoint list')

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

        # -- Saved models --
        models_frame = ttk.LabelFrame(self, text='Saved Models', padding=4)
        models_frame.pack(fill=tk.X, padx=8, pady=4)

        self.models_list = tk.Listbox(models_frame, height=4, width=60)
        self.models_list.pack(fill=tk.X)
        self._refresh_models()

    def _refresh_checkpoints(self):
        self._checkpoint_list = ['(new)']
        if MODELS_DIR.exists():
            for f in sorted(MODELS_DIR.glob('*.pt')):
                self._checkpoint_list.append(f.name)
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

        cmd = [
            'python', '-u', '-m', 'simulation.train',
            '--cycles', self.v_cycles.get(),
            '--mappo-steps', self.v_mappo.get(),
            '--ppo-steps', self.v_ppo.get(),
            '--es-generations', self.v_es_gens.get(),
            '--es-variants', self.v_es_vars.get(),
            '--lr', self.v_lr.get(),
            '--seed', self.v_seed.get(),
        ]
        run_name = self.v_run_name.get().strip()
        if run_name:
            cmd.extend(['--name', run_name])
        resume = self.v_resume.get()
        if resume and resume != '(new)':
            cmd.extend(['--resume', str(MODELS_DIR / resume)])

        self._log(f'Starting: {" ".join(cmd)}\n\n')
        self._process = subprocess.Popen(
            cmd, cwd=str(SRC_DIR),
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

    def _refresh_models(self):
        self.models_list.delete(0, tk.END)
        if MODELS_DIR.exists():
            for f in sorted(MODELS_DIR.glob('*.npz')):
                if f.name.startswith('_'):
                    continue
                size_mb = f.stat().st_size / (1024 * 1024)
                mtime = time.strftime('%Y-%m-%d %H:%M', time.localtime(f.stat().st_mtime))
                self.models_list.insert(tk.END, f'{f.name:30s} {size_mb:.1f}MB  {mtime}')
