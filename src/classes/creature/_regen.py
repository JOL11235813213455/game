from __future__ import annotations
import math
from classes.stats import Stat

# Hunger thresholds
_WELL_FED = 0.75    # above this: regen bonus
_SATIATED = 0.5     # above this: positive mood
_HUNGRY = 0.0       # below this: negative effects start
_STARVING = -0.5    # below this: HP/stamina/mana drain


def encumbrance_penalty(ratio: float) -> float:
    """S-curve penalty from carry weight ratio.

    Returns 0.0 (no penalty) to 1.0 (full penalty).
    No penalty below 100% carry weight. Above 100%: slow initial
    decline, then plummets, then normalizes at 1.0.
      ratio 0.0-1.0 → 0.0 (no penalty)
      ratio 1.15    → ~0.5 (half regen speed)
      ratio 1.3     → ~0.95 (almost no regen)
      ratio 1.5+    → ~1.0 (regen stopped)
    """
    if ratio <= 1.0:
        return 0.0
    x = max(-20, min(20, 12 * (ratio - 1.15)))
    return 1.0 / (1.0 + math.exp(-x))


class RegenMixin:
    """HP, stamina, and mana regeneration methods for Creature."""

    def _do_hunger_tick(self, _now: int):
        """Drain hunger over time. Apply starvation effects."""
        if not self.is_alive:
            return
        self.hunger = max(-1.0, self.hunger - self._hunger_drain)

        # Well-fed bonus: boost regen rates
        if self.hunger >= _WELL_FED:
            bonus = (self.hunger - _WELL_FED) / (1.0 - _WELL_FED)  # 0-1
            # Boost HP regen by shortening delay
            # Boost stamina/mana regen handled in their tick methods
            self._hunger_regen_bonus = bonus * 0.5  # up to +50% regen
        else:
            self._hunger_regen_bonus = 0.0

        # Starving: drain HP, stamina, mana
        if self.hunger <= _STARVING:
            severity = abs(self.hunger - _STARVING) / (1.0 - abs(_STARVING))
            # Logarithmic drain: gets worse faster as you approach -1
            drain = math.log(1 + severity * 3) * 2
            hp = self.stats.base.get(Stat.HP_CURR, 0)
            self.stats.base[Stat.HP_CURR] = max(0, hp - int(drain))
            stam = self.stats.base.get(Stat.CUR_STAMINA, 0)
            self.stats.base[Stat.CUR_STAMINA] = max(0, stam - int(drain))
            self._ensure_stamina_regen()
            mana = self.stats.base.get(Stat.CUR_MANA, 0)
            self.stats.base[Stat.CUR_MANA] = max(0, mana - int(drain))
            self._ensure_mana_regen()
            if 'hp_regen' not in self._timed_events:
                self.register_tick('hp_regen', 1000, self._do_hp_regen)
            if self.stats.base.get(Stat.HP_CURR, 0) <= 0:
                self.die()

    def eat(self, amount: float = 0.3):
        """Restore hunger. Called when consuming food items.

        amount: how much hunger to restore (0.3 = small meal, 0.6 = feast)
        """
        self.hunger = min(1.0, self.hunger + amount)

    def on_hit(self, now: int, damage: int = 0):
        """Call when this creature takes damage. Resets HP regen timer."""
        delay_s = self.stats.active[Stat.HP_REGEN_DELAY]()
        self._regen_start = now + delay_s * 1000
        self._regen_fib = (1, 1)
        if damage > self._max_hit_taken:
            self._max_hit_taken = damage
        if 'hp_regen' not in self._timed_events:
            self.register_tick('hp_regen', 1000, self._do_hp_regen)

    def _ensure_stamina_regen(self):
        """Re-register stamina regen tick after stamina was consumed."""
        if 'stamina_regen' not in self._timed_events:
            self.register_tick('stamina_regen', 1000, self._do_stamina_regen)

    def _ensure_mana_regen(self):
        """Re-register mana regen tick after mana was consumed."""
        if 'mana_regen' not in self._timed_events:
            self.register_tick('mana_regen', 1000, self._do_mana_regen)

    def _encumbrance_multiplier(self) -> float:
        """Return 1.0 (unencumbered) down to 0.0 (fully encumbered)."""
        carry_max = self.stats.active[Stat.CARRY_WEIGHT]()
        if carry_max <= 0:
            return 1.0
        ratio = self.carried_weight / carry_max
        return max(0.0, 1.0 - encumbrance_penalty(ratio))

    def _do_hp_regen(self, now: int):
        """Fibonacci HP regen, capped at 15% of HP_MAX per second."""
        if now < self._regen_start:
            return
        hp_curr = self.stats.base.get(Stat.HP_CURR, 0)
        hp_max = self.stats.active[Stat.HP_MAX]()
        if hp_curr >= hp_max:
            self.unregister_tick('hp_regen')
            return
        cap = max(1, int(hp_max * 0.15))
        heal = min(self._regen_fib[0], cap)
        heal = max(1, int(heal * self._encumbrance_multiplier()))
        self.stats.base[Stat.HP_CURR] = min(hp_max, hp_curr + heal)
        self._regen_fib = (self._regen_fib[1], self._regen_fib[0] + self._regen_fib[1])

    def _do_stamina_regen(self, _now: int):
        """Restore stamina per second based on STAM_REGEN."""
        cur = self.stats.base.get(Stat.CUR_STAMINA, 0)
        mx = self.stats.active[Stat.MAX_STAMINA]()
        if cur >= mx:
            self.unregister_tick('stamina_regen')
            return
        regen = self.stats.active[Stat.STAM_REGEN]()
        bonus = getattr(self, '_hunger_regen_bonus', 0.0)
        regen = int(regen * (1.0 + bonus) * self._encumbrance_multiplier())
        self.stats.base[Stat.CUR_STAMINA] = min(mx, cur + max(0, regen))

    def _do_mana_regen(self, _now: int):
        """Restore mana per second based on MANA_REGEN."""
        cur = self.stats.base.get(Stat.CUR_MANA, 0)
        mx = self.stats.active[Stat.MAX_MANA]()
        if cur >= mx:
            self.unregister_tick('mana_regen')
            return
        regen = self.stats.active[Stat.MANA_REGEN]()
        bonus = getattr(self, '_hunger_regen_bonus', 0.0)
        regen = int(regen * (1.0 + bonus) * self._encumbrance_multiplier())
        self.stats.base[Stat.CUR_MANA] = min(mx, cur + max(0, regen))

    # -- Regen state checks ------------------------------------------------

    @property
    def is_regenerating_hp(self) -> bool:
        """True if HP regen cooldown has passed and HP is below max."""
        now = getattr(self, '_last_update_time', 0)
        if now < self._regen_start:
            return False
        return self.stats.active[Stat.HP_CURR]() < self.stats.active[Stat.HP_MAX]()

    @property
    def is_regenerating_mana(self) -> bool:
        """True if mana is below max (mana regens continuously)."""
        return self.stats.active[Stat.CUR_MANA]() < self.stats.active[Stat.MAX_MANA]()

    @property
    def is_regenerating_stamina(self) -> bool:
        """True if stamina is below max (stamina regens continuously)."""
        return self.stats.active[Stat.CUR_STAMINA]() < self.stats.active[Stat.MAX_STAMINA]()

    @property
    def hp_regen_ready(self) -> bool:
        """True if HP regen cooldown has passed (regardless of current HP)."""
        now = getattr(self, '_last_update_time', 0)
        return now >= self._regen_start
