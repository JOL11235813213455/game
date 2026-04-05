import tkinter as tk
from tkinter import ttk

from editor.db import migrate_db
from editor.items_tab import ItemsTab
from editor.species_tab import SpeciesTab
from editor.sprites_tab import SpritesTab
from editor.tiles_tab import TilesTab
from editor.tile_sets_tab import TileSetsTab
from editor.maps_tab import MapsTab
from editor.animations_tab import AnimationsTab


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

        self.items_tab     = ItemsTab(notebook)
        self.species_tab   = SpeciesTab(notebook)
        self.sprites_tab   = SpritesTab(notebook, on_sprites_changed=self._on_sprites_changed)
        self.tiles_tab     = TilesTab(notebook)
        self.tile_sets_tab = TileSetsTab(notebook)
        self.maps_tab      = MapsTab(notebook)
        self.anims_tab     = AnimationsTab(notebook)

        notebook.add(self.sprites_tab,   text='  Sprites  ')
        notebook.add(self.anims_tab,     text='  Animations  ')
        notebook.add(self.tiles_tab,     text='  Tiles  ')
        notebook.add(self.tile_sets_tab, text='  Tile Sets  ')
        notebook.add(self.maps_tab,      text='  Maps  ')
        notebook.add(self.species_tab,   text='  Species  ')
        notebook.add(self.items_tab,     text='  Items  ')

        notebook.bind('<<NotebookTabChanged>>', self._on_tab_changed)

    def _on_sprites_changed(self):
        self.items_tab.refresh_sprite_dropdown()
        self.species_tab.refresh_sprite_dropdown()
        self.tiles_tab.refresh_sprite_dropdown()
        self.tile_sets_tab.refresh_sprite_dropdown()

    def _on_tab_changed(self, event):
        tab = event.widget.tab(event.widget.select(), 'text').strip()
        if tab in ('Items', 'Species', 'Tiles', 'Tile Sets'):
            self.items_tab.refresh_sprite_dropdown()
            self.species_tab.refresh_sprite_dropdown()
            self.tiles_tab.refresh_sprite_dropdown()
            self.tile_sets_tab.refresh_sprite_dropdown()
        if tab == 'Maps':
            self.maps_tab.refresh_tile_set_dropdown()
        if tab == 'Animations':
            self.anims_tab.refresh_dropdowns()
