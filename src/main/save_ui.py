"""
Modal save / load UI rendered over the game screen.

Usage in main loop:
    result = save_ui.handle_event(event)
    save_ui.draw(screen)

handle_event returns one of:
    None                   – nothing actionable yet
    ('close',)             – user cancelled
    ('saved',)             – save was written
    ('loaded', player)     – save was loaded; caller should swap player
"""

import pygame
from datetime import datetime

from main.save import (
    list_save_files, create_save_file, delete_save_file,
    list_saves, create_save, overwrite_save, load_save, delete_save,
)
from main.config import SCREEN_WIDTH, SCREEN_HEIGHT

# ---- layout -----------------------------------------------------------------
BOX_W        = 560
MAX_VISIBLE  = 10
ROW_H        = 38
FILE_ROW_H   = 40
INPUT_H      = 40
HINT_H       = 28
PADDING      = 16
DD_MAX       = 8     # max visible rows in the file dropdown

_C_BG        = (20,  20,  20)
_C_BORDER    = (110, 110, 110)
_C_TITLE     = (220, 220, 220)
_C_ROW_SEL   = (50,  80,  120)
_C_ROW_BG    = (35,  35,  35)
_C_DD_BG     = (28,  28,  28)
_C_DD_BORDER = (90,  90,  90)
_C_TEXT      = (200, 200, 200)
_C_DIM       = (100, 100, 100)
_C_INPUT_BG  = (30,  30,  30)
_C_INPUT_BD  = (140, 140, 140)
_C_RED       = (200,  60,  60)
_C_GREEN     = ( 80, 180,  80)
_C_YELLOW    = (200, 180,  60)


class SaveLoadUI:

    def __init__(self, mode: str):
        assert mode in ('save', 'load')
        self.mode  = mode

        # save-list state
        self._saves   = []
        self._sel     = -1
        self._scroll  = 0
        self._name    = ''

        # save-file dropdown state
        self._save_files      = []
        self._active_file_id  = None
        self._dropdown_open   = False
        self._dd_scroll       = 0     # scroll offset inside dropdown

        # new-file creation (shown inside the dropdown)
        self._new_file_mode = False
        self._new_file_name = ''

        # cursor blink
        self._cursor  = True
        self._blink_t = 0

        # click-hit rects populated each draw call
        self._selector_rect  = None   # the collapsed file selector button
        self._dd_rows        = []     # [(rect, file_id)]  file_id=None → "new" row
        self._dd_del_rects   = []     # [(rect, file_id)]

        self._title_font = pygame.font.SysFont(None, 52)
        self._row_font   = pygame.font.SysFont(None, 28)
        self._hint_font  = pygame.font.SysFont(None, 22)
        self._input_font = pygame.font.SysFont(None, 30)

        self._refresh_files()

    # ---- public -------------------------------------------------------------

    def handle_event(self, event) -> tuple | None:
        if event.type == pygame.KEYDOWN:
            return self._on_key(event)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            return self._on_click(event)
        return None

    def draw(self, surface):
        now = pygame.time.get_ticks()
        if now - self._blink_t > 500:
            self._cursor  = not self._cursor
            self._blink_t = now

        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        surface.blit(overlay, (0, 0))

        box_h = self._box_height()
        box_x = (SCREEN_WIDTH  - BOX_W) // 2
        box_y = (SCREEN_HEIGHT - box_h) // 2

        pygame.draw.rect(surface, _C_BG,     (box_x, box_y, BOX_W, box_h))
        pygame.draw.rect(surface, _C_BORDER, (box_x, box_y, BOX_W, box_h), 2)

        y = box_y + PADDING

        # title
        label = 'SAVE GAME' if self.mode == 'save' else 'LOAD GAME'
        title = self._title_font.render(label, True, _C_TITLE)
        surface.blit(title, (box_x + (BOX_W - title.get_width()) // 2, y))
        y += title.get_height() + PADDING

        # file selector (collapsed)
        y = self._draw_file_selector(surface, box_x, y)

        # save name input (save mode only)
        if self.mode == 'save' and not self._dropdown_open:
            y = self._draw_name_input(surface, box_x, y)

        # saves list
        if not self._dropdown_open:
            y = self._draw_saves_list(surface, box_x, y)

        # hints
        self._draw_hints(surface, box_x, box_y + box_h - HINT_H - PADDING // 2)

        # dropdown overlay (drawn last so it sits on top)
        if self._dropdown_open:
            self._draw_dropdown(surface, box_x)

    # ---- private: layout ----------------------------------------------------

    def _box_height(self):
        h  = PADDING + 52 + PADDING   # title
        h += FILE_ROW_H + PADDING     # file selector
        if not self._dropdown_open:
            if self.mode == 'save':
                h += INPUT_H + PADDING
            rows = min(len(self._saves), MAX_VISIBLE)
            h += max(rows, 1) * ROW_H + PADDING
        else:
            # reserve space so the box doesn't shrink when dropdown opens
            h += max(min(len(self._save_files) + 1, DD_MAX), 2) * ROW_H + PADDING
            if self._new_file_mode:
                h += INPUT_H + PADDING
        h += HINT_H + PADDING
        return h

    # ---- private: drawing ---------------------------------------------------

    def _draw_file_selector(self, surface, box_x, y):
        lbl = self._row_font.render('Save File:', True, _C_DIM)
        surface.blit(lbl, (box_x + PADDING, y + (FILE_ROW_H - lbl.get_height()) // 2))

        bx = box_x + PADDING + lbl.get_width() + 8
        bw = BOX_W - PADDING - (bx - box_x) - PADDING
        rect = pygame.Rect(bx, y, bw, FILE_ROW_H)
        self._selector_rect = rect

        border_col = _C_YELLOW if self._dropdown_open else _C_INPUT_BD
        pygame.draw.rect(surface, _C_INPUT_BG, rect)
        pygame.draw.rect(surface, border_col,  rect, 1)

        active_name = self._active_file_name()
        name_surf = self._input_font.render(active_name, True, _C_TEXT)
        surface.blit(name_surf, (bx + 6, y + (FILE_ROW_H - name_surf.get_height()) // 2))

        # ▼ / ▲ indicator
        arrow = '▲' if self._dropdown_open else '▼'
        arr_s = self._hint_font.render(arrow, True, _C_DIM)
        surface.blit(arr_s, (bx + bw - arr_s.get_width() - 6,
                             y + (FILE_ROW_H - arr_s.get_height()) // 2))
        return y + FILE_ROW_H + PADDING

    def _draw_dropdown(self, surface, box_x):
        """Drawn after everything else so it overlays the content below."""
        self._dd_rows      = []
        self._dd_del_rects = []

        # position just below the selector
        dy = self._selector_rect.bottom + 2
        dx = self._selector_rect.x
        dw = self._selector_rect.width

        visible_files = self._save_files[self._dd_scroll : self._dd_scroll + DD_MAX]
        new_row_h     = INPUT_H if self._new_file_mode else ROW_H
        total_h       = len(visible_files) * ROW_H + new_row_h + 4

        pygame.draw.rect(surface, _C_DD_BG,     (dx, dy, dw, total_h))
        pygame.draw.rect(surface, _C_DD_BORDER, (dx, dy, dw, total_h), 1)

        iy = dy + 2
        for file_row in visible_files:
            fid   = file_row['id']
            fname = file_row['name']
            row_rect = pygame.Rect(dx + 1, iy, dw - 2, ROW_H - 1)
            bg = _C_ROW_SEL if fid == self._active_file_id else _C_ROW_BG
            pygame.draw.rect(surface, bg, row_rect)

            name_s = self._row_font.render(fname, True, _C_TEXT)
            surface.blit(name_s, (dx + 8, iy + (ROW_H - name_s.get_height()) // 2))

            # [x] delete button (only show if more than one file)
            if len(self._save_files) > 1:
                del_s    = self._hint_font.render('[x]', True, _C_RED)
                del_x    = dx + dw - del_s.get_width() - 8
                del_rect = pygame.Rect(del_x, iy + 4, del_s.get_width(), ROW_H - 8)
                surface.blit(del_s, (del_x, iy + (ROW_H - del_s.get_height()) // 2))
                self._dd_del_rects.append((del_rect, fid))

            self._dd_rows.append((row_rect, fid))
            iy += ROW_H

        # scroll arrows inside dropdown
        if self._dd_scroll > 0:
            self._draw_small_arrow(surface, dx + dw - 10, dy + 4, up=True)
        if self._dd_scroll + DD_MAX < len(self._save_files):
            self._draw_small_arrow(surface, dx + dw - 10, iy - 10, up=False)

        # "+ New Save File" row (or inline input)
        new_rect = pygame.Rect(dx + 1, iy, dw - 2, new_row_h - 1)
        pygame.draw.rect(surface, _C_ROW_BG, new_rect)

        if self._new_file_mode:
            display = self._new_file_name + ('|' if self._cursor else ' ')
            inp_s = self._input_font.render(display, True, _C_TEXT)
            surface.blit(inp_s, (dx + 8, iy + (new_row_h - inp_s.get_height()) // 2))
            hint_s = self._hint_font.render('[Enter] create  [Esc] cancel', True, _C_DIM)
            surface.blit(hint_s, (dx + dw - hint_s.get_width() - 8,
                                  iy + (new_row_h - hint_s.get_height()) // 2))
        else:
            plus_s = self._row_font.render('+ New Save File', True, _C_GREEN)
            surface.blit(plus_s, (dx + 8, iy + (ROW_H - plus_s.get_height()) // 2))

        self._dd_rows.append((new_rect, None))  # None = "new file" action

    def _draw_name_input(self, surface, box_x, y):
        lbl = self._row_font.render('Name:', True, _C_DIM)
        surface.blit(lbl, (box_x + PADDING, y + (INPUT_H - lbl.get_height()) // 2))
        ix   = box_x + PADDING + lbl.get_width() + 8
        iw   = BOX_W - PADDING - (ix - box_x) - PADDING
        rect = pygame.Rect(ix, y, iw, INPUT_H)
        pygame.draw.rect(surface, _C_INPUT_BG, rect)
        pygame.draw.rect(surface, _C_INPUT_BD, rect, 1)
        display = self._name + ('|' if self._cursor else ' ')
        txt = self._input_font.render(display, True, _C_TEXT)
        surface.blit(txt, (ix + 6, y + (INPUT_H - txt.get_height()) // 2))
        return y + INPUT_H + PADDING

    def _draw_saves_list(self, surface, box_x, y):
        if not self._saves:
            msg = self._row_font.render('No saves in this file.', True, _C_DIM)
            surface.blit(msg, (box_x + PADDING, y + 8))
            return y + ROW_H + PADDING

        visible = self._saves[self._scroll : self._scroll + MAX_VISIBLE]
        for i, row in enumerate(visible):
            abs_i  = self._scroll + i
            is_sel = abs_i == self._sel
            rx = box_x + PADDING
            rw = BOX_W - PADDING * 2
            bg = _C_ROW_SEL if is_sel else _C_ROW_BG
            pygame.draw.rect(surface, bg, (rx, y, rw, ROW_H - 2))
            name_s = self._row_font.render(row['name'], True, _C_TEXT)
            surface.blit(name_s, (rx + 6, y + (ROW_H - name_s.get_height()) // 2))
            ts_s = self._hint_font.render(self._fmt_ts(row['saved_at']), True, _C_DIM)
            surface.blit(ts_s, (rx + rw - ts_s.get_width() - 6,
                                y + (ROW_H - ts_s.get_height()) // 2))
            y += ROW_H

        # scroll indicators
        edge = box_x + BOX_W - PADDING
        if self._scroll > 0:
            self._draw_small_arrow(surface, edge, y - ROW_H * len(visible) - 4, up=True)
        if self._scroll + MAX_VISIBLE < len(self._saves):
            self._draw_small_arrow(surface, edge, y - 4, up=False)

        return y + PADDING

    def _draw_hints(self, surface, x, y):
        if self._dropdown_open:
            hints = [('Esc', 'Close dropdown', _C_DIM)]
        elif self.mode == 'save':
            enter_lbl = 'Overwrite' if self._sel >= 0 else 'New save'
            hints = [
                ('Enter', enter_lbl, _C_GREEN),
                ('Del',   'Delete',  _C_RED),
                ('Esc',   'Back',    _C_DIM),
            ]
        else:
            hints = [
                ('Enter', 'Load',   _C_GREEN),
                ('Del',   'Delete', _C_RED),
                ('Esc',   'Back',   _C_DIM),
            ]
        cx = x + PADDING
        for key, lbl, col in hints:
            k = self._hint_font.render(f'[{key}]', True, col)
            l = self._hint_font.render(f' {lbl}   ', True, _C_DIM)
            surface.blit(k, (cx, y))
            surface.blit(l, (cx + k.get_width(), y))
            cx += k.get_width() + l.get_width()

    def _draw_small_arrow(self, surface, x, y, up: bool):
        pts = [(x-5, y+5), (x+5, y+5), (x, y)] if up else [(x-5, y), (x+5, y), (x, y+5)]
        pygame.draw.polygon(surface, _C_DIM, pts)

    @staticmethod
    def _fmt_ts(iso: str) -> str:
        try:
            return datetime.fromisoformat(iso).astimezone().strftime('%Y-%m-%d  %H:%M')
        except Exception:
            return iso

    # ---- private: input -----------------------------------------------------

    def _on_key(self, event) -> tuple | None:
        k = event.key

        # ---- dropdown / new-file mode ---------------------------------------
        if self._dropdown_open:
            if self._new_file_mode:
                if k == pygame.K_ESCAPE:
                    self._new_file_mode = False
                    self._new_file_name = ''
                elif k == pygame.K_RETURN:
                    self._commit_new_file()
                elif k == pygame.K_BACKSPACE:
                    self._new_file_name = self._new_file_name[:-1]
                elif event.unicode and event.unicode.isprintable():
                    self._new_file_name += event.unicode
            else:
                if k == pygame.K_ESCAPE:
                    self._dropdown_open = False
                elif k == pygame.K_UP:
                    self._dd_scroll = max(0, self._dd_scroll - 1)
                elif k == pygame.K_DOWN:
                    self._dd_scroll = min(max(0, len(self._save_files) - DD_MAX),
                                         self._dd_scroll + 1)
                elif k == pygame.K_RETURN:
                    # select the first visible file
                    if self._save_files:
                        self._select_file(self._save_files[self._dd_scroll]['id'])
            return None

        # ---- normal mode ----------------------------------------------------
        if k == pygame.K_ESCAPE:
            return ('close',)
        if k == pygame.K_UP:
            self._move_sel(-1)
            return None
        if k == pygame.K_DOWN:
            self._move_sel(1)
            return None
        if k == pygame.K_DELETE and self._sel >= 0:
            self._delete_selected_save()
            return None
        if k == pygame.K_RETURN:
            if self.mode == 'save':
                return self._do_save(overwrite=self._sel >= 0)
            else:
                return self._do_load()
        if self.mode == 'save':
            if k == pygame.K_BACKSPACE:
                self._name = self._name[:-1]
            elif event.unicode and event.unicode.isprintable():
                self._name += event.unicode
        return None

    def _on_click(self, event) -> tuple | None:
        mx, my = event.pos

        # ---- dropdown is open: check dropdown hits first --------------------
        if self._dropdown_open:
            # delete buttons
            for rect, fid in self._dd_del_rects:
                if rect.collidepoint(mx, my):
                    self._delete_file(fid)
                    return None
            # file rows (including "new" row at the end)
            for rect, fid in self._dd_rows:
                if rect.collidepoint(mx, my):
                    if fid is None:
                        # "+" new save file row
                        self._new_file_mode = True
                        self._new_file_name = ''
                    else:
                        self._select_file(fid)
                    return None
            # click outside dropdown → close it
            self._dropdown_open = False
            return None

        # ---- selector button ------------------------------------------------
        if self._selector_rect and self._selector_rect.collidepoint(mx, my):
            self._dropdown_open = True
            self._new_file_mode = False
            return None

        # ---- saves list -----------------------------------------------------
        box_h = self._box_height()
        box_x = (SCREEN_WIDTH  - BOX_W) // 2
        box_y = (SCREEN_HEIGHT - box_h) // 2
        list_y = box_y + PADDING + 52 + PADDING + FILE_ROW_H + PADDING
        if self.mode == 'save':
            list_y += INPUT_H + PADDING

        for i in range(min(len(self._saves), MAX_VISIBLE)):
            ry = list_y + i * ROW_H
            if ry <= my < ry + ROW_H and box_x <= mx <= box_x + BOX_W:
                abs_i = self._scroll + i
                if self._sel == abs_i and self.mode == 'load':
                    return self._do_load()
                self._sel = abs_i
                if self.mode == 'save':
                    self._name = self._saves[abs_i]['name']
                return None

        return None

    # ---- private: actions ---------------------------------------------------

    def _refresh_files(self):
        self._save_files = list_save_files()
        ids = [f['id'] for f in self._save_files]
        if self._active_file_id not in ids:
            self._active_file_id = ids[0] if ids else None
        self._refresh_saves()

    def _refresh_saves(self):
        if self._active_file_id is None:
            self._saves = []
        else:
            self._saves = list_saves(self._active_file_id)
        self._sel = min(self._sel, len(self._saves) - 1)

    def _active_file_name(self) -> str:
        for f in self._save_files:
            if f['id'] == self._active_file_id:
                return f['name']
        return '(none)'

    def _select_file(self, file_id: int):
        self._active_file_id = file_id
        self._dropdown_open  = False
        self._new_file_mode  = False
        self._sel            = -1
        self._scroll         = 0
        self._refresh_saves()

    def _commit_new_file(self):
        name = self._new_file_name.strip()
        if not name:
            return
        fid = create_save_file(name)
        self._new_file_mode = False
        self._new_file_name = ''
        self._refresh_files()
        self._select_file(fid)

    def _delete_file(self, file_id: int):
        delete_save_file(file_id)
        self._refresh_files()
        # dd_scroll may now be out of range
        self._dd_scroll = max(0, min(self._dd_scroll,
                                     len(self._save_files) - 1))

    def _move_sel(self, delta: int):
        if not self._saves:
            return
        self._sel = max(0, min(len(self._saves) - 1, self._sel + delta))
        if self._sel < self._scroll:
            self._scroll = self._sel
        elif self._sel >= self._scroll + MAX_VISIBLE:
            self._scroll = self._sel - MAX_VISIBLE + 1
        if self.mode == 'save' and self._sel >= 0:
            self._name = self._saves[self._sel]['name']

    def _do_save(self, overwrite: bool) -> tuple | None:
        name = self._name.strip()
        if not name or self._active_file_id is None:
            return None
        if overwrite and self._sel >= 0:
            overwrite_save(_current_player[0], self._saves[self._sel]['id'])
        else:
            create_save(_current_player[0], name, self._active_file_id)
        self._refresh_saves()
        return ('saved',)

    def _do_load(self) -> tuple | None:
        if self._sel < 0 or self._sel >= len(self._saves):
            return None
        player = load_save(self._saves[self._sel]['id'])
        return ('loaded', player) if player is not None else None

    def _delete_selected_save(self):
        if self._sel < 0:
            return
        delete_save(self._saves[self._sel]['id'])
        self._refresh_saves()
        if self._sel >= len(self._saves):
            self._sel = len(self._saves) - 1


# The UI needs the current player to serialise on save.
# main.py sets this before opening the UI.
_current_player: list = [None]


def set_player(player):
    _current_player[0] = player
