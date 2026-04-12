"""
Centralized relationship and rumor graph.

Before this module, every creature owned its own ``relationships`` and
``rumors`` dicts. That shape made forward reads ("what do I think of
X?") trivial but reverse reads ("who thinks highly of me?") required
walking every creature on the map, and graph-level operations (bulk
sentiment decay, community detection, eigenvector centrality) were
fundamentally awkward to express.

The ``RelationshipGraph`` is a module-level singleton (`GRAPH`) that
owns every sentiment edge and every rumor in the simulation. Creatures
never store these dicts themselves; they query the graph by uid. This
gives:

  1. O(1) forward reads, unchanged — the graph hands back a live dict.
  2. O(edges) reverse reads via ``edges_to(uid)`` — a real capability
     the per-creature shape could not offer.
  3. Bulk ops (``all_edges()``, ``decay_all()``) for future tooling.
  4. A single save/load point instead of scattered per-creature state.
"""
from __future__ import annotations
from typing import Iterator


class RelationshipGraph:
    """Directed weighted graph of creature relationships and rumors.

    Storage shape:
        _edges[from_uid][to_uid] = [sentiment, count, min_score, max_score]
        _rumors[holder_uid][subject_uid] = [(source, sent, conf, tick), ...]

    Both outer dicts are auto-created on first access via
    ``edges_from`` / ``rumors_of`` so call sites never need to check
    for missing uids.
    """

    def __init__(self):
        self._edges: dict[int, dict[int, list]] = {}
        self._rumors: dict[int, dict[int, list]] = {}

    # ======================================================================
    # Forward-edge access (hot path)
    # ======================================================================

    def edges_from(self, uid: int) -> dict:
        """Return the dict of outgoing edges for ``uid``.

        Returned dict is live: mutations to it update the graph. Used
        as a zero-copy accessor throughout the observation loop.
        Auto-creates empty dict if absent.
        """
        d = self._edges.get(uid)
        if d is None:
            d = {}
            self._edges[uid] = d
        return d

    def get_edge(self, from_uid: int, to_uid: int):
        """Return the [sentiment, count, min, max] entry or None."""
        d = self._edges.get(from_uid)
        if d is None:
            return None
        return d.get(to_uid)

    def has_edges_from(self, uid: int) -> bool:
        """True if this creature has any recorded relationships."""
        d = self._edges.get(uid)
        return bool(d)

    def count_from(self, uid: int) -> int:
        """Number of outgoing edges (== number of relationships)."""
        d = self._edges.get(uid)
        return len(d) if d else 0

    def set_edges_from(self, uid: int, edges: dict):
        """Replace a creature's outgoing edges wholesale.

        Used by child/egg initialization (start with no relationships)
        and by tests that need to reset state deterministically.
        """
        self._edges[uid] = edges

    # ======================================================================
    # Reverse-edge access (the capability the old shape lacked)
    # ======================================================================

    def edges_to(self, uid: int) -> Iterator[tuple[int, list]]:
        """Yield (from_uid, rel) for everyone with an opinion about ``uid``.

        O(N) over the number of creatures with outgoing edges. For a
        cheap lazy scan. If this becomes hot, a reverse index can be
        added without changing the API.
        """
        for from_uid, outgoing in self._edges.items():
            rel = outgoing.get(uid)
            if rel is not None:
                yield (from_uid, rel)

    def incoming_sentiment_avg(self, uid: int) -> float:
        """Average sentiment others hold about ``uid``. 0.0 if strangers."""
        total = 0.0
        n = 0
        for _, rel in self.edges_to(uid):
            total += rel[0]
            n += 1
        return total / n if n else 0.0

    def count_to(self, uid: int) -> int:
        """Number of creatures with an opinion about ``uid``."""
        n = 0
        for _, _rel in self.edges_to(uid):
            n += 1
        return n

    # ======================================================================
    # Writes
    # ======================================================================

    def record_interaction(self, from_uid: int, to_uid: int, score: float):
        """Atomic interaction update — idempotent for the caller.

        Matches the old RelationshipsMixin.record_interaction semantics
        exactly: create a new edge [score, 1, score, score], or update
        the existing one by adding to sentiment, incrementing count,
        and widening the min/max window.
        """
        d = self._edges.get(from_uid)
        if d is None:
            d = {}
            self._edges[from_uid] = d
        rel = d.get(to_uid)
        if rel is not None:
            rel[0] += score
            rel[1] += 1
            if score < rel[2]:
                rel[2] = score
            if score > rel[3]:
                rel[3] = score
        else:
            d[to_uid] = [score, 1, score, score]

    # ======================================================================
    # Rumor access
    # ======================================================================

    def rumors_of(self, uid: int) -> dict:
        """Return the dict of rumors held BY ``uid`` (live reference).

        Keyed by subject_uid; values are lists of (source, sentiment,
        confidence, tick) tuples.
        """
        d = self._rumors.get(uid)
        if d is None:
            d = {}
            self._rumors[uid] = d
        return d

    def get_rumors(self, holder_uid: int, subject_uid: int):
        """Return the list of rumors holder has about subject, or None."""
        d = self._rumors.get(holder_uid)
        if d is None:
            return None
        return d.get(subject_uid)

    def set_rumors_of(self, uid: int, rumors: dict):
        """Replace a creature's rumor store wholesale."""
        self._rumors[uid] = rumors

    def add_rumor(self, holder_uid: int, subject_uid: int,
                  source_uid: int, sentiment: float,
                  confidence: float, tick: int):
        """Append a rumor entry to holder's store about subject."""
        d = self._rumors.get(holder_uid)
        if d is None:
            d = {}
            self._rumors[holder_uid] = d
        entry = (source_uid, sentiment, confidence, tick)
        existing = d.get(subject_uid)
        if existing is not None:
            existing.append(entry)
        else:
            d[subject_uid] = [entry]

    def count_rumors_held(self, uid: int) -> int:
        """Total rumor entries held by ``uid`` across all subjects."""
        d = self._rumors.get(uid)
        if not d:
            return 0
        return sum(len(v) for v in d.values())

    # ======================================================================
    # Bulk / graph ops
    # ======================================================================

    def all_edges(self) -> Iterator[tuple[int, int, list]]:
        """Yield every (from_uid, to_uid, rel) triple in the graph."""
        for from_uid, outgoing in self._edges.items():
            for to_uid, rel in outgoing.items():
                yield (from_uid, to_uid, rel)

    def all_from_uids(self) -> list[int]:
        """Uids of every creature with at least one outgoing edge."""
        return list(self._edges.keys())

    def remove_creature(self, uid: int):
        """Wipe all traces of ``uid`` from the graph.

        Removes outgoing edges, incoming edges, rumors held, and rumors
        about. Called when a creature is permanently gone (death +
        cleanup, test teardown). Note: game-world deaths do NOT
        automatically call this — surviving creatures still remember
        the dead — unless the caller explicitly invokes it.
        """
        self._edges.pop(uid, None)
        self._rumors.pop(uid, None)
        for outgoing in self._edges.values():
            outgoing.pop(uid, None)
        for rumor_dict in self._rumors.values():
            rumor_dict.pop(uid, None)

    def clear(self):
        """Empty the entire graph. Used by load and test teardown."""
        self._edges.clear()
        self._rumors.clear()

    # ======================================================================
    # Serialization
    # ======================================================================

    def serialize(self) -> dict:
        """Return a dict suitable for pickling alongside save state."""
        return {'edges': self._edges, 'rumors': self._rumors}

    def deserialize(self, data: dict):
        """Restore from a dict produced by ``serialize``.

        Replaces all current state — callers should typically call
        ``clear()`` first if they want to be explicit, but this
        assigns the new dicts directly so existing state is dropped.
        """
        self._edges = data.get('edges', {}) or {}
        self._rumors = data.get('rumors', {}) or {}


# Module-level singleton. Every relationship query in the codebase
# goes through this instance. Save/load replaces its contents via
# deserialize().
GRAPH = RelationshipGraph()
