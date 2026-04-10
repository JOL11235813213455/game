from __future__ import annotations
import math
from classes.stats import Stat

# Hunger thresholds
_WELL_FED = 0.75    # above this: regen bonus
_SATIATED = 0.5     # above this: positive mood
_HUNGRY = 0.0       # below this: negative effects start
_STARVING = -0.5    # below this: HP/stamina/mana drain


class RegenMixin:
    """HP, stamina, and mana regeneration methods for Creature."""

    def _do_hunger_tick(self, _now: int):
        """Drain hunger over time. Apply starvation effects."""
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
            mana = self.stats.base.get(Stat.CUR_MANA, 0)
            self.stats.base[Stat.CUR_MANA] = max(0, mana - int(drain))
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

    def _do_hp_regen(self, now: int):
        """Fibonacci HP regen, capped at 15% of HP_MAX per second."""
        if now < self._regen_start:
            return
        hp_curr = self.stats.active[Stat.HP_CURR]()
        hp_max = self.stats.active[Stat.HP_MAX]()
        if hp_curr >= hp_max:
            return
        cap = max(1, int(hp_max * 0.15))
        heal = min(self._regen_fib[0], cap)
        self.stats.base[Stat.HP_CURR] = min(hp_max, hp_curr + heal)
        self._regen_fib = (self._regen_fib[1], self._regen_fib[0] + self._regen_fib[1])

    def _do_stamina_regen(self, _now: int):
        """Restore stamina per second based on STAM_REGEN. Well-fed bonus applies."""
        cur = self.stats.active[Stat.CUR_STAMINA]()
        mx = self.stats.active[Stat.MAX_STAMINA]()
        if cur >= mx:
            return
        regen = self.stats.active[Stat.STAM_REGEN]()
        bonus = getattr(self, '_hunger_regen_bonus', 0.0)
        regen = int(regen * (1.0 + bonus))
        self.stats.base[Stat.CUR_STAMINA] = min(mx, cur + regen)

    def _do_mana_regen(self, _now: int):
        """Restore mana per second based on MANA_REGEN. Well-fed bonus applies."""
        cur = self.stats.active[Stat.CUR_MANA]()
        mx = self.stats.active[Stat.MAX_MANA]()
        if cur >= mx:
            return
        regen = self.stats.active[Stat.MANA_REGEN]()
        bonus = getattr(self, '_hunger_regen_bonus', 0.0)
        regen = int(regen * (1.0 + bonus))
        self.stats.base[Stat.CUR_MANA] = min(mx, cur + regen)

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
