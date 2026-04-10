"""
Single-step processing recipes: raw materials → refined goods.

This is the transformation layer between HARVEST (extraction) and
USE_ITEM/TRADE (consumption/exchange). A creature standing on a
crafting-purpose tile can dispatch :class:`~classes.actions.Action.PROCESS`
to convert ingredients in its inventory into a finished item.

Two families of recipes live here:

* **Food** — raw wheat → bread, raw fish → cooked fish, etc. Output is a
  :class:`Consumable` with a better ``heal_amount`` per unit weight than
  the raw ingredient. Feeds the hunger loop.
* **Smelting / refining** — raw ore → iron ingot. Output is a tradeable
  :class:`Stackable` that wanderers/merchants can sell via TRADE. Gives
  mining a purpose beyond its (now-removed) gold-minting shortcut.

Recipes are intentionally simple: fixed input quantities, fixed output,
no tool requirements, no skill scaling. Scaling / quality / spoilage
can come later. The catalog is a module-level dict rather than a DB
table because it's small and stable — when the set grows we can move
it to :file:`src/data/db.py` like the item_frame recipes.

A recipe is:

    {
        'ingredient_name': required_quantity,
        ...
    }

The output is a factory callable that returns a fresh item with the
right name, weight, value, and (for consumables) heal_amount.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable
from classes.inventory import Stackable, Consumable


@dataclass
class Recipe:
    """One single-step transformation."""
    name: str                     # display name — 'bake_bread', 'smelt_iron'
    inputs: dict                  # {ingredient_name: quantity}
    output_factory: Callable      # () -> Item
    category: str                 # 'food' or 'material'


def _food(name: str, heal: int, value: float = 0.0, weight: float = 0.1) -> Callable:
    """Factory helper: produces a consumable food item of the given spec."""
    def _make():
        c = Consumable(
            name=name,
            description=f'Prepared {name.lower()}.',
            weight=weight,
            value=value,
            quantity=1,
            heal_amount=heal,
            duration=0,
        )
        c.is_food = True
        return c
    return _make


def _material(name: str, value: float, weight: float = 0.5) -> Callable:
    """Factory helper: produces a tradeable stackable material."""
    def _make():
        return Stackable(
            name=name,
            description=f'Refined {name.lower()}.',
            weight=weight,
            value=value,
            quantity=1,
        )
    return _make


PROCESSING_RECIPES: list[Recipe] = [
    # --- Food ---
    Recipe('bake_bread',    {'Wheat':   2}, _food('Bread',       heal=5, value=4.0), 'food'),
    Recipe('cook_fish',     {'Fish':    1}, _food('CookedFish',  heal=7, value=5.0), 'food'),
    Recipe('make_jam',      {'Berries': 3}, _food('Jam',         heal=4, value=4.0), 'food'),
    Recipe('roast_meat',    {'Game':    1}, _food('RoastMeat',   heal=8, value=6.0), 'food'),
    Recipe('dry_mushrooms', {'Mushrooms': 2}, _food('DriedMushrooms', heal=3, value=2.0), 'food'),
    # --- Materials ---
    Recipe('smelt_iron',    {'Ore':     2}, _material('IronIngot', value=8.0), 'material'),
]


def find_matching_recipe(inventory_items: list, category: str = None) -> Recipe | None:
    """Find the first recipe the given inventory can satisfy.

    Returns the recipe, or None if no ingredients match. If ``category``
    is given, restricts to that family (``'food'`` or ``'material'``).
    """
    counts: dict[str, int] = {}
    for item in inventory_items:
        if not hasattr(item, 'name'):
            continue
        qty = getattr(item, 'quantity', 1)
        counts[item.name] = counts.get(item.name, 0) + qty

    for recipe in PROCESSING_RECIPES:
        if category and recipe.category != category:
            continue
        if all(counts.get(ing, 0) >= need for ing, need in recipe.inputs.items()):
            return recipe
    return None


def consume_inputs(inventory, recipe: Recipe) -> bool:
    """Deduct a recipe's inputs from the inventory in-place.

    Walks stackable items of matching names and decrements their quantity,
    removing items that hit zero. Returns True on full success, False if
    ingredients were insufficient (inventory left unchanged).
    """
    # First verify sufficient total quantity per ingredient.
    counts: dict[str, int] = {}
    for item in inventory.items:
        if not hasattr(item, 'name'):
            continue
        qty = getattr(item, 'quantity', 1)
        counts[item.name] = counts.get(item.name, 0) + qty
    for ing, need in recipe.inputs.items():
        if counts.get(ing, 0) < need:
            return False

    # Deduct. Prefer stackables; for non-stackable items, remove whole.
    for ing, need in recipe.inputs.items():
        remaining = need
        to_remove = []
        for item in inventory.items:
            if remaining <= 0:
                break
            if getattr(item, 'name', None) != ing:
                continue
            qty = getattr(item, 'quantity', 1)
            if qty <= remaining:
                to_remove.append(item)
                remaining -= qty
            else:
                item.quantity = qty - remaining
                remaining = 0
        for item in to_remove:
            inventory.items.remove(item)

    return True
