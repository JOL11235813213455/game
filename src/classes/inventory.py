from __future__ import annotations
from enum import Enum
from classes.trackable import Trackable
from classes.world_object import WorldObject


class Slot(Enum):
    HEAD        = 'head'
    NECK        = 'neck'
    SHOULDERS   = 'shoulders'
    CHEST       = 'chest'
    BACK        = 'back'
    WRISTS      = 'wrists'
    HANDS       = 'hands'
    WAIST       = 'waist'
    LEGS        = 'legs'
    FEET        = 'feet'
    RING_L      = 'ring_l'
    RING_R      = 'ring_r'
    HAND_L      = 'hand_l'
    HAND_R      = 'hand_r'


class Item(WorldObject):
    z_index   = 2
    collision = False
    def __init__(
        self
        ,name: str = ''
        ,description: str = ''
        ,weight: float = 0
        ,value: float = 0
        ,sprite_name: str = None
        ,inventoriable: bool = True
        ,buffs: dict = None
        ,action_word: str = ''
        ,requirements: dict = None
        ):
        super().__init__()
        self.name         = name
        self.description  = description
        self.weight       = weight
        self.value        = value
        self.sprite_name  = sprite_name
        self.inventoriable = inventoriable
        self.buffs        = buffs or {}
        self.action_word  = action_word
        self.requirements = requirements or {}

    # -- KPI Valuation ------------------------------------------------------

    # Stat weights for KPI scoring — how valuable each derived stat point is
    # in gold-equivalent terms. Tunable constants.
    _STAT_WEIGHTS = None  # lazy-loaded to avoid circular imports

    @classmethod
    def _get_stat_weights(cls) -> dict:
        if cls._STAT_WEIGHTS is None:
            from classes.stats import Stat
            cls._STAT_WEIGHTS = {
                Stat.HP_MAX: 2.0, Stat.MELEE_DMG: 3.0, Stat.RANGED_DMG: 3.0,
                Stat.MAGIC_DMG: 3.0, Stat.ACCURACY: 2.0, Stat.CRIT_CHANCE: 1.5,
                Stat.CRIT_DMG: 1.5, Stat.DODGE: 2.5, Stat.ARMOR: 2.5,
                Stat.BLOCK: 2.0, Stat.MOVE_SPEED: 1.5, Stat.SIGHT_RANGE: 1.0,
                Stat.HEARING_RANGE: 0.5, Stat.STEALTH: 1.5, Stat.DETECTION: 1.5,
                Stat.CARRY_WEIGHT: 0.5, Stat.MAX_STAMINA: 1.5, Stat.MAX_MANA: 1.5,
                Stat.MANA_REGEN: 1.0, Stat.STAM_REGEN: 1.0,
                Stat.POISON_RESIST: 1.0, Stat.DISEASE_RESIST: 1.0,
                Stat.MAGIC_RESIST: 1.5, Stat.STAGGER_RESIST: 1.0,
                Stat.FEAR_RESIST: 1.0, Stat.PERSUASION: 1.0,
                Stat.INTIMIDATION: 1.0, Stat.DECEPTION: 1.0,
                Stat.COMPANION_LIMIT: 0.5, Stat.CRAFT_QUALITY: 0.5,
                Stat.LOOT_GINI: 0.5, Stat.XP_MOD: 1.0,
            }
            # Base stats — changes cascade through derived, so weight them higher
            for s in (Stat.STR, Stat.VIT, Stat.AGL, Stat.PER,
                      Stat.INT, Stat.CHR, Stat.LCK):
                cls._STAT_WEIGHTS[s] = 4.0
        return cls._STAT_WEIGHTS

    def effective_kpi(self, creature) -> float:
        """Compute this item's effective KPI for a specific creature.

        Temporarily applies all buffs, snapshots the stat delta,
        and scores the changes by stat weights.

        Returns a gold-equivalent utility score.
        """
        if not self.buffs:
            # Items with no buffs: use base value as KPI
            return self.value

        weights = self._get_stat_weights()

        # Snapshot before
        before = creature.stats.snapshot()

        # Temporarily apply buffs
        mods = []
        source = '_kpi_eval'
        for stat, amount in self.buffs.items():
            mods.append(creature.stats.add_mod(source, stat, amount))

        # Snapshot after
        after = creature.stats.snapshot()

        # Remove temp mods
        for mod in mods:
            creature.stats.remove_mod(mod)

        # Score the deltas
        score = 0.0
        for stat in after:
            delta = after[stat] - before.get(stat, 0)
            if delta != 0:
                w = weights.get(stat, 1.0)
                score += delta * w

        # Add primary item attributes
        if hasattr(self, 'damage') and self.damage:
            score += self.damage * 2.0

        return max(0.0, score)

    def lifetime_kpi(self, creature) -> float:
        """Duration-weighted KPI: effective_kpi × durability × quality bonus.

        Captures total remaining value over the item's lifespan.
        """
        eff = self.effective_kpi(creature)

        # Durability ratio (if applicable)
        dur_ratio = 1.0
        if hasattr(self, 'durability_max') and self.durability_max > 0:
            dur_cur = getattr(self, 'durability_current', self.durability_max)
            dur_ratio = dur_cur / self.durability_max

        # Craft quality bonus: each level adds 10%
        craft_bonus = 1.0
        if creature:
            from classes.stats import Stat
            cq = creature.stats.active[Stat.CRAFT_QUALITY]()
            craft_bonus = 1.0 + max(0, cq) * 0.1

        return eff * dur_ratio * craft_bonus

class Stackable(Item):

    def __init__(self, *args, max_stack_size: int = 99, quantity: int = 1, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_stack_size = max_stack_size
        self.quantity       = quantity

    def add(self, amount: int, inventory: Inventory) -> int:
        """
        Add amount to this stack. If the stack is full, create new stacks in
        the inventory for the overflow. Returns any amount that could not fit.
        """
        space = self.max_stack_size - self.quantity
        added = min(amount, space)
        self.quantity += added
        remaining = amount - added
        while remaining > 0:
            new_stack = self.__class__(
                name=self.name, description=self.description,
                weight=self.weight, value=self.value,
                sprite_name=self.sprite_name, inventoriable=self.inventoriable,
                buffs=dict(self.buffs), max_stack_size=self.max_stack_size,
                quantity=0,
            )
            inventory.items.append(new_stack)
            chunk = min(remaining, self.max_stack_size)
            new_stack.quantity = chunk
            remaining -= chunk
        return 0

    @staticmethod
    def coalesce(inventory: Inventory):
        """Merge stacks of the same item type (matched by name) where possible."""
        from collections import defaultdict
        groups: dict[str, list[Stackable]] = defaultdict(list)
        for item in inventory.items:
            if isinstance(item, Stackable):
                groups[item.name].append(item)
        for name, stacks in groups.items():
            stacks.sort(key=lambda s: s.quantity)
            for i in range(len(stacks) - 1):
                src = stacks[i]
                for dst in stacks[i + 1:]:
                    if dst.quantity >= dst.max_stack_size:
                        continue
                    space = dst.max_stack_size - dst.quantity
                    move  = min(src.quantity, space)
                    dst.quantity += move
                    src.quantity -= move
        inventory.items = [i for i in inventory.items
                           if not isinstance(i, Stackable) or i.quantity > 0]


class Consumable(Stackable):

    def __init__(self, *args, duration: float = 0.0,
                 heal_amount: int = 0, mana_restore: int = 0,
                 stamina_restore: int = 0, **kwargs):
        super().__init__(*args, **kwargs)
        self.duration         = duration
        self.heal_amount      = heal_amount       # direct HP heal
        self.mana_restore     = mana_restore      # direct mana restore
        self.stamina_restore  = stamina_restore   # direct stamina restore


class Ammunition(Stackable):

    def __init__(self, *args, damage: float = 0, destroy_on_use_probability: float = 1.0,
                 recoverable: bool = True, status_effect: str = None,
                 status_dc: int = 0, **kwargs):
        super().__init__(*args, **kwargs)
        self.damage                    = damage
        self.destroy_on_use_probability = destroy_on_use_probability
        self.recoverable               = recoverable
        self.status_effect             = status_effect  # e.g. 'poison'
        self.status_dc                 = status_dc      # DC for status resist


class Meat(Consumable):
    """Meat dropped from a killed creature or monster.

    Carries the species tag of the deceased so consumers can detect
    cannibalism. Spoils in 48 game-hours unless cooked (+48hr) or
    preserved (permanent).
    """

    def __init__(self, *args,
                 species: str = None,
                 meat_value: float = 0.3,
                 spoil_tick: int = 0,
                 is_cooked: bool = False,
                 is_preserved: bool = False,
                 is_monster_meat: bool = False,
                 **kwargs):
        # Hunger restoration maps to Consumable's heal_amount conceptually,
        # but we use meat_value directly when a creature eats meat.
        kwargs.setdefault('is_food', True)
        super().__init__(*args, **kwargs)
        self.species = species
        self.meat_value = meat_value
        self.spoil_tick = spoil_tick
        self.is_cooked = is_cooked
        self.is_preserved = is_preserved
        self.is_monster_meat = is_monster_meat

    def is_spoiled(self, now: int) -> bool:
        if self.is_preserved:
            return False
        return now >= self.spoil_tick


class Equippable(Item):

    def __init__(
        self
        ,*args
        ,slots: list[Slot] = None
        ,slot_count: int = 1
        ,durability_max: int = 100
        ,durability_current: int = None
        ,render_on_creature: bool = False
        ,**kwargs
        ):
        super().__init__(*args, **kwargs)
        self.slots              = slots or []
        self.slot_count         = slot_count
        self.durability_max     = durability_max
        self.durability_current = durability_current if durability_current is not None else durability_max
        self.render_on_creature = render_on_creature


class Weapon(Equippable):

    def __init__(
        self
        ,*args
        ,damage: float = 0
        ,attack_time_ms: int = 500
        ,directions: list[str] = None
        ,range: int = 1
        ,ammunition_type: str = None
        ,hit_dice: int = 0
        ,hit_dice_count: int = 0
        ,crit_chance_mod: int = 0
        ,crit_damage_mod: float = 0
        ,stagger_dc: int = 0
        ,stamina_cost: int = 0
        ,status_effect: str = None
        ,status_dc: int = 0
        ,is_natural: bool = False
        ,infinite_ammo: bool = False
        ,**kwargs
        ):
        super().__init__(*args, **kwargs)
        self.damage           = damage
        self.attack_time_ms   = attack_time_ms
        self.directions       = directions or ['front']
        self.range            = range
        self.ammunition_type  = ammunition_type
        self.hit_dice         = hit_dice          # e.g. 6 for d6
        self.hit_dice_count   = hit_dice_count    # e.g. 2 for 2d6
        self.crit_chance_mod  = crit_chance_mod   # +/- to crit chance %
        self.crit_damage_mod  = crit_damage_mod   # +/- to crit damage multiplier
        self.stagger_dc       = stagger_dc or int(damage)  # DC for stagger check
        self.stamina_cost     = stamina_cost      # 0 = use default formula
        self.status_effect    = status_effect      # e.g. 'poison', 'bleed'
        self.status_dc        = status_dc          # DC for status resist
        self.is_natural       = is_natural         # monster-origin (e.g. acid spit)
        self.infinite_ammo    = infinite_ammo      # ranged natural weapons don't need ammo

class Wearable(Equippable):
    pass

class Structure(Item):
    z_index   = 1
    collision = False

    def __init__(
        self
        ,*args
        ,footprint: list[list[int]] = None
        ,collision_mask: list[list[int]] = None
        ,entry_points: dict[str, list[int]] = None
        ,nested_map: str = None
        ,**kwargs
        ):
        kwargs.setdefault('inventoriable', False)
        super().__init__(*args, **kwargs)
        self.footprint      = [tuple(p) for p in (footprint or [[0, 0]])]
        self.collision_mask  = [tuple(p) for p in (collision_mask or list(self.footprint))]
        self.entry_points    = entry_points or {}
        self.nested_map_name = nested_map
        self.wall_face: str | None = None  # N/S/E/W — locks sprite to a wall face in first-person

class Egg(Item):
    """An egg containing an unhatched creature.

    The egg is a special item: it contains a full Creature object that
    cannot act until hatched. The creature inside has genetics, stats,
    parents, species — but zero agency.
    """
    z_index   = 2
    collision = False

    def __init__(
        self,
        creature=None,
        mother_species: str = '',
        father_species: str = '',
        **kwargs,
    ):
        kwargs.setdefault('name', 'Egg')
        kwargs.setdefault('description', 'A fertilized egg')
        kwargs.setdefault('weight', 1.0)
        kwargs.setdefault('value', 2.0)
        kwargs.setdefault('inventoriable', True)
        super().__init__(**kwargs)
        self.creature = creature           # the Creature inside (unhatched)
        self.live = True                   # False = stopped growing / dead
        self.days_with_mother = 0          # days carried by biological mother
        self.gestation_days = 0            # total days since conception
        self.gestation_period = 30         # days until hatch
        self.mother_species = mother_species
        self.father_species = father_species

    @property
    def is_abomination(self) -> bool:
        return self.mother_species != self.father_species

    @property
    def ready_to_hatch(self) -> bool:
        return self.live and self.gestation_days >= self.gestation_period

    def tick_gestation(self, carried_by_mother: bool = False):
        """Advance one day of gestation.

        Args:
            carried_by_mother: True if biological mother is carrying this egg
        """
        if not self.live:
            return
        self.gestation_days += 1
        if carried_by_mother:
            self.days_with_mother += 1

        # Random chance of egg dying (~1% per day)
        import random
        if random.random() < 0.01:
            self.live = False

    def apply_maternal_buff(self):
        """Apply stat buff to the creature based on time with mother.

        Full 30 days → +2 to a random base stat.
        Partial time → proportional chance of +1.
        """
        if self.creature is None or self.days_with_mother <= 0:
            return
        import random
        from classes.stats import Stat, BASE_STATS
        ratio = min(1.0, self.days_with_mother / self.gestation_period)
        # Full term = guaranteed +2 to random stat, partial = proportional
        bonus = 2 if ratio >= 1.0 else (1 if random.random() < ratio else 0)
        if bonus > 0:
            stat = random.choice(list(BASE_STATS))
            if hasattr(self.creature, 'stats'):
                self.creature.stats.base[stat] = self.creature.stats.base.get(stat, 0) + bonus

    def hatch(self, game_map, location):
        """Hatch the egg: apply maternal buff, create proper creature on map.

        Returns the Creature, or None if egg is dead.
        """
        if not self.live or self.creature is None:
            return None

        self.apply_maternal_buff()
        embryo = self.creature

        # If the embryo has stored stats (from _execute_pairing), use them
        # to create a proper fully-initialized Creature
        stats = getattr(embryo, '_stats_for_egg', None)
        if stats is not None:
            from classes.creature import Creature
            child = Creature(
                current_map=game_map,
                location=location,
                name=embryo.name,
                species=embryo.species,
                stats=stats,
                sex=embryo.sex,
                age=0,
                chromosomes=embryo.chromosomes,
                mother_uid=embryo.mother_uid,
                father_uid=embryo.father_uid,
                is_abomination=embryo.is_abomination,
                prudishness=embryo.prudishness,
            )
            child.inbred = getattr(embryo, 'inbred', False)
        else:
            # Fallback: embryo is already a full Creature
            embryo.current_map = game_map
            embryo.location = location
            embryo.age = 0
            child = embryo

        self.live = False  # Egg is consumed
        self.creature = child  # Update reference
        return child


class ItemFrame(Item):
    """Crafting frame: holds a recipe and an inventory of ingredient parts.

    The frame IS the item when complete — a sword frame with blade, hilt,
    and pommel becomes the usable sword. Parts retain their individual
    crafter_uid, and multi-crafter items are intrinsically more valuable.

    Two completion behaviors (controlled by `consumable_output`):
    - False (default): the frame itself becomes the finished item. Stats,
      buffs, equip slots all come from the frame's own properties.
      Disassembly pops parts back into owner inventory.
    - True (food/potions): produces a consumable output, destroys all
      ingredients and the frame itself.

    If auto_pop is True, picking up any matching ingredient auto-creates
    the frame in the creature's inventory.

    When items are spawned from DB with a recipe, they spawn as a
    complete ItemFrame with all parts already inside.
    """
    z_index = 2
    collision = False

    def __init__(
        self,
        frame_key: str = '',
        recipe: dict = None,
        auto_pop: bool = False,
        consumable_output: bool = False,
        output_item_factory: callable = None,
        composite_name: str = None,
        **kwargs,
    ):
        kwargs.setdefault('name', f'Frame: {frame_key}')
        kwargs.setdefault('inventoriable', True)
        kwargs.setdefault('weight', 0.1)
        kwargs.setdefault('value', 0)
        super().__init__(**kwargs)
        self.frame_key = frame_key
        # recipe: {item_key: required_count}
        self.recipe: dict[str, int] = recipe or {}
        # internal inventory holding ingredient parts
        self.ingredients: Inventory = Inventory()
        self.auto_pop = auto_pop
        self.composite_name = composite_name
        # consumable_output: if True, crafting produces a separate item and
        # destroys the frame + ingredients (food, potions).
        # If False, the frame itself IS the finished item.
        self.consumable_output = consumable_output
        self._output_factory = output_item_factory

    @property
    def is_complete(self) -> bool:
        """True when all recipe ingredients are present."""
        for item_key, needed in self.recipe.items():
            count = self._count_ingredient(item_key)
            if count < needed:
                return False
        return True

    @property
    def completion_ratio(self) -> float:
        """0.0 to 1.0 — fraction of recipe satisfied."""
        if not self.recipe:
            return 1.0
        total_needed = sum(self.recipe.values())
        total_have = 0
        for item_key, needed in self.recipe.items():
            total_have += min(self._count_ingredient(item_key), needed)
        return total_have / max(1, total_needed)

    @property
    def crafter_uids(self) -> set[int]:
        """Set of unique crafter UIDs across all ingredient parts."""
        uids = set()
        for item in self.ingredients.items:
            uid = getattr(item, 'crafter_uid', None)
            if uid is not None:
                uids.add(uid)
        return uids

    @property
    def multi_crafter_bonus(self) -> float:
        """Value multiplier from multiple unique crafters.

        Each additional unique crafter adds 10% to item value.
        A solo-crafted item = 1.0x. Two crafters = 1.1x. Three = 1.2x.
        """
        n = len(self.crafter_uids)
        return 1.0 + max(0, n - 1) * 0.1

    @property
    def value(self) -> float:
        """Total value: sum of parts × multi-crafter bonus."""
        parts_value = sum(getattr(i, 'value', 0) for i in self.ingredients.items)
        base = self._base_value if hasattr(self, '_base_value') else super().value
        return (parts_value + base) * self.multi_crafter_bonus

    @value.setter
    def value(self, v):
        self._base_value = v

    @property
    def weight(self) -> float:
        """Total weight: frame weight + all parts."""
        parts_weight = sum(getattr(i, 'weight', 0) for i in self.ingredients.items)
        base = self._base_weight if hasattr(self, '_base_weight') else 0.1
        return parts_weight + base

    @weight.setter
    def weight(self, v):
        self._base_weight = v

    def _count_ingredient(self, item_key: str) -> int:
        return sum(1 for i in self.ingredients.items
                   if getattr(i, 'name', '') == item_key
                   or getattr(i, 'key', '') == item_key)

    def add_ingredient(self, item) -> bool:
        """Add an item to the frame's ingredient inventory.

        Returns True if the item is a valid ingredient and was added.
        """
        item_id = getattr(item, 'key', '') or getattr(item, 'name', '')
        if item_id not in self.recipe:
            return False
        needed = self.recipe[item_id]
        if self._count_ingredient(item_id) >= needed:
            return False
        self.ingredients.items.append(item)
        return True

    def remove_ingredient(self, item) -> bool:
        """Remove an ingredient from the frame back to caller.

        Returns True if removed.
        """
        if item in self.ingredients.items:
            self.ingredients.items.remove(item)
            return True
        return False

    def try_complete(self, owner) -> 'Item | None':
        """Attempt to finalize crafting.

        For consumable_output frames: produces output item, destroys
        ingredients and frame, returns the output.

        For non-consumable frames: the frame itself IS the finished item.
        Returns self (caller should NOT destroy it).
        """
        if not self.is_complete:
            return None

        if not self.consumable_output:
            # Frame IS the item — nothing to produce or destroy
            return self

        # Consumable path: produce output, destroy everything
        output = None
        if self._output_factory:
            output = self._output_factory()
        if output is None:
            return None

        # Apply craft quality from owner
        from classes.stats import Stat
        craft_quality = owner.stats.active[Stat.CRAFT_QUALITY]()
        if hasattr(output, 'durability_max') and output.durability_max > 0:
            bonus = max(0, craft_quality) * 0.05
            output.durability_max = int(output.durability_max * (1 + bonus))
            output.durability_current = output.durability_max

        # Stamp crafter (use all unique crafter UIDs as a set)
        output.crafter_uid = owner.uid

        # Destroy all ingredients and frame
        self.ingredients.items.clear()
        owner.inventory.items.append(output)
        if self in owner.inventory.items:
            owner.inventory.items.remove(self)

        return output

    def disassemble_into(self, owner_inventory: 'Inventory') -> list:
        """Pop all parts out of frame into the target inventory.

        Frame remains in place (now incomplete/empty).
        Returns list of items moved out.
        """
        moved = list(self.ingredients.items)
        for item in moved:
            owner_inventory.items.append(item)
        self.ingredients.items.clear()
        return moved


CLASS_MAP: dict[str, type] = {
    'Item':       Item,
    'Stackable':  Stackable,
    'Consumable': Consumable,
    'Ammunition': Ammunition,
    'Weapon':     Weapon,
    'Wearable':   Wearable,
    'Structure':  Structure,
    'Egg':        Egg,
    'ItemFrame':  ItemFrame,
}

class Inventory(Trackable):
    def __init__(self, items: list = None):
        super().__init__()
        self.items: list[Item] = list(items) if items else []
