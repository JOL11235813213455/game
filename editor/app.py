import tkinter as tk
from tkinter import ttk

from editor.db import migrate_db


class _LazyTab(ttk.Frame):
    """Placeholder that builds the real tab on first view."""

    def __init__(self, parent, factory, **kwargs):
        super().__init__(parent, **kwargs)
        self._factory = factory
        self._built = False
        self._real = None

    def _ensure_built(self):
        if not self._built:
            self._real = self._factory(self)
            self._real.pack(fill=tk.BOTH, expand=True)
            self._built = True
        return self._real


class EditorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        migrate_db()
        self.title('RPG Database Editor')
        self.minsize(1000, 700)
        self.geometry('1200x800')

        style = ttk.Style(self)
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass

        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # ALL tabs lazy loaded for fast startup
        self._gfx_lazy = _LazyTab(notebook, self._make_graphics)
        self._maps_lazy = _LazyTab(notebook, self._make_maps)
        notebook.add(self._gfx_lazy, text='  Graphics  ')
        notebook.add(self._maps_lazy, text='  Maps  ')
        self._creatures_lazy = _LazyTab(notebook, self._make_creatures)
        self._items_lazy = _LazyTab(notebook, self._make_items)
        self._spells_lazy = _LazyTab(notebook, self._make_spells)
        self._quests_lazy = _LazyTab(notebook, self._make_quests)
        self._gods_lazy = _LazyTab(notebook, self._make_gods)
        self._dialogue_lazy = _LazyTab(notebook, self._make_dialogue)
        self._training_lazy = _LazyTab(notebook, self._make_training)
        self._sql_lazy = _LazyTab(notebook, self._make_sql)

        notebook.add(self._creatures_lazy, text='  Creatures  ')
        notebook.add(self._items_lazy,     text='  Items  ')
        notebook.add(self._spells_lazy,    text='  Spells  ')
        notebook.add(self._quests_lazy,    text='  Quests  ')
        notebook.add(self._gods_lazy,      text='  Gods  ')
        notebook.add(self._dialogue_lazy,  text='  Dialogue  ')
        notebook.add(self._training_lazy,  text='  Training  ')
        notebook.add(self._sql_lazy,       text='  SQL  ')

        notebook.bind('<<NotebookTabChanged>>', self._on_tab_changed)

    # -- Lazy factories --
    def _make_graphics(self, parent):
        from editor.sprites_tab import SpritesTab
        from editor.animations_tab import AnimationsTab
        from editor.composites_tab import CompositesTab
        nb = ttk.Notebook(parent)
        nb.pack(fill=tk.BOTH, expand=True)
        self.sprites_tab = SpritesTab(nb, on_sprites_changed=self._on_sprites_changed)
        self.anims_tab = AnimationsTab(nb)
        self.composites_tab = CompositesTab(nb)
        nb.add(self.sprites_tab, text='  Sprites  ')
        nb.add(self.anims_tab, text='  Simple  ')
        nb.add(self.composites_tab, text='  Composite  ')
        return nb

    def _make_maps(self, parent):
        from editor.map_editor_tab import MapEditorTab
        from editor.tiles_tab import TilesTab
        nb = ttk.Notebook(parent)
        nb.pack(fill=tk.BOTH, expand=True)
        self.map_editor_tab = MapEditorTab(nb)
        self.tiles_tab = TilesTab(nb)
        nb.add(self.map_editor_tab, text='  Map Editor  ')
        nb.add(self.tiles_tab, text='  Tile Templates  ')
        return nb

    def _make_creatures(self, parent):
        from editor.creatures_master_tab import CreaturesMasterTab
        return CreaturesMasterTab(parent)

    def _make_items(self, parent):
        from editor.items_tab import ItemsTab
        return ItemsTab(parent)

    def _make_spells(self, parent):
        from editor.spells_tab import SpellsTab
        return SpellsTab(parent)

    def _make_quests(self, parent):
        from editor.quests_tab import QuestsTab
        return QuestsTab(parent)

    def _make_gods(self, parent):
        from editor.gods_tab import GodsTab
        return GodsTab(parent)

    def _make_dialogue(self, parent):
        from editor.dialogue_tab import DialogueTab
        return DialogueTab(parent)

    def _make_training(self, parent):
        from editor.training_tab import TrainingTab
        return TrainingTab(parent)

    def _make_sql(self, parent):
        from editor.sql_tab import SqlTab
        return SqlTab(parent)

    def _on_sprites_changed(self):
        if hasattr(self, 'tiles_tab'):
            self.tiles_tab.refresh_sprite_dropdown()
        for lazy in [self._creatures_lazy, self._items_lazy, self._spells_lazy]:
            if lazy._real and hasattr(lazy._real, 'refresh_sprite_dropdown'):
                lazy._real.refresh_sprite_dropdown()

    def _on_tab_changed(self, event):
        tab = event.widget.tab(event.widget.select(), 'text').strip()

        # Build lazy tab on first visit
        for lazy in [self._gfx_lazy, self._maps_lazy,
                     self._creatures_lazy, self._items_lazy, self._spells_lazy,
                     self._quests_lazy, self._gods_lazy, self._dialogue_lazy,
                     self._training_lazy, self._sql_lazy]:
            # Check if this lazy tab is the currently selected one
            try:
                if event.widget.select() == str(lazy):
                    lazy._ensure_built()
            except Exception:
                pass

        if tab in ('Items', 'Creatures', 'Tile Templates', 'Maps'):
            if hasattr(self, 'tiles_tab'):
                self.tiles_tab.refresh_sprite_dropdown()
            for lazy in [self._creatures_lazy, self._items_lazy]:
                if lazy._real and hasattr(lazy._real, 'refresh_sprite_dropdown'):
                    lazy._real.refresh_sprite_dropdown()
        if tab == 'Creatures' and self._creatures_lazy._real:
            if hasattr(self._creatures_lazy._real, 'refresh_species_dropdown'):
                self._creatures_lazy._real.refresh_species_dropdown()
        if tab in ('Map Editor', 'Maps') and hasattr(self, 'map_editor_tab'):
            self.map_editor_tab.refresh_dropdowns()
        if tab in ('Simple', 'Animations') and hasattr(self, 'anims_tab'):
            self.anims_tab.refresh_dropdowns()
        if tab in ('Composite', 'Composites') and hasattr(self, 'composites_tab'):
            self.composites_tab.refresh_dropdowns()
        if tab == 'Dialogue' and self._dialogue_lazy._real:
            if hasattr(self._dialogue_lazy._real, 'refresh_dropdowns'):
                self._dialogue_lazy._real.refresh_dropdowns()
