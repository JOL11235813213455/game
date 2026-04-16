from __future__ import annotations
import random
from classes.stats import Stat
from classes.inventory import Weapon, Ammunition, Slot


class CombatMixin:
    """Combat methods for Creature."""

    def _tick_durability(self, item):
        """Decrement durability by 1 per hit. Break at 0."""
        if not hasattr(item, 'durability_current') or item.durability_current is None:
            return
        item.durability_current -= 1
        if item.durability_current <= 0:
            for slot, eq in list(self.equipment.items()):
                if eq is item:
                    self.equipment[slot] = None
                    self.stats.remove_mods_by_source(f'equip_{item.uid}')
            if item in self.inventory.items:
                self.inventory.items.remove(item)

    def _sight_distance(self, other) -> int:
        """Manhattan distance between self and other."""
        return abs(self.location.x - other.location.x) + abs(self.location.y - other.location.y)

    def can_see(self, other) -> bool:
        """Return True if other is within effective sight range.

        Covered tiles block cross-cover vision: a creature under cover
        cannot see outside, and an uncovered creature cannot see in,
        unless both are on the same tile.
        """
        if self.location == other.location:
            effective_range = self.stats.active[Stat.SIGHT_RANGE]() - other.stats.active[Stat.STEALTH]()
            return self._sight_distance(other) <= effective_range
        my_tile = self.current_map.tiles.get(self.location) if self.current_map else None
        their_tile = other.current_map.tiles.get(other.location) if other.current_map else None
        my_covered = getattr(my_tile, 'covered', False) if my_tile else False
        their_covered = getattr(their_tile, 'covered', False) if their_tile else False
        if my_covered != their_covered:
            return False
        effective_range = self.stats.active[Stat.SIGHT_RANGE]() - other.stats.active[Stat.STEALTH]()
        return self._sight_distance(other) <= effective_range

    def melee_attack(self, target, now: int) -> dict:
        """Execute a melee attack against an adjacent creature.

        Returns a result dict with keys:
            hit: bool, damage: int, crit: bool, staggered: bool,
            reason: str (if miss/fail)
        """
        result = {'hit': False, 'damage': 0, 'crit': False,
                  'staggered': False, 'betrayal': False, 'reason': ''}

        # Must be adjacent (Manhattan distance 1)
        if self._sight_distance(target) > 1:
            result['reason'] = 'not_adjacent'
            return result

        # Weapon check — get equipped weapon or use unarmed defaults
        weapon = self.equipment.get(Slot.HAND_R) or self.equipment.get(Slot.HAND_L)
        if weapon and isinstance(weapon, Weapon):
            weapon_dmg = weapon.damage
            weapon_dc = getattr(weapon, 'damage', 5)  # armor DC
            weapon_impact = weapon_dmg  # stagger force scales with damage
            stamina_cost = max(5, 10 - (self.stats.active[Stat.STR]() - 10) // 2)
        else:
            # Unarmed
            weapon_dmg = 0
            weapon_dc = 3
            weapon_impact = 2
            stamina_cost = 5

        # Stamina check
        cur_stam = self.stats.active[Stat.CUR_STAMINA]()
        if cur_stam < stamina_cost:
            result['reason'] = 'no_stamina'
            return result
        self.stats.base[Stat.CUR_STAMINA] = cur_stam - stamina_cost
        self._ensure_stamina_regen()

        # Betrayal check: the ACT of attacking someone with positive history
        # triggers regardless of whether the attack hits
        rel = self.get_relationship(target)
        if rel and rel[0] > 0:
            self.record_interaction(target, -10.0)
            target.record_interaction(self, -10.0)
            result['betrayal'] = True

        # Can defender see attacker? If not, auto-hit (ambush)
        ambush = not target.can_see(self)
        if not ambush:
            # Defender picks dodge (default active defense)
            hit_won, _ = self.stats.contest(target.stats, 'accuracy_vs_dodge')
            if not hit_won:
                result['reason'] = 'dodged'
                target.record_interaction(self, -1.0)
                return result

        # Hit lands — armor resist check
        armor_blocked = target.stats.resist_check(weapon_dc, Stat.ARMOR)
        if armor_blocked:
            result['reason'] = 'armor_absorbed'
            result['hit'] = True
            result['damage'] = 0
            target.on_hit(now)
            target.record_interaction(self, -2.0)
            return result

        # Damage calculation
        str_mod = (self.stats.active[Stat.STR]() - 10) // 2
        base_dmg = str_mod + weapon_dmg
        # Lucky STR bonus: (LCK+1)/(LCK+2) chance of adding STR mod again
        lck = self.stats.active[Stat.LCK]()
        lucky_chance = (lck + 1) / (lck + 2) if lck + 2 > 0 else 0
        if random.random() < lucky_chance:
            base_dmg += max(0, str_mod)

        # Crit check
        crit_chance = self.stats.active[Stat.CRIT_CHANCE]()
        crit = random.randint(1, 100) <= crit_chance
        if crit:
            result['crit'] = True
            base_dmg = base_dmg * 2 + str_mod

        damage = max(1, base_dmg)
        result['hit'] = True
        result['damage'] = damage

        # Apply damage
        hp = target.stats.active[Stat.HP_CURR]()
        final_dmg = min(hp, damage)  # can't deal more than remaining HP
        target.stats.base[Stat.HP_CURR] = max(0, hp - damage)
        self._damage_dealt = getattr(self, '_damage_dealt', 0) + final_dmg

        # Track kill if target died from this hit
        if target.stats.active[Stat.HP_CURR]() <= 0:
            self._kills = getattr(self, '_kills', 0) + 1
            self.gain_exp(10)

        # Stagger check
        staggered = not target.stats.resist_check(weapon_impact, Stat.STAGGER_RESIST)
        result['staggered'] = staggered

        # Reset defender's HP regen
        target.on_hit(now)

        # Weapon durability tick
        if weapon and isinstance(weapon, Weapon):
            self._tick_durability(weapon)

        # Armor durability tick on defender's equipped armor
        from classes.inventory import Wearable
        for eq in set(target.equipment.values()):
            if eq is not None and isinstance(eq, Wearable):
                target._tick_durability(eq)

        # Record combat interaction
        target.record_interaction(self, -5.0)

        return result

    def ranged_attack(self, target, now: int) -> dict:
        """Execute a ranged attack against a creature within weapon range.

        Requires a ranged weapon equipped and matching ammunition in inventory.
        Returns result dict: hit, damage, crit, reason.
        """
        result = {'hit': False, 'damage': 0, 'crit': False, 'reason': ''}

        # Weapon check — need a ranged weapon (range > 1)
        weapon = self.equipment.get(Slot.HAND_R) or self.equipment.get(Slot.HAND_L)
        if not weapon or not isinstance(weapon, Weapon) or weapon.range <= 1:
            result['reason'] = 'no_ranged_weapon'
            return result

        # Range check
        dist = self._sight_distance(target)
        if dist > weapon.range:
            result['reason'] = 'out_of_range'
            return result
        if dist < 1:
            result['reason'] = 'too_close'
            return result

        # Ammo check
        ammo = None
        if weapon.ammunition_type:
            for item in self.inventory.items:
                if isinstance(item, Ammunition) and item.name == weapon.ammunition_type and item.quantity > 0:
                    ammo = item
                    break
            if ammo is None:
                result['reason'] = 'no_ammo'
                return result

        # Stamina cost
        stamina_cost = max(3, 8 - (self.stats.active[Stat.STR]() - 10) // 2)
        cur_stam = self.stats.active[Stat.CUR_STAMINA]()
        if cur_stam < stamina_cost:
            result['reason'] = 'no_stamina'
            return result
        self.stats.base[Stat.CUR_STAMINA] = cur_stam - stamina_cost
        self._ensure_stamina_regen()

        # Betrayal check
        rel = self.get_relationship(target)
        if rel and rel[0] > 0:
            self.record_interaction(target, -10.0)
            target.record_interaction(self, -10.0)
            result['betrayal'] = True

        # Consume one ammo unit up front
        ammo_dmg = 0
        if ammo:
            ammo_dmg = ammo.damage
            ammo.quantity -= 1
            if ammo.quantity <= 0:
                self.inventory.items.remove(ammo)

        def _drop_ammo_on_tile():
            """Recoverable ammo lands on the target's tile on miss."""
            if ammo and ammo.recoverable:
                tile = target.current_map.tiles.get(target.location)
                if tile is not None:
                    # Create a single recovered projectile on the tile
                    recovered = Ammunition(
                        name=ammo.name, weight=ammo.weight, quantity=1,
                        damage=ammo.damage,
                        destroy_on_use_probability=ammo.destroy_on_use_probability,
                        recoverable=ammo.recoverable,
                    )
                    tile.inventory.items.append(recovered)

        # Accuracy at distance
        hit_prob = self.stats.accuracy_at_distance(dist)
        if random.random() > hit_prob:
            result['reason'] = 'missed'
            _drop_ammo_on_tile()
            if target.can_see(self):
                target.record_interaction(self, -1.0)
            return result

        # Dodge contest if defender can see attacker
        if target.can_see(self):
            hit_won, _ = self.stats.contest(target.stats, 'accuracy_vs_dodge')
            if not hit_won:
                result['reason'] = 'dodged'
                _drop_ammo_on_tile()
                target.record_interaction(self, -1.0)
                return result

        # Armor resist
        weapon_dc = weapon.damage
        armor_blocked = target.stats.resist_check(weapon_dc, Stat.ARMOR)
        if armor_blocked:
            result['hit'] = True
            result['damage'] = 0
            result['reason'] = 'armor_absorbed'
            target.on_hit(now)
            target.record_interaction(self, -2.0)
            return result

        # Damage: weapon + ammo + STR if weapon requires it (bows)
        base_dmg = weapon.damage + ammo_dmg

        # Crit check
        crit_chance = self.stats.active[Stat.CRIT_CHANCE]()
        crit = random.randint(1, 100) <= crit_chance
        if crit:
            result['crit'] = True
            base_dmg *= 2

        damage = max(1, base_dmg)
        result['hit'] = True
        result['damage'] = damage

        # Apply damage
        hp = target.stats.active[Stat.HP_CURR]()
        final_dmg = min(hp, damage)
        target.stats.base[Stat.HP_CURR] = max(0, hp - damage)
        self._damage_dealt = getattr(self, '_damage_dealt', 0) + final_dmg
        target.on_hit(now)

        # Track kill if target died from this hit
        if target.stats.active[Stat.HP_CURR]() <= 0:
            self._kills = getattr(self, '_kills', 0) + 1
            self.gain_exp(10)

        # Weapon durability tick
        if weapon and isinstance(weapon, Weapon):
            self._tick_durability(weapon)

        # Armor durability tick on defender
        from classes.inventory import Wearable
        for eq in set(target.equipment.values()):
            if eq is not None and isinstance(eq, Wearable):
                target._tick_durability(eq)

        # Record interaction
        if target.can_see(self):
            target.record_interaction(self, -5.0)

        return result

    def cast_spell(self, spell: dict, target, now: int) -> dict:
        """Cast a spell.

        Args:
            spell: spell definition dict (from SPELLS)
            target: target creature (None for self-targeted spells)
            now: current timestamp

        Returns result dict: hit, damage, effect_applied, reason.
        """
        result = {'hit': False, 'damage': 0, 'effect_applied': False,
                  'secondary_applied': False, 'reason': ''}

        # Self-targeted spells target self
        if spell['target_type'] == 'self':
            target = self
        elif target is None:
            result['reason'] = 'no_target'
            return result

        # Requirements check
        for stat, min_val in spell['requirements'].items():
            if self.stats.active[stat]() < min_val:
                result['reason'] = 'requirements_not_met'
                return result

        # Mana check
        cur_mana = self.stats.active[Stat.CUR_MANA]()
        if cur_mana < spell['mana_cost']:
            result['reason'] = 'no_mana'
            return result

        # Stamina check
        cur_stam = self.stats.active[Stat.CUR_STAMINA]()
        if cur_stam < spell['stamina_cost']:
            result['reason'] = 'no_stamina'
            return result

        # Range check (not for self-targeted)
        if target is not self:
            dist = self._sight_distance(target)
            if dist > spell['range']:
                result['reason'] = 'out_of_range'
                return result

        # Consume resources
        self.stats.base[Stat.CUR_MANA] = cur_mana - spell['mana_cost']
        self._ensure_mana_regen()
        self.stats.base[Stat.CUR_STAMINA] = cur_stam - spell['stamina_cost']
        self._ensure_stamina_regen()

        # Dodge contest (if dodgeable and target can see caster)
        if spell['dodgeable'] and target is not self:
            if target.can_see(self):
                hit_won, _ = self.stats.contest(target.stats, 'accuracy_vs_dodge')
                if not hit_won:
                    result['reason'] = 'dodged'
                    target.record_interaction(self, -1.0)
                    return result

        # Magic resist check — only for hostile spells (damage/debuff)
        if target is not self and spell['effect_type'] in ('damage', 'debuff'):
            resisted = target.stats.resist_check(spell['spell_dc'], Stat.MAGIC_RESIST)
            if resisted:
                result['reason'] = 'resisted'
                result['hit'] = True
                target.record_interaction(self, -1.0)
                return result

        result['hit'] = True

        # Apply effect based on type
        effect = spell['effect_type']

        if effect == 'damage':
            magic_dmg = self.stats.active[Stat.MAGIC_DMG]()
            damage = max(1, int(spell['damage'] + magic_dmg))
            result['damage'] = damage
            hp = target.stats.active[Stat.HP_CURR]()
            final_dmg = min(hp, damage)
            target.stats.base[Stat.HP_CURR] = max(0, hp - damage)
            if target is not self:
                self._damage_dealt = getattr(self, '_damage_dealt', 0) + final_dmg
                # Track kill if target died from this hit
                if target.stats.active[Stat.HP_CURR]() <= 0:
                    self._kills = getattr(self, '_kills', 0) + 1
                    self.gain_exp(10)
            target.on_hit(now)
            result['effect_applied'] = True
            if target is not self:
                target.record_interaction(self, -5.0)

        elif effect == 'heal':
            heal = max(1, int(spell['damage'] + self.stats.active[Stat.MAGIC_DMG]()))
            hp = target.stats.active[Stat.HP_CURR]()
            hp_max = target.stats.active[Stat.HP_MAX]()
            target.stats.base[Stat.HP_CURR] = min(hp_max, hp + heal)
            result['damage'] = -heal  # negative = healing
            result['effect_applied'] = True
            if target is not self:
                target.record_interaction(self, 4.0)

        elif effect in ('buff', 'debuff'):
            if spell['buffs']:
                from classes.creature import Creature
                Creature._next_consumable_id += 1
                source = f'spell_{Creature._next_consumable_id}'
                for stat, amount in spell['buffs'].items():
                    self.stats.add_mod(source, stat, amount) if target is self \
                        else target.stats.add_mod(source, stat, amount)

                # Schedule expiry if duration > 0
                if spell['duration'] > 0:
                    tick_name = f'expire_{source}'
                    interval_ms = int(spell['duration'] * 1000)
                    t = target
                    def _expire(_now, s=source, tn=tick_name, tgt=t):
                        tgt.stats.remove_mods_by_source(s)
                        tgt.unregister_tick(tn)
                    target.register_tick(tick_name, interval_ms, _expire)

                result['effect_applied'] = True
                if target is not self:
                    sentiment = 3.0 if effect == 'buff' else -4.0
                    target.record_interaction(self, sentiment)

        # Secondary resist check (e.g. poison from a spell)
        if spell['secondary_resist'] and spell['secondary_dc']:
            from classes.stats import Stat as S
            resist_stat_name = spell['secondary_resist']
            # Look up the Stat enum by value string
            resist_stat = None
            for s in S:
                if s.value == resist_stat_name:
                    resist_stat = s
                    break
            if resist_stat and target is not self:
                blocked = target.stats.resist_check(spell['secondary_dc'], resist_stat)
                if not blocked:
                    result['secondary_applied'] = True

        return result

    def get_known_spells(self) -> list[str]:
        """Return spell keys this creature knows (from species + creature lists)."""
        from data.db import SPELL_LISTS
        spells = []
        # Species spells
        if self.species:
            spells.extend(SPELL_LISTS.get(self.species, []))
        # Creature-specific spells
        spells.extend(SPELL_LISTS.get(self.name, []))
        return list(dict.fromkeys(spells))  # dedupe preserving order

    def grapple(self, target) -> dict:
        """Initiate a grapple with an adjacent creature.

        Contest: d20 + max(STR, AGL) vs d20 + max(STR, AGL-1).
        High stamina cost. Loser takes social/dominance hit.
        Returns dict: success, margin, reason.
        """
        result = {'success': False, 'margin': 0, 'reason': ''}

        if self._sight_distance(target) > 1:
            result['reason'] = 'not_adjacent'
            return result

        # High stamina cost
        stamina_cost = 15
        cur_stam = self.stats.active[Stat.CUR_STAMINA]()
        if cur_stam < stamina_cost:
            result['reason'] = 'no_stamina'
            return result
        self.stats.base[Stat.CUR_STAMINA] = cur_stam - stamina_cost
        self._ensure_stamina_regen()

        # Attacker: max(STR, AGL)
        atk_str = self.stats.active[Stat.STR]()
        atk_agl = self.stats.active[Stat.AGL]()
        atk_val = max(atk_str, atk_agl) + random.randint(1, 20)

        # Defender: max(STR, AGL-1) — slight agility disadvantage
        def_str = target.stats.active[Stat.STR]()
        def_agl = target.stats.active[Stat.AGL]() - 1
        def_val = max(def_str, def_agl) + random.randint(1, 20)

        margin = atk_val - def_val
        result['margin'] = margin

        if margin > 0:
            result['success'] = True
            # Winner dominance: positive for self, negative for loser
            self.record_interaction(target, 2.0)
            target.record_interaction(self, -5.0)
        else:
            result['reason'] = 'escaped'
            # Loser takes social hit, both negative
            self.record_interaction(target, -3.0)
            target.record_interaction(self, -2.0)

        return result

    def _check_trap(self, tile):
        """Check if a tile has a trap and resolve it against this creature."""
        trap_dc = tile.stat_mods.get('trap_dc')
        if trap_dc is None:
            return
        if tile.stat_mods.get('trap_creator_uid') == self.uid:
            return

        # Detection check: d20 + DETECTION vs trap_dc
        detection = self.stats.active[Stat.DETECTION]()
        roll = random.randint(1, 20) + detection
        if roll >= trap_dc:
            # Detected — trap is revealed but not triggered
            return

        # Trap triggered — find trap item on tile
        trap_name = tile.stat_mods.get('trap_item', '')
        trap_item = None
        for item in tile.inventory.items:
            if item.name == trap_name:
                trap_item = item
                break

        # Apply trap damage (trap_dc as rough damage proxy)
        damage = max(1, trap_dc // 2)
        hp = self.stats.active[Stat.HP_CURR]()
        self.stats.base[Stat.HP_CURR] = max(0, hp - damage)
        self.on_hit(0)

        # Remove trap after triggering
        if trap_item:
            tile.inventory.items.remove(trap_item)
        tile.stat_mods.pop('trap_dc', None)
        tile.stat_mods.pop('trap_item', None)
        tile.stat_mods.pop('trap_creator_uid', None)

    def die(self):
        """Handle creature death: drop inventory + gold, maybe become ghost."""
        tile = self.current_map.tiles.get(self.location)
        if tile:
            tile.gold += self.gold
            self.gold = 0
            for item in list(self.inventory.items):
                tile.inventory.items.append(item)
            self.inventory.items.clear()
            for item in set(self.equipment.values()):
                tile.inventory.items.append(item)
                self.stats.remove_mods_by_source(f'equip_{item.uid}')
            self.equipment.clear()

        # 1% chance to become a ghost
        if random.random() < 0.01:
            self._become_ghost()
            return

        self.play_animation('death')
        self._timed_events.clear()

        # Permanently remove non-ghost dead creature from spatial registries.
        # Keep incoming relationship edges — survivors remember the dead.
        from classes.creature import Creature
        from classes.relationship_graph import GRAPH
        Creature._uid_registry.pop(self.uid, None)
        if self._current_map and hasattr(self._current_map, 'unregister_creature_at'):
            self._current_map.unregister_creature_at(
                self, self.location.x, self.location.y, self.location.z)
        # Clear only the dead creature's own memories, not others' memories of them
        GRAPH._edges.pop(self.uid, None)
        GRAPH._rumors.pop(self.uid, None)
        GRAPH._deceits.pop(self.uid, None)
        self.current_map = None

    def _become_ghost(self):
        """Transform this creature into a ghost that haunts periodically."""
        from classes.relationship_graph import GRAPH

        self.is_ghost = True
        map_name = getattr(self.current_map, 'name', '') or ''
        self._ghost_death_location = (map_name, self.location.x, self.location.y)

        # Determine death day from game clock
        try:
            from classes.creature._utility import _current_hour
            # Find game day via Trackable scan for GameClock
            from classes.trackable import Trackable
            for obj in Trackable.all_instances():
                if hasattr(obj, 'day') and hasattr(obj, 'hour'):
                    self._ghost_death_day = int(obj.day)
                    break
        except Exception:
            self._ghost_death_day = 0

        # Find worst enemy and closest friend to haunt
        rels = GRAPH.edges_from(self.uid)
        worst_uid = None
        worst_sent = 0.0
        best_uid = None
        best_sent = 0.0
        for uid, rel in rels.items():
            if rel[0] < worst_sent:
                worst_sent = rel[0]
                worst_uid = uid
            if rel[0] > best_sent:
                best_sent = rel[0]
                best_uid = uid
        self._ghost_haunt_uid = worst_uid     # worst enemy
        self._ghost_loved_uid = best_uid      # closest friend
        self._ghost_visit_count = 0           # alternates targets

        # Ghost starts invisible — will manifest on schedule
        self._ghost_visible = False
        self.stats.base[Stat.HP_CURR] = 1  # alive but ghostly

        # Unregister from spatial grid (invisible until manifested)
        if self._current_map and hasattr(self._current_map, 'unregister_creature_at'):
            self._current_map.unregister_creature_at(
                self, self.location.x, self.location.y, self.location.z)

        # Register ghost tick — checks manifestation schedule
        self.register_tick('ghost', 500, self._do_ghost_tick)
        self.play_animation('idle')

    def _do_ghost_tick(self, now: int):
        """Periodic ghost check: manifest/demanifest and spook nearby."""
        if not self.is_ghost:
            return

        cur_day = 0
        cur_hour = 12.0
        try:
            from classes.trackable import Trackable
            for obj in Trackable.all_instances():
                if hasattr(obj, 'day') and hasattr(obj, 'hour'):
                    cur_day = int(obj.day)
                    cur_hour = obj.hour
                    break
        except Exception:
            return

        days_since = cur_day - self._ghost_death_day
        is_haunt_day = days_since >= 0 and days_since % 7 == 0
        is_haunt_hour = cur_hour >= 23.0 or cur_hour < 1.0
        should_show = is_haunt_day and is_haunt_hour

        if should_show and not self._ghost_visible:
            self._manifest()
        elif not should_show and self._ghost_visible:
            self._demanifest()

        # Spook nearby living creatures while manifested
        if self._ghost_visible:
            self._spook_nearby()

    def _manifest(self):
        """Ghost becomes visible — alternates between enemy, friend, and death spot."""
        from classes.creature import Creature
        from classes.maps import MapKey

        self._ghost_visible = True
        self._ghost_visit_count = getattr(self, '_ghost_visit_count', 0) + 1

        # Cycle: enemy → death spot → friend → death spot → ...
        cycle = self._ghost_visit_count % 4
        target = None
        if cycle == 0 and self._ghost_haunt_uid is not None:
            target = Creature.by_uid(self._ghost_haunt_uid)
        elif cycle == 2 and getattr(self, '_ghost_loved_uid', None) is not None:
            target = Creature.by_uid(self._ghost_loved_uid)

        if target is not None and target.current_map == self.current_map:
            self.location = MapKey(target.location.x + random.choice([-1, 0, 1]),
                                   target.location.y + random.choice([-1, 0, 1]),
                                   target.location.z)
        elif self._ghost_death_location:
            map_name, dx, dy = self._ghost_death_location
            self.location = MapKey(dx, dy, 0)

        # Re-register in spatial grid
        if self._current_map and hasattr(self._current_map, 'register_creature_at'):
            self._current_map.register_creature_at(
                self, self.location.x, self.location.y, self.location.z)
        Creature._uid_registry[self.uid] = self
        self.play_animation('ghost')

    def _spook_nearby(self):
        """Affect living creatures within 3 tiles based on the ghost's
        relationship with each target.

        The ghost's pre-death sentiment toward the target determines
        the interaction:
          Hated (< -10): terrifying — strong fear debuff, big sentiment hit
          Disliked (-10 to -3): unsettling — moderate fear
          Neutral (-3 to +3): eerie — mild unease
          Liked (+3 to +10): bittersweet — small positive sentiment
          Loved (> +10): protective — warmth, small stat buff
        """
        from classes.sound import emit_sound
        from classes.relationship_graph import GRAPH

        # Ghost's preserved feelings toward others
        ghost_rels = GRAPH.edges_from(self.uid)

        emit_sound(self, 'death_cry', volume=4.0, tick=0)

        for other in self.nearby(max_dist=3):
            if other.is_ghost:
                continue

            # How did the ghost feel about this creature in life?
            rel = ghost_rels.get(other.uid)
            ghost_sentiment = rel[0] if rel else 0.0

            source = f'spooked_{self.uid}'

            if ghost_sentiment < -10:
                # Hated: terrifying haunting
                other.record_interaction(self, -3.0)
                if not any(m['source'] == source for m in other.stats.mods):
                    other.stats.add_mod(source, Stat.PER, -3)
                    other.stats.add_mod(source, Stat.CHR, -2)
                    other.stats.add_mod(source, Stat.AGL, -1)
            elif ghost_sentiment < -3:
                # Disliked: unsettling
                other.record_interaction(self, -1.5)
                if not any(m['source'] == source for m in other.stats.mods):
                    other.stats.add_mod(source, Stat.PER, -1)
                    other.stats.add_mod(source, Stat.CHR, -1)
            elif ghost_sentiment <= 3:
                # Neutral: eerie presence
                other.record_interaction(self, -0.5)
            elif ghost_sentiment <= 10:
                # Liked: bittersweet visitation
                other.record_interaction(self, 0.5)
            else:
                # Loved: protective presence
                other.record_interaction(self, 1.0)
                if not any(m['source'] == source for m in other.stats.mods):
                    other.stats.add_mod(source, Stat.PER, 1)
                    other.stats.add_mod(source, Stat.CHR, 1)

    def _demanifest(self):
        """Ghost fades away until next haunting cycle."""
        from classes.creature import Creature

        # Remove fear debuffs from all creatures this ghost spooked
        source = f'spooked_{self.uid}'
        for c in self.nearby(max_dist=10):
            c.stats.remove_mods_by_source(source)

        self._ghost_visible = False
        Creature._uid_registry.pop(self.uid, None)
        if self._current_map and hasattr(self._current_map, 'unregister_creature_at'):
            self._current_map.unregister_creature_at(
                self, self.location.x, self.location.y, self.location.z)

    @property
    def is_alive(self) -> bool:
        if self.is_ghost:
            return self._ghost_visible
        if self.current_map is None:
            return False
        return self.stats.active[Stat.HP_CURR]() > 0

    @property
    def is_targetable(self) -> bool:
        """Ghosts can be seen but not targeted for combat, trade, or social."""
        return self.is_alive and not self.is_ghost
