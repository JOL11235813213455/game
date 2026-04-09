from __future__ import annotations
from classes.stats import Stat


class RegenMixin:
    """HP, stamina, and mana regeneration methods for Creature."""

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
        """Restore stamina per second based on STAM_REGEN."""
        cur = self.stats.active[Stat.CUR_STAMINA]()
        mx = self.stats.active[Stat.MAX_STAMINA]()
        if cur >= mx:
            return
        regen = self.stats.active[Stat.STAM_REGEN]()
        self.stats.base[Stat.CUR_STAMINA] = min(mx, cur + regen)

    def _do_mana_regen(self, _now: int):
        """Restore mana per second based on MANA_REGEN."""
        cur = self.stats.active[Stat.CUR_MANA]()
        mx = self.stats.active[Stat.MAX_MANA]()
        if cur >= mx:
            return
        regen = self.stats.active[Stat.MANA_REGEN]()
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
