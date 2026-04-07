"""Visual map editor tab — unified map metadata + tile painting."""
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

from editor.db import (get_con, fetch_tile_template_keys, fetch_tile_set_names,
                        fetch_map_names, fetch_sprite_names,
                        fetch_animation_names)
from editor.map_canvas import MapCanvas
from editor.tile_palette import TilePalette
from editor.tooltip import add_tooltip


class MapEditorTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._map_names: list[str] = []
        self._current_map_name: str | None = None
        self._all_tiles: dict[tuple, dict] = {}  # (x,y) → tile_sets row, all Z levels
        self._tiles: dict[tuple, dict] = {}       # (x,y) → filtered to current Z
        self._dirty = False
        self._build_ui()
        self.refresh_map_list()

    # ------------------------------------------------------------------
    # UI Build
    # ------------------------------------------------------------------

    # Sentinel for mixed values across a multi-tile selection
    _MIXED = object()

    # All tile property fields: (field_key, label, widget_type, tooltip)
    # widget_type: 'entry', 'check', 'combo_tmpl', 'combo_map', 'bounds_row'
    _PROP_FIELDS = [
        ('tile_template', 'Template', 'combo_tmpl',
         'Tile template key'),
        ('walkable', 'Walkable', 'check',
         'Whether creatures can walk on this tile'),
        ('covered', 'Covered', 'check',
         'Whether this tile acts as a roof/ceiling'),
        ('sprite_name', 'Sprite', 'combo_sprite',
         'Override sprite (leave empty to use template)'),
        ('tile_scale', 'Tile Scale', 'entry',
         'Visual scale multiplier (1.0 = normal)'),
        ('animation_name', 'Animation', 'combo_anim',
         'Animation to play on this tile'),
        ('search_text', 'Search Text', 'entry',
         'Arbitrary text for searching/filtering tiles'),
        ('stat_mods', 'Stat Mods', 'entry',
         'JSON dict of stat modifiers (e.g. {"str": 1})'),
        ('nested_map', 'Nested Map', 'combo_map',
         'Map contained inside this structure'),
        ('linked_map', 'Linked Map', 'combo_map',
         'Target map for teleportation link'),
        ('linked_x', 'Link X', 'entry',
         'Target X coordinate for link'),
        ('linked_y', 'Link Y', 'entry',
         'Target Y coordinate for link'),
        ('linked_z', 'Link Z', 'entry',
         'Target Z coordinate for link'),
        ('link_auto', 'Link Auto', 'check',
         'Automatically teleport on step (no interaction)'),
    ]

    _BOUND_DIRS = ('n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw')

    def _build_ui(self):
        outer = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # ---- LEFT: Map list + metadata ----
        left = ttk.Frame(outer, width=220)
        outer.add(left, weight=0)

        # Map list
        ttk.Label(left, text='Maps',
                   font=('TkDefaultFont', 9, 'bold')).pack(anchor='w', padx=4)
        list_f = ttk.Frame(left)
        list_f.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
        self._map_listbox = tk.Listbox(list_f, exportselection=False, width=22)
        sb = ttk.Scrollbar(list_f, orient=tk.VERTICAL,
                            command=self._map_listbox.yview)
        self._map_listbox.configure(yscrollcommand=sb.set)
        self._map_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._map_listbox.bind('<<ListboxSelect>>', self._on_map_select)

        btn_f = ttk.Frame(left)
        btn_f.pack(fill=tk.X, padx=4, pady=2)
        btn_new = ttk.Button(btn_f, text='New', command=self._new_map)
        btn_new.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_new, 'Create a new map')
        btn_save = ttk.Button(btn_f, text='Save', command=self._save_map)
        btn_save.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_save, 'Save map metadata and all tile placements')
        btn_del = ttk.Button(btn_f, text='Delete', command=self._delete_map)
        btn_del.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_del, 'Delete the selected map and its tiles')

        # Metadata fields
        meta_f = ttk.LabelFrame(left, text='Map Properties', padding=4)
        meta_f.pack(fill=tk.X, padx=4, pady=(6, 2))

        r = 0
        ttk.Label(meta_f, text='Name').grid(row=r, column=0, sticky='w', padx=2, pady=2)
        self.v_name = tk.StringVar()
        e = ttk.Entry(meta_f, textvariable=self.v_name, width=16)
        e.grid(row=r, column=1, sticky='ew', padx=2, pady=2)
        add_tooltip(e, 'Unique map name (also used as tile set name)')
        r += 1

        ttk.Label(meta_f, text='Default Tile').grid(row=r, column=0, sticky='w', padx=2, pady=2)
        self.v_default = tk.StringVar()
        self._default_cb = ttk.Combobox(
            meta_f, textvariable=self.v_default,
            values=[''] + fetch_tile_template_keys(), state='readonly', width=14)
        self._default_cb.grid(row=r, column=1, sticky='ew', padx=2, pady=2)
        add_tooltip(self._default_cb, 'Tile template used to fill unset coordinates')
        r += 1

        ttk.Label(meta_f, text='Entrance').grid(row=r, column=0, sticky='w', padx=2, pady=2)
        ent_f = ttk.Frame(meta_f)
        ent_f.grid(row=r, column=1, sticky='w', padx=2, pady=2)
        self.v_ent_x = tk.StringVar(value='0')
        self.v_ent_y = tk.StringVar(value='0')
        self.v_ent_x.trace_add('write', lambda *_: self._update_entrance())
        self.v_ent_y.trace_add('write', lambda *_: self._update_entrance())
        ex = ttk.Entry(ent_f, textvariable=self.v_ent_x, width=4)
        ex.pack(side=tk.LEFT, padx=(0, 2))
        add_tooltip(ex, 'Entrance X coordinate')
        ey = ttk.Entry(ent_f, textvariable=self.v_ent_y, width=4)
        ey.pack(side=tk.LEFT)
        add_tooltip(ey, 'Entrance Y coordinate')
        r += 1

        # Dimension bounds
        for axis in ('x', 'y'):
            ttk.Label(meta_f, text=f'{axis.upper()} range').grid(
                row=r, column=0, sticky='w', padx=2, pady=2)
            range_f = ttk.Frame(meta_f)
            range_f.grid(row=r, column=1, sticky='w', padx=2, pady=2)
            vmin = tk.StringVar(value='0')
            vmax = tk.StringVar(value='31')
            setattr(self, f'v_{axis}_min', vmin)
            setattr(self, f'v_{axis}_max', vmax)
            e_min = ttk.Entry(range_f, textvariable=vmin, width=4)
            e_min.pack(side=tk.LEFT, padx=(0, 2))
            add_tooltip(e_min, f'{axis.upper()} minimum coordinate')
            ttk.Label(range_f, text='to').pack(side=tk.LEFT, padx=2)
            e_max = ttk.Entry(range_f, textvariable=vmax, width=4)
            e_max.pack(side=tk.LEFT)
            add_tooltip(e_max, f'{axis.upper()} maximum coordinate')
            r += 1

        # Z level
        ttk.Label(meta_f, text='Z level').grid(row=r, column=0, sticky='w', padx=2, pady=2)
        z_f = ttk.Frame(meta_f)
        z_f.grid(row=r, column=1, sticky='w', padx=2, pady=2)
        self.v_z_level = tk.StringVar(value='0')
        z_down = ttk.Button(z_f, text='\u25bc', width=2, command=self._z_down)
        z_down.pack(side=tk.LEFT, padx=(0, 2))
        add_tooltip(z_down, 'Go down one Z level')
        z_entry = ttk.Entry(z_f, textvariable=self.v_z_level, width=4)
        z_entry.pack(side=tk.LEFT, padx=2)
        add_tooltip(z_entry, 'Current Z level being edited')
        z_up = ttk.Button(z_f, text='\u25b2', width=2, command=self._z_up)
        z_up.pack(side=tk.LEFT, padx=2)
        add_tooltip(z_up, 'Go up one Z level')
        r += 1

        ttk.Label(meta_f, text='Z range').grid(row=r, column=0, sticky='w', padx=2, pady=2)
        zr_f = ttk.Frame(meta_f)
        zr_f.grid(row=r, column=1, sticky='w', padx=2, pady=2)
        self.v_z_min = tk.StringVar(value='0')
        self.v_z_max = tk.StringVar(value='0')
        e_zmin = ttk.Entry(zr_f, textvariable=self.v_z_min, width=4)
        e_zmin.pack(side=tk.LEFT, padx=(0, 2))
        add_tooltip(e_zmin, 'Z minimum coordinate')
        ttk.Label(zr_f, text='to').pack(side=tk.LEFT, padx=2)
        e_zmax = ttk.Entry(zr_f, textvariable=self.v_z_max, width=4)
        e_zmax.pack(side=tk.LEFT)
        add_tooltip(e_zmax, 'Z maximum coordinate')
        r += 1

        meta_f.columnconfigure(1, weight=1)

        # Coordinate display
        self._coord_var = tk.StringVar(value='')
        ttk.Label(left, textvariable=self._coord_var,
                   font=('Courier', 9)).pack(anchor='w', padx=6, pady=4)

        # ---- CENTER: Canvas (top) + Palette (bottom) ----
        center = ttk.Frame(outer)
        outer.add(center, weight=1)

        center_pane = ttk.PanedWindow(center, orient=tk.VERTICAL)
        center_pane.pack(fill=tk.BOTH, expand=True)

        # Top: toolbar + canvas
        canvas_frame = ttk.Frame(center_pane)
        center_pane.add(canvas_frame, weight=3)

        # Toolbar
        toolbar = ttk.Frame(canvas_frame)
        toolbar.pack(fill=tk.X, pady=(0, 2))

        self._zoom_var = tk.StringVar(value='1.0x')
        ttk.Label(toolbar, text='Zoom:').pack(side=tk.LEFT, padx=(4, 2))
        ttk.Label(toolbar, textvariable=self._zoom_var,
                   width=5).pack(side=tk.LEFT)
        zoom_in = ttk.Button(toolbar, text='+', width=2,
                              command=lambda: self._canvas.set_zoom(
                                  self._canvas.get_zoom() + 0.25))
        zoom_in.pack(side=tk.LEFT, padx=1)
        add_tooltip(zoom_in, 'Zoom in')
        zoom_out = ttk.Button(toolbar, text='-', width=2,
                               command=lambda: self._canvas.set_zoom(
                                   self._canvas.get_zoom() - 0.25))
        zoom_out.pack(side=tk.LEFT, padx=1)
        add_tooltip(zoom_out, 'Zoom out')

        self._grid_var = tk.BooleanVar(value=True)
        grid_cb = ttk.Checkbutton(toolbar, text='Grid',
                                   variable=self._grid_var,
                                   command=self._toggle_grid)
        grid_cb.pack(side=tk.LEFT, padx=8)
        add_tooltip(grid_cb, 'Toggle grid overlay')

        refresh_btn = ttk.Button(toolbar, text='\u21bb', width=3,
                                  command=self._refresh_canvas)
        refresh_btn.pack(side=tk.LEFT, padx=4)
        add_tooltip(refresh_btn, 'Refresh canvas rendering')

        self._dirty_label = ttk.Label(toolbar, text='', foreground='#c04040')
        self._dirty_label.pack(side=tk.RIGHT, padx=6)

        # Controls hint
        hint = ttk.Label(
            canvas_frame,
            text='Click: paint | Shift+click: range select | '
                 'Ctrl+click: toggle select | Right-click: context menu | '
                 'Scroll: pan | Shift+scroll: pan horiz | Ctrl+scroll: zoom',
            font=('TkDefaultFont', 8), foreground='#888888')
        hint.pack(fill=tk.X, padx=4, pady=(0, 2))

        # Canvas
        self._canvas = MapCanvas(canvas_frame,
                                  on_paint=self._on_paint,
                                  on_inspect=self._on_inspect,
                                  on_context_menu=self._on_context_menu,
                                  on_selection_change=self._on_selection_change)
        self._canvas.pack(fill=tk.BOTH, expand=True)

        # Bottom: tile palette
        palette_frame = ttk.Frame(center_pane)
        center_pane.add(palette_frame, weight=0)

        self._palette = TilePalette(palette_frame, on_select=self._on_palette_select)
        self._palette.pack(fill=tk.BOTH, expand=True)

        # ---- RIGHT: Tile Properties ----
        right = ttk.Frame(outer, width=240)
        outer.add(right, weight=0)
        self._build_properties_panel(right)

    # ------------------------------------------------------------------
    # Properties Panel
    # ------------------------------------------------------------------

    def _build_properties_panel(self, parent):
        """Build the right-side tile properties panel."""
        ttk.Label(parent, text='Tile Properties',
                   font=('TkDefaultFont', 9, 'bold')).pack(
            anchor='w', padx=4, pady=(4, 2))

        self._prop_selection_label = ttk.Label(
            parent, text='No selection', foreground='#888888',
            font=('TkDefaultFont', 8))
        self._prop_selection_label.pack(anchor='w', padx=4, pady=(0, 4))

        # Scrollable frame for properties
        prop_canvas = tk.Canvas(parent, highlightthickness=0)
        prop_sb = ttk.Scrollbar(parent, orient=tk.VERTICAL,
                                 command=prop_canvas.yview)
        self._prop_inner = ttk.Frame(prop_canvas)
        self._prop_inner.bind(
            '<Configure>',
            lambda e: prop_canvas.configure(
                scrollregion=prop_canvas.bbox('all')))
        prop_canvas.create_window((0, 0), window=self._prop_inner, anchor='nw')
        prop_canvas.configure(yscrollcommand=prop_sb.set)
        prop_sb.pack(side=tk.RIGHT, fill=tk.Y)
        prop_canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=4)

        # Build field widgets
        self._prop_widgets = {}  # field_key → {var, widget, label, type}
        tmpl_vals = [''] + fetch_tile_template_keys()
        map_vals = [''] + fetch_map_names()
        sprite_vals = [''] + fetch_sprite_names()
        anim_vals = [''] + fetch_animation_names()

        r = 0
        for field_key, label_text, wtype, tip in self._PROP_FIELDS:
            lbl = ttk.Label(self._prop_inner, text=label_text)
            lbl.grid(row=r, column=0, sticky='w', padx=2, pady=2)
            var = tk.StringVar()
            if wtype == 'check':
                var = tk.StringVar(value='')
                w = ttk.Combobox(self._prop_inner, textvariable=var,
                                  values=['', '0', '1'], width=4, state='readonly')
            elif wtype == 'combo_tmpl':
                w = ttk.Combobox(self._prop_inner, textvariable=var,
                                  values=tmpl_vals, width=14)
            elif wtype == 'combo_map':
                w = ttk.Combobox(self._prop_inner, textvariable=var,
                                  values=map_vals, width=14)
            elif wtype == 'combo_sprite':
                w = ttk.Combobox(self._prop_inner, textvariable=var,
                                  values=sprite_vals, width=14)
            elif wtype == 'combo_anim':
                w = ttk.Combobox(self._prop_inner, textvariable=var,
                                  values=anim_vals, width=14)
            else:
                w = ttk.Entry(self._prop_inner, textvariable=var, width=16)
            w.grid(row=r, column=1, sticky='ew', padx=2, pady=2)
            add_tooltip(w, tip)
            self._prop_widgets[field_key] = {
                'var': var, 'widget': w, 'label': lbl, 'type': wtype}
            r += 1

        # Bounds section
        ttk.Separator(self._prop_inner, orient=tk.HORIZONTAL).grid(
            row=r, column=0, columnspan=2, sticky='ew', padx=2, pady=4)
        r += 1
        ttk.Label(self._prop_inner, text='Bounds',
                   font=('TkDefaultFont', 8, 'bold')).grid(
            row=r, column=0, columnspan=2, sticky='w', padx=2, pady=(0, 2))
        r += 1

        self._bound_prop_vars = {}
        for d in self._BOUND_DIRS:
            lbl = ttk.Label(self._prop_inner, text=d.upper())
            lbl.grid(row=r, column=0, sticky='w', padx=2, pady=1)
            var = tk.StringVar(value='')
            w = ttk.Combobox(self._prop_inner, textvariable=var,
                              values=['', '0', '1'], width=4, state='readonly')
            w.grid(row=r, column=1, sticky='w', padx=2, pady=1)
            add_tooltip(w, f'{d.upper()} edge traversable (1) or blocked (0)')
            self._bound_prop_vars[d] = {'var': var, 'widget': w}
            r += 1

        self._prop_inner.columnconfigure(1, weight=1)

        # Apply button
        btn_f = ttk.Frame(parent)
        btn_f.pack(fill=tk.X, padx=4, pady=6)
        apply_btn = ttk.Button(btn_f, text='Apply to Selection',
                                command=self._apply_properties)
        apply_btn.pack(fill=tk.X)
        add_tooltip(apply_btn,
                    'Apply all non-empty property values to selected tiles')

    def _on_selection_change(self, selected_tiles: set):
        """Called when canvas selection changes. Populate the properties panel."""
        n = len(selected_tiles)
        if n == 0:
            self._prop_selection_label.configure(text='No selection')
            self._clear_prop_fields()
            return
        self._prop_selection_label.configure(
            text=f'{n} tile{"s" if n != 1 else ""} selected')
        self._populate_prop_fields(selected_tiles)

    def _clear_prop_fields(self):
        """Clear all property fields."""
        for info in self._prop_widgets.values():
            info['var'].set('')
            info['widget'].configure(foreground='')
        for info in self._bound_prop_vars.values():
            info['var'].set('')

    def _populate_prop_fields(self, selected_tiles: set):
        """Read values from selected tiles. Uniform → show value (black),
        mixed → show empty (grey), all-empty → show empty (normal)."""
        # Gather tile dicts
        tile_dicts = []
        for (x, y) in selected_tiles:
            td = self._tiles.get((x, y))
            if td:
                tile_dicts.append(td)

        if not tile_dicts:
            self._clear_prop_fields()
            return

        # Regular fields
        for field_key, _label, wtype, _tip in self._PROP_FIELDS:
            values = set()
            for td in tile_dicts:
                v = td.get(field_key)
                values.add(v)

            info = self._prop_widgets[field_key]
            if len(values) == 1:
                val = values.pop()
                if val is None:
                    info['var'].set('')
                    info['widget'].configure(foreground='')
                else:
                    info['var'].set(str(val))
                    info['widget'].configure(foreground='black')
            else:
                # Mixed
                info['var'].set('')
                info['widget'].configure(foreground='grey')

        # Bounds fields
        for d in self._BOUND_DIRS:
            key = f'bounds_{d}'
            values = set()
            for td in tile_dicts:
                v = td.get(key)
                values.add(v)

            info = self._bound_prop_vars[d]
            if len(values) == 1:
                val = values.pop()
                if val is None:
                    info['var'].set('')
                else:
                    info['var'].set(str(int(val)))
            else:
                info['var'].set('')
                info['widget'].configure(foreground='grey')

    def _apply_properties(self):
        """Apply property values from the sidebar to all selected tiles."""
        selected = self._canvas.get_selected()
        if not selected:
            messagebox.showinfo('Apply', 'Select tiles first.')
            return

        try:
            z = int(self.v_z_level.get())
        except ValueError:
            z = 0

        # Collect values to apply (skip empty = no change)
        changes = {}
        for field_key, _label, wtype, _tip in self._PROP_FIELDS:
            val_str = self._prop_widgets[field_key]['var'].get()
            if val_str == '':
                continue
            if wtype == 'check':
                changes[field_key] = int(val_str)
            elif field_key in ('linked_x', 'linked_y', 'linked_z'):
                try:
                    changes[field_key] = int(val_str)
                except ValueError:
                    continue
            elif field_key == 'tile_scale':
                try:
                    changes[field_key] = float(val_str)
                except ValueError:
                    continue
            elif field_key == 'link_auto':
                changes[field_key] = int(val_str)
            else:
                changes[field_key] = val_str if val_str else None

        # Bounds
        for d in self._BOUND_DIRS:
            val_str = self._bound_prop_vars[d]['var'].get()
            if val_str == '':
                continue
            changes[f'bounds_{d}'] = int(val_str)

        if not changes:
            return

        for (x, y) in selected:
            td = self._tiles.get((x, y))
            if td is None:
                td = {'x': x, 'y': y, 'z': z}
                self._tiles[(x, y)] = td
                self._all_tiles[(x, y)] = td
            td.update(changes)
            self._canvas.set_tile(x, y, td)

        self._mark_dirty()
        self._canvas._render_full()
        # Refresh sidebar to show applied values
        self._populate_prop_fields(selected)

    def _refresh_prop_dropdowns(self):
        """Refresh combo values in the properties panel."""
        tmpl_vals = [''] + fetch_tile_template_keys()
        map_vals = [''] + fetch_map_names()
        sprite_vals = [''] + fetch_sprite_names()
        anim_vals = [''] + fetch_animation_names()
        for field_key, info in self._prop_widgets.items():
            fdef = next((f for f in self._PROP_FIELDS if f[0] == field_key), None)
            if not fdef:
                continue
            wtype = fdef[2]
            if wtype == 'combo_tmpl':
                info['widget']['values'] = tmpl_vals
            elif wtype == 'combo_map':
                info['widget']['values'] = map_vals
            elif wtype == 'combo_sprite':
                info['widget']['values'] = sprite_vals
            elif wtype == 'combo_anim':
                info['widget']['values'] = anim_vals

    # ------------------------------------------------------------------
    # Map list
    # ------------------------------------------------------------------

    def refresh_map_list(self):
        con = get_con()
        try:
            rows = con.execute('SELECT name FROM maps ORDER BY name').fetchall()
            self._map_names = [r['name'] for r in rows]
        finally:
            con.close()
        self._map_listbox.delete(0, tk.END)
        for n in self._map_names:
            self._map_listbox.insert(tk.END, n)

    def refresh_dropdowns(self):
        """Refresh all dropdowns (called when switching to this tab)."""
        self._default_cb['values'] = [''] + fetch_tile_template_keys()
        self._palette.refresh()
        self._refresh_prop_dropdowns()

    def _on_map_select(self, event=None):
        sel = self._map_listbox.curselection()
        if not sel:
            return
        name = self._map_names[sel[0]]
        if self._dirty and self._current_map_name:
            if messagebox.askyesno('Unsaved Changes',
                                    f'Save changes to "{self._current_map_name}" first?'):
                self._save_map()
        self._load_map(name)

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------

    def _load_map(self, name: str):
        con = get_con()
        try:
            mrow = con.execute('SELECT * FROM maps WHERE name=?', (name,)).fetchone()
            if mrow is None:
                return

            self.v_name.set(mrow['name'])
            self.v_default.set(mrow['default_tile_template'] or '')
            self.v_ent_x.set(str(mrow['entrance_x']))
            self.v_ent_y.set(str(mrow['entrance_y']))
            self.v_x_min.set(str(mrow['x_min']))
            self.v_x_max.set(str(mrow['x_max']))
            self.v_y_min.set(str(mrow['y_min']))
            self.v_y_max.set(str(mrow['y_max']))
            self.v_z_min.set(str(mrow['z_min']))
            self.v_z_max.set(str(mrow['z_max']))

            # Load tile entries
            tile_set = mrow['tile_set'] or mrow['name']
            rows = con.execute(
                'SELECT * FROM tile_sets WHERE tile_set=? ORDER BY x,y,z',
                (tile_set,)).fetchall()
        finally:
            con.close()

        self._all_tiles = {}
        for r in rows:
            self._all_tiles[(r['x'], r['y'])] = dict(r)

        # Filter to current Z level
        try:
            z = int(self.v_z_level.get())
        except ValueError:
            z = 0
        self._tiles = {k: v for k, v in self._all_tiles.items()
                       if v.get('z', 0) == z}

        self._current_map_name = name
        self._dirty = False
        self._dirty_label.configure(text='')

        # Resolve default tile sprite
        default_key = mrow['default_tile_template']
        default_sprite = None
        if default_key:
            con2 = get_con()
            try:
                tr = con2.execute(
                    'SELECT sprite_name FROM tile_templates WHERE key=?',
                    (default_key,)).fetchone()
                if tr:
                    default_sprite = tr['sprite_name']
            finally:
                con2.close()

        self._canvas.set_map_data(
            self._tiles,
            (int(mrow['x_min']), int(mrow['x_max'])),
            (int(mrow['y_min']), int(mrow['y_max'])),
            default_sprite,
            (int(mrow['entrance_x']), int(mrow['entrance_y'])),
        )

    def _save_map(self):
        name = self.v_name.get().strip()
        if not name:
            messagebox.showerror('Save', 'Map name is required.')
            return

        tile_set = name  # tile_set name = map name
        try:
            ent_x = int(self.v_ent_x.get())
            ent_y = int(self.v_ent_y.get())
            x_min = int(self.v_x_min.get())
            x_max = int(self.v_x_max.get())
            y_min = int(self.v_y_min.get())
            y_max = int(self.v_y_max.get())
            z_min = int(self.v_z_min.get())
            z_max = int(self.v_z_max.get())
        except ValueError:
            messagebox.showerror('Save', 'Coordinates must be integers.')
            return

        con = get_con()
        try:
            # Upsert map metadata
            con.execute(
                '''INSERT INTO maps
                   (name, tile_set, default_tile_template, entrance_x, entrance_y,
                    x_min, x_max, y_min, y_max,
                    z_min, z_max)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(name) DO UPDATE SET
                   tile_set=excluded.tile_set,
                   default_tile_template=excluded.default_tile_template,
                   entrance_x=excluded.entrance_x,
                   entrance_y=excluded.entrance_y,
                   x_min=excluded.x_min, x_max=excluded.x_max,
                   y_min=excluded.y_min, y_max=excluded.y_max,
                   z_min=excluded.z_min, z_max=excluded.z_max''',
                (name, tile_set, self.v_default.get().strip() or None,
                 ent_x, ent_y, x_min, x_max, y_min, y_max, z_min, z_max))

            # Delete old tile entries and rewrite
            con.execute('DELETE FROM tile_sets WHERE tile_set=?', (tile_set,))
            for (x, y), td in self._all_tiles.items():
                con.execute(
                    '''INSERT INTO tile_sets
                       (tile_set, x, y, z, tile_template, walkable, covered,
                        sprite_name, tile_scale, animation_name,
                        bounds_n, bounds_s, bounds_e, bounds_w,
                        bounds_ne, bounds_nw, bounds_se, bounds_sw,
                        nested_map, linked_map, linked_x, linked_y, linked_z,
                        link_auto, stat_mods, search_text)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (tile_set, x, y, td.get('z', 0),
                     td.get('tile_template'), td.get('walkable'), td.get('covered'),
                     td.get('sprite_name'), td.get('tile_scale'),
                     td.get('animation_name'),
                     td.get('bounds_n'), td.get('bounds_s'),
                     td.get('bounds_e'), td.get('bounds_w'),
                     td.get('bounds_ne'), td.get('bounds_nw'),
                     td.get('bounds_se'), td.get('bounds_sw'),
                     td.get('nested_map'), td.get('linked_map'),
                     td.get('linked_x'), td.get('linked_y'),
                     td.get('linked_z'),
                     td.get('link_auto', 0), td.get('stat_mods'),
                     td.get('search_text')))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()

        self._current_map_name = name
        self._dirty = False
        self._dirty_label.configure(text='')
        self.refresh_map_list()
        # Notify parent to refresh other tabs
        self.event_generate('<<MapSaved>>')
        # Re-select in list
        if name in self._map_names:
            idx = self._map_names.index(name)
            self._map_listbox.selection_set(idx)
            self._map_listbox.see(idx)

    def _new_map(self):
        if self._dirty and self._current_map_name:
            if messagebox.askyesno('Unsaved Changes',
                                    f'Save changes to "{self._current_map_name}" first?'):
                self._save_map()
        self._map_listbox.selection_clear(0, tk.END)
        self._current_map_name = None
        self._tiles = {}
        self._all_tiles = {}
        self._dirty = False
        self._dirty_label.configure(text='')
        self.v_name.set('')
        self.v_default.set('')
        self.v_ent_x.set('0')
        self.v_ent_y.set('0')
        self.v_x_min.set('0')
        self.v_x_max.set('31')
        self.v_y_min.set('0')
        self.v_y_max.set('31')
        self.v_z_min.set('0')
        self.v_z_max.set('0')
        self._canvas.set_map_data({}, (0, 31), (0, 31), None, (0, 0))

    def _delete_map(self):
        name = self._current_map_name
        if not name:
            messagebox.showwarning('Delete', 'Select a map first.')
            return
        if not messagebox.askyesno('Delete',
                                    f'Delete map "{name}" and all its tile entries?'):
            return
        con = get_con()
        try:
            con.execute('DELETE FROM tile_sets WHERE tile_set=?', (name,))
            con.execute('DELETE FROM maps WHERE name=?', (name,))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self._current_map_name = None
        self._tiles = {}
        self._dirty = False
        self.refresh_map_list()
        self._new_map()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def _on_paint(self, x: int, y: int):
        try:
            z = int(self.v_z_level.get())
        except ValueError:
            z = 0
        template_key = self._palette.get_selected()
        if template_key is None:
            # Eraser — remove tile
            if (x, y) in self._tiles:
                del self._tiles[(x, y)]
                self._all_tiles.pop((x, y), None)
                self._canvas.set_tile(x, y, None)
                self._mark_dirty()
        else:
            # Paint — add/update tile
            existing = self._tiles.get((x, y), {})
            td = dict(existing)
            td['tile_template'] = template_key
            td['x'] = x
            td['y'] = y
            td['z'] = z
            self._tiles[(x, y)] = td
            self._all_tiles[(x, y)] = td
            self._canvas.set_tile(x, y, td)
            self._mark_dirty()

        # Update coordinate display
        self._coord_var.set(f'({x}, {y})')

    def _on_inspect(self, x: int, y: int):
        """Right-click: show tile info (Phase 2 will have a full inspector)."""
        td = self._tiles.get((x, y))
        self._coord_var.set(f'({x}, {y})')
        if td:
            template = td.get('tile_template', '?')
            info = f'({x}, {y}) template={template}'
            if td.get('linked_map'):
                info += f' link={td["linked_map"]}'
            if td.get('nested_map'):
                info += f' nested={td["nested_map"]}'
            self._coord_var.set(info)
        else:
            self._coord_var.set(f'({x}, {y}) [default fill]')

    def _on_palette_select(self, key):
        """Palette selection changed."""
        pass  # Brush is read from palette on each click

    def _on_context_menu(self, event, selected_tiles: set):
        """Show right-click context menu for selected tiles."""
        menu = tk.Menu(self, tearoff=0)
        n = len(selected_tiles)
        menu.add_command(label=f'{n} tile{"s" if n != 1 else ""} selected',
                         state='disabled')
        menu.add_separator()

        # Set tile template
        menu.add_command(label='Set Template...',
                         command=lambda: self._bulk_set_template(selected_tiles))
        menu.add_separator()

        # Walkability
        menu.add_command(label='Set Walkable',
                         command=lambda: self._bulk_set_field(selected_tiles, 'walkable', 1))
        menu.add_command(label='Set Blocked',
                         command=lambda: self._bulk_set_field(selected_tiles, 'walkable', 0))
        menu.add_separator()

        # Bounds
        bounds_menu = tk.Menu(menu, tearoff=0)
        for d in ('n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'):
            sub = tk.Menu(bounds_menu, tearoff=0)
            sub.add_command(label=f'{d.upper()} → Traversable',
                            command=lambda d=d: self._bulk_set_field(
                                selected_tiles, f'bounds_{d}', 1))
            sub.add_command(label=f'{d.upper()} → Blocked',
                            command=lambda d=d: self._bulk_set_field(
                                selected_tiles, f'bounds_{d}', 0))
            bounds_menu.add_cascade(label=d.upper(), menu=sub)
        bounds_menu.add_separator()
        bounds_menu.add_command(label='All Edges → Blocked',
                                command=lambda: self._bulk_set_all_bounds(
                                    selected_tiles, 0))
        bounds_menu.add_command(label='All Edges → Traversable',
                                command=lambda: self._bulk_set_all_bounds(
                                    selected_tiles, 1))
        menu.add_cascade(label='Bounds', menu=bounds_menu)
        menu.add_separator()

        # Link
        menu.add_command(label='Set Link...',
                         command=lambda: self._bulk_set_link(selected_tiles))
        menu.add_command(label='Clear Link',
                         command=lambda: self._bulk_clear_fields(
                             selected_tiles,
                             ['linked_map', 'linked_x', 'linked_y', 'linked_z', 'link_auto']))
        menu.add_separator()

        # Erase
        menu.add_command(label='Erase Tiles',
                         command=lambda: self._bulk_erase(selected_tiles))

        menu.post(event.x_root, event.y_root)

    def _bulk_set_template(self, tiles: set):
        """Set tile template on all selected tiles to current palette selection."""
        template_key = self._palette.get_selected()
        if template_key is None:
            from tkinter import messagebox
            messagebox.showinfo('Set Template', 'Select a template from the palette first.')
            return
        for (x, y) in tiles:
            td = self._tiles.get((x, y), {})
            td = dict(td)
            td['tile_template'] = template_key
            td['x'] = x
            td['y'] = y
            try:
                td['z'] = int(self.v_z_level.get())
            except ValueError:
                td['z'] = 0
            self._tiles[(x, y)] = td
            self._all_tiles[(x, y)] = td
            self._canvas.set_tile(x, y, td)
        self._mark_dirty()

    def _bulk_set_field(self, tiles: set, field: str, value):
        """Set a single field on all selected tiles."""
        for (x, y) in tiles:
            td = self._tiles.get((x, y))
            if td is None:
                continue
            td[field] = value
            self._canvas.set_tile(x, y, td)
        self._mark_dirty()
        self._canvas._render_full()

    def _bulk_set_all_bounds(self, tiles: set, value: int):
        """Set all 8 bound directions on selected tiles."""
        for d in ('n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'):
            for (x, y) in tiles:
                td = self._tiles.get((x, y))
                if td:
                    td[f'bounds_{d}'] = value
        self._mark_dirty()
        self._canvas._render_full()

    def _bulk_set_link(self, tiles: set):
        """Popup to set linked_map on selected tiles."""
        from tkinter import simpledialog
        map_name = simpledialog.askstring('Set Link',
                                           'Enter target map name:',
                                           parent=self)
        if not map_name:
            return
        for (x, y) in tiles:
            td = self._tiles.get((x, y))
            if td:
                td['linked_map'] = map_name
        self._mark_dirty()
        self._canvas._render_full()

    def _bulk_clear_fields(self, tiles: set, fields: list):
        """Clear specific fields on selected tiles."""
        for (x, y) in tiles:
            td = self._tiles.get((x, y))
            if td:
                for f in fields:
                    td.pop(f, None)
        self._mark_dirty()
        self._canvas._render_full()

    def _bulk_erase(self, tiles: set):
        """Erase all selected tiles (revert to default)."""
        for (x, y) in tiles:
            self._tiles.pop((x, y), None)
            self._all_tiles.pop((x, y), None)
            self._canvas.set_tile(x, y, None)
        self._mark_dirty()
        self._canvas.clear_selection()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            self._dirty_label.configure(text='* unsaved')

    def _toggle_grid(self):
        self._canvas.set_grid(self._grid_var.get())

    def _update_entrance(self):
        try:
            ex = int(self.v_ent_x.get())
            ey = int(self.v_ent_y.get())
            self._canvas.set_entrance(ex, ey)
        except ValueError:
            pass

    def _z_up(self):
        try:
            z = int(self.v_z_level.get())
        except ValueError:
            z = 0
        self.v_z_level.set(str(z + 1))
        self._reload_z_layer()

    def _z_down(self):
        try:
            z = int(self.v_z_level.get())
        except ValueError:
            z = 0
        self.v_z_level.set(str(z - 1))
        self._reload_z_layer()

    def _reload_z_layer(self):
        """Reload tiles filtered to the current Z level."""
        if not self._current_map_name:
            return
        try:
            z = int(self.v_z_level.get())
        except ValueError:
            z = 0
        # Filter in-memory tiles to current Z
        visible = {}
        for (x, y), td in self._all_tiles.items():
            if td.get('z', 0) == z:
                visible[(x, y)] = td
        self._tiles = visible
        self._refresh_canvas()

    def _refresh_canvas(self):
        """Force a full canvas re-render from current in-memory state."""
        default_sprite = self._resolve_default_sprite()
        try:
            x_min = int(self.v_x_min.get())
            x_max = int(self.v_x_max.get())
            y_min = int(self.v_y_min.get())
            y_max = int(self.v_y_max.get())
            ent_x = int(self.v_ent_x.get())
            ent_y = int(self.v_ent_y.get())
        except ValueError:
            x_min, x_max, y_min, y_max = 0, 31, 0, 31
            ent_x, ent_y = 0, 0
        self._canvas.set_map_data(
            self._tiles,
            (x_min, x_max), (y_min, y_max),
            default_sprite, (ent_x, ent_y))

    def _resolve_default_sprite(self) -> str | None:
        default_key = self.v_default.get().strip()
        if not default_key:
            return None
        con = get_con()
        try:
            r = con.execute(
                'SELECT sprite_name FROM tile_templates WHERE key=?',
                (default_key,)).fetchone()
            return r['sprite_name'] if r else None
        finally:
            con.close()

    def _int_field(self, var, default=0):
        try:
            return int(var.get())
        except ValueError:
            return default
