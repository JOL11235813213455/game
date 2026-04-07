"""Scrollable, zoomable tile map canvas for the visual map editor."""
import tkinter as tk

from editor.sprite_to_photoimage import (
    sprite_to_photoimage, invalidate_cache,
    make_default_tile_photo, make_empty_tile_photo,
)
from editor.tooltip import add_tooltip

# 3/4 perspective ratio
TILE_HEIGHT_RATIO = 0.75

# Colors
COLOR_GRID = '#ffffff'
COLOR_HOVER = '#ffffff'
COLOR_ENTRANCE = '#4b73c3'
COLOR_WALKABLE_TINT = (60, 90, 60, 255)
COLOR_BLOCKED_TINT = (40, 40, 40, 255)
COLOR_NESTED = '#b48c3c'
COLOR_LINK = '#c04040'
COLOR_SELECT = '#44aaff'
COLOR_BOUND_BLOCKED = '#ff4444'


class MapCanvas(tk.Canvas):
    """Visual tile grid with pan, zoom, painting, and viewport-only rendering."""

    BASE_TILE_SIZE = 32

    def __init__(self, parent, on_paint=None, on_inspect=None,
                 on_context_menu=None, on_selection_change=None, **kwargs):
        super().__init__(parent, bg='#1a1a1a', highlightthickness=0, **kwargs)

        self._on_paint = on_paint              # callback(x, y) on left click/drag
        self._on_inspect = on_inspect          # callback(x, y) on right click
        self._on_context_menu = on_context_menu  # callback(event, selected_tiles)
        self._on_selection_change = on_selection_change  # callback(selected_tiles)

        # Map state
        self._tiles = {}          # (x, y) → dict with tile_set row data
        self._x_min = 0
        self._x_max = 31
        self._y_min = 0
        self._y_max = 31
        self._default_template = None   # sprite_name for default fill
        self._entrance = (0, 0)

        # Display state
        self._zoom = 1.0
        self._show_grid = True
        self._pan_x = 0.0       # pixel offset for panning
        self._pan_y = 0.0
        self._drag_start = None  # for middle-click panning

        # Selection
        self._selected: set[tuple] = set()  # set of (x, y)
        self._select_anchor = None           # for shift-click range select
        self._selection_items = []           # canvas item ids for selection rects
        self._bounds_items = []              # canvas item ids for boundary lines

        # Hover
        self._hover_tile = None  # (x, y) or None
        self._hover_rect_id = None

        # Canvas item tracking
        self._tile_items = {}    # (x, y) → canvas item id
        self._grid_items = []
        self._overlay_items = []

        # Photo reference holder (prevent GC)
        self._photos = {}

        # Animation state
        self._anim_cache = {}     # animation_name → [(sprite_name, duration_ms), ...]
        self._anim_tiles = {}     # (x, y) → animation_name — tiles with active animations
        self._anim_time_ms = 0
        self._anim_after_id = None
        self._anim_interval = 100  # ms between ticks

        # Bind events
        self.bind('<Configure>', self._on_configure)
        self.bind('<Button-1>', self._on_left_click)
        self.bind('<Shift-Button-1>', self._on_shift_click)
        self.bind('<Control-Button-1>', self._on_ctrl_click)
        self.bind('<B1-Motion>', self._on_left_drag)
        self.bind('<Button-3>', self._on_right_click)
        self.bind('<Button-2>', self._on_middle_down)
        self.bind('<B2-Motion>', self._on_middle_drag)
        self.bind('<ButtonRelease-2>', self._on_middle_up)
        self.bind('<Motion>', self._on_mouse_move)
        self.bind('<Leave>', self._on_mouse_leave)
        # Scroll to pan, Ctrl+scroll to zoom
        self.bind('<Button-4>', self._on_scroll)
        self.bind('<Button-5>', self._on_scroll)
        self.bind('<MouseWheel>', self._on_scroll)
        self.bind('<Shift-Button-4>', self._on_shift_scroll)
        self.bind('<Shift-Button-5>', self._on_shift_scroll)
        self.bind('<Shift-MouseWheel>', self._on_shift_scroll)
        self.bind('<Control-Button-4>', lambda e: self._zoom_at(e, 1))
        self.bind('<Control-Button-5>', lambda e: self._zoom_at(e, -1))
        self.bind('<Control-MouseWheel>', lambda e: self._zoom_at(e, 1 if e.delta > 0 else -1))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_map_data(self, tiles: dict, x_range: tuple, y_range: tuple,
                     default_sprite: str | None, entrance: tuple):
        """Load a map's tile data for display.

        tiles: {(x,y): row_dict} from tile_sets table
        x_range: (x_min, x_max)
        y_range: (y_min, y_max)
        default_sprite: sprite_name of the default_tile_template
        entrance: (ex, ey)
        """
        self._tiles = dict(tiles)
        self._x_min, self._x_max = x_range
        self._y_min, self._y_max = y_range
        self._default_template = default_sprite
        self._entrance = entrance
        self._render_full()

    def set_tile(self, x: int, y: int, tile_data: dict | None):
        """Add or update a single tile. Pass None to remove (revert to default)."""
        if tile_data is None:
            self._tiles.pop((x, y), None)
        else:
            self._tiles[(x, y)] = tile_data
        self._render_tile(x, y)

    def set_zoom(self, level: float):
        level = max(0.25, min(4.0, level))
        if level != self._zoom:
            self._zoom = level
            invalidate_cache()
            self._photos.clear()
            self._render_full()

    def set_grid(self, show: bool):
        self._show_grid = show
        self._render_full()

    def set_entrance(self, ex: int, ey: int):
        self._entrance = (ex, ey)
        self._draw_overlays()

    def get_selected(self) -> set[tuple]:
        """Return set of (x, y) for all selected tiles."""
        return set(self._selected)

    def clear_selection(self):
        self._selected.clear()
        self._select_anchor = None
        self._draw_selection()
        self._fire_selection_change()

    def _fire_selection_change(self):
        if self._on_selection_change:
            self._on_selection_change(set(self._selected))

    def get_zoom(self):
        return self._zoom

    # ------------------------------------------------------------------
    # Coordinate conversion
    # ------------------------------------------------------------------

    @property
    def _tile_w(self):
        return int(self.BASE_TILE_SIZE * self._zoom)

    @property
    def _tile_h(self):
        return int(self.BASE_TILE_SIZE * self._zoom * TILE_HEIGHT_RATIO)

    def _screen_to_tile(self, sx, sy):
        """Convert canvas pixel coords to tile coords."""
        tx = int((sx + self._pan_x) // self._tile_w) + self._x_min
        ty = int((sy + self._pan_y) // self._tile_h) + self._y_min
        return tx, ty

    def _tile_to_screen(self, tx, ty):
        """Convert tile coords to canvas pixel coords (top-left of tile)."""
        sx = (tx - self._x_min) * self._tile_w - self._pan_x
        sy = (ty - self._y_min) * self._tile_h - self._pan_y
        return sx, sy

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_full(self):
        """Clear and redraw everything."""
        self._stop_anim_timer()
        self.delete('all')
        self._tile_items.clear()
        self._grid_items.clear()
        self._overlay_items.clear()
        self._photos.clear()
        self._anim_tiles.clear()

        tw, th = self._tile_w, self._tile_h
        canvas_w = self.winfo_width() or 800
        canvas_h = self.winfo_height() or 600

        # Determine visible range
        vx_min, vy_min = self._screen_to_tile(0, 0)
        vx_max, vy_max = self._screen_to_tile(canvas_w, canvas_h)
        # Clamp to map bounds with buffer
        vx_min = max(self._x_min, vx_min - 1)
        vy_min = max(self._y_min, vy_min - 1)
        vx_max = min(self._x_max, vx_max + 1)
        vy_max = min(self._y_max, vy_max + 1)

        # Draw tiles
        for y in range(vy_min, vy_max + 1):
            for x in range(vx_min, vx_max + 1):
                self._render_tile(x, y)

        if self._show_grid:
            self._draw_grid(vx_min, vy_min, vx_max, vy_max)

        self._draw_bounds(vx_min, vy_min, vx_max, vy_max)
        self._draw_overlays()
        self._draw_selection()
        self._start_anim_timer()

    def _render_tile(self, x: int, y: int):
        """Render a single tile at grid position (x, y)."""
        # Remove existing item
        old = self._tile_items.pop((x, y), None)
        if old:
            self.delete(old)

        sx, sy = self._tile_to_screen(x, y)
        tw, th = self._tile_w, self._tile_h

        tile_data = self._tiles.get((x, y))
        photo = None

        # Check for animation first (animation overrides static sprite)
        anim_name = self._resolve_tile_animation(tile_data)
        if anim_name:
            self._anim_tiles[(x, y)] = anim_name
            sprite = self._resolve_anim_sprite(anim_name, self._anim_time_ms)
            if sprite:
                photo = sprite_to_photoimage(sprite, tw, th)
        else:
            self._anim_tiles.pop((x, y), None)

        # Fall back to static sprite
        if photo is None and tile_data:
            sprite = tile_data.get('sprite_name') or None
            if not sprite and tile_data.get('tile_template'):
                sprite = self._resolve_template_sprite(tile_data['tile_template'])
            if sprite:
                photo = sprite_to_photoimage(sprite, tw, th)
        if photo is None and self._default_template:
            photo = sprite_to_photoimage(self._default_template, tw, th)

        if photo is None:
            # Walkability-based color fallback
            walkable = True
            if tile_data and tile_data.get('walkable') is not None:
                walkable = bool(tile_data['walkable'])
            color = COLOR_WALKABLE_TINT if walkable else COLOR_BLOCKED_TINT
            photo = make_default_tile_photo(tw, th, color)

        self._photos[(x, y)] = photo
        item = self.create_image(sx, sy, image=photo, anchor='nw')
        self._tile_items[(x, y)] = item

    def _resolve_template_sprite(self, template_key: str) -> str | None:
        """Look up a tile template's sprite_name from DB (cached)."""
        if not hasattr(self, '_template_cache'):
            self._template_cache = {}
        if template_key in self._template_cache:
            return self._template_cache[template_key]
        from editor.db import get_con
        con = get_con()
        try:
            row = con.execute(
                'SELECT sprite_name FROM tile_templates WHERE key=?',
                (template_key,)).fetchone()
            sprite = row['sprite_name'] if row else None
        finally:
            con.close()
        self._template_cache[template_key] = sprite
        return sprite

    def _draw_grid(self, vx_min, vy_min, vx_max, vy_max):
        """Draw grid lines over the visible area."""
        tw, th = self._tile_w, self._tile_h
        for y in range(vy_min, vy_max + 2):
            sy = (y - self._y_min) * th - self._pan_y
            sx0 = (vx_min - self._x_min) * tw - self._pan_x
            sx1 = (vx_max + 1 - self._x_min) * tw - self._pan_x
            item = self.create_line(sx0, sy, sx1, sy, fill=COLOR_GRID,
                                    width=1, stipple='gray50')
            self._grid_items.append(item)
        for x in range(vx_min, vx_max + 2):
            sx = (x - self._x_min) * tw - self._pan_x
            sy0 = (vy_min - self._y_min) * th - self._pan_y
            sy1 = (vy_max + 1 - self._y_min) * th - self._pan_y
            item = self.create_line(sx, sy0, sx, sy1, fill=COLOR_GRID,
                                    width=1, stipple='gray50')
            self._grid_items.append(item)

    def _draw_overlays(self):
        """Draw entrance marker and other indicators."""
        for item in self._overlay_items:
            self.delete(item)
        self._overlay_items.clear()

        tw, th = self._tile_w, self._tile_h
        ex, ey = self._entrance

        # Entrance marker
        sx, sy = self._tile_to_screen(ex, ey)
        pad = max(2, tw // 8)
        item = self.create_rectangle(
            sx + pad, sy + pad, sx + tw - pad, sy + th - pad,
            outline=COLOR_ENTRANCE, width=2, dash=(4, 2))
        self._overlay_items.append(item)
        label = self.create_text(
            sx + tw // 2, sy + th // 2, text='E',
            fill=COLOR_ENTRANCE, font=('Courier', max(8, tw // 4), 'bold'))
        self._overlay_items.append(label)

        # Warp indicators
        for (x, y), td in self._tiles.items():
            if td.get('linked_map'):
                sx, sy = self._tile_to_screen(x, y)
                item = self.create_rectangle(
                    sx + 1, sy + 1, sx + tw - 1, sy + th - 1,
                    outline=COLOR_LINK, width=2)
                self._overlay_items.append(item)
            if td.get('nested_map'):
                sx, sy = self._tile_to_screen(x, y)
                item = self.create_rectangle(
                    sx + 1, sy + 1, sx + tw - 1, sy + th - 1,
                    outline=COLOR_NESTED, width=2)
                self._overlay_items.append(item)

    def _draw_selection(self):
        """Draw selection highlight on selected tiles."""
        for item in self._selection_items:
            self.delete(item)
        self._selection_items.clear()

        tw, th = self._tile_w, self._tile_h
        for (x, y) in self._selected:
            sx, sy = self._tile_to_screen(x, y)
            item = self.create_rectangle(
                sx + 1, sy + 1, sx + tw - 1, sy + th - 1,
                outline=COLOR_SELECT, width=2, dash=(3, 2))
            self._selection_items.append(item)

    def _draw_bounds(self, vx_min, vy_min, vx_max, vy_max):
        """Draw dim red highlights on tile edges where bounds are blocked."""
        for item in self._bounds_items:
            self.delete(item)
        self._bounds_items.clear()

        tw, th = self._tile_w, self._tile_h
        # Edge thickness as fraction of tile size
        edge_t = max(2, tw // 6)
        # Edge rects: direction → (x0_frac, y0_frac, x1_frac, y1_frac)
        # These define thin rectangles along each edge
        edge_rects = {
            'n':  (0, 0, tw, edge_t),
            's':  (0, th - edge_t, tw, th),
            'e':  (tw - edge_t, 0, tw, th),
            'w':  (0, 0, edge_t, th),
        }
        # Corner rects: small squares at corners
        corner_rects = {
            'ne': (tw - edge_t, 0, tw, edge_t),
            'nw': (0, 0, edge_t, edge_t),
            'se': (tw - edge_t, th - edge_t, tw, th),
            'sw': (0, th - edge_t, edge_t, th),
        }

        for y in range(vy_min, vy_max + 1):
            for x in range(vx_min, vx_max + 1):
                td = self._tiles.get((x, y))
                if not td:
                    continue
                # Bounds come from tile_sets data only
                bounds = {}
                for d in ('n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'):
                    val = td.get(f'bounds_{d}')
                    if val is not None:
                        bounds[d] = (val != 0)

                sx, sy = self._tile_to_screen(x, y)

                # Draw blocked edges as dim red filled rectangles
                for d, (x0, y0, x1, y1) in edge_rects.items():
                    if not bounds.get(d, True):
                        item = self.create_rectangle(
                            sx + x0, sy + y0, sx + x1, sy + y1,
                            fill=COLOR_BOUND_BLOCKED, outline='',
                            stipple='gray50')
                        self._bounds_items.append(item)

                # Draw blocked corners as dim red filled squares
                for d, (x0, y0, x1, y1) in corner_rects.items():
                    if not bounds.get(d, True):
                        item = self.create_rectangle(
                            sx + x0, sy + y0, sx + x1, sy + y1,
                            fill=COLOR_BOUND_BLOCKED, outline='',
                            stipple='gray50')
                        self._bounds_items.append(item)

    def _resolve_template_bounds(self, template_key: str | None) -> dict:
        """Get bounds from a tile template as a dict of {direction: bool}."""
        if not template_key:
            return {}
        if not hasattr(self, '_bounds_cache'):
            self._bounds_cache = {}
        if template_key in self._bounds_cache:
            return dict(self._bounds_cache[template_key])
        from editor.db import get_con
        con = get_con()
        try:
            row = con.execute(
                'SELECT bounds_n, bounds_s, bounds_e, bounds_w, '
                'bounds_ne, bounds_nw, bounds_se, bounds_sw '
                'FROM tile_templates WHERE key=?',
                (template_key,)).fetchone()
            if row:
                result = {}
                for d in ('n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'):
                    val = row[f'bounds_{d}']
                    result[d] = (val != 0) if val is not None else True
                self._bounds_cache[template_key] = result
                return dict(result)
        finally:
            con.close()
        return {}

    # ------------------------------------------------------------------
    # Tile Animations
    # ------------------------------------------------------------------

    def _resolve_tile_animation(self, tile_data: dict | None) -> str | None:
        """Get the animation_name for a tile (direct or via template)."""
        if not tile_data:
            return None
        anim = tile_data.get('animation_name')
        if anim:
            return anim
        tmpl = tile_data.get('tile_template')
        if tmpl:
            return self._resolve_template_animation(tmpl)
        return None

    def _resolve_template_animation(self, template_key: str) -> str | None:
        """Look up a tile template's animation_name from DB (cached)."""
        if not hasattr(self, '_tmpl_anim_cache'):
            self._tmpl_anim_cache = {}
        if template_key in self._tmpl_anim_cache:
            return self._tmpl_anim_cache[template_key]
        from editor.db import get_con
        con = get_con()
        try:
            row = con.execute(
                'SELECT animation_name FROM tile_templates WHERE key=?',
                (template_key,)).fetchone()
            anim = row['animation_name'] if row else None
        finally:
            con.close()
        self._tmpl_anim_cache[template_key] = anim
        return anim

    def _get_anim_frames(self, anim_name: str) -> list:
        """Fetch animation frames from DB (cached).
        Returns [(sprite_name, duration_ms), ...]."""
        if anim_name in self._anim_cache:
            return self._anim_cache[anim_name]
        from editor.db import get_con
        con = get_con()
        try:
            rows = con.execute(
                'SELECT sprite_name, duration_ms FROM animation_frames'
                ' WHERE animation_name=? ORDER BY frame_index',
                (anim_name,)).fetchall()
            frames = [(r['sprite_name'], r['duration_ms']) for r in rows]
        finally:
            con.close()
        self._anim_cache[anim_name] = frames
        return frames

    def _resolve_anim_sprite(self, anim_name: str, time_ms: int) -> str | None:
        """Return the sprite_name for the current animation frame at time_ms."""
        frames = self._get_anim_frames(anim_name)
        if not frames:
            return None
        total = sum(d for _, d in frames)
        if total <= 0:
            return frames[0][0]
        t = time_ms % total
        acc = 0
        for sprite, dur in frames:
            acc += dur
            if t < acc:
                return sprite
        return frames[-1][0]

    def _start_anim_timer(self):
        """Start the animation tick loop if there are animated tiles."""
        if self._anim_after_id is not None:
            return  # already running
        if self._anim_tiles:
            self._anim_time_ms = 0
            self._tick_anim()

    def _stop_anim_timer(self):
        """Stop the animation tick loop."""
        if self._anim_after_id is not None:
            self.after_cancel(self._anim_after_id)
            self._anim_after_id = None

    def _tick_anim(self):
        """Advance animation time and update animated tile images."""
        self._anim_time_ms += self._anim_interval
        tw, th = self._tile_w, self._tile_h
        for (x, y), anim_name in self._anim_tiles.items():
            item = self._tile_items.get((x, y))
            if item is None:
                continue
            sprite = self._resolve_anim_sprite(anim_name, self._anim_time_ms)
            if sprite:
                photo = sprite_to_photoimage(sprite, tw, th)
                if photo:
                    self._photos[(x, y)] = photo
                    self.itemconfig(item, image=photo)
        self._anim_after_id = self.after(self._anim_interval, self._tick_anim)

    # ------------------------------------------------------------------
    # Hover
    # ------------------------------------------------------------------

    def _on_mouse_move(self, event):
        tx, ty = self._screen_to_tile(event.x, event.y)
        if (tx, ty) != self._hover_tile:
            self._hover_tile = (tx, ty)
            if self._hover_rect_id:
                self.delete(self._hover_rect_id)
            if self._x_min <= tx <= self._x_max and self._y_min <= ty <= self._y_max:
                sx, sy = self._tile_to_screen(tx, ty)
                self._hover_rect_id = self.create_rectangle(
                    sx, sy, sx + self._tile_w, sy + self._tile_h,
                    outline=COLOR_HOVER, width=2)

    def _on_mouse_leave(self, event):
        self._hover_tile = None
        if self._hover_rect_id:
            self.delete(self._hover_rect_id)
            self._hover_rect_id = None

    # ------------------------------------------------------------------
    # Click / Drag / Selection
    # ------------------------------------------------------------------

    def _in_bounds(self, tx, ty):
        return self._x_min <= tx <= self._x_max and self._y_min <= ty <= self._y_max

    def _on_left_click(self, event):
        tx, ty = self._screen_to_tile(event.x, event.y)
        if not self._in_bounds(tx, ty):
            return
        # Clear selection and paint
        self._selected.clear()
        self._select_anchor = (tx, ty)
        self._draw_selection()
        self._fire_selection_change()
        if self._on_paint:
            self._on_paint(tx, ty)

    def _on_shift_click(self, event):
        """Range select from anchor to clicked tile."""
        tx, ty = self._screen_to_tile(event.x, event.y)
        if not self._in_bounds(tx, ty):
            return
        if self._select_anchor is None:
            self._select_anchor = (tx, ty)
        ax, ay = self._select_anchor
        x0, x1 = min(ax, tx), max(ax, tx)
        y0, y1 = min(ay, ty), max(ay, ty)
        self._selected = {(x, y) for x in range(x0, x1 + 1)
                          for y in range(y0, y1 + 1)}
        self._draw_selection()
        self._fire_selection_change()

    def _on_ctrl_click(self, event):
        """Toggle a single tile in the selection."""
        tx, ty = self._screen_to_tile(event.x, event.y)
        if not self._in_bounds(tx, ty):
            return
        if (tx, ty) in self._selected:
            self._selected.discard((tx, ty))
        else:
            self._selected.add((tx, ty))
        self._select_anchor = (tx, ty)
        self._draw_selection()
        self._fire_selection_change()

    def _on_left_drag(self, event):
        tx, ty = self._screen_to_tile(event.x, event.y)
        if self._on_paint and self._in_bounds(tx, ty):
            self._on_paint(tx, ty)

    def _on_right_click(self, event):
        tx, ty = self._screen_to_tile(event.x, event.y)
        if not self._in_bounds(tx, ty):
            return
        # If right-clicking outside selection, select just this tile
        if (tx, ty) not in self._selected:
            self._selected = {(tx, ty)}
            self._select_anchor = (tx, ty)
            self._draw_selection()
            self._fire_selection_change()
        # Fire context menu callback with selected tiles
        if self._on_context_menu:
            self._on_context_menu(event, self._selected)
        elif self._on_inspect:
            self._on_inspect(tx, ty)

    # ------------------------------------------------------------------
    # Pan (middle click drag)
    # ------------------------------------------------------------------

    def _on_middle_down(self, event):
        self._drag_start = (event.x, event.y, self._pan_x, self._pan_y)

    def _on_middle_drag(self, event):
        if self._drag_start is None:
            return
        sx, sy, px, py = self._drag_start
        self._pan_x = px - (event.x - sx)
        self._pan_y = py - (event.y - sy)
        self._render_full()

    def _on_middle_up(self, event):
        self._drag_start = None

    # ------------------------------------------------------------------
    # Scroll to pan
    # ------------------------------------------------------------------

    def _scroll_direction(self, event):
        """Return -1 or +1 for scroll direction."""
        if event.num == 4:
            return -1
        if event.num == 5:
            return 1
        return -1 if event.delta > 0 else 1

    def _on_scroll(self, event):
        """Scroll vertically to pan."""
        d = self._scroll_direction(event)
        self._pan_y += d * self._tile_h * 2
        self._render_full()

    def _on_shift_scroll(self, event):
        """Shift+scroll to pan horizontally."""
        d = self._scroll_direction(event)
        self._pan_x += d * self._tile_w * 2
        self._render_full()

    # ------------------------------------------------------------------
    # Zoom
    # ------------------------------------------------------------------

    def _zoom_at(self, event, direction):
        old_zoom = self._zoom
        step = 0.25
        new_zoom = max(0.25, min(4.0, self._zoom + direction * step))
        if new_zoom == old_zoom:
            return

        # Zoom centered on mouse position
        tx, ty = self._screen_to_tile(event.x, event.y)
        self._zoom = new_zoom
        invalidate_cache()
        self._photos.clear()
        if hasattr(self, '_template_cache'):
            self._template_cache.clear()
        if hasattr(self, '_tmpl_anim_cache'):
            self._tmpl_anim_cache.clear()
        self._anim_cache.clear()

        # Adjust pan so the tile under cursor stays put
        new_sx = (tx - self._x_min) * self._tile_w - event.x
        new_sy = (ty - self._y_min) * self._tile_h - event.y
        self._pan_x = new_sx
        self._pan_y = new_sy

        self._render_full()

    # ------------------------------------------------------------------
    # Resize
    # ------------------------------------------------------------------

    def _on_configure(self, event):
        if event.width > 1 and event.height > 1:
            self._render_full()
