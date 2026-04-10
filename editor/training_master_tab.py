"""
Training master tab — wraps Standard, Curriculum, and Models in a sub-notebook.

The Training top-level tab in the editor is now a Notebook with three
sub-tabs:

  Standard   — original manual MAPPO/ES/PPO config (legacy TrainingTab)
  Curriculum — staged training curriculum: edit per-stage config, run one
               or all stages
  Models     — browse all trained models in nn_models, edit notes, delete

This module is purely a layout/wiring shell. The actual sub-tab classes
live in their own files and follow the standard editor tab pattern
(left listbox + right form, get_con/save/delete).
"""
import tkinter as tk
from tkinter import ttk


class TrainingMasterTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True)

        # Lazy imports so editor startup doesn't pay torch / tensorboard
        # cost just to render the empty Training tab.
        from editor.training_tab import TrainingStandardTab
        from editor.training_curriculum_tab import TrainingCurriculumTab
        from editor.training_models_tab import TrainingModelsTab

        self.standard = TrainingStandardTab(nb)
        self.curriculum = TrainingCurriculumTab(nb)
        self.models = TrainingModelsTab(nb)

        nb.add(self.standard,   text='  Standard  ')
        nb.add(self.curriculum, text='  Curriculum  ')
        nb.add(self.models,     text='  Models  ')
