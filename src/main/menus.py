"""
Player UI menus: Inventory, Quest Log, and the rich HUD overlay.

Each menu is a class with:
  - draw(surface, player): render to the screen
  - handle_event(event, player): respond to a pygame event, return
    one of None, 'close', or an action tuple

The main game loop opens a menu by setting an instance variable to
one of these classes and dispatching events to it instead of the
gameplay handlers.

Keybindings (when a menu is open):
  Inventory:
    Up/Down       move cursor between item slots
    Left/Right    switch between Inventory tab and Equipment tab
    E or Enter    equip/unequip selected (or eat if consumable)
    D             drop selected
    Esc / I       close

  Quest Log:
    Up/Down       move cursor between quests
    Esc / Q       close

The HUD is always visible and is NOT a menu — it's an overlay drawn
every frame.
"""
from __future__ import annotations
import pygame

from classes.stats import Stat
from classes.inventory import Equippable, Weapon, Wearable, Consumable, Stackable, Slot


# ---------------------------------------------------------------------------
# Color palette (deliberately muted; gold accent for selection/equipped)
# ---------------------------------------------------------------------------
C_BG          = (20, 20, 25)
C_PANEL       = (38, 38, 46)
C_PANEL_LIGHT = (55, 55, 65)
C_BORDER      = (90, 90, 100)
C_TEXT        = (220, 220, 220)
C_TEXT_DIM    = (140, 140, 145)
C_GOLD        = (220, 180, 60)
C_GOLD_BRIGHT = (255, 220, 100)
C_HP          = (200, 60, 60)
C_STAM        = (200, 180, 60)
C_MANA        = (60, 130, 220)
C_HUNGER      = (220, 140, 60)
C_HUNGER_LOW  = (200, 60, 60)
C_BLACK       = (0, 0, 0)


def _draw_panel(surface, rect, title=None, font=None):
    """Draw a bordered dark panel; optional title bar at top."""
    pygame.draw.rect(surface, C_BG, rect)
    pygame.draw.rect(surface, C_PANEL, rect.inflate(-4, -4))
    pygame.draw.rect(surface, C_BORDER, rect, 2)
    if title and font:
        title_surf = font.render(title, True, C_GOLD)
        surface.blit(title_surf, (rect.x + 12, rect.y + 8))
        pygame.draw.line(surface, C_BORDER,
                         (rect.x + 8, rect.y + 32),
                         (rect.right - 8, rect.y + 32), 1)


def _draw_meter(surface, x, y, w, h, ratio, fill_color, label=None,
                font=None, label_color=C_TEXT):
    """Draw a horizontal progress meter with optional label inside."""
    ratio = max(0.0, min(1.0, ratio))
    pygame.draw.rect(surface, C_BLACK, (x, y, w, h))
    pygame.draw.rect(surface, C_PANEL_LIGHT, (x + 1, y + 1, w - 2, h - 2))
    fill_w = int((w - 2) * ratio)
    if fill_w > 0:
        pygame.draw.rect(surface, fill_color, (x + 1, y + 1, fill_w, h - 2))
    pygame.draw.rect(surface, C_BORDER, (x, y, w, h), 1)
    if label and font:
        text = font.render(label, True, label_color)
        tw, th = text.get_size()
        surface.blit(text, (x + (w - tw) // 2, y + (h - th) // 2))


# ---------------------------------------------------------------------------
# Inventory Menu
# ---------------------------------------------------------------------------

class InventoryMenu:
    """Two-tab inventory: Bag (carried items) + Equipment (slot grid)."""

    TAB_BAG = 0
    TAB_EQUIP = 1

    EQUIP_LAYOUT = [
        # (slot, label, x_col, y_row) on a 3x5 grid
        (Slot.HEAD,      'Head',      1, 0),
        (Slot.NECK,      'Neck',      2, 0),
        (Slot.SHOULDERS, 'Shoulders', 0, 1),
        (Slot.CHEST,     'Chest',     1, 1),
        (Slot.BACK,      'Back',      2, 1),
        (Slot.WRISTS,    'Wrists',    0, 2),
        (Slot.HANDS,     'Hands',     1, 2),
        (Slot.WAIST,     'Waist',     2, 2),
        (Slot.LEGS,      'Legs',      1, 3),
        (Slot.FEET,      'Feet',      1, 4),
        (Slot.HAND_L,    'Off-hand',  0, 3),
        (Slot.HAND_R,    'Main hand', 2, 3),
        (Slot.RING_L,    'L. Ring',   0, 4),
        (Slot.RING_R,    'R. Ring',   2, 4),
    ]

    def __init__(self):
        self.tab = self.TAB_BAG
        self.bag_cursor = 0
        self.equip_cursor = 0   # index into EQUIP_LAYOUT
        self.font = None
        self.font_sm = None
        self.font_lg = None
        self.message = None
        self.message_until = 0

    def _ensure_fonts(self):
        if self.font is None:
            self.font = pygame.font.SysFont('arial', 18)
            self.font_sm = pygame.font.SysFont('arial', 14)
            self.font_lg = pygame.font.SysFont('arial', 24, bold=True)

    def _set_message(self, msg):
        self.message = msg
        self.message_until = pygame.time.get_ticks() + 2000

    def handle_event(self, event, player):
        """Return None, 'close', or an action tuple ('drop', item)."""
        if event.type != pygame.KEYDOWN:
            return None
        k = event.key
        if k in (pygame.K_ESCAPE, pygame.K_i):
            return 'close'

        if k in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_TAB):
            self.tab = 1 - self.tab
            return None

        items = self._bag_items(player)

        if self.tab == self.TAB_BAG:
            if k == pygame.K_UP:
                if items:
                    self.bag_cursor = (self.bag_cursor - 1) % len(items)
            elif k == pygame.K_DOWN:
                if items:
                    self.bag_cursor = (self.bag_cursor + 1) % len(items)
            elif k in (pygame.K_e, pygame.K_RETURN):
                if items:
                    item = items[self.bag_cursor]
                    self._activate_bag_item(player, item)
            elif k == pygame.K_d:
                if items:
                    item = items[self.bag_cursor]
                    self._drop_item(player, item)
        else:
            if k == pygame.K_UP:
                self.equip_cursor = (self.equip_cursor - 1) % len(self.EQUIP_LAYOUT)
            elif k == pygame.K_DOWN:
                self.equip_cursor = (self.equip_cursor + 1) % len(self.EQUIP_LAYOUT)
            elif k in (pygame.K_e, pygame.K_RETURN):
                slot = self.EQUIP_LAYOUT[self.equip_cursor][0]
                self._unequip_slot(player, slot)
        return None

    def _bag_items(self, player):
        """All items in the player's inventory that aren't equipped."""
        equipped = set(id(v) for v in player.equipment.values() if v is not None)
        return [it for it in player.inventory.items if id(it) not in equipped]

    def _activate_bag_item(self, player, item):
        """E or Enter on a bag item: equip if equippable, eat if consumable."""
        if isinstance(item, Equippable):
            if hasattr(player, 'equip') and player.equip(item):
                self._set_message(f'Equipped {item.name}')
            else:
                self._set_message(f'Cannot equip {item.name}')
        elif isinstance(item, Consumable):
            heal = getattr(item, 'heal_amount', 0)
            mana = getattr(item, 'mana_restore', 0)
            stam = getattr(item, 'stamina_restore', 0)
            if heal > 0:
                cur = player.stats.active[Stat.HP_CURR]()
                mx = player.stats.active[Stat.HP_MAX]()
                player.stats.base[Stat.HP_CURR] = min(mx, cur + heal)
            if mana > 0:
                cur = player.stats.active[Stat.CUR_MANA]()
                mx = player.stats.active[Stat.MAX_MANA]()
                player.stats.base[Stat.CUR_MANA] = min(mx, cur + mana)
            if stam > 0:
                cur = player.stats.active[Stat.CUR_STAMINA]()
                mx = player.stats.active[Stat.MAX_STAMINA]()
                player.stats.base[Stat.CUR_STAMINA] = min(mx, cur + stam)
            if getattr(item, 'is_food', False) and hasattr(player, 'eat'):
                player.eat(0.3)
            # Decrement quantity
            qty = getattr(item, 'quantity', 1)
            if qty > 1:
                item.quantity = qty - 1
            else:
                player.inventory.items.remove(item)
                if self.bag_cursor >= len(self._bag_items(player)) and self.bag_cursor > 0:
                    self.bag_cursor -= 1
            self._set_message(f'Used {item.name}')
        else:
            self._set_message(f'{item.name} cannot be used directly')

    def _drop_item(self, player, item):
        """D on a bag item: unequip if needed, drop on the current tile."""
        # Unequip if equipped
        for slot, equipped in list(player.equipment.items()):
            if equipped is item:
                player.equipment[slot] = None
        if hasattr(player, 'drop') and player.drop(item):
            self._set_message(f'Dropped {item.name}')
            if self.bag_cursor >= len(self._bag_items(player)) and self.bag_cursor > 0:
                self.bag_cursor -= 1

    def _unequip_slot(self, player, slot):
        item = player.equipment.get(slot)
        if item is None:
            self._set_message('Slot is empty')
            return
        player.equipment[slot] = None
        self._set_message(f'Unequipped {item.name}')

    def draw(self, surface, player):
        self._ensure_fonts()
        sw, sh = surface.get_size()
        # Centered panel ~80% of screen
        pw = int(sw * 0.8)
        ph = int(sh * 0.8)
        px = (sw - pw) // 2
        py = (sh - ph) // 2
        rect = pygame.Rect(px, py, pw, ph)
        _draw_panel(surface, rect, 'INVENTORY', self.font_lg)

        # Tabs
        tab_y = py + 42
        bag_color = C_GOLD if self.tab == self.TAB_BAG else C_TEXT_DIM
        eq_color = C_GOLD if self.tab == self.TAB_EQUIP else C_TEXT_DIM
        bag_text = self.font.render('[Bag]', True, bag_color)
        eq_text = self.font.render('[Equipment]', True, eq_color)
        surface.blit(bag_text, (px + 16, tab_y))
        surface.blit(eq_text, (px + 16 + bag_text.get_width() + 20, tab_y))
        hint = self.font_sm.render('Tab/<>/| switch  E/Enter use  D drop  Esc close',
                                    True, C_TEXT_DIM)
        surface.blit(hint, (px + pw - hint.get_width() - 16, tab_y + 4))

        if self.tab == self.TAB_BAG:
            self._draw_bag(surface, player, px + 16, tab_y + 32, pw - 32, ph - 100)
        else:
            self._draw_equipment(surface, player, px + 16, tab_y + 32, pw - 32, ph - 100)

        # Status message
        if self.message and pygame.time.get_ticks() < self.message_until:
            msg_surf = self.font.render(self.message, True, C_GOLD_BRIGHT)
            surface.blit(msg_surf, (px + 16, py + ph - 28))

    def _draw_bag(self, surface, player, x, y, w, h):
        items = self._bag_items(player)
        if not items:
            empty = self.font.render('(empty)', True, C_TEXT_DIM)
            surface.blit(empty, (x + 8, y + 8))
            return

        line_h = 28
        max_lines = h // line_h
        # Scroll: keep cursor in view
        scroll = max(0, self.bag_cursor - (max_lines - 1))
        visible = items[scroll:scroll + max_lines]

        for i, item in enumerate(visible):
            real_idx = scroll + i
            row_y = y + i * line_h
            row_rect = pygame.Rect(x, row_y, w, line_h - 2)
            is_cursor = (real_idx == self.bag_cursor)
            if is_cursor:
                pygame.draw.rect(surface, C_PANEL_LIGHT, row_rect)
                pygame.draw.rect(surface, C_GOLD, row_rect, 2)

            # Quantity
            qty = getattr(item, 'quantity', 1)
            qty_str = f'x{qty}' if qty > 1 else '   '
            label = self.font.render(qty_str, True, C_TEXT_DIM)
            surface.blit(label, (x + 8, row_y + 5))

            # Name
            name_color = C_TEXT
            if isinstance(item, Equippable):
                name_color = (180, 220, 220)
            elif isinstance(item, Consumable):
                name_color = (220, 200, 160)
            name = self.font.render(getattr(item, 'name', '?'),
                                     True, name_color)
            surface.blit(name, (x + 50, row_y + 5))

            # E flag if currently equipped or usable
            if isinstance(item, Equippable) and item in player.equipment.values():
                e_flag = self.font_sm.render('[E]quipped', True, C_GOLD_BRIGHT)
                surface.blit(e_flag, (x + w - e_flag.get_width() - 12, row_y + 7))
            elif isinstance(item, Consumable):
                e_flag = self.font_sm.render('[E] use', True, C_TEXT_DIM)
                surface.blit(e_flag, (x + w - e_flag.get_width() - 12, row_y + 7))
            elif isinstance(item, Equippable):
                e_flag = self.font_sm.render('[E] equip', True, C_TEXT_DIM)
                surface.blit(e_flag, (x + w - e_flag.get_width() - 12, row_y + 7))

    def _draw_equipment(self, surface, player, x, y, w, h):
        # 3x5 grid of slot squares
        cols = 3
        rows = 5
        cell_w = (w - 32) // cols
        cell_h = min(80, (h - 16) // rows)
        for i, (slot, label, cx, cy) in enumerate(self.EQUIP_LAYOUT):
            sx = x + 16 + cx * cell_w
            sy = y + cy * cell_h
            cell_rect = pygame.Rect(sx, sy, cell_w - 8, cell_h - 8)
            is_cursor = (i == self.equip_cursor)
            equipped = player.equipment.get(slot)

            pygame.draw.rect(surface, C_PANEL_LIGHT, cell_rect)
            if equipped is not None:
                # Gold border for equipped slots
                pygame.draw.rect(surface, C_GOLD, cell_rect, 3)
            else:
                pygame.draw.rect(surface, C_BORDER, cell_rect, 1)
            if is_cursor:
                pygame.draw.rect(surface, C_GOLD_BRIGHT, cell_rect.inflate(4, 4), 2)

            label_surf = self.font_sm.render(label, True, C_TEXT_DIM)
            surface.blit(label_surf, (sx + 4, sy + 2))
            if equipped is not None:
                name = self.font_sm.render(getattr(equipped, 'name', '?'),
                                            True, C_GOLD_BRIGHT)
                surface.blit(name, (sx + 4, sy + 22))
                e_flag = self.font_sm.render('[E]', True, C_GOLD_BRIGHT)
                surface.blit(e_flag, (sx + cell_w - 30, sy + 4))


# ---------------------------------------------------------------------------
# Quest Log Menu
# ---------------------------------------------------------------------------

class QuestLogMenu:
    """Lists active quests and their step status."""

    def __init__(self):
        self.cursor = 0
        self.font = None
        self.font_sm = None
        self.font_lg = None

    def _ensure_fonts(self):
        if self.font is None:
            self.font = pygame.font.SysFont('arial', 18)
            self.font_sm = pygame.font.SysFont('arial', 14)
            self.font_lg = pygame.font.SysFont('arial', 24, bold=True)

    def _quest_list(self, player):
        if not hasattr(player, 'quest_log'):
            return []
        try:
            return list(player.quest_log.get_active_quests())
        except Exception:
            return []

    def handle_event(self, event, player):
        if event.type != pygame.KEYDOWN:
            return None
        k = event.key
        if k in (pygame.K_ESCAPE, pygame.K_q):
            return 'close'
        quests = self._quest_list(player)
        if not quests:
            return None
        if k == pygame.K_UP:
            self.cursor = (self.cursor - 1) % len(quests)
        elif k == pygame.K_DOWN:
            self.cursor = (self.cursor + 1) % len(quests)
        return None

    def draw(self, surface, player):
        self._ensure_fonts()
        sw, sh = surface.get_size()
        pw = int(sw * 0.8)
        ph = int(sh * 0.8)
        px = (sw - pw) // 2
        py = (sh - ph) // 2
        rect = pygame.Rect(px, py, pw, ph)
        _draw_panel(surface, rect, 'QUEST LOG', self.font_lg)

        hint = self.font_sm.render('Up/Down navigate  Esc/Q close', True, C_TEXT_DIM)
        surface.blit(hint, (px + pw - hint.get_width() - 16, py + 12))

        quests = self._quest_list(player)
        if not quests:
            empty = self.font.render('No active quests.', True, C_TEXT_DIM)
            surface.blit(empty, (px + 24, py + 60))
            return

        # Left column: list of quest names
        list_w = pw // 3
        for i, q in enumerate(quests):
            y_row = py + 60 + i * 28
            row_rect = pygame.Rect(px + 16, y_row, list_w - 16, 26)
            if i == self.cursor:
                pygame.draw.rect(surface, C_PANEL_LIGHT, row_rect)
                pygame.draw.rect(surface, C_GOLD, row_rect, 2)
            name = getattr(q, 'name', None) or getattr(q, 'quest_name', None) or '?'
            label = self.font.render(name, True, C_TEXT)
            surface.blit(label, (px + 24, y_row + 4))

        # Right column: details of selected quest
        if 0 <= self.cursor < len(quests):
            q = quests[self.cursor]
            dx = px + list_w + 16
            dy = py + 60
            name = getattr(q, 'name', None) or getattr(q, 'quest_name', None) or '?'
            title = self.font_lg.render(name, True, C_GOLD)
            surface.blit(title, (dx, dy))
            dy += 36
            desc = getattr(q, 'description', '') or ''
            for line in self._wrap(desc, pw - list_w - 32, self.font):
                surface.blit(self.font.render(line, True, C_TEXT), (dx, dy))
                dy += 22
            dy += 12
            # Steps
            steps = getattr(q, 'steps', None) or []
            current_step = getattr(q, 'current_step', 0)
            for i, step in enumerate(steps):
                done = i < current_step
                marker = '[X]' if done else ('[ ]' if i == current_step else '   ')
                color = C_TEXT_DIM if done else C_TEXT
                step_desc = getattr(step, 'description', '') or '?'
                line = f'{marker}  {step_desc}'
                surface.blit(self.font_sm.render(line, True, color), (dx, dy))
                dy += 18

    def _wrap(self, text, max_width, font):
        words = text.split()
        lines = []
        current = ''
        for w in words:
            test = current + (' ' if current else '') + w
            if font.size(test)[0] > max_width and current:
                lines.append(current)
                current = w
            else:
                current = test
        if current:
            lines.append(current)
        return lines


# ---------------------------------------------------------------------------
# Rich HUD overlay
# ---------------------------------------------------------------------------

class HUD:
    """Always-visible meters: HP, stamina, mana, hunger, plus level/EXP/gold."""

    def __init__(self):
        self.font = None
        self.font_sm = None

    def _ensure_fonts(self):
        if self.font is None:
            self.font = pygame.font.SysFont('arial', 16, bold=True)
            self.font_sm = pygame.font.SysFont('arial', 12)

    def draw(self, surface, player):
        self._ensure_fonts()
        sw, sh = surface.get_size()

        # Bottom-left meter cluster
        x = 12
        y = sh - 110
        bar_w = 220
        bar_h = 16
        gap = 4

        # HP
        hp = player.stats.active[Stat.HP_CURR]()
        hp_max = max(1, player.stats.active[Stat.HP_MAX]())
        _draw_meter(surface, x, y, bar_w, bar_h, hp / hp_max, C_HP,
                    label=f'HP {hp}/{hp_max}', font=self.font_sm)
        y += bar_h + gap

        # Stamina
        try:
            stam = player.stats.active[Stat.CUR_STAMINA]()
            stam_max = max(1, player.stats.active[Stat.MAX_STAMINA]())
            _draw_meter(surface, x, y, bar_w, bar_h, stam / stam_max, C_STAM,
                        label=f'STA {stam}/{stam_max}', font=self.font_sm)
            y += bar_h + gap
        except Exception:
            pass

        # Mana
        try:
            mana = player.stats.active[Stat.CUR_MANA]()
            mana_max = max(1, player.stats.active[Stat.MAX_MANA]())
            _draw_meter(surface, x, y, bar_w, bar_h, mana / mana_max, C_MANA,
                        label=f'MP {mana}/{mana_max}', font=self.font_sm)
            y += bar_h + gap
        except Exception:
            pass

        # Hunger — uses creature.hunger which is -1..1
        hunger = getattr(player, 'hunger', 0.5)
        # Convert to 0..1 fill
        hunger_fill = (hunger + 1) / 2
        hunger_color = C_HUNGER_LOW if hunger < -0.2 else C_HUNGER
        hunger_label = f'HUNGER {hunger:+.2f}'
        if hunger < -0.6:
            hunger_label += ' STARVING'
        elif hunger < -0.2:
            hunger_label += ' hungry'
        _draw_meter(surface, x, y, bar_w, bar_h, hunger_fill, hunger_color,
                    label=hunger_label, font=self.font_sm)

        # Top-left: level + gold + name
        try:
            from classes.levels import exp_for_level
            lvl = player.stats.active[Stat.LVL]()
            exp = player.stats.active[Stat.EXP]()
            exp_next = exp_for_level(lvl + 1)
        except Exception:
            lvl = 1
            exp = 0
            exp_next = 1
        gold = getattr(player, 'gold', 0)
        name = getattr(player, 'name', None) or 'Player'

        info_lines = [
            (name, C_GOLD_BRIGHT),
            (f'Lv {lvl}   EXP {exp}/{exp_next}', C_TEXT),
            (f'Gold: {gold}', C_GOLD),
        ]
        ix, iy = 12, 12
        for text, color in info_lines:
            surf = self.font.render(text, True, color)
            surface.blit(surf, (ix, iy))
            iy += 20

        # Top-right: keybind hint
        hint = self.font_sm.render('I=Inventory  Q=Quests  Esc=Menu', True, C_TEXT_DIM)
        surface.blit(hint, (sw - hint.get_width() - 12, 12))
