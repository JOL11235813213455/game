"""
Map connectivity graph for cross-map pathfinding.

Builds a graph of how maps connect via linked tiles, enabling NPCs
to navigate between maps. The graph is built from the tile_sets DB
or from loaded Map objects.

Example: Town map has a tile at (5,0) linking to Forest map.
         Forest map has a tile at (0,10) linking to Mine map.
         A creature in Town wanting to reach Mine knows the path:
         Town -> Forest -> Mine.
"""
from __future__ import annotations
from collections import deque


class MapGraph:
    """Graph of map connections for cross-map pathfinding.

    Nodes are map names. Edges are connections (with source/dest coordinates).
    Each connection records: which tile on the source map links to which tile
    on the destination map.
    """

    def __init__(self):
        # {map_name: [(dest_map, src_x, src_y, dest_x, dest_y), ...]}
        self.connections: dict[str, list[tuple]] = {}

    def build_from_maps(self, maps: dict) -> None:
        """Build graph from loaded MAPS dict (map_name -> Map object).

        Scans all tiles in all maps for linked_map references.
        """
        self.connections.clear()
        for map_name, map_obj in maps.items():
            conns = []
            for key, tile in map_obj.tiles.items():
                linked = getattr(tile, 'linked_map', None)
                if not linked:
                    continue
                ll = getattr(tile, 'linked_location', None)
                if ll is not None:
                    dest_x, dest_y = ll.x, ll.y
                else:
                    # Fall back to destination map entrance
                    dest_map_obj = maps.get(linked)
                    if dest_map_obj is not None:
                        dest_x, dest_y = dest_map_obj.entrance
                    else:
                        dest_x, dest_y = 0, 0
                conns.append((linked, key.x, key.y, dest_x, dest_y))
            self.connections[map_name] = conns

    def build_from_db(self) -> None:
        """Build graph from tile_sets DB table.

        Reads linked_map, linked_x, linked_y from tile_sets and
        cross-references with maps table to determine which map each
        tile_set belongs to.
        """
        import sqlite3
        from pathlib import Path

        db_path = Path(__file__).parent.parent / 'data' / 'game.db'
        if not db_path.exists():
            return

        con = sqlite3.connect(str(db_path))
        con.row_factory = sqlite3.Row
        try:
            # Build map_name -> tile_set mapping
            map_rows = con.execute('SELECT name, tile_set FROM maps').fetchall()
            ts_to_map: dict[str, str] = {}
            for r in map_rows:
                if r['tile_set']:
                    ts_to_map[r['tile_set']] = r['name']

            # Also grab entrance coords for fallback destinations
            map_entrances: dict[str, tuple[int, int]] = {}
            for r in map_rows:
                map_entrances[r['name']] = (0, 0)
            ent_rows = con.execute(
                'SELECT name, entrance_x, entrance_y FROM maps'
            ).fetchall()
            for r in ent_rows:
                map_entrances[r['name']] = (r['entrance_x'], r['entrance_y'])

            # Scan tile_sets for links
            self.connections.clear()
            rows = con.execute(
                'SELECT tile_set, x, y, linked_map, linked_x, linked_y '
                'FROM tile_sets WHERE linked_map IS NOT NULL AND linked_map != ""'
            ).fetchall()

            for r in rows:
                src_map = ts_to_map.get(r['tile_set'])
                if src_map is None:
                    continue
                dest_map = r['linked_map']
                src_x, src_y = r['x'], r['y']
                dest_x = r['linked_x'] if r['linked_x'] is not None else map_entrances.get(dest_map, (0, 0))[0]
                dest_y = r['linked_y'] if r['linked_y'] is not None else map_entrances.get(dest_map, (0, 0))[1]
                self.connections.setdefault(src_map, []).append(
                    (dest_map, src_x, src_y, dest_x, dest_y)
                )
        finally:
            con.close()

    def get_connections(self, map_name: str) -> list[tuple]:
        """Get all connections from a map.

        Returns [(dest_map, src_x, src_y, dest_x, dest_y), ...]
        """
        return self.connections.get(map_name, [])

    def find_path(self, from_map: str, to_map: str) -> list[str] | None:
        """BFS shortest path between maps.

        Returns list of map names [from_map, ..., to_map] or None
        if no path exists. Returns [from_map] if already there.
        """
        if from_map == to_map:
            return [from_map]

        visited: set[str] = {from_map}
        queue: deque[list[str]] = deque([[from_map]])

        while queue:
            path = queue.popleft()
            current = path[-1]
            for dest_map, _, _, _, _ in self.get_connections(current):
                if dest_map == to_map:
                    return path + [dest_map]
                if dest_map not in visited:
                    visited.add(dest_map)
                    queue.append(path + [dest_map])

        return None

    def find_path_detailed(self, from_map: str, to_map: str) -> list[tuple] | None:
        """Detailed path with coordinates.

        Returns [(map_name, exit_x, exit_y, next_map, entry_x, entry_y), ...]
        or None if no path exists. Returns [] if already on target map.

        Each tuple represents one map transition: walk to (exit_x, exit_y)
        on map_name, then you arrive at (entry_x, entry_y) on next_map.
        """
        if from_map == to_map:
            return []

        # BFS tracking predecessor edges
        visited: set[str] = {from_map}
        # predecessor[map_name] = (prev_map, dest_map, src_x, src_y, dest_x, dest_y)
        predecessor: dict[str, tuple] = {}
        queue: deque[str] = deque([from_map])

        while queue:
            current = queue.popleft()
            for dest_map, src_x, src_y, dest_x, dest_y in self.get_connections(current):
                if dest_map not in visited:
                    visited.add(dest_map)
                    predecessor[dest_map] = (current, dest_map, src_x, src_y, dest_x, dest_y)
                    if dest_map == to_map:
                        # Reconstruct
                        result = []
                        node = to_map
                        while node in predecessor:
                            prev_map, dm, sx, sy, dx, dy = predecessor[node]
                            result.append((prev_map, sx, sy, dm, dx, dy))
                            node = prev_map
                        result.reverse()
                        return result
                    queue.append(dest_map)

        return None

    def distance(self, from_map: str, to_map: str) -> int:
        """Number of map transitions between two maps.

        Returns 0 if same map, -1 if unreachable.
        """
        if from_map == to_map:
            return 0
        path = self.find_path(from_map, to_map)
        if path is None:
            return -1
        return len(path) - 1

    def __repr__(self) -> str:
        total_conns = sum(len(v) for v in self.connections.values())
        return f'<MapGraph maps={len(self.connections)} connections={total_conns}>'
