# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True
"""
C struct array for creature hot data — synced per tick from Python objects.

The CreatureHotArray is a transient acceleration structure. Python objects
remain authoritative. The C array is rebuilt at the start of each tick
via sync(), then read by perception scans, census loops, and observation
building. Never serialized.
"""
from libc.stdlib cimport malloc, free, realloc
from libc.math cimport sqrt, fabs
import numpy as np
cimport numpy as np

np.import_array()


cdef struct CreatureHotData:
    int uid
    int x, y, z
    int hp_cur, hp_max
    int stealth
    int detection
    int melee_dmg
    int armor
    int sight_range
    int hearing_range
    int is_alive
    int species_id
    int sex            # 0=male, 1=female
    int is_child
    int is_pregnant
    int is_sleeping
    int equipment_count
    int size_units
    int age
    int partner_uid
    int mother_uid
    int father_uid
    int deity_id       # -1 = no deity
    float gold
    float piety


cdef class CreatureHotArray:
    """Managed array of CreatureHotData structs."""
    cdef CreatureHotData* data
    cdef int count
    cdef int capacity
    cdef dict uid_to_index  # uid → index in data array

    def __cinit__(self):
        self.data = NULL
        self.count = 0
        self.capacity = 0
        self.uid_to_index = {}

    def __dealloc__(self):
        if self.data != NULL:
            free(self.data)

    def sync(self, list creatures):
        """Sync C array from Python creature objects.

        Call once at the start of each tick. After this, use
        the C array for all hot-path reads.
        """
        cdef int n = len(creatures)
        if n > self.capacity:
            self.capacity = max(n, self.capacity * 2, 64)
            if self.data != NULL:
                self.data = <CreatureHotData*>realloc(
                    self.data, self.capacity * sizeof(CreatureHotData))
            else:
                self.data = <CreatureHotData*>malloc(
                    self.capacity * sizeof(CreatureHotData))
        self.count = n
        self.uid_to_index = {}

        cdef int i
        cdef CreatureHotData* d
        for i in range(n):
            c = creatures[i]
            d = &self.data[i]
            d.uid = c.uid
            loc = c.location
            d.x = loc.x
            d.y = loc.y
            d.z = loc.z
            d.is_alive = 1 if c.is_alive else 0

            if d.is_alive:
                s = c.stats.active
                from classes.stats import Stat
                d.hp_cur = s[Stat.HP_CURR]()
                d.hp_max = max(1, s[Stat.HP_MAX]())
                d.stealth = s[Stat.STEALTH]()
                d.detection = s[Stat.DETECTION]()
                d.melee_dmg = s[Stat.MELEE_DMG]()
                d.armor = s[Stat.ARMOR]()
                d.sight_range = max(1, s[Stat.SIGHT_RANGE]())
                d.hearing_range = max(1, s[Stat.HEARING_RANGE]())
                d.species_id = hash(c.species or '') & 0x7FFFFFFF
                d.sex = 0 if c.sex == 'male' else 1
                d.is_child = 1 if getattr(c, 'is_child', False) else 0
                d.is_pregnant = 1 if c.is_pregnant else 0
                d.is_sleeping = 1 if getattr(c, 'is_sleeping', False) else 0
                d.equipment_count = len(c.equipment)
                from classes.creature._constants import SIZE_UNITS
                d.size_units = SIZE_UNITS.get(getattr(c, 'size', 'medium'), 3)
                d.age = getattr(c, 'age', 0)
                d.partner_uid = c.partner_uid if c.partner_uid is not None else -1
                d.mother_uid = getattr(c, 'mother_uid', None) or -1
                d.father_uid = getattr(c, 'father_uid', None) or -1
                d.deity_id = hash(c.deity) & 0x7FFFFFFF if c.deity else -1
                d.gold = float(c.gold)
                d.piety = float(c.piety)
            else:
                d.hp_cur = 0
                d.hp_max = 1

            self.uid_to_index[d.uid] = i

    def perception_scan(self, int self_uid, int self_x, int self_y,
                         int sight, int hearing):
        """Fast perception scan. Returns (visible, heard_only) as lists of
        (distance, uid, index) tuples, sorted by distance.

        Replaces the Python loop in get_perception() for the hot path.
        """
        cdef int i, d, eff_sight
        cdef CreatureHotData* other
        visible = []
        heard = []

        for i in range(self.count):
            other = &self.data[i]
            if other.uid == self_uid or not other.is_alive:
                continue
            d = abs(self_x - other.x) + abs(self_y - other.y)
            eff_sight = sight - other.stealth
            if d <= eff_sight:
                visible.append((d, other.uid, i))
            elif d <= hearing:
                heard.append((d, other.uid, i))

        visible.sort()
        heard.sort()
        return visible, heard

    def get_data(self, int index):
        """Get a dict of hot data for creature at index (for Python consumers)."""
        if index < 0 or index >= self.count:
            return None
        cdef CreatureHotData* d = &self.data[index]
        return {
            'uid': d.uid, 'x': d.x, 'y': d.y,
            'hp_cur': d.hp_cur, 'hp_max': d.hp_max,
            'stealth': d.stealth, 'detection': d.detection,
            'melee_dmg': d.melee_dmg, 'armor': d.armor,
            'sight_range': d.sight_range, 'hearing_range': d.hearing_range,
            'is_alive': d.is_alive, 'species_id': d.species_id,
            'sex': d.sex, 'is_child': d.is_child,
            'is_pregnant': d.is_pregnant, 'is_sleeping': d.is_sleeping,
            'equipment_count': d.equipment_count, 'size_units': d.size_units,
            'age': d.age, 'partner_uid': d.partner_uid,
            'mother_uid': d.mother_uid, 'father_uid': d.father_uid,
            'deity_id': d.deity_id, 'gold': d.gold, 'piety': d.piety,
        }

    def index_for_uid(self, int uid):
        """Get array index for a creature UID, or -1."""
        return self.uid_to_index.get(uid, -1)

    @property
    def size(self):
        return self.count
