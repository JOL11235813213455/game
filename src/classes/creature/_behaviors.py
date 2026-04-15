from __future__ import annotations
import random
from classes.stats import Stat


class RandomWanderBehavior:
    """Simple behavior: move in a random direction each think tick."""

    def think(self, creature, cols: int, rows: int):
        dx, dy = random.choice([
            (-1, -1), (0, -1), (1, -1),
            (-1,  0),          (1,  0),
            (-1,  1), (0,  1), (1,  1),
        ])
        creature.move(dx, dy, cols, rows)


class PairedBehavior:
    """Behavior for amorous pairs: follow partner, share resources.

    Wraps an inner behavior (e.g. StatWeightedBehavior) and overrides
    movement to stay near partner. When partner is out of sight,
    falls back to inner behavior. If bond is broken, reverts fully.
    """

    def __init__(self, inner_behavior=None):
        self.inner = inner_behavior or RandomWanderBehavior()

    def think(self, creature, cols: int, rows: int):
        partner = creature.get_partner()

        if partner is None or not partner.is_alive:
            # Bond broken — revert to inner behavior
            creature.break_pair_bond()
            self.inner.think(creature, cols, rows)
            return

        dist = creature._sight_distance(partner)

        # Stay near partner: if too far, follow
        if dist > 3:
            creature.follow(partner, cols, rows)
            return

        # If adjacent, occasionally share resources
        if dist <= 1 and random.random() < 0.1:
            # Share healing if partner is low HP
            p_hp_ratio = partner.stats.active[Stat.HP_CURR]() / max(1, partner.stats.active[Stat.HP_MAX]())
            if p_hp_ratio < 0.5:
                # Look for consumable to give
                from classes.inventory import Consumable as C
                for item in creature.inventory.items:
                    if isinstance(item, C) and item.buffs:
                        creature.inventory.items.remove(item)
                        partner.inventory.items.append(item)
                        creature.record_interaction(partner, 2.0)
                        partner.record_interaction(creature, 2.0)
                        break

        # Otherwise, use inner behavior but bias toward partner's direction
        if dist > 1:
            creature.follow(partner, cols, rows)
        else:
            self.inner.think(creature, cols, rows)


class NeuralBehavior:
    """Neural net-driven behavior module.

    Uses a shared CreatureNet to select actions. The net takes the
    creature's observation vector and outputs action probabilities.
    A target selection heuristic picks the best target for targeted actions.
    """

    def __init__(self, net, temperature: float = 1.0):
        """Args:
            net: a simulation.net.CreatureNet instance (shared across all creatures)
            temperature: sampling temperature (0 = greedy, 1 = stochastic)
        """
        self.net = net
        self.temperature = temperature
        self._prev_snapshot = None

    @staticmethod
    def _int_temperature(base_temp: float, int_val: int) -> float:
        """INT -> decision quality. Graduated: every point matters.
        INT 3->1.7, 6->1.4, 10->1.0, 14->0.6, 18->0.4, 20->0.3"""
        return max(0.3, base_temp * (2.0 - int_val / 10.0))

    @staticmethod
    def _per_noise(per_val: int) -> float:
        """PER -> observation noise magnitude. Graduated.
        PER 3->0.3, 6->0.2, 10->0.1, 14->0.05, 18->0.01, 20->0.0"""
        return max(0.0, 0.35 - per_val * 0.0175)

    @staticmethod
    def _lck_reroll_chance(lck_val: int) -> float:
        """LCK -> chance of lucky reroll on failed action. Graduated.
        LCK 3->0%, 6->5%, 10->15%, 14->25%, 18->40%, 20->50%"""
        return max(0.0, min(0.5, (lck_val - 3) * 0.03))

    def think(self, creature, cols: int, rows: int):
        from classes.observation import build_observation, make_snapshot, apply_preset_mask
        from classes.actions import dispatch, Action
        from classes.world_object import WorldObject
        from classes.creature import Creature
        import numpy as np

        # Build observation
        obs = build_observation(creature, cols, rows, prev_snapshot=self._prev_snapshot)
        self._prev_snapshot = make_snapshot(creature)

        # Apply observation mask if creature has one
        if creature.observation_mask:
            apply_preset_mask(obs, creature.observation_mask)

        obs_arr = np.array(obs, dtype=np.float32)

        # --- PER: observation noise (graduated) ---
        # Low PER creatures get fuzzy inputs — misread distances, HP ratios, etc.
        per_val = creature.stats.active[Stat.PER]()
        noise_mag = self._per_noise(per_val)
        if noise_mag > 0:
            noise = np.random.normal(0, noise_mag, size=obs_arr.shape).astype(np.float32)
            obs_arr = obs_arr + noise

        # --- INT: temperature scaling (graduated) ---
        int_val = creature.stats.active[Stat.INT]()
        int_temp = self._int_temperature(self.temperature, int_val)

        # Select action from net
        action_idx = self.net.select_action(obs_arr, int_temp)

        # --- LCK: lucky reroll on failure (graduated) ---
        # If the chosen action would fail, LCK gives a chance to pick
        # the second-best action instead
        lck_val = creature.stats.active[Stat.LCK]()
        reroll_chance = self._lck_reroll_chance(lck_val)

        # Build context first (needed for failure check)
        target = next((o for o in creature.nearby() if creature.can_see(o)), None)

        now = 0  # ticks managed by simulation loop
        context = {
            'cols': cols, 'rows': rows,
            'target': target, 'now': now,
            'combat_enabled': getattr(creature, '_combat_enabled', True),
        }

        # Execute action — with LCK reroll on failure
        result = dispatch(creature, action_idx, context)

        if not result.get('success', result.get('hit', False)):
            # Action failed — LCK reroll?
            if reroll_chance > 0 and random.random() < reroll_chance:
                # Get full probability distribution and pick second-best
                import numpy as _np
                probs = self.net.forward(obs_arr)
                # Zero out the failed action and pick from remaining
                probs[action_idx] = 0.0
                remaining_sum = probs.sum()
                if remaining_sum > 0:
                    probs = probs / remaining_sum
                    reroll_idx = int(_np.random.choice(len(probs), p=probs))
                    dispatch(creature, reroll_idx, context)


class StatWeightedBehavior:
    """Stat-weighted decision table behavior (fallback/interim).

    Uses creature stats to weight action probabilities directly,
    without a neural net. Higher STR -> prefer melee, higher INT ->
    prefer social actions, higher AGL -> prefer movement/flee, etc.

    Serves as immediate usable AI before training, and as a baseline
    for comparing against the neural net.
    """

    def think(self, creature, cols: int, rows: int):
        from classes.actions import dispatch, Action, ACTION_NAMES

        str_mod = (creature.stats.active[Stat.STR]() - 10) // 2
        agl_mod = (creature.stats.active[Stat.AGL]() - 10) // 2
        int_mod = (creature.stats.active[Stat.INT]() - 10) // 2
        chr_mod = (creature.stats.active[Stat.CHR]() - 10) // 2
        per_mod = (creature.stats.active[Stat.PER]() - 10) // 2

        hp_ratio = creature.stats.active[Stat.HP_CURR]() / max(1, creature.stats.active[Stat.HP_MAX]())
        stam_ratio = creature.stats.active[Stat.CUR_STAMINA]() / max(1, creature.stats.active[Stat.MAX_STAMINA]())
        hunger = getattr(creature, 'hunger', 0.0)

        target = next((o for o in creature.nearby() if creature.can_see(o)), None)
        nearest_dist = creature._sight_distance(target) if target else 999

        candidates = []

        # Movement — single MOVE action (auto-direction toward goal)
        candidates.append((Action.MOVE, 8 + agl_mod))

        if stam_ratio < 0.2:
            candidates.append((Action.WAIT, 20))
        else:
            candidates.append((Action.WAIT, 2))

        # Eat when hungry
        if hunger < 0:
            candidates.append((Action.USE_ITEM, int(5 + abs(hunger) * 10)))

        # Pickup items on tile
        tile = creature.current_map.tiles.get(creature.location) if creature.current_map else None
        if tile and (tile.inventory.items or getattr(tile, 'gold', 0) > 0):
            candidates.append((Action.PICKUP, 6 + per_mod))

        if target is not None:
            rel = creature.get_relationship(target)
            sentiment = rel[0] if rel else 0.0

            if nearest_dist <= 1:
                if sentiment < -3 or hp_ratio > 0.5:
                    candidates.append((Action.MELEE_ATTACK, 8 + str_mod * 2))
                    candidates.append((Action.GRAPPLE, 4 + str_mod))

                if sentiment >= 0:
                    candidates.append((Action.TALK, 5 + chr_mod * 2))
                    candidates.append((Action.TRADE, 4 + chr_mod))
                    candidates.append((Action.INTIMIDATE, 3 + str_mod + chr_mod))

                if rel is None:
                    curiosity = creature.curiosity_toward(target)
                    candidates.append((Action.TALK, int(curiosity * 10 + int_mod * 2)))

            elif nearest_dist <= 8:
                if sentiment < -3:
                    candidates.append((Action.RANGED_ATTACK, 5 + per_mod * 2))
                    candidates.append((Action.FLEE, 3 + agl_mod))

                if rel is None or sentiment > 0:
                    candidates.append((Action.FOLLOW, 5 + int_mod))

            if hp_ratio < 0.3 and sentiment < 0:
                candidates.append((Action.FLEE, 15 + agl_mod * 2))

        candidates.append((Action.SEARCH, 2 + int_mod + per_mod))
        candidates.append((Action.GUARD, 1 + str_mod))

        # Economy: harvest/farm if on resource tile
        if tile and getattr(tile, 'resource_type', None) and getattr(tile, 'resource_amount', 0) > 0:
            candidates.append((Action.HARVEST, 5 + str_mod))
            candidates.append((Action.FARM, 3))

        # Sleep when fatigued
        if getattr(creature, 'sleep_debt', 0) >= 2:
            candidates.append((Action.SLEEP, 10 + getattr(creature, 'sleep_debt', 0) * 3))

        # Piety modifier
        if creature.deity and creature.piety > 0:
            from classes.gods import WorldData as _WD
            instances = _WD.all()
            if instances:
                god = instances[-1].gods.get(creature.deity)
                if god:
                    piety_boost = int(creature.piety * 5)
                    new_candidates = []
                    for action, weight in candidates:
                        aname = ACTION_NAMES.get(action, '')
                        if aname in god.aligned_actions:
                            weight += piety_boost
                        elif aname in god.opposed_actions:
                            weight = max(1, weight - piety_boost)
                        new_candidates.append((action, weight))
                    candidates = new_candidates

        weights = [max(1, w) for _, w in candidates]
        total = sum(weights)
        probs = [w / total for w in weights]
        idx = random.choices(range(len(candidates)), weights=probs, k=1)[0]
        chosen_action = candidates[idx][0]

        dispatch(creature, chosen_action, {
            'cols': cols, 'rows': rows,
            'target': target, 'now': 0,
            'combat_enabled': getattr(creature, '_combat_enabled', True),
        })
