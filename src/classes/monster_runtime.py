"""
Monster + pack runtime driver.

Wires observation → NN inference → action dispatch each simulation step.
Mirrors the creature BatchBehavior pattern: collect monsters needing
decisions, batch-inference MonsterNet, dispatch actions, fire pack
NN on slow cadence, propagate pack events.

Usage from Simulation.step():
    monster_tick(sim.monsters, sim.packs, sim.now, cols, rows,
                 monster_net=net, pack_net=pnet,
                 game_clock=sim.game_clock)
"""
from __future__ import annotations
import numpy as np
from classes.monster_actions import MonsterAction, compute_monster_mask, NUM_MONSTER_ACTIONS
from classes.monster_observation import build_monster_observation
from classes.monster_dispatch import dispatch_monster
from classes.monster_heuristic import heuristic_monster_action, heuristic_pack_outputs
from classes.pack_net import build_pack_observation
from classes.stats import Stat


# Pack NN fires every PACK_TICK_INTERVAL monster ticks (slow cadence)
PACK_TICK_INTERVAL_MS = 2000  # 2 seconds


def monster_tick(monsters: list, packs: list, now: int,
                 cols: int, rows: int,
                 monster_net=None, pack_net=None,
                 game_clock=None,
                 use_heuristic: bool = False,
                 temperature: float = 1.0) -> list[dict]:
    """Run one tick of monster + pack updates.

    Args:
        monsters: list of Monster instances
        packs: list of Pack instances
        now: simulation time in ms
        cols, rows: map dimensions
        monster_net: MonsterNet (or None to use heuristic)
        pack_net: PackNet (or None to use heuristic)
        game_clock: optional GameClock
        use_heuristic: force heuristic even if NNs provided
        temperature: softmax temperature for MonsterNet

    Returns:
        list of dicts: {monster, action, result} for each monster that acted
    """
    # 1. Refresh pack signals on slow cadence
    for pack in packs:
        if pack.size == 0:
            continue
        last_tick = getattr(pack, '_last_nn_tick', 0)
        if now - last_tick >= PACK_TICK_INTERVAL_MS:
            _run_pack_nn(pack, pack_net, game_clock, use_heuristic)
            pack._last_nn_tick = now

    # 2. Fire monster decisions
    action_log = []
    alive_monsters = [m for m in monsters if m.is_alive]
    if not alive_monsters:
        return action_log

    if monster_net is not None and not use_heuristic:
        # Batch inference
        obs_batch = []
        masks = []
        for m in alive_monsters:
            obs = build_monster_observation(m, cols, rows, game_clock=game_clock)
            obs_batch.append(np.array(obs, dtype=np.float32))
            masks.append(compute_monster_mask(m))
        obs_np = np.stack(obs_batch)
        probs_batch = monster_net.forward(obs_np)

        for i, m in enumerate(alive_monsters):
            probs = probs_batch[i].copy()
            mask = masks[i]
            probs *= mask
            total = probs.sum()
            if total > 0:
                probs /= total
            else:
                probs = mask / mask.sum() if mask.sum() > 0 else np.ones_like(probs) / len(probs)
            if temperature != 1.0 and temperature > 0:
                logits = np.log(probs + 1e-8) / temperature
                logits -= logits.max()
                probs = np.exp(logits)
                probs /= probs.sum()
            action = int(np.random.choice(NUM_MONSTER_ACTIONS, p=probs))
            result = dispatch_monster(m, action, {
                'cols': cols, 'rows': rows, 'now': now, 'target': None,
            })
            action_log.append({'monster': m, 'action': action, 'result': result})
            # Propagate pack-level events after action
            _propagate_member_events(m)
    else:
        # Heuristic path
        for m in alive_monsters:
            action = heuristic_monster_action(m)
            result = dispatch_monster(m, action, {
                'cols': cols, 'rows': rows, 'now': now, 'target': None,
            })
            action_log.append({'monster': m, 'action': action, 'result': result})
            _propagate_member_events(m)

    # 3. Per-pack housekeeping (split detection, dominance updates)
    for pack in list(packs):
        _pack_housekeeping(pack, packs, now)

    return action_log


def _run_pack_nn(pack, pack_net, game_clock, use_heuristic):
    """Compute pack NN outputs and broadcast to members."""
    if pack_net is None or use_heuristic:
        sleep, alert, cohesion, roles = heuristic_pack_outputs(
            pack, game_clock=game_clock)
    else:
        pack_obs = build_pack_observation(pack, game_clock=game_clock)
        sleep, alert, cohesion, roles = pack_net.forward(pack_obs)

    pack.broadcast_signals(sleep, alert, cohesion, roles)


def _propagate_member_events(monster):
    """After a monster acts, push state changes into its pack."""
    pack = monster.pack
    if pack is None:
        return

    # Push creature sightings (simplified — look at nearby creatures)
    from classes.creature import Creature
    if monster.current_map is not None:
        sight = max(1, monster.stats.active[Stat.SIGHT_RANGE]())
        mx, my = monster.location.x, monster.location.y
        for c in Creature.on_same_map(monster.current_map):
            if not c.is_alive:
                continue
            d = abs(c.location.x - mx) + abs(c.location.y - my)
            if d <= sight:
                pack.on_creature_spotted(c.uid, c.location.x, c.location.y, 0)

    # Push monster's own state (HP, position) into pack state accumulator
    hp_max = max(1, monster.stats.active[Stat.HP_MAX]())
    pack.on_member_state(monster.uid,
                          hp_ratio=monster.stats.active[Stat.HP_CURR]() / hp_max,
                          x=monster.location.x, y=monster.location.y,
                          hunger=monster.hunger)


def _pack_housekeeping(pack, all_packs: list, now: int):
    """Per-tick pack maintenance: splits, merges, challenges."""
    # Split if size exceeds threshold
    if pack.size >= pack.split_size:
        _trigger_split(pack, all_packs)

    # Merge check — look for compatible nearby packs
    for other in all_packs:
        if other is pack or other.size == 0:
            continue
        if not pack.can_merge_with(other):
            continue
        # Proximity check: any member of one pack within 2 tiles of any
        # member of the other
        if _packs_in_contact(pack, other):
            _trigger_merge(pack, other, all_packs)
            return  # this pack merged; stop iteration

    # Pregnancy/egg laying (pregnant females drop eggs after gestation end)
    for m in list(pack.members):
        if getattr(m, 'is_pregnant', False):
            gest_end = getattr(m, '_gestation_tick_end', None)
            if gest_end is not None and now >= gest_end:
                _lay_egg(m, pack, now)
                m.is_pregnant = False
                m._gestation_tick_end = None


def _trigger_split(pack, all_packs: list):
    """Split pack in half by rank. Top half keeps territory, bottom roams."""
    from classes.pack import Pack
    # Combine M+F members into rank-ordered list (males first, females second
    # by rank). Alpha pair stays in top half.
    top_m = pack.members_m[:len(pack.members_m) // 2] or pack.members_m[:1]
    bot_m = pack.members_m[len(top_m):]
    top_f = pack.members_f[:len(pack.members_f) // 2] or pack.members_f[:1]
    bot_f = pack.members_f[len(top_f):]

    if not (bot_m or bot_f):
        return  # nothing to split into

    # Create new pack B for the bottom half
    # Simplistic center placement: offset by territory_size in random dir
    import random as _rng
    import math
    offset = int(pack.effective_territory_size() * 3)
    dx = _rng.choice([-offset, offset])
    dy = _rng.choice([-offset, offset])
    new_center = pack.territory_center._replace(
        x=max(0, pack.territory_center.x + dx),
        y=max(0, pack.territory_center.y + dy))

    new_pack = Pack(pack.species, new_center, pack.game_map)

    # Move bottom-half monsters to new pack
    from classes.monster import Monster
    for uid in bot_m + bot_f:
        m = Monster.by_uid(uid)
        if m is None:
            continue
        if uid in pack.members_m:
            pack.members_m.remove(uid)
        if uid in pack.members_f:
            pack.members_f.remove(uid)
        new_pack.add_member(m)

    pack._update_alpha_flags()
    all_packs.append(new_pack)


def _packs_in_contact(pack_a, pack_b) -> bool:
    """True if any member of pack_a is within 2 tiles of any member of pack_b."""
    members_a = pack_a.members
    members_b = pack_b.members
    for ma in members_a:
        for mb in members_b:
            d = abs(ma.location.x - mb.location.x) + abs(ma.location.y - mb.location.y)
            if d <= 2:
                return True
    return False


def _trigger_merge(pack_a, pack_b, all_packs: list):
    """Merge two compatible packs. Winner (by alpha stat composite) keeps territory."""
    from classes.monster import Monster
    from classes.stats import Stat

    def alpha_score(alpha):
        if alpha is None:
            return 0
        return (alpha.stats.base.get(Stat.STR, 10) +
                alpha.stats.base.get(Stat.VIT, 10) +
                alpha.stats.base.get(Stat.AGL, 10))

    a_alpha = pack_a.alpha_male or (pack_a.members[0] if pack_a.members else None)
    b_alpha = pack_b.alpha_male or (pack_b.members[0] if pack_b.members else None)
    winner = pack_a if alpha_score(a_alpha) >= alpha_score(b_alpha) else pack_b
    loser = pack_b if winner is pack_a else pack_a

    # Transfer loser's members to winner (bottom of hierarchy)
    for uid in loser.members_m:
        m = Monster.by_uid(uid)
        if m is None:
            continue
        winner.members_m.append(uid)
        m.pack = winner
    for uid in loser.members_f:
        m = Monster.by_uid(uid)
        if m is None:
            continue
        winner.members_f.append(uid)
        m.pack = winner
    loser.members_m.clear()
    loser.members_f.clear()
    winner._update_alpha_flags()

    # Drop the loser pack from the world
    if loser in all_packs:
        all_packs.remove(loser)


def _lay_egg(female, pack, now: int):
    """Drop a monster egg on the female's tile."""
    from classes.inventory import Egg
    if female.current_map is None:
        return
    tile = female.current_map.tiles.get(female.location)
    if tile is None:
        return
    egg = Egg(
        creature=None,  # hatched later by _hatch_monster_egg
        mother_species=female.species,
        father_species=female.species,
        name=f'{female.species}_egg',
        description=f'Egg from a {female.species}',
        weight=0.5,
        value=0,
    )
    egg._pack_ref = pack
    egg._is_monster_egg = True
    tile.inventory.items.append(egg)
