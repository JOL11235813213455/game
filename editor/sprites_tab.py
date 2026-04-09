import copy
import json
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox, colorchooser

from editor.db import get_con, fetch_sprite_sets
from editor.constants import GRID_COLS, GRID_ROWS, CELL_SIZE, MAX_PALETTE
from editor.tooltip import add_tooltip


class SpritesTab(ttk.Frame):
    """Full sprite editor with pixel grid, palette, fill tool, and image import."""

    TRANSPARENT_CHAR = '.'
    CHECKER_A        = '#cccccc'
    CHECKER_B        = '#aaaaaa'
    CELL_PX          = CELL_SIZE
    MAX_HISTORY      = 10

    def __init__(self, parent, on_sprites_changed=None):
        super().__init__(parent)
        self.on_sprites_changed = on_sprites_changed

        self._cols: int               = GRID_COLS
        self._rows: int               = GRID_ROWS
        self._pixels: list[list[str]] = self._empty_pixels()
        self._palette: dict[str, str] = {}
        self._selected_char: str | None = None
        self._palette_widgets: list[dict] = []
        self._action_point: tuple[int, int] | None = None
        self._action_point_mode: bool              = False

        # undo — stores (pixels_deepcopy, cols, rows)
        self._history: list = []

        # selection tool state
        self._select_mode: bool       = False
        self._sel_rect: tuple | None  = None   # (r1,c1,r2,c2) finalized selection
        self._sel_start: tuple | None = None   # rubber-band anchor
        self._sel_end: tuple | None   = None   # rubber-band cursor
        self._sel_moving: bool        = False  # dragging selection to move it
        self._sel_move_anchor: tuple | None = None
        self._sel_buffer: list | None = None   # floating pixels during move
        self._sel_buf_r: int          = 0      # buffer top-left row
        self._sel_buf_c: int          = 0      # buffer top-left col

        # clipboard for cut / paste
        self._clipboard: list | None  = None   # list[list[str]]

        self._build_ui()
        self.refresh_list()

    # ---- layout -----------------------------------------------------------

    def _build_ui(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        left = ttk.Frame(pane, width=160)
        pane.add(left, weight=0)

        ttk.Label(left, text='Sprites').pack(anchor='w')
        list_frame = ttk.Frame(left)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.listbox = tk.Listbox(list_frame, exportselection=False, width=20)
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.bind('<<ListboxSelect>>', self._on_select)
        self.listbox.bind('<Shift-Delete>', lambda e: self._delete())

        btn_row = ttk.Frame(left)
        btn_row.pack(fill=tk.X, pady=4)
        new_btn = ttk.Button(btn_row, text='New', command=self._new)
        new_btn.pack(side=tk.LEFT, padx=2)
        add_tooltip(new_btn, 'Clear form to create a new sprite')
        save_btn = ttk.Button(btn_row, text='Save', command=self._save)
        save_btn.pack(side=tk.LEFT, padx=2)
        add_tooltip(save_btn, 'Save the current sprite to the database')
        del_btn = ttk.Button(btn_row, text='Delete', command=self._delete)
        del_btn.pack(side=tk.LEFT, padx=2)
        add_tooltip(del_btn, 'Delete the selected sprite')

        right_outer = ttk.Frame(pane)
        pane.add(right_outer, weight=1)

        right_canvas = tk.Canvas(right_outer, highlightthickness=0)
        right_sb = ttk.Scrollbar(right_outer, orient=tk.VERTICAL, command=right_canvas.yview)
        right_canvas.configure(yscrollcommand=right_sb.set)
        right_sb.pack(side=tk.RIGHT, fill=tk.Y)
        right_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right = ttk.Frame(right_canvas)
        self._right_win = right_canvas.create_window((0, 0), window=right, anchor='nw')

        def _on_right_configure(e):
            right_canvas.configure(scrollregion=right_canvas.bbox('all'))
        def _on_rc_configure(e):
            right_canvas.itemconfig(self._right_win, width=e.width)

        right.bind('<Configure>', _on_right_configure)
        right_canvas.bind('<Configure>', _on_rc_configure)

        def _on_mousewheel(e):
            right_canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units')
        right_canvas.bind_all('<MouseWheel>', _on_mousewheel)

        name_row = ttk.Frame(right)
        name_row.pack(fill=tk.X, padx=6, pady=6)
        ttk.Label(name_row, text='Name:').pack(side=tk.LEFT)
        self.v_name = tk.StringVar()
        name_entry = ttk.Entry(name_row, textvariable=self.v_name, width=24)
        name_entry.pack(side=tk.LEFT, padx=6)
        add_tooltip(name_entry, 'Unique identifier for this sprite')

        set_row = ttk.Frame(right)
        set_row.pack(fill=tk.X, padx=6, pady=2)
        ttk.Label(set_row, text='Set:').pack(side=tk.LEFT)
        self.v_sprite_set = tk.StringVar()
        self._sprite_set_cb = ttk.Combobox(
            set_row, textvariable=self.v_sprite_set,
            values=[''] + fetch_sprite_sets(), width=20)
        self._sprite_set_cb.pack(side=tk.LEFT, padx=6)
        add_tooltip(self._sprite_set_cb,
                    'Optional grouping tag (e.g. "human_male", "goblin") — '
                    'type a new name or pick an existing one')

        size_row = ttk.Frame(right)
        size_row.pack(fill=tk.X, padx=6, pady=2)
        ttk.Label(size_row, text='Size:').pack(side=tk.LEFT)
        self.v_width  = tk.StringVar(value=str(GRID_COLS))
        self.v_height = tk.StringVar(value=str(GRID_ROWS))
        w_spin = ttk.Spinbox(size_row, from_=1, to=128, textvariable=self.v_width,  width=5)
        w_spin.pack(side=tk.LEFT, padx=(4, 0))
        add_tooltip(w_spin, 'Sprite width in pixels (1-128)')
        ttk.Label(size_row, text='\u00d7').pack(side=tk.LEFT, padx=2)
        h_spin = ttk.Spinbox(size_row, from_=1, to=128, textvariable=self.v_height, width=5)
        h_spin.pack(side=tk.LEFT, padx=(0, 4))
        add_tooltip(h_spin, 'Sprite height in pixels (1-128)')
        apply_btn = ttk.Button(size_row, text='Apply', command=self._apply_size)
        apply_btn.pack(side=tk.LEFT, padx=4)
        add_tooltip(apply_btn, 'Resize the pixel grid to the specified dimensions')
        import_btn = ttk.Button(size_row, text='Import Image', command=self._import_image)
        import_btn.pack(side=tk.LEFT, padx=4)
        add_tooltip(import_btn, 'Import an image file and quantize to palette')

        editor_row = ttk.Frame(right)
        editor_row.pack(fill=tk.X, padx=6, pady=4)

        grid_w = self.CELL_PX * self._cols
        grid_h = self.CELL_PX * self._rows
        self.grid_canvas = tk.Canvas(
            editor_row, width=grid_w, height=grid_h, bg='white',
            cursor='crosshair', takefocus=True)
        self.grid_canvas.pack(side=tk.LEFT, anchor='n')

        self.grid_canvas.bind('<Button-1>',         self._on_grid_click)
        self.grid_canvas.bind('<B1-Motion>',         self._on_grid_drag)
        self.grid_canvas.bind('<ButtonRelease-1>',   self._on_grid_release)
        self.grid_canvas.bind('<Button-3>',          self._on_grid_erase_click)
        self.grid_canvas.bind('<B3-Motion>',         self._on_grid_erase)
        self.grid_canvas.bind('<Control-z>',         self._undo)
        self.grid_canvas.bind('<Control-x>',         self._cut)
        self.grid_canvas.bind('<Control-v>',         self._paste)

        self._draw_grid()

        palette_outer = ttk.Frame(editor_row)
        palette_outer.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0), anchor='n')

        ttk.Label(palette_outer, text='Palette', font=('TkDefaultFont', 10, 'bold')).pack(anchor='w')

        self._selected_label = ttk.Label(palette_outer, text='Selected: (none)', foreground='#555')
        self._selected_label.pack(anchor='w', pady=(0, 4))

        self.palette_frame = ttk.Frame(palette_outer)
        self.palette_frame.pack(fill=tk.X)

        add_pal_btn = ttk.Button(palette_outer, text='+ Add Palette Entry',
                                command=self._add_palette_entry)
        add_pal_btn.pack(anchor='w', pady=4)
        add_tooltip(add_pal_btn, 'Add a new color to the palette')

        ttk.Separator(palette_outer, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

        ttk.Label(palette_outer, text='Tools', font=('TkDefaultFont', 10, 'bold')).pack(anchor='w')

        # Row 1: paint tools
        tools_row1 = ttk.Frame(palette_outer)
        tools_row1.pack(fill=tk.X, pady=(2, 0))

        self._fill_mode = False
        self._fill_btn = ttk.Button(tools_row1, text='Fill', command=self._toggle_fill_mode)
        self._fill_btn.pack(side=tk.LEFT, padx=(0, 4))
        add_tooltip(self._fill_btn, 'Flood-fill a region with the selected colour (L-click)\nor erase a region (R-click)')

        self._ap_btn = ttk.Button(tools_row1, text='Action Point', command=self._toggle_action_point_mode)
        self._ap_btn.pack(side=tk.LEFT, padx=(0, 4))
        add_tooltip(self._ap_btn, 'Set the anchor point used to align this sprite\non its tile (e.g. feet position)')

        self._sel_btn = ttk.Button(tools_row1, text='Select', command=self._toggle_select_mode)
        self._sel_btn.pack(side=tk.LEFT, padx=(0, 4))
        add_tooltip(self._sel_btn,
                    'Drag to select a rectangular region.\n'
                    'Drag selection to move it.\n'
                    'Ctrl+X cut  |  Ctrl+V paste  |  Ctrl+Z undo')

        # Row 2: utility tools
        tools_row2 = ttk.Frame(palette_outer)
        tools_row2.pack(fill=tk.X, pady=(2, 0))

        lasso_btn = ttk.Button(tools_row2, text='Lasso', command=self._lasso)
        lasso_btn.pack(side=tk.LEFT, padx=(0, 4))
        add_tooltip(lasso_btn, 'Auto-crop: trim transparent border to fit content')

        self._eraser_mode = False
        self._eraser_btn = ttk.Button(tools_row2, text='Eraser', command=self._toggle_eraser_mode)
        self._eraser_btn.pack(side=tk.LEFT, padx=(0, 4))
        add_tooltip(self._eraser_btn, 'Circle eraser: click/drag to erase pixels\nwithin the specified radius')

        ef = ttk.Frame(tools_row2)
        ef.pack(side=tk.LEFT)
        ttk.Label(ef, text='r:').pack(side=tk.LEFT)
        self.v_eraser_radius = tk.StringVar(value='2')
        er_spin = ttk.Spinbox(ef, from_=1, to=20, textvariable=self.v_eraser_radius, width=3)
        er_spin.pack(side=tk.LEFT)
        add_tooltip(er_spin, 'Eraser radius in pixels')

        # Row 3: flip
        tools_row3 = ttk.Frame(palette_outer)
        tools_row3.pack(fill=tk.X, pady=(2, 0))

        fh_btn = ttk.Button(tools_row3, text='Flip H', command=self._flip_h)
        fh_btn.pack(side=tk.LEFT, padx=(0, 4))
        add_tooltip(fh_btn, 'Mirror the sprite horizontally (left \u2194 right)')
        fv_btn = ttk.Button(tools_row3, text='Flip V', command=self._flip_v)
        fv_btn.pack(side=tk.LEFT, padx=(0, 4))
        add_tooltip(fv_btn, 'Mirror the sprite vertically (top \u2194 bottom)')

        # Row 4: rotate
        tools_row4 = ttk.Frame(palette_outer)
        tools_row4.pack(fill=tk.X, pady=(2, 0))

        cw_btn = ttk.Button(tools_row4, text='Rot CW', command=self._rotate_cw)
        cw_btn.pack(side=tk.LEFT, padx=(0, 4))
        add_tooltip(cw_btn, 'Rotate the sprite 90\u00b0 clockwise')
        ccw_btn = ttk.Button(tools_row4, text='Rot CCW', command=self._rotate_ccw)
        ccw_btn.pack(side=tk.LEFT, padx=(0, 4))
        add_tooltip(ccw_btn, 'Rotate the sprite 90\u00b0 counter-clockwise')

        self._ap_label = ttk.Label(palette_outer, text='Action point: (none)', foreground='#555')
        self._ap_label.pack(anchor='w', pady=(2, 0))

    # ---- pixel grid -------------------------------------------------------

    def _empty_pixels(self) -> list[list[str]]:
        return [['.' for _ in range(self._cols)] for _ in range(self._rows)]

    def _draw_grid(self):
        self.grid_canvas.delete('all')
        cp = self.CELL_PX
        for row in range(self._rows):
            for col in range(self._cols):
                x0 = col * cp
                y0 = row * cp
                x1 = x0 + cp
                y1 = y0 + cp
                ch = self._pixels[row][col]
                if ch == self.TRANSPARENT_CHAR or ch not in self._palette:
                    color = self.CHECKER_A if (row + col) % 2 == 0 else self.CHECKER_B
                else:
                    color = self._palette[ch]
                tag = f'cell_{row}_{col}'
                self.grid_canvas.create_rectangle(
                    x0, y0, x1, y1, fill=color, outline='#888888', width=1, tags=tag)

        # draw floating buffer on top (during selection move)
        if self._sel_buffer is not None:
            for br, row_data in enumerate(self._sel_buffer):
                for bc, ch in enumerate(row_data):
                    r = self._sel_buf_r + br
                    c = self._sel_buf_c + bc
                    if r < 0 or r >= self._rows or c < 0 or c >= self._cols:
                        continue
                    x0, y0 = c * cp, r * cp
                    if ch == self.TRANSPARENT_CHAR or ch not in self._palette:
                        color = self.CHECKER_A if (r + c) % 2 == 0 else self.CHECKER_B
                    else:
                        color = self._palette[ch]
                    self.grid_canvas.create_rectangle(
                        x0, y0, x0 + cp, y0 + cp,
                        fill=color, outline='#888888', width=1)

        # draw selection overlay
        rect = None
        if self._sel_start is not None and self._sel_end is not None:
            r1 = min(self._sel_start[0], self._sel_end[0])
            r2 = max(self._sel_start[0], self._sel_end[0])
            c1 = min(self._sel_start[1], self._sel_end[1])
            c2 = max(self._sel_start[1], self._sel_end[1])
            rect = (r1, c1, r2, c2)
        elif self._sel_rect is not None:
            rect = self._sel_rect
        if rect is not None:
            r1, c1, r2, c2 = rect
            self.grid_canvas.create_rectangle(
                c1 * cp, r1 * cp, (c2 + 1) * cp, (r2 + 1) * cp,
                outline='#0088ff', width=2, dash=(4, 2), fill='')

        # draw action point
        if self._action_point is not None:
            ar, ac = self._action_point
            x0 = ac * cp
            y0 = ar * cp
            x1 = x0 + cp
            y1 = y0 + cp
            self.grid_canvas.create_line(x0, y0, x1, y1, fill='#ff2222', width=2, tags='ap')
            self.grid_canvas.create_line(x1, y0, x0, y1, fill='#ff2222', width=2, tags='ap')

    def _cell_from_event(self, event) -> tuple[int, int] | None:
        col = event.x // self.CELL_PX
        row = event.y // self.CELL_PX
        if 0 <= row < self._rows and 0 <= col < self._cols:
            return row, col
        return None

    def _paint_cell(self, row: int, col: int):
        if self._selected_char is None:
            return
        self._pixels[row][col] = self._selected_char
        cp = self.CELL_PX
        x0 = col * cp
        y0 = row * cp
        x1 = x0 + cp
        y1 = y0 + cp
        tag = f'cell_{row}_{col}'
        self.grid_canvas.delete(tag)
        ch = self._selected_char
        if ch == self.TRANSPARENT_CHAR or ch not in self._palette:
            color = self.CHECKER_A if (row + col) % 2 == 0 else self.CHECKER_B
        else:
            color = self._palette[ch]
        self.grid_canvas.create_rectangle(
            x0, y0, x1, y1, fill=color, outline='#888888', width=1, tags=tag)

    def _erase_cell_canvas(self, r: int, c: int):
        """Erase one cell in _pixels and update the canvas rectangle."""
        self._pixels[r][c] = self.TRANSPARENT_CHAR
        cp = self.CELL_PX
        x0, y0 = c * cp, r * cp
        tag = f'cell_{r}_{c}'
        self.grid_canvas.delete(tag)
        color = self.CHECKER_A if (r + c) % 2 == 0 else self.CHECKER_B
        self.grid_canvas.create_rectangle(
            x0, y0, x0 + cp, y0 + cp,
            fill=color, outline='#888888', width=1, tags=tag)

    def _erase_circle(self, center_row: int, center_col: int):
        try:
            radius = int(self.v_eraser_radius.get())
        except ValueError:
            radius = 2
        for r in range(max(0, center_row - radius), min(self._rows, center_row + radius + 1)):
            for c in range(max(0, center_col - radius), min(self._cols, center_col + radius + 1)):
                if (r - center_row) ** 2 + (c - center_col) ** 2 <= radius ** 2:
                    self._erase_cell_canvas(r, c)

    # ---- mouse event handlers ---------------------------------------------

    def _on_grid_click(self, event):
        self.grid_canvas.focus_set()
        cell = self._cell_from_event(event)
        if cell is None:
            return

        if self._select_mode:
            if self._sel_rect is not None and self._point_in_sel(cell):
                # start moving the existing selection
                self._push_history()
                self._start_sel_move(cell)
            else:
                # start a new rubber-band selection
                if self._sel_buffer is not None:
                    self._finish_sel_move()
                self._sel_start = cell
                self._sel_end   = cell
                self._sel_rect  = None
                self._draw_grid()
            return

        self._push_history()
        if self._action_point_mode:
            self._action_point = cell
            self._update_ap_label()
            self._draw_grid()
        elif self._eraser_mode:
            self._erase_circle(*cell)
        elif self._fill_mode:
            self._flood_fill(*cell)
        else:
            self._paint_cell(*cell)

    def _on_grid_drag(self, event):
        cell = self._cell_from_event(event)
        if cell is None:
            return

        if self._select_mode:
            if self._sel_moving:
                self._update_sel_move(cell)
            else:
                self._sel_end = cell
                self._draw_grid()
            return

        if self._eraser_mode:
            self._erase_circle(*cell)
        elif not self._action_point_mode and not self._fill_mode:
            self._paint_cell(*cell)

    def _on_grid_release(self, event):
        if self._select_mode:
            if self._sel_moving:
                self._finish_sel_move()
            elif self._sel_start is not None:
                r1 = min(self._sel_start[0], self._sel_end[0])
                r2 = max(self._sel_start[0], self._sel_end[0])
                c1 = min(self._sel_start[1], self._sel_end[1])
                c2 = max(self._sel_start[1], self._sel_end[1])
                self._sel_rect  = (r1, c1, r2, c2)
                self._sel_start = None
                self._sel_end   = None
                self._draw_grid()

    def _on_grid_erase_click(self, event):
        self.grid_canvas.focus_set()
        cell = self._cell_from_event(event)
        if cell is None:
            return
        self._push_history()
        if self._eraser_mode:
            self._erase_circle(*cell)
        elif self._fill_mode:
            self._flood_fill_erase(*cell)
        else:
            self._erase_cell_canvas(*cell)

    def _on_grid_erase(self, event):
        cell = self._cell_from_event(event)
        if cell is None:
            return
        if self._eraser_mode:
            self._erase_circle(*cell)
        elif self._fill_mode:
            self._flood_fill_erase(*cell)
        else:
            self._erase_cell_canvas(*cell)

    # ---- undo -------------------------------------------------------------

    def _push_history(self):
        self._history.append((copy.deepcopy(self._pixels), self._cols, self._rows))
        if len(self._history) > self.MAX_HISTORY:
            self._history.pop(0)

    def _undo(self, event=None):
        if not self._history:
            return
        pixels, cols, rows = self._history.pop()
        self._pixels = pixels
        self._cols   = cols
        self._rows   = rows
        self.v_width.set(str(cols))
        self.v_height.set(str(rows))
        cp = self.CELL_PX
        self.grid_canvas.configure(width=cols * cp, height=rows * cp)
        self._sel_rect   = None
        self._sel_start  = None
        self._sel_buffer = None
        self._sel_moving = False
        self._draw_grid()

    # ---- selection tool ---------------------------------------------------

    def _point_in_sel(self, cell) -> bool:
        if self._sel_rect is None:
            return False
        r1, c1, r2, c2 = self._sel_rect
        r, c = cell
        return r1 <= r <= r2 and c1 <= c <= c2

    def _start_sel_move(self, cell):
        self._sel_moving     = True
        self._sel_move_anchor = cell
        r1, c1, r2, c2 = self._sel_rect
        self._sel_buffer = [
            [self._pixels[r][c] for c in range(c1, c2 + 1)]
            for r in range(r1, r2 + 1)
        ]
        self._sel_buf_r = r1
        self._sel_buf_c = c1
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                self._pixels[r][c] = self.TRANSPARENT_CHAR
        self._draw_grid()

    def _update_sel_move(self, cell):
        dr = cell[0] - self._sel_move_anchor[0]
        dc = cell[1] - self._sel_move_anchor[1]
        if dr == 0 and dc == 0:
            return
        self._sel_move_anchor = cell
        r1, c1, r2, c2 = self._sel_rect
        buf_h = r2 - r1 + 1
        buf_w = c2 - c1 + 1
        new_r = max(0, min(self._sel_buf_r + dr, self._rows - buf_h))
        new_c = max(0, min(self._sel_buf_c + dc, self._cols - buf_w))
        self._sel_buf_r = new_r
        self._sel_buf_c = new_c
        self._sel_rect  = (new_r, new_c, new_r + buf_h - 1, new_c + buf_w - 1)
        self._draw_grid()

    def _finish_sel_move(self):
        if self._sel_buffer is None:
            return
        r1, c1, r2, c2 = self._sel_rect
        for br, r in enumerate(range(r1, r2 + 1)):
            for bc, c in enumerate(range(c1, c2 + 1)):
                px = self._sel_buffer[br][bc]
                if px != self.TRANSPARENT_CHAR:
                    self._pixels[r][c] = px
        self._sel_moving = False
        self._sel_buffer = None
        self._draw_grid()

    # ---- cut / paste ------------------------------------------------------

    def _cut(self, event=None):
        if self._sel_rect is None:
            return
        self._push_history()
        r1, c1, r2, c2 = self._sel_rect
        self._clipboard = [
            [self._pixels[r][c] for c in range(c1, c2 + 1)]
            for r in range(r1, r2 + 1)
        ]
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                self._pixels[r][c] = self.TRANSPARENT_CHAR
        self._sel_rect = None
        self._draw_grid()

    def _paste(self, event=None):
        if self._clipboard is None:
            return
        self._push_history()
        buf_h = len(self._clipboard)
        buf_w = len(self._clipboard[0]) if buf_h else 0
        for br in range(buf_h):
            for bc in range(buf_w):
                r = br
                c = bc
                if r < self._rows and c < self._cols:
                    px = self._clipboard[br][bc]
                    if px != self.TRANSPARENT_CHAR:
                        self._pixels[r][c] = px
        # select pasted region so user can move it right away
        self._sel_rect = (0, 0,
                          min(buf_h - 1, self._rows - 1),
                          min(buf_w - 1, self._cols - 1))
        # switch to select mode automatically
        if not self._select_mode:
            self._toggle_select_mode()
        self._draw_grid()

    # ---- palette ----------------------------------------------------------

    def _rebuild_palette_widgets(self):
        for w in self._palette_widgets:
            w['frame'].destroy()
        self._palette_widgets = []
        for char, color in list(self._palette.items()):
            self._create_palette_row(char, color)

    def _create_palette_row(self, char: str, color: str):
        frame = ttk.Frame(self.palette_frame)
        frame.pack(fill=tk.X, pady=2)

        select_btn = tk.Button(frame, text='  ', relief=tk.RAISED, width=2, bg='#e0e0e0')
        select_btn.pack(side=tk.LEFT, padx=(0, 4))
        add_tooltip(select_btn, 'Select this color for drawing')

        char_var = tk.StringVar(value=char)
        char_entry = ttk.Entry(frame, textvariable=char_var, width=3)
        char_entry.pack(side=tk.LEFT, padx=(0, 4))
        add_tooltip(char_entry, 'Single character used in the pixel grid')

        swatch = tk.Button(frame, bg=color, width=3, relief=tk.RAISED)
        swatch.pack(side=tk.LEFT, padx=(0, 4))
        add_tooltip(swatch, 'Click to change this palette color')

        del_btn = ttk.Button(frame, text='\u2715', width=2)
        del_btn.pack(side=tk.LEFT, padx=(0, 4))
        add_tooltip(del_btn, 'Remove this color from the palette')

        entry = {
            'frame': frame, 'char_var': char_var, 'color': color,
            'select_btn': select_btn, 'swatch': swatch, 'char': char,
        }
        self._palette_widgets.append(entry)

        def on_select(e=None, w=entry):
            self._select_palette_entry(w)

        def on_char_change(*args, w=entry, cv=char_var):
            new_char = cv.get()
            if len(new_char) == 1 and new_char != '.':
                old_char = w['char']
                if new_char != old_char and new_char not in self._palette:
                    self._palette[new_char] = self._palette.pop(old_char)
                    for r in range(self._rows):
                        for c in range(self._cols):
                            if self._pixels[r][c] == old_char:
                                self._pixels[r][c] = new_char
                    w['char'] = new_char
                    if self._selected_char == old_char:
                        self._selected_char = new_char
                        self._update_selected_label()

        def on_swatch_click(e=None, w=entry):
            initial = w['color']
            result = colorchooser.askcolor(color=initial, title='Choose color')
            if result and result[1]:
                new_color = result[1]
                w['color'] = new_color
                w['swatch'].configure(bg=new_color)
                ch = w['char']
                self._palette[ch] = new_color
                self._draw_grid()

        def on_delete(e=None, w=entry):
            ch = w['char']
            self._palette.pop(ch, None)
            if self._selected_char == ch:
                self._selected_char = None
                self._update_selected_label()
            for r in range(self._rows):
                for c in range(self._cols):
                    if self._pixels[r][c] == ch:
                        self._pixels[r][c] = '.'
            self._draw_grid()
            self._rebuild_palette_widgets()

        select_btn.configure(command=on_select)
        char_var.trace_add('write', on_char_change)
        swatch.configure(command=on_swatch_click)
        del_btn.configure(command=on_delete)
        frame.bind('<Button-1>', on_select)

    def _select_palette_entry(self, entry: dict):
        self._selected_char = entry['char']
        self._update_selected_label()
        for w in self._palette_widgets:
            w['select_btn'].configure(relief=tk.RAISED, bg='#e0e0e0')
        entry['select_btn'].configure(relief=tk.SUNKEN, bg='#a0c8f0')

    def _update_selected_label(self):
        if self._selected_char is None:
            self._selected_label.configure(text='Selected: (none)')
        elif self._selected_char == self.TRANSPARENT_CHAR:
            self._selected_label.configure(text='Selected: . (transparent)')
        else:
            color = self._palette.get(self._selected_char, '?')
            self._selected_label.configure(text=f'Selected: {self._selected_char}  {color}')

    def _add_palette_entry(self):
        if len(self._palette) >= MAX_PALETTE:
            messagebox.showwarning('Palette', f'Maximum {MAX_PALETTE} palette entries.')
            return
        used = set(self._palette.keys()) | {self.TRANSPARENT_CHAR}
        new_char = None
        for ch in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789':
            if ch not in used:
                new_char = ch
                break
        if new_char is None:
            messagebox.showwarning('Palette', 'No available single characters.')
            return
        self._palette[new_char] = '#ffffff'
        self._create_palette_row(new_char, '#ffffff')

    # ---- size, tools, action point ----------------------------------------

    def _apply_size(self):
        try:
            new_cols = int(self.v_width.get())
            new_rows = int(self.v_height.get())
        except ValueError:
            messagebox.showerror('Size', 'Width and height must be integers.')
            return
        if not (1 <= new_cols <= 128 and 1 <= new_rows <= 128):
            messagebox.showerror('Size', 'Width/height must be between 1 and 128.')
            return
        self._push_history()
        self._resize_grid(new_cols, new_rows)

    def _import_image(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title='Import Image',
            filetypes=[
                ('Image files', '*.png *.bmp *.jpg *.jpeg *.gif *.tga *.webp'),
                ('All files', '*.*'),
            ],
        )
        if not path:
            return
        try:
            from PIL import Image
        except ImportError:
            messagebox.showerror('Import', 'Pillow is required: pip install Pillow')
            return
        try:
            img = Image.open(path).convert('RGBA')
        except Exception as e:
            messagebox.showerror('Import', f'Failed to open image:\n{e}')
            return

        ALPHA_THRESHOLD = 128
        CHARS = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        target_w = self._cols
        target_h = self._rows
        img = img.resize((target_w, target_h), Image.LANCZOS)

        alpha_mask = []
        raw = img.load()
        for y in range(target_h):
            row = []
            for x in range(target_w):
                row.append(raw[x, y][3] >= ALPHA_THRESHOLD)
            alpha_mask.append(row)

        rgb_img = img.convert('RGB')
        quantized = rgb_img.quantize(colors=MAX_PALETTE, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)
        pal_data = quantized.getpalette()
        q_pixels = quantized.load()

        new_palette = {}
        idx_to_char = {}
        used_indices = set()
        for y in range(target_h):
            for x in range(target_w):
                if alpha_mask[y][x]:
                    used_indices.add(q_pixels[x, y])

        for ci, idx in enumerate(sorted(used_indices)):
            if ci >= len(CHARS):
                break
            ch = CHARS[ci]
            r = pal_data[idx * 3]
            g = pal_data[idx * 3 + 1]
            b = pal_data[idx * 3 + 2]
            new_palette[ch] = f'#{r:02x}{g:02x}{b:02x}'
            idx_to_char[idx] = ch

        new_pixels = []
        for y in range(target_h):
            row = []
            for x in range(target_w):
                if not alpha_mask[y][x]:
                    row.append('.')
                else:
                    idx = q_pixels[x, y]
                    row.append(idx_to_char.get(idx, '.'))
            new_pixels.append(row)

        self._push_history()
        self._palette = new_palette
        self._pixels = new_pixels
        self._selected_char = None
        self._rebuild_palette_widgets()
        self._update_selected_label()
        self._draw_grid()

    def _resize_grid(self, new_cols: int, new_rows: int):
        new_pixels = []
        for row in range(new_rows):
            if row < len(self._pixels):
                old_row = self._pixels[row][:new_cols]
                while len(old_row) < new_cols:
                    old_row.append('.')
            else:
                old_row = ['.'] * new_cols
            new_pixels.append(old_row)
        self._pixels = new_pixels
        self._cols   = new_cols
        self._rows   = new_rows
        if self._action_point is not None:
            ar, ac = self._action_point
            if ar >= new_rows or ac >= new_cols:
                self._action_point = None
                self._update_ap_label()
        self._sel_rect  = None
        self._sel_start = None
        cp = self.CELL_PX
        self.grid_canvas.configure(width=new_cols * cp, height=new_rows * cp)
        self._draw_grid()

    def _deactivate_modes(self, except_mode=None):
        if except_mode != 'action_point' and self._action_point_mode:
            self._action_point_mode = False
            self._ap_btn.configure(text='Action Point')
        if except_mode != 'fill' and self._fill_mode:
            self._fill_mode = False
            self._fill_btn.configure(text='Fill')
        if except_mode != 'eraser' and self._eraser_mode:
            self._eraser_mode = False
            self._eraser_btn.configure(text='Eraser')
        if except_mode != 'select' and self._select_mode:
            self._select_mode = False
            self._sel_btn.configure(text='Select')
            self._sel_rect   = None
            self._sel_start  = None
            self._sel_buffer = None
            self._sel_moving = False
        if except_mode is None:
            self.grid_canvas.configure(cursor='crosshair')

    def _toggle_action_point_mode(self):
        self._deactivate_modes(except_mode='action_point')
        self._action_point_mode = not self._action_point_mode
        if self._action_point_mode:
            self._ap_btn.configure(text='[Action Point]')
            self.grid_canvas.configure(cursor='tcross')
        else:
            self._ap_btn.configure(text='Action Point')
            self.grid_canvas.configure(cursor='crosshair')

    def _toggle_fill_mode(self):
        self._deactivate_modes(except_mode='fill')
        self._fill_mode = not self._fill_mode
        if self._fill_mode:
            self._fill_btn.configure(text='[Fill]')
            self.grid_canvas.configure(cursor='spraycan')
        else:
            self._fill_btn.configure(text='Fill')
            self.grid_canvas.configure(cursor='crosshair')

    def _toggle_eraser_mode(self):
        self._deactivate_modes(except_mode='eraser')
        self._eraser_mode = not self._eraser_mode
        if self._eraser_mode:
            self._eraser_btn.configure(text='[Eraser]')
            self.grid_canvas.configure(cursor='circle')
        else:
            self._eraser_btn.configure(text='Eraser')
            self.grid_canvas.configure(cursor='crosshair')

    def _toggle_select_mode(self):
        self._deactivate_modes(except_mode='select')
        self._select_mode = not self._select_mode
        if self._select_mode:
            self._sel_btn.configure(text='[Select]')
            self.grid_canvas.configure(cursor='sizing')
        else:
            self._sel_btn.configure(text='Select')
            self.grid_canvas.configure(cursor='crosshair')
            if self._sel_buffer is not None:
                self._finish_sel_move()
            self._sel_rect  = None
            self._sel_start = None
            self._draw_grid()

    def _flood_fill(self, row: int, col: int):
        if self._selected_char is None:
            return
        target = self._pixels[row][col]
        replacement = self._selected_char
        if target == replacement:
            return
        stack = [(row, col)]
        visited = set()
        while stack:
            r, c = stack.pop()
            if (r, c) in visited:
                continue
            if r < 0 or r >= self._rows or c < 0 or c >= self._cols:
                continue
            if self._pixels[r][c] != target:
                continue
            visited.add((r, c))
            self._pixels[r][c] = replacement
            stack.extend([(r-1, c), (r+1, c), (r, c-1), (r, c+1)])
        self._draw_grid()

    def _flood_fill_erase(self, row: int, col: int):
        target = self._pixels[row][col]
        if target == self.TRANSPARENT_CHAR:
            return
        stack = [(row, col)]
        visited = set()
        while stack:
            r, c = stack.pop()
            if (r, c) in visited:
                continue
            if r < 0 or r >= self._rows or c < 0 or c >= self._cols:
                continue
            if self._pixels[r][c] != target:
                continue
            visited.add((r, c))
            self._pixels[r][c] = self.TRANSPARENT_CHAR
            stack.extend([(r-1, c), (r+1, c), (r, c-1), (r, c+1)])
        self._draw_grid()

    def _lasso(self):
        min_r = min_c = None
        max_r = max_c = None
        for r in range(self._rows):
            for c in range(self._cols):
                if self._pixels[r][c] != self.TRANSPARENT_CHAR:
                    if min_r is None:
                        min_r = max_r = r
                        min_c = max_c = c
                    else:
                        min_r = min(min_r, r)
                        max_r = max(max_r, r)
                        min_c = min(min_c, c)
                        max_c = max(max_c, c)
        if min_r is None:
            messagebox.showinfo('Lasso', 'Nothing drawn — canvas is empty.')
            return
        new_rows = max_r - min_r + 1
        new_cols = max_c - min_c + 1
        self._push_history()
        new_pixels = []
        for r in range(min_r, max_r + 1):
            new_pixels.append(self._pixels[r][min_c:max_c + 1])
        self._pixels = new_pixels
        self._cols = new_cols
        self._rows = new_rows
        self.v_width.set(str(new_cols))
        self.v_height.set(str(new_rows))
        if self._action_point is not None:
            ar, ac = self._action_point
            ar -= min_r
            ac -= min_c
            if 0 <= ar < new_rows and 0 <= ac < new_cols:
                self._action_point = (ar, ac)
            else:
                self._action_point = None
            self._update_ap_label()
        self._sel_rect  = None
        self._sel_start = None
        cp = self.CELL_PX
        self.grid_canvas.configure(width=new_cols * cp, height=new_rows * cp)
        self._draw_grid()

    def _flip_h(self):
        self._push_history()
        for row in self._pixels:
            row.reverse()
        if self._action_point is not None:
            ar, ac = self._action_point
            self._action_point = (ar, self._cols - 1 - ac)
            self._update_ap_label()
        self._draw_grid()

    def _flip_v(self):
        self._push_history()
        self._pixels.reverse()
        if self._action_point is not None:
            ar, ac = self._action_point
            self._action_point = (self._rows - 1 - ar, ac)
            self._update_ap_label()
        self._draw_grid()

    def _rotate_cw(self):
        self._push_history()
        old_rows, old_cols = self._rows, self._cols
        new_pixels = []
        for c in range(old_cols):
            new_pixels.append([self._pixels[old_rows - 1 - r][c] for r in range(old_rows)])
        self._pixels = new_pixels
        self._rows, self._cols = old_cols, old_rows
        self.v_width.set(str(self._cols))
        self.v_height.set(str(self._rows))
        if self._action_point is not None:
            ar, ac = self._action_point
            self._action_point = (ac, old_rows - 1 - ar)
            self._update_ap_label()
        cp = self.CELL_PX
        self.grid_canvas.configure(width=self._cols * cp, height=self._rows * cp)
        self._draw_grid()

    def _rotate_ccw(self):
        self._push_history()
        old_rows, old_cols = self._rows, self._cols
        new_pixels = []
        for c in range(old_cols - 1, -1, -1):
            new_pixels.append([self._pixels[r][c] for r in range(old_rows)])
        self._pixels = new_pixels
        self._rows, self._cols = old_cols, old_rows
        self.v_width.set(str(self._cols))
        self.v_height.set(str(self._rows))
        if self._action_point is not None:
            ar, ac = self._action_point
            self._action_point = (old_cols - 1 - ac, ar)
            self._update_ap_label()
        cp = self.CELL_PX
        self.grid_canvas.configure(width=self._cols * cp, height=self._rows * cp)
        self._draw_grid()

    def _update_ap_label(self):
        if self._action_point is None:
            self._ap_label.configure(text='Action point: (none)')
        else:
            ar, ac = self._action_point
            self._ap_label.configure(text=f'Action point: x={ac}, y={ar}')

    # ---- list management --------------------------------------------------

    def refresh_list(self):
        con = get_con()
        try:
            rows = con.execute('SELECT name FROM sprites ORDER BY name').fetchall()
        finally:
            con.close()
        self.listbox.delete(0, tk.END)
        for r in rows:
            self.listbox.insert(tk.END, r['name'])

    def _clear_editor(self):
        self.v_name.set('')
        self.v_sprite_set.set('')
        self._cols = GRID_COLS
        self._rows = GRID_ROWS
        self.v_width.set(str(GRID_COLS))
        self.v_height.set(str(GRID_ROWS))
        self._pixels = self._empty_pixels()
        self._action_point      = None
        self._action_point_mode = False
        self._fill_mode         = False
        self._eraser_mode       = False
        self._select_mode       = False
        self._sel_rect          = None
        self._sel_start         = None
        self._sel_buffer        = None
        self._sel_moving        = False
        self._history           = []
        self._ap_btn.configure(text='Action Point')
        self._fill_btn.configure(text='Fill')
        self._eraser_btn.configure(text='Eraser')
        self._sel_btn.configure(text='Select')
        self.grid_canvas.configure(
            width=self._cols * self.CELL_PX,
            height=self._rows * self.CELL_PX,
            cursor='crosshair',
        )
        self._palette = {}
        self._selected_char = None
        self._update_selected_label()
        self._update_ap_label()
        self._draw_grid()
        self._rebuild_palette_widgets()

    def _load_sprite(self, name: str):
        con = get_con()
        try:
            row = con.execute(
                'SELECT name, palette, pixels, width, height,'
                ' action_point_x, action_point_y, sprite_set'
                ' FROM sprites WHERE name=?', (name,)
            ).fetchone()
            if row is None:
                return
        finally:
            con.close()

        self.v_name.set(row['name'])
        self.v_sprite_set.set(row['sprite_set'] or '')
        raw_palette = json.loads(row['palette'])
        self._palette = {}
        for char, val in raw_palette.items():
            if isinstance(val, (list, tuple)):
                r2, g2, b2 = val
                self._palette[char] = f'#{r2:02x}{g2:02x}{b2:02x}'
            else:
                self._palette[char] = val

        raw_pixels = json.loads(row['pixels'])
        self._pixels = [list(r) for r in raw_pixels]

        stored_cols = row['width']  or (len(self._pixels[0]) if self._pixels else GRID_COLS)
        stored_rows = row['height'] or len(self._pixels) or GRID_ROWS
        self._cols = stored_cols
        self._rows = stored_rows
        self.v_width.set(str(self._cols))
        self.v_height.set(str(self._rows))

        while len(self._pixels) < self._rows:
            self._pixels.append(['.'] * self._cols)
        self._pixels = self._pixels[:self._rows]
        for i, r in enumerate(self._pixels):
            while len(r) < self._cols:
                r.append('.')
            self._pixels[i] = r[:self._cols]

        apx = row['action_point_x']
        apy = row['action_point_y']
        self._action_point = (apy, apx) if apx is not None and apy is not None else None
        self._update_ap_label()

        self._history  = []
        self._sel_rect = None
        cp = self.CELL_PX
        self.grid_canvas.configure(width=self._cols * cp, height=self._rows * cp)

        self._selected_char = None
        self._update_selected_label()
        self._draw_grid()
        self._rebuild_palette_widgets()

    def _on_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        self._load_sprite(self.listbox.get(sel[0]))

    def _new(self):
        self.listbox.selection_clear(0, tk.END)
        self._clear_editor()

    def _save(self):
        name = self.v_name.get().strip()
        if not name:
            messagebox.showerror('Validation', 'Sprite name is required.')
            return

        palette_out = {}
        for char, hexcolor in self._palette.items():
            hexcolor = hexcolor.lstrip('#')
            r = int(hexcolor[0:2], 16)
            g = int(hexcolor[2:4], 16)
            b = int(hexcolor[4:6], 16)
            palette_out[char] = [r, g, b]

        pixels_out = [''.join(row) for row in self._pixels]

        ap_x = self._action_point[1] if self._action_point else None
        ap_y = self._action_point[0] if self._action_point else None
        sprite_set = self.v_sprite_set.get().strip() or None

        con = get_con()
        try:
            con.execute(
                '''INSERT INTO sprites (name, palette, pixels, width, height,
                                        action_point_x, action_point_y, sprite_set)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                   palette=excluded.palette,
                   pixels=excluded.pixels,
                   width=excluded.width,
                   height=excluded.height,
                   action_point_x=excluded.action_point_x,
                   action_point_y=excluded.action_point_y,
                   sprite_set=excluded.sprite_set
                ''',
                (name, json.dumps(palette_out), json.dumps(pixels_out),
                 self._cols, self._rows, ap_x, ap_y, sprite_set)
            )
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()

        self.refresh_list()
        self._sprite_set_cb['values'] = [''] + fetch_sprite_sets()
        items = list(self.listbox.get(0, tk.END))
        if name in items:
            idx = items.index(name)
            self.listbox.selection_set(idx)
            self.listbox.see(idx)

        if self.on_sprites_changed:
            self.on_sprites_changed()

    def _delete(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning('Delete', 'Select a sprite first.')
            return
        name = self.listbox.get(sel[0])
        if not messagebox.askyesno('Delete', f'Delete sprite "{name}"?'):
            return
        con = get_con()
        try:
            con.execute('DELETE FROM sprites WHERE name=?', (name,))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()
        self._clear_editor()
        if self.on_sprites_changed:
            self.on_sprites_changed()
