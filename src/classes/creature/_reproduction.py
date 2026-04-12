from __future__ import annotations
import random
from classes.stats import Stat
from classes.inventory import Egg
from classes.world_object import WorldObject
from classes.maps import MapKey
from classes.relationship_graph import GRAPH


class ReproductionMixin:
    """Reproduction, pairing, and egg methods for Creature."""

    ADULT_AGE = 18  # minimum age for pairing
    PAIR_COOLDOWN_DAYS = 1  # days between pairings (both sexes)

    @staticmethod
    def _species_gate(male, female) -> bool:
        """Species knockout check. Returns True if pairing can proceed."""
        m_abom = male.is_abomination
        f_abom = female.is_abomination

        # Abom + abom: always pass
        if m_abom and f_abom:
            return True
        # Abom male + non-abom female: never willing
        if m_abom and not f_abom:
            return False
        # Non-abom male + abom female: 0.5% chance
        if not m_abom and f_abom:
            return random.random() < 0.005
        # Same species: pass
        if male.species == female.species:
            return True
        # Different species: 1% chance
        return random.random() < 0.01

    @staticmethod
    def desirability(creature, evaluator) -> float:
        """Compute desirability score of a creature from evaluator's perspective.

        Factors: stats (sex-weighted), wealth, reputation.
        Species gate is checked separately — this only runs after gate passes.
        """
        # Stat score: sex-dependent weighting
        if evaluator.sex == 'female':
            # Females value STR, CHR, INT
            stat_score = (
                creature.stats.active[Stat.STR]() * 0.3 +
                creature.stats.active[Stat.CHR]() * 0.3 +
                creature.stats.active[Stat.INT]() * 0.2 +
                creature.stats.active[Stat.VIT]() * 0.1 +
                creature.stats.active[Stat.LCK]() * 0.1
            ) / 20.0  # normalize to ~1.0
        else:
            # Males value VIT, AGL, CHR
            stat_score = (
                creature.stats.active[Stat.VIT]() * 0.25 +
                creature.stats.active[Stat.AGL]() * 0.25 +
                creature.stats.active[Stat.CHR]() * 0.3 +
                creature.stats.active[Stat.LCK]() * 0.1 +
                creature.stats.active[Stat.PER]() * 0.1
            ) / 20.0

        # Wealth
        wealth = sum(getattr(i, 'value', 0) for i in creature.inventory.items)
        wealth += sum(getattr(i, 'value', 0) for i in set(creature.equipment.values()))
        wealth_score = min(1.0, wealth / 50.0)

        # Reputation (positive sentiment from others)
        if GRAPH.has_edges_from(creature.uid):
            _rels = GRAPH.edges_from(creature.uid)
            pos = sum(r[0] for r in _rels.values() if r[0] > 0)
            total = len(_rels)
            rep_score = min(1.0, pos / (total * 5 + 1))
        else:
            rep_score = 0.0

        return stat_score * 0.4 + wealth_score * 0.3 + rep_score * 0.3

    def fecundity(self) -> float:
        """Female fecundity curve: 1.0 at age 18, drops in late adulthood, 0 at old age."""
        if self.sex != 'female' or self.age < self.ADULT_AGE:
            return 0.0
        # Linear ramp from 1.0 at 18 to 0.0 at OLD_MIN
        if self.age >= self.OLD_MIN:
            return 0.0
        adult_span = self.OLD_MIN - self.ADULT_AGE
        age_in_adulthood = self.age - self.ADULT_AGE
        # Peak at 1.0, slow decline after midpoint
        midpoint = adult_span * 0.6
        if age_in_adulthood <= midpoint:
            return 1.0
        return max(0.0, 1.0 - (age_in_adulthood - midpoint) / (adult_span - midpoint))

    def propose_pairing(self, female, now: int) -> dict:
        """Male proposes pairing to a female. Uses trade-based evaluation.

        Returns dict: accepted, egg (Egg or None), reason.
        """
        result = {'accepted': False, 'egg': None, 'reason': '', 'forced': False}

        # Validation
        if self.sex != 'male' or female.sex != 'female':
            result['reason'] = 'wrong_sex'
            return result
        if self.age < self.ADULT_AGE or female.age < self.ADULT_AGE:
            result['reason'] = 'underage'
            return result
        if female.is_pregnant:
            result['reason'] = 'already_pregnant'
            return result
        if self._sight_distance(female) > 1:
            result['reason'] = 'not_adjacent'
            return result
        if now < self._pair_cooldown:
            result['reason'] = 'cooldown'
            return result

        # Species knockout gate
        if not self._species_gate(self, female):
            result['reason'] = 'species_rejected'
            return result

        # Male willingness: inverse of prudishness
        if random.random() > (1.0 - self.prudishness):
            result['reason'] = 'male_unwilling'
            return result

        # Female evaluation: relationship depth + inverse prudishness + fecundity
        rel = female.get_relationship(self)
        rel_depth = rel[0] if rel else 0.0
        min_relationship = 5.0 * female.prudishness  # higher prudishness = need more relationship
        male_desirability = self.desirability(self, female)

        # Female willingness: needs positive relationship OR sufficient desirability
        female_willing = (
            rel_depth >= min_relationship or
            male_desirability > 0.7  # very attractive males can override
        )
        female_willing = female_willing and (random.random() < (1.0 - female.prudishness))
        female_willing = female_willing and (random.random() < female.fecundity())

        if not female_willing:
            result['reason'] = 'female_unwilling'
            return result

        return self._execute_pairing(female, now, result)

    def force_pairing(self, female, now: int) -> dict:
        """Attempt forced pairing via grapple. Male-initiated only.

        Returns dict: accepted, egg, reason, forced.
        """
        result = {'accepted': False, 'egg': None, 'reason': '', 'forced': True}

        # Same validation as propose_pairing
        if self.sex != 'male' or female.sex != 'female':
            result['reason'] = 'wrong_sex'
            return result
        if self.age < self.ADULT_AGE or female.age < self.ADULT_AGE:
            result['reason'] = 'underage'
            return result
        if female.is_pregnant:
            result['reason'] = 'already_pregnant'
            return result
        if self._sight_distance(female) > 1:
            result['reason'] = 'not_adjacent'
            return result
        if now < self._pair_cooldown:
            result['reason'] = 'cooldown'
            return result
        if not self._species_gate(self, female):
            result['reason'] = 'species_rejected'
            return result

        # Grapple check
        grapple_result = self.grapple(female)
        if not grapple_result['success']:
            result['reason'] = 'grapple_failed'
            female.record_interaction(self, -8.0)
            return result

        return self._execute_pairing(female, now, result)

    def _execute_pairing(self, female, now: int, result: dict) -> dict:
        """Common pairing execution after willingness/grapple check passes."""
        from classes.genetics import (
            inherit, express, apply_genetics, check_inbreeding,
            generate_chromosomes,
        )
        from classes.creature import Creature

        # Costs
        # Male: small HP + stamina cost
        hp = self.stats.active[Stat.HP_CURR]()
        self.stats.base[Stat.HP_CURR] = max(1, hp - max(1, hp // 10))
        stam = self.stats.active[Stat.CUR_STAMINA]()
        self.stats.base[Stat.CUR_STAMINA] = max(0, stam - max(1, stam // 5))

        # Cooldowns
        day_ms = 86_400_000  # 1 game day in ms (assuming 1 day = 1440 real seconds)
        self._pair_cooldown = now + day_ms

        # Determine child sex
        child_sex = random.choice(('male', 'female'))

        # Check inbreeding
        from classes.trackable import Trackable
        lineage = {}
        for obj in Trackable.all_instances():
            if hasattr(obj, 'mother_uid') and hasattr(obj, 'father_uid'):
                lineage[obj.uid] = (obj.mother_uid, obj.father_uid)

        inbreeding_closeness = check_inbreeding(
            female.uid, self.uid, lineage, generations=3
        )

        # Generate child chromosomes
        if self.chromosomes and female.chromosomes:
            child_chroms = inherit(
                female.chromosomes, self.chromosomes,
                child_sex, inbreeding_closeness=inbreeding_closeness,
            )
        else:
            child_chroms = generate_chromosomes(child_sex)

        # Determine species
        is_abom = self.species != female.species or self.is_abomination or female.is_abomination
        child_species = female.species if not is_abom else 'abomination'

        # Derive stats from genetics
        from data.db import SPECIES
        species_stats = {}
        species_data = SPECIES.get(child_species, {})
        for k, v in species_data.items():
            if isinstance(k, Stat):
                species_stats[k] = v

        genetic_mods = express(child_chroms)
        child_stats = apply_genetics(species_stats, genetic_mods)
        child_stats[Stat.LVL] = 0

        # Create the creature inside the egg (unhatched, no map yet)
        child = Creature.__new__(Creature)
        # Minimal init — full init happens at hatch via Egg.hatch()
        child.name = None
        child.species = child_species
        child.sex = child_sex
        child.chromosomes = child_chroms
        child.mother_uid = female.uid
        child.father_uid = self.uid
        child.is_abomination = is_abom
        child.inbred = inbreeding_closeness > 0
        child.age = 0
        child.prudishness = species_data.get('prudishness', 0.5)
        # GRAPH auto-creates empty dicts on first access — no init needed
        child.is_pregnant = False
        child._pair_cooldown = 0
        child.sleep_debt = 0
        child._fatigue_level = 0
        child._stats_for_egg = child_stats  # stored for hatch init

        # Create egg
        egg = Egg(
            creature=child,
            mother_species=female.species,
            father_species=self.species,
        )

        # Mother drops abomination eggs immediately
        if is_abom:
            tile = female.current_map.tiles.get(female.location)
            if tile:
                tile.inventory.items.append(egg)
            # Reputational + psychic penalty for mother
            female.record_interaction(self, -5.0)
        else:
            # Mother carries the egg — enters pregnancy
            female.inventory.items.append(egg)
            female.is_pregnant = True
            female._pregnancy_egg = egg

            # Apply pregnancy debuffs
            female.stats.add_mod('pregnancy', Stat.HP_REGEN_DELAY, 3)
            female.stats.add_mod('pregnancy', Stat.STAM_REGEN, -2)
            female.stats.add_mod('pregnancy', Stat.MANA_REGEN, -1)
            female.stats.add_mod('pregnancy', Stat.AGL, -2)
            female.stats.add_mod('pregnancy', Stat.MOVE_SPEED, -1)
            # Pregnancy buff: loot quality
            female.stats.add_mod('pregnancy', Stat.LOOT_GINI, 0.1)

        # Record interactions
        self.record_interaction(female, 5.0)
        female.record_interaction(self, 3.0 if not result.get('forced') else -5.0)

        # Form amorous pair bond (only for willing pairings)
        if not result.get('forced'):
            self.partner_uid = female.uid
            female.partner_uid = self.uid

        result['accepted'] = True
        result['egg'] = egg
        return result

    @staticmethod
    def spawn_tent(game_map, location: MapKey) -> WorldObject:
        """Place a tent sprite on the map during a pairing act.

        Returns the tent WorldObject for later removal.
        """
        tent = WorldObject(current_map=game_map, location=location)
        tent.sprite_name = 'tent_pairing'
        tent.z_index = 4  # above creatures
        tent.collision = False
        tent.tile_scale = 2.0
        return tent

    @staticmethod
    def despawn_tent(tent: WorldObject):
        """Remove a tent from the map."""
        tent.current_map = None  # removes from _by_map index

    def end_pregnancy(self):
        """End pregnancy: remove debuffs, return egg."""
        if not self.is_pregnant:
            return None
        self.is_pregnant = False
        self.stats.remove_mods_by_source('pregnancy')
        egg = getattr(self, '_pregnancy_egg', None)
        self._pregnancy_egg = None
        # Female cooldown: 1 day after hatching
        self._pair_cooldown = 86_400_000  # reset by caller with actual timestamp
        return egg

    @property
    def has_partner(self) -> bool:
        return self.partner_uid is not None

    def get_partner(self):
        """Find partner creature by UID on the same map."""
        from classes.creature import Creature
        if self.partner_uid is None:
            return None
        for obj in WorldObject.on_map(self.current_map):
            if isinstance(obj, Creature) and obj.uid == self.partner_uid:
                return obj
        return None

    def break_pair_bond(self):
        """End the amorous pair bond. Updates both partners."""
        partner = self.get_partner()
        self.partner_uid = None
        if partner:
            partner.partner_uid = None

    def witness_forced_encounter(self, male, female):
        """Record a witness reaction to a forced pairing encounter.

        Reaction based on relative sentiment toward male vs female:
        - Favor male: neutral (don't record)
        - Favor female: negative for male
        - Strongly hate female AND love male: positive (rare)
        """
        rel_m = self.get_relationship(male)
        rel_f = self.get_relationship(female)
        sent_m = rel_m[0] if rel_m else 0.0
        sent_f = rel_f[0] if rel_f else 0.0

        if sent_m > sent_f:
            # Favor male → neutral, don't record
            return
        elif sent_f > sent_m:
            # Favor female → negative for male
            self.record_interaction(male, -5.0)
        # Edge case: strongly hate female and love male → positive
        if sent_f < -15 and sent_m > 15:
            self.record_interaction(male, 3.0)

    def eat_egg(self, egg) -> dict:
        """Eat an egg. Major reputation event if same species.

        Returns dict: eaten, cannibalism (bool).
        """
        from classes.creature import Creature

        result = {'eaten': False, 'cannibalism': False}

        if not isinstance(egg, Egg):
            return result

        # Remove from wherever it is
        if egg in self.inventory.items:
            self.inventory.items.remove(egg)
        else:
            tile = self.current_map.tiles.get(self.location)
            if tile and egg in tile.inventory.items:
                tile.inventory.items.remove(egg)
            else:
                return result

        result['eaten'] = True
        egg.live = False

        # Check cannibalism: egg species matches eater's species
        if (egg.mother_species == self.species or egg.father_species == self.species):
            result['cannibalism'] = True
            # All witnesses record MASSIVE negative
            for obj in WorldObject.on_map(self.current_map):
                if isinstance(obj, Creature) and obj is not self and obj.can_see(self):
                    obj.record_interaction(self, -20.0)

        return result

    def bond_with_child(self, child):
        """Parent-child bonding at hatching. Both parents present gain deep bond.

        The child also records massive positive toward present parents.
        Parents always side with bonded children.
        """
        # Parent → child: massive positive
        self.record_interaction(child, 15.0)
        # Child → parent: massive positive
        child.record_interaction(self, 15.0)

    @property
    def is_adult(self) -> bool:
        return self.age >= self.ADULT_AGE

    @property
    def is_child(self) -> bool:
        return self.age < self.ADULT_AGE

    @property
    def is_fertile(self) -> bool:
        if self.sex == 'female':
            return self.fecundity() > 0
        return self.age >= self.ADULT_AGE

    @property
    def is_mother(self) -> bool:
        """True if this creature has successfully hatched a child."""
        return getattr(self, '_has_hatched_child', False)

    def mark_as_mother(self):
        """Mark this creature as having hatched a child."""
        self._has_hatched_child = True

    def age_sentiment_modifier(self, other) -> float:
        """Return a sentiment modifier based on age dynamics.

        - Older creatures exploit young (negative for young)
        - Mothers are kinder to children
        - Older women hostile to younger attractive fertile women
        - Older men favorable to younger women (inverse age curve)
        """
        mod = 0.0

        # Older creatures exploit children
        if other.is_child and self.is_adult:
            mod -= 2.0  # tendency to deceive/intimidate

        # Mothers are kinder to children
        if self.is_mother and other.is_child:
            mod += 3.0

        # Older women hostile to younger attractive fertile women
        if (self.sex == 'female' and other.sex == 'female' and
                self.age > other.age and other.is_adult and other.is_fertile):
            # More hostile if other is more attractive
            other_desir = self.desirability(other, self)
            self_desir = self.desirability(self, self)
            if other_desir >= self_desir:
                mod -= 3.0

        # Older men favorable to younger women
        if (self.sex == 'male' and other.sex == 'female' and
                self.age > other.age and other.is_adult):
            age_gap = self.age - other.age
            # Inverse curve: bigger gap = more favorable (capped)
            mod += min(3.0, age_gap / 50.0)

        return mod

    def attractiveness_rank_nearby(self) -> float:
        """How this creature ranks in attractiveness among visible same-sex creatures.

        Returns 0.0 (least attractive) to 1.0 (most attractive).
        Used for gender competition dynamics.
        """
        from classes.creature import Creature
        same_sex = []
        for obj in WorldObject.on_map(self.current_map):
            if (isinstance(obj, Creature) and obj is not self and
                    obj.sex == self.sex and obj.is_alive and self.can_see(obj)):
                same_sex.append(obj)

        if not same_sex:
            return 0.5  # no competitors → neutral

        my_desir = self.desirability(self, self)  # self-assessment proxy
        higher = sum(1 for c in same_sex
                     if self.desirability(c, self) > my_desir)
        return 1.0 - (higher / len(same_sex))

    def pairing_eagerness(self) -> float:
        """How eager this creature is to pursue pairing, considering competition.

        Males: increase eagerness with more attractive rivals (competitive drive)
        Females: reduce standards with more attractive rivals (scarcity pressure)

        Returns modifier in [-1, 1] — applied to willingness thresholds.
        """
        rank = self.attractiveness_rank_nearby()

        if self.sex == 'male':
            # More attractive rivals → more eager (competitive)
            # rank near 0 (I'm least attractive) → highest eagerness
            return 0.5 - rank  # -0.5 to +0.5
        else:
            # More attractive rivals → lower standards (accept worse deals)
            # rank near 0 (I'm least attractive) → standards drop
            return rank - 0.5  # -0.5 to +0.5

    @staticmethod
    def count_eggs_in_world() -> int:
        """Count total live eggs across all inventories and tiles."""
        count = 0
        from classes.trackable import Trackable
        for obj in Trackable.all_instances():
            if isinstance(obj, Egg) and obj.live:
                count += 1
        return count

    @staticmethod
    def egg_limit_reached(max_eggs: int = 20) -> bool:
        """Check if the world egg cap has been reached."""
        from classes.creature import Creature
        return Creature.count_eggs_in_world() >= max_eggs
