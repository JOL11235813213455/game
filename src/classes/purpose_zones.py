"""
Purpose zone system -- rectangular areas on maps with designated purposes.

Loaded from the purpose_places DB table. Provides fast lookup of what
purposes apply at any (map, x, y, z) coordinate.

Multiple zones can overlap -- a market square might be both 'trading'
and 'socializing'. Tile-level purpose (tile.purpose) is checked as a
fallback if no zone matches.
"""
from __future__ import annotations
from classes.maps import MapKey


class PurposeZone:
    """A rectangular area on a map with a designated purpose."""
    __slots__ = ('id', 'map_name', 'purpose', 'name',
                 'x_min', 'y_min', 'z_min', 'x_max', 'y_max', 'z_max')

    def __init__(self, id: int, map_name: str, purpose: str, name: str,
                 x_min: int, y_min: int, z_min: int,
                 x_max: int, y_max: int, z_max: int):
        self.id = id
        self.map_name = map_name
        self.purpose = purpose
        self.name = name
        self.x_min = x_min
        self.y_min = y_min
        self.z_min = z_min
        self.x_max = x_max
        self.y_max = y_max
        self.z_max = z_max

    def contains(self, x: int, y: int, z: int = 0) -> bool:
        return (self.x_min <= x <= self.x_max and
                self.y_min <= y <= self.y_max and
                self.z_min <= z <= self.z_max)


class PurposeZoneRegistry:
    """Fast lookup of purposes at any map coordinate.

    Loaded once from DB. Provides:
    - get_purposes(map_name, x, y, z) -> set of purpose strings
    - get_zones(map_name, x, y, z) -> list of PurposeZone objects
    - get_zones_for_purpose(map_name, purpose) -> list of zones
    - get_nearest_zone(map_name, purpose, x, y) -> (zone, distance)
    """

    def __init__(self):
        # {map_name: [PurposeZone, ...]}
        self._zones: dict[str, list[PurposeZone]] = {}

    def load_from_db(self):
        """Load all zones from the purpose_places table."""
        import sqlite3
        from pathlib import Path
        db_path = Path(__file__).parent.parent / 'data' / 'game.db'
        if not db_path.exists():
            return
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        for row in con.execute('SELECT * FROM purpose_places'):
            zone = PurposeZone(
                id=row['id'], map_name=row['map_name'],
                purpose=row['purpose'], name=row['name'] or '',
                x_min=row['x_min'], y_min=row['y_min'], z_min=row['z_min'],
                x_max=row['x_max'], y_max=row['y_max'], z_max=row['z_max'],
            )
            self._zones.setdefault(zone.map_name, []).append(zone)
        con.close()

    def add_zone(self, zone: PurposeZone):
        """Add a zone programmatically (for training arenas)."""
        self._zones.setdefault(zone.map_name, []).append(zone)

    def get_purposes(self, map_name: str, x: int, y: int, z: int = 0) -> set[str]:
        """Return all purposes that apply at this coordinate."""
        purposes = set()
        for zone in self._zones.get(map_name, []):
            if zone.contains(x, y, z):
                purposes.add(zone.purpose)
        return purposes

    def get_zones(self, map_name: str, x: int, y: int, z: int = 0) -> list[PurposeZone]:
        """Return all zones containing this coordinate."""
        return [zn for zn in self._zones.get(map_name, [])
                if zn.contains(x, y, z)]

    def get_zones_for_purpose(self, map_name: str, purpose: str) -> list[PurposeZone]:
        """Return all zones on this map with the given purpose."""
        return [zn for zn in self._zones.get(map_name, [])
                if zn.purpose == purpose]

    def get_nearest_zone(self, map_name: str, purpose: str,
                         x: int, y: int) -> tuple[PurposeZone | None, float]:
        """Find the nearest zone with the given purpose.

        Returns (zone, manhattan_distance). Distance is 0 if already inside.
        Returns (None, float('inf')) if no zone exists.
        """
        best_zone = None
        best_dist = float('inf')
        for zone in self._zones.get(map_name, []):
            if zone.purpose != purpose:
                continue
            # Manhattan distance to nearest edge of the zone
            dx = max(0, zone.x_min - x, x - zone.x_max)
            dy = max(0, zone.y_min - y, y - zone.y_max)
            dist = dx + dy
            if dist < best_dist:
                best_dist = dist
                best_zone = zone
        return best_zone, best_dist

    def get_center(self, zone: PurposeZone) -> tuple[float, float]:
        """Get the center point of a zone."""
        return ((zone.x_min + zone.x_max) / 2,
                (zone.y_min + zone.y_max) / 2)
