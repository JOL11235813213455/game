import sqlite3
import json
from pathlib import Path

from classes.creature import Stat
from classes.inventory import (
    Item, Stackable, Consumable, Ammunition,
    Equippable, Weapon, Wearable, Slot, CLASS_MAP
)

_DB_PATH = Path(__file__).parent / 'game.db'
_loaded  = False

SPECIES:     dict[str, dict] = {}
PLAYABLE:    dict[str, dict] = {}
NONPLAYABLE: dict[str, dict] = {}
ITEMS:       dict[str, Item] = {}
SPRITE_DATA: dict[str, dict] = {}


def load(db_path: Path = _DB_PATH) -> None:
    global _loaded
    if _loaded:
        return
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        _load_species(con)
        _load_items(con)
        _load_sprites(con)
    finally:
        con.close()
    _loaded = True


def _load_species(con: sqlite3.Connection) -> None:
    rows      = con.execute('SELECT name, playable, sprite_name FROM species').fetchall()
    stat_rows = con.execute('SELECT species_name, stat, value FROM species_stats').fetchall()

    stats_by_species: dict[str, dict] = {r['name']: {} for r in rows}
    for r in stat_rows:
        stats_by_species[r['species_name']][Stat(r['stat'])] = r['value']

    for r in rows:
        name  = r['name']
        block = stats_by_species[name]
        if r['sprite_name'] is not None:
            block['sprite_name'] = r['sprite_name']
        SPECIES[name] = block
        if r['playable']:
            PLAYABLE[name] = block
        else:
            NONPLAYABLE[name] = block


def _load_items(con: sqlite3.Connection) -> None:
    rows      = con.execute('SELECT * FROM items').fetchall()
    slot_rows = con.execute('SELECT item_key, slot FROM item_slots').fetchall()

    slots_by_key: dict[str, list] = {}
    for r in slot_rows:
        slots_by_key.setdefault(r['item_key'], []).append(Slot(r['slot']))

    for r in rows:
        key   = r['key']
        cls   = CLASS_MAP.get(r['class'], Item)
        base  = dict(
            name        = r['name']
            ,description = r['description']
            ,weight      = r['weight']
            ,value       = r['value']
            ,inventoriable = bool(r['inventoriable'])
            ,buffs       = json.loads(r['buffs'] or '{}')
        )
        if r['sprite_name'] is not None:
            base['sprite_name'] = r['sprite_name']

        if cls in (Stackable, Consumable, Ammunition):
            if r['max_stack_size'] is not None:
                base['max_stack_size'] = r['max_stack_size']
            if r['quantity'] is not None:
                base['quantity'] = r['quantity']

        if cls == Consumable and r['duration'] is not None:
            base['duration'] = r['duration']

        if cls == Ammunition:
            if r['damage'] is not None:
                base['damage'] = r['damage']
            if r['destroy_on_use_probability'] is not None:
                base['destroy_on_use_probability'] = r['destroy_on_use_probability']

        if cls in (Equippable, Weapon, Wearable):
            base['slots']              = slots_by_key.get(key, [])
            base['slot_count']         = r['slot_count'] or 1
            base['durability_max']     = r['durability_max'] or 100
            base['durability_current'] = r['durability_current'] or r['durability_max'] or 100
            base['render_on_creature'] = bool(r['render_on_creature'] or 0)

        if cls == Weapon:
            if r['damage'] is not None:
                base['damage'] = r['damage']
            if r['attack_time_ms'] is not None:
                base['attack_time_ms'] = r['attack_time_ms']
            if r['directions'] is not None:
                base['directions'] = json.loads(r['directions'])
            if r['range'] is not None:
                base['range'] = r['range']
            if r['ammunition_type'] is not None:
                base['ammunition_type'] = r['ammunition_type']

        ITEMS[key] = cls(**base)


def _load_sprites(con: sqlite3.Connection) -> None:
    rows = con.execute('SELECT name, palette, pixels FROM sprites').fetchall()
    for r in rows:
        palette_raw = json.loads(r['palette'])
        SPRITE_DATA[r['name']] = {
            'palette': {char: tuple(rgb) for char, rgb in palette_raw.items()}
            ,'pixels': json.loads(r['pixels'])
        }
