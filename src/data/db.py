import sqlite3
import json
from pathlib import Path

from classes.creature import Stat
from classes.inventory import Item, ItemType, Slot, StateOfMatter

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
        key = r['key']
        kwargs = dict(
            name               = r['name']
            ,description       = r['description']
            ,item_type         = ItemType(r['item_type'])
            ,state             = StateOfMatter(r['state'])
            ,value             = r['value']
            ,weight            = r['weight']
            ,damage            = r['damage']
            ,defense           = r['defense']
            ,health            = r['health']
            ,poison            = bool(r['poison'])
            ,equippable        = bool(r['equippable'])
            ,slots             = slots_by_key.get(key, [Slot.HAND_L])
            ,slot_count        = r['slot_count']
            ,consumable        = bool(r['consumable'])
            ,stackable         = bool(r['stackable'])
            ,quantity          = r['quantity']
            ,durability        = r['durability']
            ,durability_current = r['durability_current']
        )
        if r['sprite_name'] is not None:
            kwargs['sprite_name'] = r['sprite_name']
        ITEMS[key] = Item(**kwargs)


def _load_sprites(con: sqlite3.Connection) -> None:
    rows = con.execute('SELECT name, palette, pixels FROM sprites').fetchall()
    for r in rows:
        palette_raw = json.loads(r['palette'])
        SPRITE_DATA[r['name']] = {
            'palette': {char: tuple(rgb) for char, rgb in palette_raw.items()}
            ,'pixels': json.loads(r['pixels'])
        }
