"""
Composites editor — three sub-tabs for composite sprite workflow.

Tab 1 (Layers):   composite picker, layer list + detail, variants per layer, preview
Tab 2 (Connect):  connection setup with large composite preview
Tab 3 (Animate):  animation picker, scrollable spreadsheet keyframes, preview
"""
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
        return 0, 0, 0.0, None, None, 1.0
    if len(keyframes) == 1:
        k = keyframes[0]
        return (k['offset_x'], k['offset_y'], k['rotation_deg'],
                k.get('variant_name'), k.get('tint'), k.get('opacity', 1.0))
    prev = keyframes[0]
    for kf in keyframes:
        if kf['time_ms'] > time_ms:
            nxt = kf
            break
        prev = kf
    else:
        return (prev['offset_x'], prev['offset_y'], prev['rotation_deg'],
                prev.get('variant_name'), prev.get('tint'),
                prev.get('opacity', 1.0))
    if prev['time_ms'] == nxt['time_ms']:
        return (prev['offset_x'], prev['offset_y'], prev['rotation_deg'],
                prev.get('variant_name'), prev.get('tint'),
                prev.get('opacity', 1.0))
    t = (time_ms - prev['time_ms']) / (nxt['time_ms'] - prev['time_ms'])
    # Interpolate tint
    tint = None
    pt, nt = prev.get('tint'), nxt.get('tint')
    if pt and nt:
        tint = (int(_lerp(pt[0], nt[0], t)),
                int(_lerp(pt[1], nt[1], t)),
                int(_lerp(pt[2], nt[2], t)))
    elif pt:
        tint = pt
    elif nt:
        tint = nt
    return (_lerp(prev['offset_x'], nxt['offset_x'], t),
            _lerp(prev['offset_y'], nxt['offset_y'], t),
            _lerp(prev['rotation_deg'], nxt['rotation_deg'], t),
            prev.get('variant_name') or nxt.get('variant_name'),
            tint,
            _lerp(prev.get('opacity', 1.0), nxt.get('opacity', 1.0), t))


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
               variant_overrides=None, anim_offsets=None,
               anim_opacity=None, show_sockets=False):
        self.delete('all')
        if not layers:
            self._checkerboard()
            return
        variant_overrides = variant_overrides or {}
        anim_offsets = anim_offsets or {}
        anim_opacity = anim_opacity or {}

        def _resolve(offsets):
            pos = {}
            def resolve(name, depth=0):
                if name in pos or depth > 20:
                    return
                if name == root_layer:
                    pos[name] = (0, 0)
                else:
                    conn = connections.get(name)
                    if not conn:
                        pos[name] = (0, 0)
                        return
                    resolve(conn['parent_layer'], depth + 1)
                    pp = pos.get(conn['parent_layer'], (0, 0))
                    sx, sy = conn['parent_socket']
                    ax, ay = conn['child_anchor']
                    pos[name] = (pp[0] + sx - ax, pp[1] + sy - ay)
                ao = offsets.get(name)
                if ao:
                    ox, oy, _rot = ao
                    px, py = pos[name]
                    pos[name] = (px + ox, py + oy)
            for name in layers:
                resolve(name)
            return pos

        # Static positions for stable bounding box / scale
        static_positions = _resolve({})
        # Animated positions for rendering
        positions = _resolve(anim_offsets) if anim_offsets else static_positions

        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')
        for name, (px, py) in static_positions.items():
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

        import math
        for name, info in sorted(layers.items(),
                                  key=lambda x: x[1].get('z_layer', 0)):
            data = variant_overrides.get(name) or info.get('sprite_data')
            if not data:
                continue
            opacity = anim_opacity.get(name, 1.0)
            if opacity <= 0.01:
                continue
            px, py = positions.get(name, (0, 0))
            palette = data['palette']
            # Check if this layer has rotation
            ao = anim_offsets.get(name)
            rot = ao[2] if ao else 0.0
            # Rotation pivot = connection anchor point on this layer
            if rot:
                conn = connections.get(name)
                if conn:
                    ax, ay = conn['child_anchor']
                else:
                    w = data.get('width', 0)
                    h = len(data.get('pixels', []))
                    ax, ay = w / 2, h / 2
                rad = math.radians(-rot)
                cos_a, sin_a = math.cos(rad), math.sin(rad)
            for ri, row_str in enumerate(data.get('pixels', [])):
                for ci, ch in enumerate(row_str):
                    if ch == '.' or ch not in palette:
                        continue
                    color = palette[ch]
                    if opacity < 1.0:
                        try:
                            cr = int(int(color[1:3], 16) * opacity)
                            cg = int(int(color[3:5], 16) * opacity)
                            cb = int(int(color[5:7], 16) * opacity)
                            color = f'#{cr:02x}{cg:02x}{cb:02x}'
                        except (ValueError, IndexError):
                            pass
                    # Pixel position, optionally rotated around anchor
                    lx, ly = ci, ri
                    if rot:
                        dx, dy = lx - ax, ly - ay
                        lx = ax + dx * cos_a - dy * sin_a
                        ly = ay + dx * sin_a + dy * cos_a
                    sx = pad + (px - min_x + lx) * scale
                    sy = pad + (py - min_y + ly) * scale
                    self.create_rectangle(sx, sy, sx + scale, sy + scale,
                                          fill=color, outline='')

        if show_sockets:
            for child, conn in connections.items():
                pp = positions.get(conn['parent_layer'], (0, 0))
                sx = pad + (pp[0] - min_x + conn['parent_socket'][0]) * scale
                sy = pad + (pp[1] - min_y + conn['parent_socket'][1]) * scale
                r = max(2, scale * 0.4)
                self.create_oval(sx - r, sy - r, sx + r, sy + r,
                                 fill='#44ff44', outline='white', width=1)
                # Child anchor marker
                cp = positions.get(child, (0, 0))
                cx = pad + (cp[0] - min_x + conn['child_anchor'][0]) * scale
                cy = pad + (cp[1] - min_y + conn['child_anchor'][1]) * scale
                self.create_oval(cx - r, cy - r, cx + r, cy + r,
                                 fill='#ff4444', outline='white', width=1)

    def _checkerboard(self):
        cs = max(1, self._size // 16)
        for r in range(16):
            for c in range(16):
                x0, y0 = c * cs, r * cs
                color = self.CHECKER_A if (r + c) % 2 == 0 else self.CHECKER_B
                self.create_rectangle(x0, y0, x0 + cs, y0 + cs,
                                      fill=color, outline='')


# ---------------------------------------------------------------------------
# Editable Treeview for keyframes
# ---------------------------------------------------------------------------

class EditableTree(ttk.Frame):
    """Treeview with inline editing on double-click."""

    COLS = ('layer', 'time_ms', 'dx', 'dy', 'rot', 'variant',
            'tint_r', 'tint_g', 'tint_b', 'opacity')
    WIDTHS = (80, 60, 40, 40, 45, 90, 40, 40, 40, 50)

    def __init__(self, parent, get_variant_choices=None, **kwargs):
        super().__init__(parent, **kwargs)
        self._get_variant_choices = get_variant_choices or (lambda ln: [])
        self._edit_widget = None

        container = ttk.Frame(self)
        container.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(
            container, columns=self.COLS, show='headings', height=10,
            selectmode='browse')
        vsb = ttk.Scrollbar(container, orient=tk.VERTICAL,
                             command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._sort_reverse = {}
        for col, w in zip(self.COLS, self.WIDTHS):
            self.tree.heading(col, text=col,
                              command=lambda c=col: self._sort_by(c))
            self.tree.column(col, width=w, minwidth=w, stretch=False)
            self._sort_reverse[col] = False

        self.tree.bind('<Double-1>', self._on_double_click)

    def clear(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

    def _sort_by(self, col):
        """Sort rows by clicking a column header."""
        col_idx = self.COLS.index(col)
        items = [(self.tree.item(k, 'values'), k)
                 for k in self.tree.get_children()]
        numeric = col not in ('layer', 'variant')

        def sort_key(pair):
            val = pair[0][col_idx] if col_idx < len(pair[0]) else ''
            if numeric:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return 0.0
            return str(val)

        items.sort(key=sort_key, reverse=self._sort_reverse[col])
        self._sort_reverse[col] = not self._sort_reverse[col]
        for idx, (vals, k) in enumerate(items):
            self.tree.move(k, '', idx)

    def add_row(self, values: tuple):
        self.tree.insert('', tk.END, values=values)

    def get_all_rows(self) -> list[tuple]:
        rows = []
        for item in self.tree.get_children():
            rows.append(self.tree.item(item, 'values'))
        return rows

    def delete_selected(self):
        sel = self.tree.selection()
        if sel:
            self.tree.delete(sel[0])

    def _on_double_click(self, event):
        if self._edit_widget:
            self._finish_edit()
        region = self.tree.identify_region(event.x, event.y)
        if region != 'cell':
            return
        item = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)
        if not item or not col_id:
            return
        col_idx = int(col_id.replace('#', '')) - 1
        col_name = self.COLS[col_idx]
        values = self.tree.item(item, 'values')
        current_val = values[col_idx] if col_idx < len(values) else ''

        bbox = self.tree.bbox(item, col_id)
        if not bbox:
            return
        x, y, w, h = bbox

        if col_name == 'variant':
            # Dropdown for variant
            layer_name = values[0] if values else ''
            choices = [''] + self._get_variant_choices(layer_name)
            widget = ttk.Combobox(self.tree, values=choices, state='readonly',
                                   width=w // 8)
            widget.set(current_val)
            widget.bind('<<ComboboxSelected>>',
                        lambda e: self._finish_edit())
            widget.bind('<Escape>', lambda e: self._cancel_edit())
        else:
            widget = ttk.Entry(self.tree, width=w // 8)
            widget.insert(0, current_val)
            widget.select_range(0, tk.END)
            widget.bind('<Return>', lambda e: self._finish_edit())
            widget.bind('<Escape>', lambda e: self._cancel_edit())

        widget.place(x=x, y=y, width=w, height=h)
        widget.focus_set()

        self._edit_widget = widget
        self._edit_item = item
        self._edit_col_idx = col_idx

    def _finish_edit(self):
        if not self._edit_widget:
            return
        new_val = self._edit_widget.get()
        values = list(self.tree.item(self._edit_item, 'values'))
        while len(values) <= self._edit_col_idx:
            values.append('')
        values[self._edit_col_idx] = new_val
        self.tree.item(self._edit_item, values=values)
        self._edit_widget.destroy()
        self._edit_widget = None

    def _cancel_edit(self):
        if self._edit_widget:
            self._edit_widget.destroy()
            self._edit_widget = None


# ---------------------------------------------------------------------------
# Main Tab (outer container with sub-tabs)
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
        self._anim_playing = False
        self._anim_after_id = None
        self._anim_time_ms = 0

        self._build_ui()
        self.refresh_list()

    # ==================================================================
    # UI construction
    # ==================================================================

    def _build_ui(self):
        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # --- Tab 1: Layers ---
        self._tab_layers = ttk.Frame(self._notebook)
        self._notebook.add(self._tab_layers, text='Layers')
        self._build_layers_tab(self._tab_layers)

        # --- Tab 2: Connections ---
        self._tab_connect = ttk.Frame(self._notebook)
        self._notebook.add(self._tab_connect, text='Connections')
        self._build_connections_tab(self._tab_connect)

        # --- Tab 3: Animate ---
        self._tab_animate = ttk.Frame(self._notebook)
        self._notebook.add(self._tab_animate, text='Animate')
        self._build_animate_tab(self._tab_animate)

        self._notebook.bind('<<NotebookTabChanged>>', self._on_subtab_changed)

    # ------------------------------------------------------------------
    # Tab 1: Layers (composite picker, layer list, layer detail, variants)
    # ------------------------------------------------------------------

    def _build_layers_tab(self, parent):
        outer = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # ---- LEFT: composite picker + layers ----
        left = ttk.Frame(outer)
        outer.add(left, weight=1)

        # -- Composite picker --
        sec = self._section(left, 'Composite')
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

        # Sprite set filter
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
                    'Filter sprite dropdowns by sprite_set tag')

        # -- Layers --
        sec = self._section(left, 'Layers')
        self.layer_listbox = tk.Listbox(sec, exportselection=False,
                                         width=36, height=6)
        self.layer_listbox.pack(fill=tk.X)
        self.layer_listbox.bind('<<ListboxSelect>>', self._on_layer_select)

        lbtns = ttk.Frame(sec)
        lbtns.pack(fill=tk.X, pady=2)
        ttk.Button(lbtns, text='+ Add Layer',
                    command=self._add_layer).pack(side=tk.LEFT, padx=2)
        ttk.Button(lbtns, text='- Remove',
                    command=self._remove_layer).pack(side=tk.LEFT, padx=2)
        ttk.Button(lbtns, text='Set as Root',
                    command=self._set_root).pack(side=tk.LEFT, padx=2)

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

        self._layer_preview = SpritePreview(det, size=PREVIEW_SIZE)
        self._layer_preview.pack(anchor='w', pady=4)

        ttk.Button(det, text='Apply Changes',
                    command=self._apply_layer_detail).pack(anchor='w', pady=2)

        # ---- RIGHT: variants + small preview ----
        right = ttk.Frame(outer)
        outer.add(right, weight=1)

        sec = self._section(right, 'Variants (for selected layer)')
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
        ttk.Button(var_form, text='+', width=2,
                    command=self._add_variant).pack(side=tk.LEFT, padx=2)

        # Small composite preview
        sec = self._section(right, 'Preview')
        self._layers_preview = CompositePreview(sec, size=200)
        self._layers_preview.pack(anchor='w', pady=4)

    # ------------------------------------------------------------------
    # Tab 2: Connections
    # ------------------------------------------------------------------

    def _build_connections_tab(self, parent):
        outer = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # ---- LEFT: connection list + form ----
        left = ttk.Frame(outer)
        outer.add(left, weight=1)

        sec = self._section(left, 'Connections')
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

        ttk.Button(conn_form, text='Set Connection',
                    command=self._add_connection).pack(anchor='w', pady=2)

        ttk.Button(sec, text='Save All', command=self._save_comp).pack(
            anchor='w', pady=(6, 2))

        # ---- RIGHT: big preview with socket markers ----
        right = ttk.Frame(outer)
        outer.add(right, weight=1)

        sec = self._section(right, 'Connection Preview')
        self._conn_preview = CompositePreview(sec, size=360)
        self._conn_preview.pack(anchor='center', pady=4)
        ttk.Label(sec, text='Green = parent socket, Red = child anchor',
                  font=('TkDefaultFont', 8), foreground='#666').pack(anchor='w')

    # ------------------------------------------------------------------
    # Tab 3: Animate
    # ------------------------------------------------------------------

    def _build_animate_tab(self, parent):
        outer = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # ---- LEFT: animation picker + keyframe spreadsheet ----
        left = ttk.Frame(outer)
        outer.add(left, weight=2)

        sec = self._section(left, 'Animation')
        anim_top = ttk.Frame(sec)
        anim_top.pack(fill=tk.X, pady=2)
        ttk.Label(anim_top, text='Name:').pack(side=tk.LEFT)
        self.v_anim_name = tk.StringVar()
        self._anim_cb = ttk.Combobox(anim_top, textvariable=self.v_anim_name,
                                      values=[], width=18)
        self._anim_cb.pack(side=tk.LEFT, padx=2)
        self._anim_cb.bind('<<ComboboxSelected>>', self._on_anim_select)
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
        ttk.Label(anim_props, text='Speed:').pack(side=tk.LEFT, padx=(8, 0))
        self.v_time_scale = tk.StringVar(value='1.0')
        ttk.Entry(anim_props, textvariable=self.v_time_scale, width=4).pack(
            side=tk.LEFT, padx=2)
        add_tooltip(anim_props,
                    'Playback speed multiplier — 2.0 = double speed, 0.5 = half speed')

        # Keyframe spreadsheet
        sec2 = self._section(left, 'Keyframes (double-click to edit)')
        self._kf_tree = EditableTree(
            sec2, get_variant_choices=self._get_variant_choices_for_layer)
        self._kf_tree.pack(fill=tk.BOTH, expand=True)

        kf_btns = ttk.Frame(sec2)
        kf_btns.pack(fill=tk.X, pady=2)

        add_frame = ttk.Frame(kf_btns)
        add_frame.pack(fill=tk.X)
        ttk.Label(add_frame, text='Layer:').pack(side=tk.LEFT)
        self.v_kf_layer = tk.StringVar()
        self._kf_layer_cb = ttk.Combobox(add_frame, textvariable=self.v_kf_layer,
                                          values=[], width=8)
        self._kf_layer_cb.pack(side=tk.LEFT, padx=2)
        ttk.Label(add_frame, text='@ms:').pack(side=tk.LEFT)
        self.v_kf_time = tk.StringVar(value='0')
        ttk.Entry(add_frame, textvariable=self.v_kf_time, width=5).pack(
            side=tk.LEFT, padx=1)
        ttk.Button(add_frame, text='+ Add Row',
                    command=self._add_keyframe_row).pack(side=tk.LEFT, padx=4)
        ttk.Button(add_frame, text='- Delete Row',
                    command=self._delete_keyframe_row).pack(side=tk.LEFT, padx=2)
        ttk.Button(add_frame, text='Apply to Animation',
                    command=self._apply_keyframes_from_tree).pack(
                        side=tk.LEFT, padx=4)

        # ---- RIGHT: animation preview ----
        right = ttk.Frame(outer)
        outer.add(right, weight=1)

        sec = self._section(right, 'Animation Preview')
        self._anim_preview = CompositePreview(sec, size=300)
        self._anim_preview.pack(anchor='center', pady=4)

        play_row = ttk.Frame(sec)
        play_row.pack(fill=tk.X, pady=4)
        self._play_btn = ttk.Button(play_row, text='\u25b6 Play',
                                     command=self._toggle_anim_preview)
        self._play_btn.pack(side=tk.LEFT, padx=2)
        ttk.Button(play_row, text='Save All',
                    command=self._save_from_animate).pack(side=tk.LEFT, padx=6)

    # ==================================================================
    # Shared helpers
    # ==================================================================

    def _section(self, parent, title):
        lf = ttk.LabelFrame(parent, text=title, padding=6)
        lf.pack(fill=tk.X, padx=4, pady=(6, 2))
        return lf

    def _get_filtered_sprites(self) -> list[str]:
        f = self.v_sprite_filter.get().strip()
        if f and f != '(all)':
            return fetch_sprite_names_by_set(f)
        return fetch_sprite_names()

    def _refresh_sprite_dropdowns(self):
        sprites = [''] + self._get_filtered_sprites()
        self._layer_sprite_cb['values'] = sprites
        self._var_sprite_cb['values'] = fetch_sprite_names()

    def _refresh_layer_dropdowns(self):
        names = [l['layer_name'] for l in self._layers]
        self._conn_child_cb['values'] = names
        self._conn_parent_cb['values'] = names
        self._kf_layer_cb['values'] = names

    def _get_variant_choices_for_layer(self, layer_name: str) -> list[str]:
        """Return variant names available for a layer (for keyframe dropdown)."""
        return list(self._variants.get(layer_name, {}).keys())

    def _on_subtab_changed(self, event=None):
        idx = self._notebook.index(self._notebook.select())
        if idx == 1:
            self._refresh_conn_preview()
        elif idx == 2:
            self._refresh_anim_preview_static()

    def _build_layers_dict(self):
        layers = {}
        for l in self._layers:
            layers[l['layer_name']] = {
                'z_layer': l['z_layer'],
                'sprite_data': fetch_sprite(l['default_sprite']),
            }
        return layers

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
                    'SELECT name, loop, duration_ms, time_scale'
                    ' FROM composite_animations WHERE composite_name=?'
                    ' ORDER BY name', (name,)).fetchall():
                anim = {'name': r['name'], 'loop': bool(r['loop']),
                         'duration_ms': r['duration_ms'],
                         'time_scale': r['time_scale'] if r['time_scale'] is not None else 1.0,
                         'keyframes': {}}
                for kf in con.execute(
                        'SELECT layer_name, time_ms, offset_x, offset_y,'
                        ' rotation_deg, variant_name, tint_r, tint_g, tint_b,'
                        ' opacity'
                        ' FROM composite_anim_keyframes'
                        ' WHERE animation_name=?'
                        ' ORDER BY layer_name, time_ms',
                        (r['name'],)).fetchall():
                    tint = None
                    if (kf['tint_r'] is not None and kf['tint_g'] is not None
                            and kf['tint_b'] is not None):
                        tint = (kf['tint_r'], kf['tint_g'], kf['tint_b'])
                    anim['keyframes'].setdefault(
                        kf['layer_name'], []).append({
                            'time_ms': kf['time_ms'],
                            'offset_x': kf['offset_x'],
                            'offset_y': kf['offset_y'],
                            'rotation_deg': kf['rotation_deg'],
                            'variant_name': kf['variant_name'],
                            'tint': tint,
                            'opacity': kf['opacity'] if kf['opacity'] is not None else 1.0,
                        })
                self._animations.append(anim)
        finally:
            con.close()
        self._selected_layer_idx = None
        self._rebuild_all()
        self._layer_preview.load(None)
        self.refresh_dropdowns()

    def _save_from_animate(self):
        """Apply current keyframe spreadsheet, then save everything.
        If the animation name is new, create it automatically."""
        name = self.v_anim_name.get().strip()
        if not name:
            messagebox.showerror('Save', 'Enter an animation name.')
            return
        # Create animation entry if it doesn't exist yet
        existing = {a['name'] for a in self._animations}
        if name not in existing:
            try:
                dur = int(self.v_anim_dur.get())
            except ValueError:
                dur = 1000
            self._animations.append({
                'name': name, 'loop': self.v_anim_loop.get(),
                'duration_ms': dur, 'time_scale': 1.0, 'keyframes': {}})
            self._rebuild_anim_ui()
            self._anim_cb.set(name)
        self._apply_keyframes_from_tree()
        self._save_comp()

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
                    ' (name, composite_name, loop, duration_ms, time_scale)'
                    ' VALUES (?, ?, ?, ?, ?)',
                    (anim['name'], name, int(anim['loop']),
                     anim['duration_ms'], anim.get('time_scale', 1.0)))
                for ln, kfs in anim['keyframes'].items():
                    for kf in kfs:
                        tint = kf.get('tint')
                        con.execute(
                            'INSERT INTO composite_anim_keyframes'
                            ' (animation_name, layer_name, time_ms,'
                            '  offset_x, offset_y, rotation_deg,'
                            '  variant_name, tint_r, tint_g, tint_b,'
                            '  opacity)'
                            ' VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            (anim['name'], ln, kf['time_ms'],
                             kf['offset_x'], kf['offset_y'],
                             kf['rotation_deg'], kf.get('variant_name'),
                             tint[0] if tint else None,
                             tint[1] if tint else None,
                             tint[2] if tint else None,
                             kf.get('opacity', 1.0)))
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
        self._refresh_layers_preview()

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
        self._refresh_layers_preview()

    def _on_layer_sprite_change(self, event=None):
        spr = self.v_layer_sprite.get() or None
        self._layer_preview.load(spr)
        if self._selected_layer_idx is not None:
            self._layers[self._selected_layer_idx]['default_sprite'] = spr
            self._rebuild_layer_listbox()
            self._refresh_layers_preview()

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
                self._refresh_conn_preview()
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
        self._refresh_conn_preview()

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
    # Previews
    # ==================================================================

    def _refresh_layers_preview(self):
        layers = self._build_layers_dict()
        self._layers_preview.render(layers, self._connections, self._root_layer)

    def _refresh_conn_preview(self):
        layers = self._build_layers_dict()
        self._conn_preview.render(layers, self._connections, self._root_layer,
                                   show_sockets=True)

    def _refresh_anim_preview_static(self):
        layers = self._build_layers_dict()
        self._anim_preview.render(layers, self._connections, self._root_layer)

    # ==================================================================
    # Animations
    # ==================================================================

    def _rebuild_anim_ui(self):
        names = [a['name'] for a in self._animations]
        self._anim_cb['values'] = names
        if names:
            self._anim_cb.set(names[0])
            self._load_keyframes_to_tree(names[0])
        else:
            self._anim_cb.set('')
            self._kf_tree.clear()

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
            self.v_time_scale.set(str(anim.get('time_scale', 1.0)))
            self._load_keyframes_to_tree(anim['name'])
        else:
            self._kf_tree.clear()
            self.v_time_scale.set('1.0')

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
                                  'duration_ms': 1000, 'time_scale': 1.0,
                                  'keyframes': {}})
        self._rebuild_anim_ui()
        self._anim_cb.set(name)

    def _delete_anim(self):
        anim = self._get_current_anim()
        if anim:
            self._animations.remove(anim)
            self._rebuild_anim_ui()

    # -- Keyframe spreadsheet --

    def _load_keyframes_to_tree(self, anim_name):
        self._kf_tree.clear()
        anim = next((a for a in self._animations
                     if a['name'] == anim_name), None)
        if not anim or not anim['keyframes']:
            return
        for ln, kfs in sorted(anim['keyframes'].items()):
            for kf in kfs:
                tint = kf.get('tint')
                self._kf_tree.add_row((
                    ln,
                    kf['time_ms'],
                    kf['offset_x'],
                    kf['offset_y'],
                    f"{kf['rotation_deg']:.1f}",
                    kf.get('variant_name') or '',
                    tint[0] if tint else '',
                    tint[1] if tint else '',
                    tint[2] if tint else '',
                    f"{kf.get('opacity', 1.0):.2f}",
                ))

    def _add_keyframe_row(self):
        layer = self.v_kf_layer.get().strip()
        time_ms = self.v_kf_time.get().strip()
        if not layer:
            messagebox.showerror('Keyframe', 'Pick a layer.')
            return
        try:
            t = int(time_ms)
        except ValueError:
            messagebox.showerror('Keyframe', 'Time must be an integer.')
            return
        self._kf_tree.add_row((layer, t, 0, 0, '0.0', '', '', '', '', '1.00'))

    def _delete_keyframe_row(self):
        self._kf_tree.delete_selected()

    def _apply_keyframes_from_tree(self):
        """Read all rows from the treeview back into the current animation."""
        anim = self._get_current_anim()
        if not anim:
            messagebox.showwarning('Keyframe', 'Select or create an animation.')
            return
        # Update duration/loop/time_scale from fields
        try:
            anim['duration_ms'] = int(self.v_anim_dur.get())
        except ValueError:
            pass
        anim['loop'] = self.v_anim_loop.get()
        try:
            anim['time_scale'] = float(self.v_time_scale.get())
        except ValueError:
            anim['time_scale'] = 1.0

        rows = self._kf_tree.get_all_rows()
        keyframes = {}
        for row in rows:
            try:
                ln = str(row[0])
                t = int(row[1])
                ox = int(row[2])
                oy = int(row[3])
                rot = float(row[4])
                var = str(row[5]).strip() or None
                tr = int(row[6]) if str(row[6]).strip() else None
                tg = int(row[7]) if str(row[7]).strip() else None
                tb = int(row[8]) if str(row[8]).strip() else None
                tint = (tr, tg, tb) if (tr is not None and tg is not None
                                         and tb is not None) else None
                opacity = float(row[9]) if str(row[9]).strip() else 1.0
            except (ValueError, IndexError):
                continue
            keyframes.setdefault(ln, []).append({
                'time_ms': t, 'offset_x': ox, 'offset_y': oy,
                'rotation_deg': rot, 'variant_name': var,
                'tint': tint, 'opacity': opacity,
            })
        # Sort each layer's keyframes by time
        for ln in keyframes:
            keyframes[ln].sort(key=lambda k: k['time_ms'])
        anim['keyframes'] = keyframes

    # -- Animation playback --

    def _toggle_anim_preview(self):
        if self._anim_playing:
            self._stop_anim_preview()
        else:
            self._start_anim_preview()

    def _start_anim_preview(self):
        # Apply current tree state first
        self._apply_keyframes_from_tree()
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
        self._refresh_anim_preview_static()

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
        opacity_map = {}
        for ln, kfs in anim['keyframes'].items():
            ox, oy, rot, var, _tint, opacity = _interp_keyframes(kfs, t)
            offsets[ln] = (int(ox), int(oy), rot)
            opacity_map[ln] = opacity
            if var:
                sn = self._variants.get(ln, {}).get(var)
                if sn:
                    data = fetch_sprite(sn)
                    if data:
                        var_overrides[ln] = data
        layers = self._build_layers_dict()
        self._anim_preview.render(
            layers, self._connections, self._root_layer,
            variant_overrides=var_overrides, anim_offsets=offsets,
            anim_opacity=opacity_map)
        self._anim_time_ms += 33
        if not anim['loop'] and self._anim_time_ms > dur:
            self._stop_anim_preview()
            return
        self._anim_after_id = self.after(33, self._tick_anim)

    # ==================================================================
    # Rebuild all
    # ==================================================================

    def _rebuild_all(self):
        self._rebuild_layer_listbox()
        self._rebuild_connections_display()
        self._rebuild_variants_display()
        self._rebuild_anim_ui()
        self._refresh_layers_preview()
