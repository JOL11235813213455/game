"""
Unified stat system for all creatures.

Stats are organized as a nested dictionary with four layers:
  base     – raw base stats (STR, PER, VIT, etc.) and tracking values (CHP, EXP)
  derived  – computed from base stats via formulas (MHP, SIGHT_RANGE, etc.)
  mods     – list of active modifiers [{source, stat, amount, stackable}, ...]
  active   – dict of callables; active[stat]() returns the final evaluated value

All stat computation, leveling, and opposing-stat resolution lives here.
"""
from __future__ import annotations
from enum import Enum
import random

from classes.levels import level_from_exp, cumulative_exp


# ---------------------------------------------------------------------------
# Stat enum
# ---------------------------------------------------------------------------

class Stat(Enum):
    # ---- Base stats ----
    STR  = 'strength'
    PER  = 'perception'
    VIT  = 'vitality'
    INT  = 'intelligence'
    CHR  = 'charisma'
    LCK  = 'luck'
    AGL  = 'agility'

    # ---- Progression (stored in base) ----
    LVL  = 'level'
    EXP  = 'cumulative xp'
    HIT_DICE = 'hit dice'

    # ---- Tracking (stored in base, not derived) ----
    HP_CURR = 'health'
    CUR_STAMINA = 'stamina'
    CUR_MANA    = 'mana'

    # ---- Derived: Combat ----
    HP_MAX     = 'max health'
    MELEE_DMG  = 'melee damage'
    RANGED_DMG = 'ranged damage'
    MAGIC_DMG  = 'magic damage'
    ATK_SPEED  = 'attack speed'
    ACCURACY   = 'accuracy'
    CRIT_CHANCE = 'critical chance'
    CRIT_DMG   = 'critical damage'
    DODGE      = 'dodge'
    ARMOR      = 'armor'
    BLOCK      = 'block'

    # ---- Derived: Movement / Exploration ----
    MOVE_SPEED   = 'move speed'
    SIGHT_RANGE  = 'sight range'
    HEARING_RANGE = 'hearing range'
    STEALTH      = 'stealth'
    DETECTION    = 'detection'
    CARRY_WEIGHT = 'carry weight'

    # ---- Derived: Resources ----
    MAX_STAMINA  = 'max stamina'
    MAX_MANA     = 'max mana'
    MANA_REGEN   = 'mana regen'
    HP_REGEN_DELAY = 'hp regen delay'
    STAM_REGEN   = 'stamina regen'

    # ---- Derived: Resistance ----
    POISON_RESIST  = 'poison resist'
    DISEASE_RESIST = 'disease resist'
    MAGIC_RESIST   = 'magic resist'
    STAGGER_RESIST = 'stagger resist'
    FEAR_RESIST    = 'fear resist'

    # ---- Derived: Social ----
    BARTER_MOD      = 'barter modifier'
    NPC_DISPOSITION = 'npc disposition'
    COMPANION_LIMIT = 'companion limit'
    PERSUASION      = 'persuasion'
    INTIMIDATION    = 'intimidation'
    DECEPTION       = 'deception'

    # ---- Derived: Loot / Craft ----
    LOOT_QUALITY  = 'loot quality'
    CRAFT_QUALITY = 'craft quality'
    DURABILITY_USE = 'durability use'

    # ---- Derived: Progression ----
    XP_MOD = 'xp modifier'


# ---------------------------------------------------------------------------
# Stat groupings
# ---------------------------------------------------------------------------

BASE_STATS = frozenset({
    Stat.STR, Stat.PER, Stat.VIT, Stat.INT, Stat.CHR, Stat.LCK, Stat.AGL,
})

PROGRESSION_STATS = frozenset({Stat.LVL, Stat.EXP, Stat.HIT_DICE})

TRACKING_STATS = frozenset({Stat.HP_CURR, Stat.CUR_STAMINA, Stat.CUR_MANA})

# Everything stored directly in stats.base
BASE_LAYER_STATS = BASE_STATS | PROGRESSION_STATS | TRACKING_STATS

DERIVED_STATS = frozenset(s for s in Stat if s not in BASE_LAYER_STATS)


# ---------------------------------------------------------------------------
# Derived stat formulas
# ---------------------------------------------------------------------------
# Each formula receives a getter callable:  g(stat) -> int
# that returns the active base stat value (base + mods for that stat).
#
# All formulas use D&D-style modifiers: (stat - 10) // 2
# 10 is neutral (±0), 20 is +5, 1 is -5.

def _dmod(val):
    """D&D-style modifier: (stat - 10) // 2."""
    return (val - 10) // 2

def _hp_max(g):
    # HD rolls are stored as mods and added on top
    lvl = g(Stat.LVL)
    return (lvl + 1) * (_dmod(g(Stat.VIT)) + 1)

def _melee_dmg(g):
    return _dmod(g(Stat.STR))

def _ranged_dmg(g):
    return _dmod(g(Stat.PER))

def _magic_dmg(g):
    return _dmod(g(Stat.INT))

def _atk_speed(_g):
    return 0  # DEPRECATED: stamina system replaces attack speed

def _accuracy(g):
    return _dmod(g(Stat.PER))

def _crit_chance(g):
    return _dmod(g(Stat.LCK))

def _crit_dmg(g):
    return 150 + max(_dmod(g(Stat.STR)), _dmod(g(Stat.PER))) * 5  # percent

def _dodge(g):
    return _dmod(g(Stat.AGL))

def _armor(_g):
    return 0  # derived entirely from items (and natural armor for some classes)

def _block(g):
    return _dmod(g(Stat.STR))

def _move_speed(g):
    return max(0, 4 + _dmod(g(Stat.AGL)))  # TPS

def _sight_range(g):
    return 5 + _dmod(g(Stat.PER))  # tiles

def _hearing_range(g):
    return 3 + _dmod(g(Stat.PER))  # tiles

def _stealth(g):
    return _dmod(g(Stat.AGL))  # reduces detection range by this many tiles

def _detection(g):
    return _dmod(g(Stat.PER))

def _carry_weight(g):
    return 50 + _dmod(g(Stat.STR)) * 10

def _max_stamina(g):
    total_mod = _dmod(g(Stat.VIT)) + _dmod(g(Stat.STR)) + _dmod(g(Stat.AGL))
    return max(10, total_mod * 15 + 25)

def _max_mana(g):
    return max(0, _dmod(g(Stat.INT)) * 5)

def _mana_regen(g):
    return max(0, _dmod(g(Stat.INT)))

def _hp_regen(g):
    # Seconds after last hit before regen starts (min 1s)
    # Regen follows fibonacci sequence once started: 1,1,2,3,5,8,13...
    # Capped at 15% of HP_MAX per second
    # This stat returns the regen delay in seconds
    return max(1, 8 - _dmod(g(Stat.VIT)))

def _stam_regen(g):
    total_mod = _dmod(g(Stat.AGL)) + _dmod(g(Stat.STR)) + _dmod(g(Stat.VIT))
    return max(1, total_mod * 3 + 1)  # per second

def _poison_resist(g):
    return _dmod(g(Stat.VIT)) + _dmod(g(Stat.CHR)) + 10

def _disease_resist(g):
    return _dmod(g(Stat.VIT)) + _dmod(g(Stat.INT)) + 10

def _magic_resist(g):
    return _dmod(g(Stat.INT))

def _stagger_resist(g):
    return _dmod(g(Stat.STR))

def _fear_resist(g):
    return _dmod(g(Stat.CHR))

def _barter_mod(g):
    return _dmod(g(Stat.CHR))

def _npc_disposition(g):
    return _dmod(g(Stat.CHR))

def _companion_limit(g):
    return max(0, 1 + _dmod(g(Stat.CHR)))

def _persuasion(g):
    return _dmod(g(Stat.CHR)) + _dmod(g(Stat.INT)) // 2

def _intimidation(g):
    return _dmod(g(Stat.CHR)) + _dmod(g(Stat.STR)) // 2

def _deception(g):
    return _dmod(g(Stat.CHR)) + _dmod(g(Stat.AGL)) // 2

def _loot_quality(g):
    return _dmod(g(Stat.LCK))

def _craft_quality(g):
    return _dmod(g(Stat.INT)) + _dmod(g(Stat.PER)) // 2

def _durability_use(g):
    return max(1, 10 - _dmod(g(Stat.STR)))  # lower is better

def _xp_mod(g):
    return _dmod(g(Stat.INT)) // 2 + _dmod(g(Stat.LCK)) // 2


DERIVED_FORMULAS: dict[Stat, callable] = {
    Stat.HP_MAX:            _hp_max,
    Stat.MELEE_DMG:      _melee_dmg,
    Stat.RANGED_DMG:     _ranged_dmg,
    Stat.MAGIC_DMG:      _magic_dmg,
    Stat.ATK_SPEED:      _atk_speed,
    Stat.ACCURACY:       _accuracy,
    Stat.CRIT_CHANCE:    _crit_chance,
    Stat.CRIT_DMG:       _crit_dmg,
    Stat.DODGE:          _dodge,
    Stat.ARMOR:          _armor,
    Stat.BLOCK:          _block,
    Stat.MOVE_SPEED:     _move_speed,
    Stat.SIGHT_RANGE:    _sight_range,
    Stat.HEARING_RANGE:  _hearing_range,
    Stat.STEALTH:        _stealth,
    Stat.DETECTION:      _detection,
    Stat.CARRY_WEIGHT:   _carry_weight,
    Stat.MAX_STAMINA:    _max_stamina,
    Stat.MAX_MANA:       _max_mana,
    Stat.MANA_REGEN:     _mana_regen,
    Stat.HP_REGEN_DELAY:       _hp_regen,
    Stat.STAM_REGEN:     _stam_regen,
    Stat.POISON_RESIST:  _poison_resist,
    Stat.DISEASE_RESIST: _disease_resist,
    Stat.MAGIC_RESIST:   _magic_resist,
    Stat.STAGGER_RESIST: _stagger_resist,
    Stat.FEAR_RESIST:    _fear_resist,
    Stat.BARTER_MOD:     _barter_mod,
    Stat.NPC_DISPOSITION: _npc_disposition,
    Stat.COMPANION_LIMIT: _companion_limit,
    Stat.PERSUASION:     _persuasion,
    Stat.INTIMIDATION:   _intimidation,
    Stat.DECEPTION:      _deception,
    Stat.LOOT_QUALITY:   _loot_quality,
    Stat.CRAFT_QUALITY:  _craft_quality,
    Stat.DURABILITY_USE: _durability_use,
    Stat.XP_MOD:         _xp_mod,
}


# ---------------------------------------------------------------------------
# Opposing stats
# ---------------------------------------------------------------------------
# Maps (attacker_stat, defender_stat) pairs for contested checks.

OPPOSING_STATS: dict[str, tuple[Stat, Stat]] = {
    'stealth_vs_detection':  (Stat.STEALTH,      Stat.DETECTION),
    'accuracy_vs_dodge':     (Stat.ACCURACY,      Stat.DODGE),
    'persuasion_vs_fear':    (Stat.PERSUASION,    Stat.FEAR_RESIST),
    'intimidation_vs_fear':  (Stat.INTIMIDATION,  Stat.FEAR_RESIST),
    'deception_vs_detection':(Stat.DECEPTION,     Stat.DETECTION),
    'melee_vs_armor':        (Stat.MELEE_DMG,     Stat.ARMOR),
    'melee_vs_block':        (Stat.MELEE_DMG,     Stat.BLOCK),
    'magic_vs_resist':       (Stat.MAGIC_DMG,     Stat.MAGIC_RESIST),
    'stagger_vs_resist':     (Stat.MELEE_DMG,     Stat.STAGGER_RESIST),
    'poison_vs_resist':      (Stat.MAGIC_DMG,     Stat.POISON_RESIST),
}


# ---------------------------------------------------------------------------
# Stats class
# ---------------------------------------------------------------------------

STAT_POINTS_PER_LEVEL = 3


class Stats:
    """Nested stat container: base, derived, mods, active.

    ``active`` is a dict whose values are callables — call them to get
    the final evaluated value for that stat:

        hp = creature.stats.active[Stat.HP_MAX]()
    """

    def __init__(self, base_stats: dict[Stat, int] | None = None,
                 hit_dice: int = 6):
        # ---- base layer ----
        self.base: dict[Stat, int] = {s: 0 for s in BASE_STATS}
        self.base[Stat.HIT_DICE]  = hit_dice
        self.base[Stat.EXP] = 0
        self.base[Stat.LVL] = 0
        self.base[Stat.HP_CURR] = 1
        self.base[Stat.CUR_STAMINA] = 0
        self.base[Stat.CUR_MANA]    = 0
        self.base[Stat.LVL] = 0
        self.unspent_stat_points: int = 0

        if base_stats:
            for stat, val in base_stats.items():
                self.base[stat] = val

        # ---- derived layer (formula cache, refreshed on demand) ----
        self.derived: dict[Stat, int] = {}

        # ---- modifier layer ----
        self.mods: list[dict] = []

        # ---- active layer (callables) ----
        self.active: dict[Stat, callable] = {}
        self._build_active()

        # reconcile exp/level if provided
        self._reconcile_exp_level()

        # initialize tracking stats from derived maxes
        self.base[Stat.HP_CURR] = self.active[Stat.HP_MAX]()
        self.base[Stat.CUR_STAMINA] = self.active[Stat.MAX_STAMINA]()
        self.base[Stat.CUR_MANA] = self.active[Stat.MAX_MANA]()

        # ---- level-up callbacks ----
        self.on_level_up: list[callable] = [_level_up_heal]

    # -- active layer construction ------------------------------------------

    def _build_active(self):
        """Populate self.active with callables for every stat."""
        for stat in BASE_LAYER_STATS:
            self.active[stat] = self._make_base_getter(stat)
        for stat in DERIVED_STATS:
            self.active[stat] = self._make_derived_getter(stat)

    def _make_base_getter(self, stat: Stat) -> callable:
        """Return a callable that computes base[stat] + sum of mods."""
        def getter():
            return self.base.get(stat, 0) + self._sum_mods(stat)
        return getter

    def _make_derived_getter(self, stat: Stat) -> callable:
        """Return a callable that computes the derived formula + mods."""
        formula = DERIVED_FORMULAS.get(stat)
        def getter():
            base_val = formula(self._active_base_getter) if formula else 0
            return base_val + self._sum_mods(stat)
        return getter

    def _active_base_getter(self, stat: Stat) -> int:
        """Get active value for a base stat (used by derived formulas)."""
        return self.base.get(stat, 0) + self._sum_mods(stat)

    def _sum_mods(self, stat: Stat) -> int:
        """Sum all modifier amounts for a given stat, respecting stackability."""
        total = 0
        seen_sources: set[str] = set()
        for mod in self.mods:
            if mod['stat'] != stat:
                continue
            source = mod['source']
            if not mod.get('stackable', True) and source in seen_sources:
                continue
            seen_sources.add(source)
            total += mod['amount']
        return total

    # -- modifier management ------------------------------------------------

    def add_mod(self, source: str, stat: Stat, amount: int,
                stackable: bool = True):
        """Add a modifier. Returns the mod dict for later removal."""
        mod = {'source': source, 'stat': stat, 'amount': amount,
               'stackable': stackable}
        self.mods.append(mod)
        return mod

    def remove_mod(self, mod: dict):
        """Remove a specific modifier (by identity)."""
        try:
            self.mods.remove(mod)
        except ValueError:
            pass

    def remove_mods_by_source(self, source: str):
        """Remove all modifiers from a given source."""
        self.mods = [m for m in self.mods if m['source'] != source]

    # -- leveling -----------------------------------------------------------

    def _reconcile_exp_level(self):
        has_exp = self.base.get(Stat.EXP, 0) > 0
        has_lvl = self.base.get(Stat.LVL, 0) > 0
        if has_exp:
            lvl, _, _ = level_from_exp(self.base[Stat.EXP])
            self.base[Stat.LVL] = lvl
        elif has_lvl:
            self.base[Stat.EXP] = cumulative_exp(self.base[Stat.LVL])

    def gain_exp(self, amount: int):
        """Award experience. Triggers level-up callbacks if level increases."""
        xp_bonus = self.active[Stat.XP_MOD]()
        effective = amount + int(amount * xp_bonus / 100)
        old_level = self.base.get(Stat.LVL, 0)
        self.base[Stat.EXP] = self.base.get(Stat.EXP, 0) + effective
        self._reconcile_exp_level()
        new_level = self.base[Stat.LVL]
        if new_level > old_level:
            levels_gained = new_level - old_level
            self.unspent_stat_points += levels_gained * STAT_POINTS_PER_LEVEL
            for callback in self.on_level_up:
                callback(self, old_level, new_level)

    def allocate_stat_point(self, stat: Stat) -> bool:
        """Spend one unspent stat point to raise a base stat by 1.

        Returns True if successful, False if no points or invalid stat.
        """
        if self.unspent_stat_points <= 0:
            return False
        if stat not in BASE_STATS:
            return False
        self.base[stat] = self.base.get(stat, 0) + 1
        self.unspent_stat_points -= 1
        return True

    # -- opposing stat contests ---------------------------------------------

    def contest(self, other: 'Stats', contest_name: str) -> tuple[bool, int]:
        """Resolve an opposing stat check against another creature's Stats.

        Args:
            other: the opposing creature's Stats
            contest_name: key into OPPOSING_STATS (e.g. 'stealth_vs_detection')

        Returns:
            (success, margin) — success is True if attacker wins,
            margin is the difference (positive = attacker advantage).
        """
        pair = OPPOSING_STATS.get(contest_name)
        if pair is None:
            return False, 0
        atk_stat, def_stat = pair
        atk_val = self.active[atk_stat]()  + random.randint(1, 20)
        def_val = other.active[def_stat]() + random.randint(1, 20)
        margin = atk_val - def_val
        return margin > 0, margin

    def contest_stat(self, other: 'Stats', atk_stat: Stat,
                     def_stat: Stat) -> tuple[bool, int]:
        """Ad-hoc opposing stat check with explicit stats."""
        atk_val = self.active[atk_stat]()  + random.randint(1, 20)
        def_val = other.active[def_stat]() + random.randint(1, 20)
        margin = atk_val - def_val
        return margin > 0, margin

    # -- snapshot -----------------------------------------------------------

    def snapshot(self) -> dict[Stat, int]:
        """Return a plain dict of all stats at their current active values."""
        return {stat: getter() for stat, getter in self.active.items()}

    def __repr__(self):
        base_str = ', '.join(f'{s.name}={self.base.get(s, 0)}'
                             for s in BASE_STATS)
        return f'Stats({base_str}, lvl={self.base.get(Stat.LVL, 0)})'


# ---------------------------------------------------------------------------
# Default level-up callback
# ---------------------------------------------------------------------------

def _level_up_heal(stats: Stats, old_level: int, new_level: int):
    """Roll HP on level-up and fully heal."""
    hd = stats.base.get(Stat.HIT_DICE, 6)
    vit = stats.active[Stat.VIT]()
    roll = random.randint(1, hd) + vit
    # Bump VIT contribution to MHP doesn't stack with the formula —
    # instead we add a permanent mod representing the HP roll.
    stats.add_mod(f'level_{new_level}_hp', Stat.HP_MAX, roll, stackable=True)
    # Full heal
    stats.base[Stat.HP_CURR] = stats.active[Stat.HP_MAX]()
    stats.base[Stat.CUR_STAMINA] = stats.active[Stat.MAX_STAMINA]()
    stats.base[Stat.CUR_MANA] = stats.active[Stat.MAX_MANA]()
