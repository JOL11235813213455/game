"""
Social topology: reduce a matrix of relationships into compact signals.

Given a list of visible creatures and a "self" creature, produce a
handful of floats that summarize the social structure of the group
in ways the NN can learn from.

Two families of metrics:

**Simple cohesion (6 floats)** — mood and integration.
  - group_mean_sentiment      : average of all internal sentiments
  - group_cohesion            : 1 / (1 + stdev of sentiments) — higher
                                 means everyone feels the same way
  - my_avg_sentiment_to_group : how I feel about them on average
  - group_avg_sentiment_to_me : how they feel about me on average
  - positive_edge_density     : fraction of internal edges with
                                 sentiment > 5
  - negative_edge_density     : fraction with sentiment < -5

**Laplacian eigenvalues (4 floats)** — graph topology.
  - friendship_connectivity   : algebraic connectivity of the
                                 positive-sentiment graph. Near zero
                                 means disconnected cliques, higher
                                 means one cohesive friend group.
  - friendship_component_count_proxy : 1.0 if the positive graph has
                                 more than one near-zero eigenvalue
                                 (disconnected friend groups exist)
  - enmity_connectivity       : same for negative-sentiment graph
  - enmity_component_count_proxy : disconnected feud camps

**Rest-of-crowd summary (7 floats)** — awareness beyond the top 10.
  - threat_max_nonslot        : max threat score I compute against
                                 any visible creature NOT in my
                                 perception slots
  - rest_crowd_size           : count of non-slotted visible
                                 creatures (clamped to 0..20)
  - rest_avg_sent_to_me       : average sentiment those creatures
                                 have toward me
  - rest_avg_sent_from_me     : average of my sentiment toward them
  - rest_min_sent             : min (most hostile) of any non-slot
  - rest_max_sent             : max (most friendly)
  - rest_stranger_count       : fraction who are unknown (no rel row)

All math is vectorized with numpy where possible for N=10..30.
"""
from __future__ import annotations
import math
import numpy as np
from classes.relationship_graph import GRAPH

SIMPLE_COHESION_SIZE = 6
LAPLACIAN_SIZE = 4
REST_OF_CROWD_SIZE = 7
SOCIAL_TOPOLOGY_SIZE = SIMPLE_COHESION_SIZE + LAPLACIAN_SIZE + REST_OF_CROWD_SIZE  # 17


def _build_sentiment_matrix(creatures: list) -> np.ndarray:
    """Return an NxN matrix of sentiments between ``creatures``.

    M[i][j] is creature[i]'s sentiment toward creature[j]. No entry
    (no relationship) becomes 0.
    """
    n = len(creatures)
    m = np.zeros((n, n), dtype=np.float32)
    for i, a in enumerate(creatures):
        for j, b in enumerate(creatures):
            if i == j:
                continue
            rel = GRAPH.get_edge(a.uid, b.uid)
            if rel:
                m[i, j] = rel[0]
    return m


def _algebraic_connectivity(adj: np.ndarray) -> tuple[float, int]:
    """Compute the second-smallest Laplacian eigenvalue for an undirected
    weighted graph given its (non-negative) adjacency matrix.

    Returns (algebraic_connectivity, component_count_proxy) where the
    proxy is the number of eigenvalues within 1e-3 of zero (a rough
    count of connected components).
    """
    n = adj.shape[0]
    if n < 2:
        return 0.0, 1
    # Laplacian L = D - A where D is the diagonal of degrees
    deg = adj.sum(axis=1)
    L = np.diag(deg) - adj
    try:
        eigs = np.linalg.eigvalsh(L)  # real because L is symmetric
    except np.linalg.LinAlgError:
        return 0.0, 1
    eigs = np.sort(eigs)
    # Zero eigenvalues (or near-zero) count components
    near_zero = int(np.sum(np.abs(eigs) < 1e-3))
    # Second-smallest is the algebraic connectivity
    if len(eigs) >= 2:
        ac = float(max(0.0, eigs[1]))
    else:
        ac = 0.0
    return ac, max(1, near_zero)


def compute_social_topology(
    self_creature,
    visible: list,            # [(distance, creature), ...] sorted
    slot_creatures: list,     # list of Creature objects in the 10 slots (None for empty)
) -> list[float]:
    """Produce the 17-float social topology vector.

    Safe for any N >= 0 — returns zeros when there's nothing visible.
    """
    result = []

    # Who is in the slots (for rest-of-crowd split)
    slot_uids = {c.uid for c in slot_creatures if c is not None}

    # Split visible into "in slots" and "rest of crowd"
    # Note: slot_creatures is derived from visible so in-slots is a
    # subset of visible.
    in_slots = [c for _, c in visible if c.uid in slot_uids]
    rest = [c for _, c in visible if c.uid not in slot_uids]

    # ---------- SIMPLE COHESION (6 floats) ----------
    # Use the in-slot group for the internal cohesion metrics (bounded
    # at 10 creatures, cheap to compute).
    if len(in_slots) >= 2:
        sentiments = []
        for i, a in enumerate(in_slots):
            for b in in_slots:
                if a is b:
                    continue
                rel = GRAPH.get_edge(a.uid, b.uid)
                if rel:
                    sentiments.append(rel[0])
        if sentiments:
            arr = np.array(sentiments, dtype=np.float32)
            group_mean = float(np.mean(arr)) / 20.0  # normalized to ~-1..1
            std = float(np.std(arr))
            cohesion = 1.0 / (1.0 + std / 5.0)
            pos_density = float(np.mean(arr > 5))
            neg_density = float(np.mean(arr < -5))
        else:
            group_mean = 0.0
            cohesion = 1.0
            pos_density = 0.0
            neg_density = 0.0

        my_to_group = []
        group_to_me = []
        for other in in_slots:
            my_rel = GRAPH.get_edge(self_creature.uid, other.uid)
            their_rel = GRAPH.get_edge(other.uid, self_creature.uid)
            if my_rel:
                my_to_group.append(my_rel[0])
            if their_rel:
                group_to_me.append(their_rel[0])
        my_avg = float(np.mean(my_to_group)) / 20.0 if my_to_group else 0.0
        their_avg = float(np.mean(group_to_me)) / 20.0 if group_to_me else 0.0
    else:
        group_mean = 0.0
        cohesion = 1.0
        my_avg = 0.0
        their_avg = 0.0
        pos_density = 0.0
        neg_density = 0.0

    result.append(max(-1.0, min(1.0, group_mean)))
    result.append(max(0.0, min(1.0, cohesion)))
    result.append(max(-1.0, min(1.0, my_avg)))
    result.append(max(-1.0, min(1.0, their_avg)))
    result.append(pos_density)
    result.append(neg_density)

    # ---------- LAPLACIAN EIGENVALUES (4 floats) ----------
    if len(in_slots) >= 3:
        m = _build_sentiment_matrix(in_slots)
        # Friendship graph: symmetrize positive edges
        friend_adj = np.clip(m, 0, None)
        friend_adj = (friend_adj + friend_adj.T) / 2.0
        enmity_adj = np.clip(-m, 0, None)
        enmity_adj = (enmity_adj + enmity_adj.T) / 2.0

        friend_ac, friend_comp = _algebraic_connectivity(friend_adj)
        enmity_ac, enmity_comp = _algebraic_connectivity(enmity_adj)
    else:
        friend_ac = 0.0
        friend_comp = 1
        enmity_ac = 0.0
        enmity_comp = 1

    # Normalize algebraic connectivity (values are in 0..~20 range for
    # our sentiment scale) and fragmentation (1 component = 0, more =
    # 1)
    result.append(min(1.0, friend_ac / 20.0))
    result.append(1.0 if friend_comp > 1 else 0.0)
    result.append(min(1.0, enmity_ac / 20.0))
    result.append(1.0 if enmity_comp > 1 else 0.0)

    # ---------- REST-OF-CROWD SUMMARY (7 floats) ----------
    threat_max = 0.0
    rest_sent_to_me = []
    rest_sent_from_me = []
    stranger_count = 0
    if rest:
        for other in rest:
            if hasattr(self_creature, '_threat_score_against'):
                threat = self_creature._threat_score_against(other)
                # Weight by their hostility toward me if known
                other_rel = GRAPH.get_edge(other.uid, self_creature.uid)
                hostility = 1.0
                if other_rel and other_rel[0] < 0:
                    hostility = 1.0 + abs(other_rel[0]) / 20.0
                weighted = threat * hostility
                if weighted > threat_max:
                    threat_max = weighted
            my_rel = GRAPH.get_edge(self_creature.uid, other.uid)
            their_rel = GRAPH.get_edge(other.uid, self_creature.uid)
            if my_rel:
                rest_sent_from_me.append(my_rel[0])
            if their_rel:
                rest_sent_to_me.append(their_rel[0])
            if not my_rel and not their_rel:
                stranger_count += 1

    result.append(min(1.0, threat_max / 40.0))                      # threat_max_nonslot
    result.append(min(1.0, len(rest) / 20.0))                        # rest_crowd_size
    result.append(float(np.mean(rest_sent_to_me)) / 20.0 if rest_sent_to_me else 0.0)
    result.append(float(np.mean(rest_sent_from_me)) / 20.0 if rest_sent_from_me else 0.0)
    result.append(float(min(rest_sent_to_me)) / 20.0 if rest_sent_to_me else 0.0)
    result.append(float(max(rest_sent_to_me)) / 20.0 if rest_sent_to_me else 0.0)
    result.append(stranger_count / max(1, len(rest)) if rest else 0.0)

    # Clamp everything to reasonable ranges
    result = [max(-1.0, min(1.0, x)) for x in result]

    # Sanity check
    assert len(result) == SOCIAL_TOPOLOGY_SIZE, \
        f'social topology produced {len(result)} floats, expected {SOCIAL_TOPOLOGY_SIZE}'
    return result
