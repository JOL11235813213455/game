"""
Composites editor — two-column layout with numbered workflow.

Left:  composite picker → layer list → layer detail (sprite dropdown + preview)
Right: composite preview → connections → variants → animations

Sprites are managed in the Sprites tab; here you just pick them from dropdowns.
An optional sprite_set filter narrows the dropdown to a specific group.
"""
import json
import math
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

from editor.db import (
    get_con, fetch_sprite_names, fetch_sprite_names_by_set,
    fetch_sprite_sets, fetch_composite_names, fetch_sprite,
)
from editor.constants import PREVIEW_SIZE
from editor.sprite_preview import SpritePreview
from editor.tooltip import add_tooltip


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lerp(a, b, t):
    return a + (b - a) * t


def _interp_keyframes(keyframes, time_ms):
    if not keyframes:
        return 0, 0, 0.0, None
    if len(keyframes) == 1:
        k = keyframes[0]
        return k['offset_x'], k['offset_y'], k['rotation_deg'], k.get('variant_name')
    prev = keyframes[0]
    for kf in keyframes:
        if kf['time_ms'] > time_ms:
            nxt = kf
            break
        prev = kf
    else:
        return prev['offset_x'], prev['offset_y'], prev['rotation_deg'], prev.get('variant_name')
    if prev['time_ms'] == nxt['time_ms']:
        return prev['offset_x'], prev['offset_y'], prev['rotation_deg'], prev.get('variant_name')
    t = (time_ms - prev['time_ms']) / (nxt['time_ms'] - prev['time_ms'])
    return (_lerp(prev['offset_x'], nxt['offset_x'], t),
            _lerp(prev['offset_y'], nxt['offset_y'], t),
            _lerp(prev['rotation_deg'], nxt['rotation_deg'], t),
            prev.get('variant_name') or nxt.get('variant_name'))


# ---------------------------------------------------------------------------
# Composite Preview Canvas
# ---------------------------------------------------------------------------

class CompositePreview(tk.Canvas):
    CHECKER_A = '#d0d0d0'
    CHECKER_B = '#b8b8b8'

    def __init__(self, parent, size=256, **kwargs):
        super().__init__(parent, width=size, height=size,
                         bg='#c0c0c0', highlightthickness=1,
                         highlightbackground='#666', **kwargs)
        self._size = size

    def render(self, layers, connections, root_layer,
               variant_overrides=None, anim_offsets=None):
        self.delete('all')
        if not layers:
            self._checkerboard()
            return
        variant_overrides = variant_overrides or {}
        anim_offsets = anim_offsets or {}

        positions = {}

        def resolve(name, depth=0):
            if name in positions or depth > 20:
                return
            if name == root_layer:
                positions[name] = (0, 0)
            else:
                conn = connections.get(name)
                if not conn:
                    positions[name] = (0, 0)
                    return
                resolve(conn['parent_layer'], depth + 1)
                pp = positions.get(conn['parent_layer'], (0, 0))
                sx, sy = conn['parent_socket']
                ax, ay = conn['child_anchor']
                positions[name] = (pp[0] + sx - ax, pp[1] + sy - ay)

        for name in layers:
            resolve(name)

        for name, (ox, oy, _rot) in anim_offsets.items():
            if name in positions:
                px, py = positions[name]
                positions[name] = (px + ox, py + oy)

        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')
        for name, (px, py) in positions.items():
            data = variant_overrides.get(name) or layers[name].get('sprite_data')
            if not data:
                continue
            w = data.get('width', 0)
            h = len(data.get('pixels', []))
            min_x, min_y = min(min_x, px), min(min_y, py)
            max_x, max_y = max(max_x, px + w), max(max_y, py + h)

        if min_x == float('inf'):
            self._checkerboard()
            return
        tw, th = max_x - min_x, max_y - min_y
        if tw <= 0 or th <= 0:
            self._checkerboard()
            return

        pad = 8
        avail = self._size - pad * 2
        scale = min(avail / tw, avail / th, avail / 4)
        scale = max(1, scale)
        self._checkerboard()

        for name, info in sorted(layers.items(),
                                  key=lambda x: x[1].get('z_layer', 0)):
            data = variant_overrides.get(name) or info.get('sprite_data')
            if not data:
                continue
            px, py = positions.get(name, (0, 0))
            palette = data['palette']
            for ri, row_str in enumerate(data.get('pixels', [])):
                for ci, ch in enumerate(row_str):
                    if ch == '.' or ch not in palette:
                        continue
                    sx = pad + (px - min_x + ci) * scale
                    sy = pad + (py - min_y + ri) * scale
                    self.create_rectangle(sx, sy, sx + scale, sy + scale,
                                          fill=palette[ch], outline='')

        for child, conn in connections.items():
            pp = positions.get(conn['parent_layer'], (0, 0))
            sx = pad + (pp[0] - min_x + conn['parent_socket'][0]) * scale
            sy = pad + (pp[1] - min_y + conn['parent_socket'][1]) * scale
            r = max(2, scale * 0.4)
            self.create_oval(sx - r, sy - r, sx + r, sy + r,
                             fill='#44ff44', outline='white', width=1)

    def _checkerboard(self):
        cs = max(1, self._size // 16)
        for r in range(16):
            for c in range(16):
                x0, y0 = c * cs, r * cs
                color = self.CHECKER_A if (r + c) % 2 == 0 else self.CHECKER_B
                self.create_rectangle(x0, y0, x0 + cs, y0 + cs,
                                      fill=color, outline='')


# ---------------------------------------------------------------------------
# Main Tab
# ---------------------------------------------------------------------------

class CompositesTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._layers: list[dict] = []
        self._connections: dict = {}
        self._variants: dict = {}
        self._root_layer: str = 'root'
        self._animations: list[dict] = []
        self._selected_layer_idx: int | None = None

        self._build_ui()
        self.refresh_list()

    # ==================================================================
    # UI
    # ==================================================================

    def _build_ui(self):
        outer = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # ---- LEFT COLUMN ----
        left_scroll = self._make_scrollable(outer)
        outer.add(left_scroll['outer'], weight=1)
        left = left_scroll['inner']

        # -- 1. Composite --
        sec = self._section(left, '1. Composite')
        row = ttk.Frame(sec)
        row.pack(fill=tk.X)
        self.comp_listbox = tk.Listbox(row, exportselection=False,
                                        width=24, height=5)
        sb = ttk.Scrollbar(row, orient=tk.VERTICAL,
                           command=self.comp_listbox.yview)
        self.comp_listbox.configure(yscrollcommand=sb.set)
        self.comp_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.comp_listbox.bind('<<ListboxSelect>>', self._on_comp_select)

        btns = ttk.Frame(sec)
        btns.pack(fill=tk.X, pady=2)
        ttk.Button(btns, text='New', command=self._new_comp).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(btns, text='Save All', command=self._save_comp).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(btns, text='Delete', command=self._delete_comp).pack(
            side=tk.LEFT, padx=2)

        nr = ttk.Frame(sec)
        nr.pack(fill=tk.X, pady=2)
        ttk.Label(nr, text='Name:').pack(side=tk.LEFT)
        self.v_comp_name = tk.StringVar()
        ne = ttk.Entry(nr, textvariable=self.v_comp_name, width=20)
        ne.pack(side=tk.LEFT, padx=4)
        add_tooltip(ne, 'Unique name for this composite sprite')

        # -- Sprite set filter (shared by all sprite dropdowns) --
        filt = ttk.Frame(sec)
        filt.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(filt, text='Sprite filter:').pack(side=tk.LEFT)
        self.v_sprite_filter = tk.StringVar()
        self._filter_cb = ttk.Combobox(
            filt, textvariable=self.v_sprite_filter,
            values=['(all)'] + fetch_sprite_sets(), width=16)
        self._filter_cb.set('(all)')
        self._filter_cb.pack(side=tk.LEFT, padx=4)
        self._filter_cb.bind('<<ComboboxSelected>>',
                              lambda e: self._refresh_sprite_dropdowns())
        add_tooltip(self._filter_cb,
                    'Filter sprite dropdowns by sprite_set tag — '
                    'or (all) to show everything')

        # -- 2. Layers --
        sec = self._section(left, '2. Layers')
        self.layer_listbox = tk.Listbox(sec, exportselection=False,
                                         width=36, height=6)
        self.layer_listbox.pack(fill=tk.X)
        self.layer_listbox.bind('<<ListboxSelect>>', self._on_layer_select)

        lbtns = ttk.Frame(sec)
        lbtns.pack(fill=tk.X, pady=2)
        b = ttk.Button(lbtns, text='+ Add Layer', command=self._add_layer)
        b.pack(side=tk.LEFT, padx=2)
        add_tooltip(b, 'Add a new layer')
        b = ttk.Button(lbtns, text='- Remove', command=self._remove_layer)
        b.pack(side=tk.LEFT, padx=2)
        b = ttk.Button(lbtns, text='Set as Root', command=self._set_root)
        b.pack(side=tk.LEFT, padx=2)
        add_tooltip(b, 'Root layer is the base — shown with * prefix')

        # Layer detail
        det = ttk.LabelFrame(sec, text='Selected Layer', padding=4)
        det.pack(fill=tk.X, pady=4)

        r1 = ttk.Frame(det)
        r1.pack(fill=tk.X, pady=1)
        ttk.Label(r1, text='Name:').pack(side=tk.LEFT)
        self.v_layer_name = tk.StringVar()
        ttk.Entry(r1, textvariable=self.v_layer_name, width=12).pack(
            side=tk.LEFT, padx=4)
        ttk.Label(r1, text='Z:').pack(side=tk.LEFT, padx=(8, 0))
        self.v_z_layer = tk.StringVar(value='0')
        ttk.Spinbox(r1, from_=-99, to=99, textvariable=self.v_z_layer,
                     width=4).pack(side=tk.LEFT, padx=2)

        r2 = ttk.Frame(det)
        r2.pack(fill=tk.X, pady=1)
        ttk.Label(r2, text='Sprite:').pack(side=tk.LEFT)
        self.v_layer_sprite = tk.StringVar()
        self._layer_sprite_cb = ttk.Combobox(
            r2, textvariable=self.v_layer_sprite,
            values=[''] + fetch_sprite_names(), state='readonly', width=20)
        self._layer_sprite_cb.pack(side=tk.LEFT, padx=4)
        self._layer_sprite_cb.bind('<<ComboboxSelected>>',
                                    self._on_layer_sprite_change)
        add_tooltip(self._layer_sprite_cb,
                    'Default sprite for this layer (filtered by sprite set above)')

        self._layer_preview = SpritePreview(det, size=PREVIEW_SIZE)
        self._layer_preview.pack(anchor='w', pady=4)

        b = ttk.Button(det, text='Apply Changes',
                        command=self._apply_layer_detail)
        b.pack(anchor='w', pady=2)
        add_tooltip(b, 'Apply name / z / sprite changes')

        # ---- RIGHT COLUMN ----
        right_scroll = self._make_scrollable(outer)
        outer.add(right_scroll['outer'], weight=0)
        right = right_scroll['inner']
        right.configure(width=360)

        # -- Composite Preview --
        sec = self._section(right, 'Composite Preview')
        self._preview = CompositePreview(sec, size=280)
        self._preview.pack(anchor='w', pady=4)

        # -- 3. Connections --
        sec = self._section(right, '3. Connections')
        self._conn_display = ttk.Frame(sec)
        self._conn_display.pack(fill=tk.X)

        conn_form = ttk.LabelFrame(sec, text='Add / Update', padding=4)
        conn_form.pack(fill=tk.X, pady=4)

        cr = ttk.Frame(conn_form)
        cr.pack(fill=tk.X, pady=1)
        ttk.Label(cr, text='Child:').pack(side=tk.LEFT)
        self.v_conn_child = tk.StringVar()
        self._conn_child_cb = ttk.Combobox(
            cr, textvariable=self.v_conn_child, values=[], width=10)
        self._conn_child_cb.pack(side=tk.LEFT, padx=2)
        ttk.Label(cr, text='anchor x,y:').pack(side=tk.LEFT, padx=(6, 0))
        self.v_conn_cax = tk.StringVar(value='0')
        self.v_conn_cay = tk.StringVar(value='0')
        ttk.Entry(cr, textvariable=self.v_conn_cax, width=3).pack(
            side=tk.LEFT, padx=1)
        ttk.Entry(cr, textvariable=self.v_conn_cay, width=3).pack(
            side=tk.LEFT, padx=1)

        pr = ttk.Frame(conn_form)
        pr.pack(fill=tk.X, pady=1)
        ttk.Label(pr, text='Parent:').pack(side=tk.LEFT)
        self.v_conn_parent = tk.StringVar()
        self._conn_parent_cb = ttk.Combobox(
            pr, textvariable=self.v_conn_parent, values=[], width=10)
        self._conn_parent_cb.pack(side=tk.LEFT, padx=2)
        ttk.Label(pr, text='socket x,y:').pack(side=tk.LEFT, padx=(6, 0))
        self.v_conn_psx = tk.StringVar(value='0')
        self.v_conn_psy = tk.StringVar(value='0')
        ttk.Entry(pr, textvariable=self.v_conn_psx, width=3).pack(
            side=tk.LEFT, padx=1)
        ttk.Entry(pr, textvariable=self.v_conn_psy, width=3).pack(
            side=tk.LEFT, padx=1)

        b = ttk.Button(conn_form, text='Set Connection',
                        command=self._add_connection)
        b.pack(anchor='w', pady=2)
        add_tooltip(b, 'Connect child anchor to parent socket')

        # -- 4. Variants --
        sec = self._section(right, '4. Variants (per layer)')
        self._variants_display = ttk.Frame(sec)
        self._variants_display.pack(fill=tk.X)

        var_form = ttk.Frame(sec)
        var_form.pack(fill=tk.X, pady=2)
        ttk.Label(var_form, text='Name:').pack(side=tk.LEFT)
        self.v_var_name = tk.StringVar()
        ttk.Entry(var_form, textvariable=self.v_var_name, width=8).pack(
            side=tk.LEFT, padx=2)
        ttk.Label(var_form, text='Sprite:').pack(side=tk.LEFT, padx=(4, 0))
        self.v_var_sprite = tk.StringVar()
        self._var_sprite_cb = ttk.Combobox(
            var_form, textvariable=self.v_var_sprite,
            values=fetch_sprite_names(), state='readonly', width=16)
        self._var_sprite_cb.pack(side=tk.LEFT, padx=2)
        b = ttk.Button(var_form, text='+', width=2, command=self._add_variant)
        b.pack(side=tk.LEFT, padx=2)
        add_tooltip(b, 'Add a variant sprite for the selected layer')

        # -- 5. Animations --
        sec = self._section(right, '5. Animations')
        anim_top = ttk.Frame(sec)
        anim_top.pack(fill=tk.X, pady=2)
        self.v_anim_name = tk.StringVar()
        self._anim_cb = ttk.Combobox(anim_top, textvariable=self.v_anim_name,
                                      values=[], width=18)
        self._anim_cb.pack(side=tk.LEFT, padx=2)
        self._anim_cb.bind('<<ComboboxSelected>>', self._on_anim_select)
        ttk.Button(anim_top, text='New', command=self._new_anim).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(anim_top, text='Del', command=self._delete_anim).pack(
            side=tk.LEFT, padx=2)

        anim_props = ttk.Frame(sec)
        anim_props.pack(fill=tk.X, pady=2)
        ttk.Label(anim_props, text='Duration ms:').pack(side=tk.LEFT)
        self.v_anim_dur = tk.StringVar(value='1000')
        ttk.Entry(anim_props, textvariable=self.v_anim_dur, width=6).pack(
            side=tk.LEFT, padx=2)
        self.v_anim_loop = tk.BooleanVar(value=True)
        ttk.Checkbutton(anim_props, text='Loop',
                         variable=self.v_anim_loop).pack(side=tk.LEFT, padx=4)

        self._kf_display = ttk.Frame(sec)
        self._kf_display.pack(fill=tk.X)

        kf_form = ttk.LabelFrame(sec, text='Add Keyframe', padding=4)
        kf_form.pack(fill=tk.X, pady=4)

        kr1 = ttk.Frame(kf_form)
        kr1.pack(fill=tk.X, pady=1)
        ttk.Label(kr1, text='Layer:').pack(side=tk.LEFT)
        self.v_kf_layer = tk.StringVar()
        self._kf_layer_cb = ttk.Combobox(kr1, textvariable=self.v_kf_layer,
                                          values=[], width=8)
        self._kf_layer_cb.pack(side=tk.LEFT, padx=2)
        ttk.Label(kr1, text='@ms:').pack(side=tk.LEFT, padx=(4, 0))
        self.v_kf_time = tk.StringVar(value='0')
        ttk.Entry(kr1, textvariable=self.v_kf_time, width=5).pack(
            side=tk.LEFT, padx=1)

        kr2 = ttk.Frame(kf_form)
        kr2.pack(fill=tk.X, pady=1)
        ttk.Label(kr2, text='dx:').pack(side=tk.LEFT)
        self.v_kf_ox = tk.StringVar(value='0')
        ttk.Entry(kr2, textvariable=self.v_kf_ox, width=3).pack(
            side=tk.LEFT, padx=1)
        ttk.Label(kr2, text='dy:').pack(side=tk.LEFT, padx=(4, 0))
        self.v_kf_oy = tk.StringVar(value='0')
        ttk.Entry(kr2, textvariable=self.v_kf_oy, width=3).pack(
            side=tk.LEFT, padx=1)
        ttk.Label(kr2, text='rot:').pack(side=tk.LEFT, padx=(4, 0))
        self.v_kf_rot = tk.StringVar(value='0')
        ttk.Entry(kr2, textvariable=self.v_kf_rot, width=4).pack(
            side=tk.LEFT, padx=1)
        ttk.Label(kr2, text='var:').pack(side=tk.LEFT, padx=(4, 0))
        self.v_kf_var = tk.StringVar()
        ttk.Entry(kr2, textvariable=self.v_kf_var, width=6).pack(
            side=tk.LEFT, padx=1)

        b = ttk.Button(kf_form, text='+ Add Keyframe',
                        command=self._add_keyframe)
        b.pack(anchor='w', pady=2)
        add_tooltip(b, 'Add/update keyframe — offsets from default '
                       'connection point, interpolated over time')

        play_row = ttk.Frame(sec)
        play_row.pack(fill=tk.X, pady=4)
        self._play_btn = ttk.Button(play_row, text='\u25b6 Play',
                                     command=self._toggle_anim_preview)
        self._play_btn.pack(side=tk.LEFT, padx=2)
        self._anim_playing = False
        self._anim_after_id = None
        self._anim_time_ms = 0

    # ---- helpers ----

    def _section(self, parent, title):
        lf = ttk.LabelFrame(parent, text=title, padding=6)
        lf.pack(fill=tk.X, padx=4, pady=(6, 2))
        return lf

    def _make_scrollable(self, parent):
        outer = ttk.Frame(parent)
        canvas = tk.Canvas(outer, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        inner = ttk.Frame(canvas)
        win = canvas.create_window((0, 0), window=inner, anchor='nw')
        inner.bind('<Configure>',
                   lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',
                    lambda e: canvas.itemconfig(win, width=e.width))
        canvas.bind_all('<MouseWheel>',
                        lambda e: canvas.yview_scroll(
                            int(-1 * (e.delta / 120)), 'units'))
        return {'outer': outer, 'inner': inner}

    def _get_filtered_sprites(self) -> list[str]:
        f = self.v_sprite_filter.get().strip()
        if f and f != '(all)':
            return fetch_sprite_names_by_set(f)
        return fetch_sprite_names()

    def _refresh_sprite_dropdowns(self):
        sprites = [''] + self._get_filtered_sprites()
        self._layer_sprite_cb['values'] = sprites
        all_sprites = fetch_sprite_names()
        self._var_sprite_cb['values'] = all_sprites

    # ==================================================================
    # Composite CRUD
    # ==================================================================

    def refresh_list(self):
        names = fetch_composite_names()
        self.comp_listbox.delete(0, tk.END)
        for n in names:
            self.comp_listbox.insert(tk.END, n)

    def refresh_dropdowns(self):
        self._filter_cb['values'] = ['(all)'] + fetch_sprite_sets()
        self._refresh_sprite_dropdowns()
        self._refresh_layer_dropdowns()

    def _refresh_layer_dropdowns(self):
        names = [l['layer_name'] for l in self._layers]
        self._conn_child_cb['values'] = names
        self._conn_parent_cb['values'] = names
        self._kf_layer_cb['values'] = names

    def _new_comp(self):
        self.comp_listbox.selection_clear(0, tk.END)
        self.v_comp_name.set('')
        self._layers = []
        self._connections = {}
        self._variants = {}
        self._root_layer = 'root'
        self._animations = []
        self._selected_layer_idx = None
        self._rebuild_all()
        self._layer_preview.load(None)

    def _on_comp_select(self, event=None):
        sel = self.comp_listbox.curselection()
        if not sel:
            return
        self._load_composite(self.comp_listbox.get(sel[0]))

    def _load_composite(self, name):
        self._stop_anim_preview()
        con = get_con()
        try:
            row = con.execute(
                'SELECT * FROM composite_sprites WHERE name=?', (name,)
            ).fetchone()
            if not row:
                return
            self.v_comp_name.set(row['name'])
            self._root_layer = row['root_layer']
            self._layers = [
                {'layer_name': r['layer_name'], 'z_layer': r['z_layer'],
                 'default_sprite': r['default_sprite']}
                for r in con.execute(
                    'SELECT layer_name, z_layer, default_sprite'
                    ' FROM composite_layers WHERE composite_name=?'
                    ' ORDER BY z_layer', (name,)).fetchall()]
            self._connections = {}
            for r in con.execute(
                    'SELECT * FROM layer_connections'
                    ' WHERE composite_name=?', (name,)).fetchall():
                self._connections[r['child_layer']] = {
                    'parent_layer': r['parent_layer'],
                    'parent_socket': (r['parent_socket_x'],
                                      r['parent_socket_y']),
                    'child_anchor': (r['child_anchor_x'],
                                     r['child_anchor_y']),
                }
            self._variants = {}
            for r in con.execute(
                    'SELECT layer_name, variant_name, sprite_name'
                    ' FROM layer_variants WHERE composite_name=?',
                    (name,)).fetchall():
                self._variants.setdefault(
                    r['layer_name'], {})[r['variant_name']] = r['sprite_name']
            self._animations = []
            for r in con.execute(
                    'SELECT name, loop, duration_ms'
                    ' FROM composite_animations WHERE composite_name=?'
                    ' ORDER BY name', (name,)).fetchall():
                anim = {'name': r['name'], 'loop': bool(r['loop']),
                         'duration_ms': r['duration_ms'], 'keyframes': {}}
                for kf in con.execute(
                        'SELECT layer_name, time_ms, offset_x, offset_y,'
                        ' rotation_deg, variant_name'
                        ' FROM composite_anim_keyframes'
                        ' WHERE animation_name=?'
                        ' ORDER BY layer_name, time_ms',
                        (r['name'],)).fetchall():
                    anim['keyframes'].setdefault(
                        kf['layer_name'], []).append({
                            'time_ms': kf['time_ms'],
                            'offset_x': kf['offset_x'],
                            'offset_y': kf['offset_y'],
                            'rotation_deg': kf['rotation_deg'],
                            'variant_name': kf['variant_name']})
                self._animations.append(anim)
        finally:
            con.close()
        self._selected_layer_idx = None
        self._rebuild_all()
        self._layer_preview.load(None)
        self.refresh_dropdowns()

    def _save_comp(self):
        name = self.v_comp_name.get().strip()
        if not name:
            messagebox.showerror('Save', 'Composite name is required.')
            return
        if not self._layers:
            messagebox.showerror('Save', 'Add at least one layer.')
            return
        if self._root_layer not in {l['layer_name'] for l in self._layers}:
            messagebox.showerror('Save',
                                 f'Root "{self._root_layer}" not in layers.')
            return
        con = get_con()
        try:
            con.execute(
                '''INSERT INTO composite_sprites (name, root_layer)
                   VALUES (?, ?) ON CONFLICT(name)
                   DO UPDATE SET root_layer=excluded.root_layer''',
                (name, self._root_layer))
            con.execute('DELETE FROM composite_layers'
                        ' WHERE composite_name=?', (name,))
            for l in self._layers:
                con.execute(
                    'INSERT INTO composite_layers'
                    ' (composite_name, layer_name, z_layer, default_sprite)'
                    ' VALUES (?, ?, ?, ?)',
                    (name, l['layer_name'], l['z_layer'],
                     l['default_sprite']))
            con.execute('DELETE FROM layer_connections'
                        ' WHERE composite_name=?', (name,))
            for child, conn in self._connections.items():
                con.execute(
                    'INSERT INTO layer_connections'
                    ' (composite_name, parent_layer, child_layer,'
                    '  parent_socket_x, parent_socket_y,'
                    '  child_anchor_x, child_anchor_y)'
                    ' VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (name, conn['parent_layer'], child,
                     conn['parent_socket'][0], conn['parent_socket'][1],
                     conn['child_anchor'][0], conn['child_anchor'][1]))
            con.execute('DELETE FROM layer_variants'
                        ' WHERE composite_name=?', (name,))
            for ln, vd in self._variants.items():
                for vn, sn in vd.items():
                    con.execute(
                        'INSERT INTO layer_variants'
                        ' (composite_name, layer_name, variant_name,'
                        '  sprite_name) VALUES (?, ?, ?, ?)',
                        (name, ln, vn, sn))
            old = [r['name'] for r in con.execute(
                'SELECT name FROM composite_animations'
                ' WHERE composite_name=?', (name,)).fetchall()]
            for an in old:
                con.execute('DELETE FROM composite_anim_keyframes'
                            ' WHERE animation_name=?', (an,))
            con.execute('DELETE FROM composite_animations'
                        ' WHERE composite_name=?', (name,))
            for anim in self._animations:
                con.execute(
                    'INSERT INTO composite_animations'
                    ' (name, composite_name, loop, duration_ms)'
                    ' VALUES (?, ?, ?, ?)',
                    (anim['name'], name, int(anim['loop']),
                     anim['duration_ms']))
                for ln, kfs in anim['keyframes'].items():
                    for kf in kfs:
                        con.execute(
                            'INSERT INTO composite_anim_keyframes'
                            ' (animation_name, layer_name, time_ms,'
                            '  offset_x, offset_y, rotation_deg,'
                            '  variant_name) VALUES (?, ?, ?, ?, ?, ?, ?)',
                            (anim['name'], ln, kf['time_ms'],
                             kf['offset_x'], kf['offset_y'],
                             kf['rotation_deg'], kf.get('variant_name')))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()
        items = list(self.comp_listbox.get(0, tk.END))
        if name in items:
            idx = items.index(name)
            self.comp_listbox.selection_set(idx)
            self.comp_listbox.see(idx)

    def _delete_comp(self):
        sel = self.comp_listbox.curselection()
        if not sel:
            return
        name = self.comp_listbox.get(sel[0])
        if not messagebox.askyesno('Delete', f'Delete "{name}"?'):
            return
        con = get_con()
        try:
            for an in [r['name'] for r in con.execute(
                    'SELECT name FROM composite_animations'
                    ' WHERE composite_name=?', (name,)).fetchall()]:
                con.execute('DELETE FROM composite_anim_keyframes'
                            ' WHERE animation_name=?', (an,))
            for tbl in ('composite_animations', 'layer_variants',
                        'layer_connections', 'composite_layers',
                        'composite_sprites'):
                col = 'name' if tbl == 'composite_sprites' else 'composite_name'
                con.execute(f'DELETE FROM {tbl} WHERE {col}=?', (name,))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()
        self._new_comp()

    # ==================================================================
    # Layers
    # ==================================================================

    def _rebuild_layer_listbox(self):
        self.layer_listbox.delete(0, tk.END)
        for l in self._layers:
            root = '*' if l['layer_name'] == self._root_layer else ' '
            spr = l['default_sprite'] or '(none)'
            self.layer_listbox.insert(
                tk.END,
                f"{root} {l['layer_name']}   z={l['z_layer']}   [{spr}]")
        self._refresh_layer_dropdowns()

    def _on_layer_select(self, event=None):
        sel = self.layer_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self._selected_layer_idx = idx
        layer = self._layers[idx]
        self.v_layer_name.set(layer['layer_name'])
        self.v_z_layer.set(str(layer['z_layer']))
        self.v_layer_sprite.set(layer['default_sprite'] or '')
        self._layer_preview.load(layer['default_sprite'])
        self._rebuild_variants_display()

    def _add_layer(self):
        existing = {l['layer_name'] for l in self._layers}
        name = 'root' if not existing else f'layer_{len(self._layers)}'
        while name in existing:
            name = f'layer_{len(self._layers) + 1}'
        self._layers.append({'layer_name': name, 'z_layer': len(self._layers),
                              'default_sprite': None})
        if len(self._layers) == 1:
            self._root_layer = name
        self._rebuild_layer_listbox()
        self.layer_listbox.selection_set(len(self._layers) - 1)
        self._on_layer_select()

    def _remove_layer(self):
        sel = self.layer_listbox.curselection()
        if not sel:
            return
        removed = self._layers.pop(sel[0])
        n = removed['layer_name']
        self._connections.pop(n, None)
        for c in [k for k, v in self._connections.items()
                   if v['parent_layer'] == n]:
            del self._connections[c]
        self._variants.pop(n, None)
        self._selected_layer_idx = None
        self._rebuild_all()
        self._layer_preview.load(None)

    def _set_root(self):
        sel = self.layer_listbox.curselection()
        if not sel:
            return
        self._root_layer = self._layers[sel[0]]['layer_name']
        self._connections.pop(self._root_layer, None)
        self._rebuild_layer_listbox()
        self._rebuild_connections_display()
        self._refresh_preview()

    def _apply_layer_detail(self):
        if self._selected_layer_idx is None:
            return
        layer = self._layers[self._selected_layer_idx]
        new_name = self.v_layer_name.get().strip()
        old_name = layer['layer_name']
        if new_name and new_name != old_name:
            if any(l['layer_name'] == new_name for l in self._layers):
                messagebox.showerror('Error', f'"{new_name}" already exists.')
                return
            layer['layer_name'] = new_name
            if old_name in self._connections:
                self._connections[new_name] = self._connections.pop(old_name)
            for conn in self._connections.values():
                if conn['parent_layer'] == old_name:
                    conn['parent_layer'] = new_name
            if old_name in self._variants:
                self._variants[new_name] = self._variants.pop(old_name)
            if self._root_layer == old_name:
                self._root_layer = new_name
            for anim in self._animations:
                if old_name in anim['keyframes']:
                    anim['keyframes'][new_name] = \
                        anim['keyframes'].pop(old_name)
        try:
            layer['z_layer'] = int(self.v_z_layer.get())
        except ValueError:
            pass
        layer['default_sprite'] = self.v_layer_sprite.get() or None
        self._rebuild_layer_listbox()
        self._rebuild_connections_display()
        self._refresh_preview()

    def _on_layer_sprite_change(self, event=None):
        spr = self.v_layer_sprite.get() or None
        self._layer_preview.load(spr)
        if self._selected_layer_idx is not None:
            self._layers[self._selected_layer_idx]['default_sprite'] = spr
            self._rebuild_layer_listbox()
            self._refresh_preview()

    # ==================================================================
    # Connections
    # ==================================================================

    def _rebuild_connections_display(self):
        for w in self._conn_display.winfo_children():
            w.destroy()
        if not self._connections:
            ttk.Label(self._conn_display, text='(no connections)',
                      foreground='#888').pack(anchor='w')
            return
        for child, conn in self._connections.items():
            row = ttk.Frame(self._conn_display)
            row.pack(fill=tk.X, pady=1)
            px, py = conn['parent_socket']
            ax, ay = conn['child_anchor']
            text = (f"({child}, {ax}, {ay})  \u2192  "
                    f"({conn['parent_layer']}, {px}, {py})")
            ttk.Label(row, text=text,
                      font=('TkFixedFont', 9)).pack(side=tk.LEFT)

            def _del(c=child):
                self._connections.pop(c, None)
                self._rebuild_connections_display()
                self._refresh_preview()
            ttk.Button(row, text='\u2715', width=2,
                       command=_del).pack(side=tk.LEFT, padx=4)

    def _add_connection(self):
        child = self.v_conn_child.get().strip()
        parent = self.v_conn_parent.get().strip()
        if not child or not parent:
            messagebox.showerror('Connection', 'Select child and parent.')
            return
        if child == parent:
            messagebox.showerror('Connection', 'Cannot self-connect.')
            return
        if child == self._root_layer:
            messagebox.showerror('Connection', 'Root cannot be a child.')
            return
        try:
            psx = int(self.v_conn_psx.get())
            psy = int(self.v_conn_psy.get())
            cax = int(self.v_conn_cax.get())
            cay = int(self.v_conn_cay.get())
        except ValueError:
            messagebox.showerror('Connection', 'Coordinates must be integers.')
            return
        self._connections[child] = {
            'parent_layer': parent,
            'parent_socket': (psx, psy),
            'child_anchor': (cax, cay)}
        self._rebuild_connections_display()
        self._refresh_preview()

    # ==================================================================
    # Variants
    # ==================================================================

    def _rebuild_variants_display(self):
        for w in self._variants_display.winfo_children():
            w.destroy()
        if self._selected_layer_idx is None:
            ttk.Label(self._variants_display, text='(select a layer)',
                      foreground='#888').pack(anchor='w')
            return
        ln = self._layers[self._selected_layer_idx]['layer_name']
        vd = self._variants.get(ln, {})
        if not vd:
            ttk.Label(self._variants_display,
                      text=f'No variants for "{ln}"',
                      foreground='#888').pack(anchor='w')
            return
        for vn, sn in vd.items():
            row = ttk.Frame(self._variants_display)
            row.pack(fill=tk.X, pady=1)
            ttk.Label(row, text=f'{vn} \u2192 {sn}').pack(side=tk.LEFT)

            def _del(v=vn, l=ln):
                self._variants.get(l, {}).pop(v, None)
                self._rebuild_variants_display()
            ttk.Button(row, text='\u2715', width=2,
                       command=_del).pack(side=tk.LEFT, padx=4)

    def _add_variant(self):
        if self._selected_layer_idx is None:
            messagebox.showwarning('Variant', 'Select a layer first.')
            return
        ln = self._layers[self._selected_layer_idx]['layer_name']
        vn = self.v_var_name.get().strip()
        sn = self.v_var_sprite.get().strip()
        if not vn or not sn:
            messagebox.showerror('Variant', 'Name and sprite required.')
            return
        self._variants.setdefault(ln, {})[vn] = sn
        self._rebuild_variants_display()

    # ==================================================================
    # Preview
    # ==================================================================

    def _refresh_preview(self):
        layers = {}
        for l in self._layers:
            layers[l['layer_name']] = {
                'z_layer': l['z_layer'],
                'sprite_data': fetch_sprite(l['default_sprite']),
            }
        self._preview.render(layers, self._connections, self._root_layer)

    # ==================================================================
    # Animations
    # ==================================================================

    def _rebuild_anim_ui(self):
        names = [a['name'] for a in self._animations]
        self._anim_cb['values'] = names
        if names:
            self._anim_cb.set(names[0])
            self._show_keyframes(names[0])
        else:
            self._anim_cb.set('')
            self._clear_keyframes()

    def _get_current_anim(self):
        name = self.v_anim_name.get().strip()
        for a in self._animations:
            if a['name'] == name:
                return a
        return None

    def _on_anim_select(self, event=None):
        self._stop_anim_preview()
        anim = self._get_current_anim()
        if anim:
            self.v_anim_dur.set(str(anim['duration_ms']))
            self.v_anim_loop.set(anim['loop'])
            self._show_keyframes(anim['name'])
        else:
            self._clear_keyframes()

    def _new_anim(self):
        comp = self.v_comp_name.get().strip()
        if not comp:
            messagebox.showwarning('Animation', 'Name the composite first.')
            return
        existing = {a['name'] for a in self._animations}
        i = 1
        name = f'{comp}_anim_{i}'
        while name in existing:
            i += 1
            name = f'{comp}_anim_{i}'
        self._animations.append({'name': name, 'loop': True,
                                  'duration_ms': 1000, 'keyframes': {}})
        self._rebuild_anim_ui()
        self._anim_cb.set(name)

    def _delete_anim(self):
        anim = self._get_current_anim()
        if anim:
            self._animations.remove(anim)
            self._rebuild_anim_ui()

    def _show_keyframes(self, anim_name):
        for w in self._kf_display.winfo_children():
            w.destroy()
        anim = next((a for a in self._animations
                     if a['name'] == anim_name), None)
        if not anim or not anim['keyframes']:
            ttk.Label(self._kf_display, text='(no keyframes)',
                      foreground='#888').pack(anchor='w')
            return
        for ln, kfs in sorted(anim['keyframes'].items()):
            for kf in kfs:
                row = ttk.Frame(self._kf_display)
                row.pack(fill=tk.X, pady=1)
                var = (f' var={kf["variant_name"]}'
                       if kf.get('variant_name') else '')
                text = (f'{ln} @{kf["time_ms"]}ms  '
                        f'dx={kf["offset_x"]} dy={kf["offset_y"]} '
                        f'rot={kf["rotation_deg"]:.0f}{var}')
                ttk.Label(row, text=text,
                          font=('TkFixedFont', 8)).pack(side=tk.LEFT)

                def _del(l=ln, t=kf['time_ms'], an=anim_name):
                    a = self._get_current_anim()
                    if a and l in a['keyframes']:
                        a['keyframes'][l] = [
                            k for k in a['keyframes'][l]
                            if k['time_ms'] != t]
                        if not a['keyframes'][l]:
                            del a['keyframes'][l]
                    self._show_keyframes(an)
                ttk.Button(row, text='\u2715', width=2,
                           command=_del).pack(side=tk.LEFT, padx=2)

    def _clear_keyframes(self):
        for w in self._kf_display.winfo_children():
            w.destroy()

    def _add_keyframe(self):
        anim = self._get_current_anim()
        if not anim:
            messagebox.showwarning('Keyframe', 'Select or create an animation.')
            return
        try:
            anim['duration_ms'] = int(self.v_anim_dur.get())
        except ValueError:
            pass
        anim['loop'] = self.v_anim_loop.get()
        layer = self.v_kf_layer.get().strip()
        if not layer:
            messagebox.showerror('Keyframe', 'Pick a layer.')
            return
        try:
            t = int(self.v_kf_time.get())
            ox = int(self.v_kf_ox.get())
            oy = int(self.v_kf_oy.get())
            rot = float(self.v_kf_rot.get())
        except ValueError:
            messagebox.showerror('Keyframe', 'Values must be numeric.')
            return
        var = self.v_kf_var.get().strip() or None
        kfs = anim['keyframes'].setdefault(layer, [])
        kfs = [k for k in kfs if k['time_ms'] != t]
        kfs.append({'time_ms': t, 'offset_x': ox, 'offset_y': oy,
                     'rotation_deg': rot, 'variant_name': var})
        kfs.sort(key=lambda k: k['time_ms'])
        anim['keyframes'][layer] = kfs
        self._show_keyframes(anim['name'])

    def _toggle_anim_preview(self):
        if self._anim_playing:
            self._stop_anim_preview()
        else:
            self._start_anim_preview()

    def _start_anim_preview(self):
        anim = self._get_current_anim()
        if not anim or not anim['keyframes']:
            return
        self._anim_playing = True
        self._anim_time_ms = 0
        self._play_btn.configure(text='\u25a0 Stop')
        self._tick_anim()

    def _stop_anim_preview(self):
        self._anim_playing = False
        if self._anim_after_id:
            self.after_cancel(self._anim_after_id)
            self._anim_after_id = None
        self._play_btn.configure(text='\u25b6 Play')
        self._refresh_preview()

    def _tick_anim(self):
        if not self._anim_playing:
            return
        anim = self._get_current_anim()
        if not anim:
            self._stop_anim_preview()
            return
        dur = anim['duration_ms']
        t = (self._anim_time_ms % dur) if (anim['loop'] and dur > 0) \
            else min(self._anim_time_ms, dur)
        offsets = {}
        var_overrides = {}
        for ln, kfs in anim['keyframes'].items():
            ox, oy, rot, var = _interp_keyframes(kfs, t)
            offsets[ln] = (int(ox), int(oy), rot)
            if var:
                sn = self._variants.get(ln, {}).get(var)
                if sn:
                    data = fetch_sprite(sn)
                    if data:
                        var_overrides[ln] = data
        layers = {}
        for l in self._layers:
            layers[l['layer_name']] = {
                'z_layer': l['z_layer'],
                'sprite_data': fetch_sprite(l['default_sprite'])}
        self._preview.render(layers, self._connections, self._root_layer,
                             variant_overrides=var_overrides,
                             anim_offsets=offsets)
        self._anim_time_ms += 33
        if not anim['loop'] and self._anim_time_ms > dur:
            self._stop_anim_preview()
            return
        self._anim_after_id = self.after(33, self._tick_anim)

    # ==================================================================
    # Rebuild
    # ==================================================================

    def _rebuild_all(self):
        self._rebuild_layer_listbox()
        self._rebuild_connections_display()
        self._rebuild_variants_display()
        self._rebuild_anim_ui()
        self._refresh_preview()
