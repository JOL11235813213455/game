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
    """Per-tick pack maintenance: splits, merges, challenges, combat."""
    # Split if size exceeds threshold
    if pack.size >= pack.split_size:
        _trigger_split(pack, all_packs)

    # Cross-pack interactions
    for other in all_packs:
        if other is pack or other.size == 0:
            continue
        # Merge (small + compatible + same species)
        if pack.can_merge_with(other):
            if _packs_in_contact(pack, other):
                _trigger_merge(pack, other, all_packs)
                return
        # Hostile engagement (territory overlap, no merge)
        elif pack.is_hostile_to(other):
            if _packs_in_contact(pack, other):
                _trigger_cross_pack_combat(pack, other, now)

    # Intra-pack dominance challenges (contest-type only, small chance per tick)
    if pack.dominance_type == 'contest' and pack.size >= 2:
        import random as _rng
        if _rng.random() < 0.002:  # ~1 challenge per 500 ticks on average
            _trigger_dominance_challenge(pack, now)

    # Pregnancy/egg laying
    for m in list(pack.members):
        if getattr(m, 'is_pregnant', False):
            gest_end = getattr(m, '_gestation_tick_end', None)
            if gest_end is not None and now >= gest_end:
                _lay_egg(m, pack, now)
                m.is_pregnant = False
                m._gestation_tick_end = None
                m._eggs_laid = getattr(m, '_eggs_laid', 0) + 1


def _trigger_cross_pack_combat(pack_a, pack_b, now):
    """Monsters from hostile packs attack each other on sight.

    Lightweight: pick one member from each that's in contact, apply
    melee_attack. This fires per tick while both packs remain in
    contact, producing attrition combat.
    """
    from classes.stats import Stat
    # Find a pair in contact and make them fight
    for ma in pack_a.members:
        for mb in pack_b.members:
            d = abs(ma.location.x - mb.location.x) + abs(ma.location.y - mb.location.y)
            if d <= 1:
                # Attack occurs; stronger side tends to win
                ma.melee_attack(mb, now)
                return


def _trigger_dominance_challenge(pack, now):
    """A lower-ranked member challenges the one above it. First-to-50%-HP loses."""
    from classes.stats import Stat
    from classes.monster import Monster

    # Pick a sex bucket with at least 2 members
    for bucket in (pack.members_m, pack.members_f):
        if len(bucket) >= 2:
            # Challenger picks a random non-alpha to challenge the one above
            challenger_idx = None
            import random as _rng
            challenger_idx = _rng.randint(1, len(bucket) - 1)
            challenger = Monster.by_uid(bucket[challenger_idx])
            target = Monster.by_uid(bucket[challenger_idx - 1])
            if challenger is None or target is None:
                continue
            # Simplified challenge: one melee exchange, winner swaps rank
            # with loser. Tracks _dominance_wins for reward.
            ch_hp_before = challenger.stats.active[Stat.HP_CURR]()
            tg_hp_before = target.stats.active[Stat.HP_CURR]()
            ch_hp_max = max(1, challenger.stats.active[Stat.HP_MAX]())
            tg_hp_max = max(1, target.stats.active[Stat.HP_MAX]())

            # Both hit each other once
            challenger.melee_attack(target, now)
            target.melee_attack(challenger, now)

            ch_hp_after = challenger.stats.active[Stat.HP_CURR]()
            tg_hp_after = target.stats.active[Stat.HP_CURR]()

            ch_loss = ch_hp_before - ch_hp_after
            tg_loss = tg_hp_before - tg_hp_after

            # Whoever hit 50% first (or took more damage) loses
            ch_ratio = ch_hp_after / ch_hp_max
            tg_ratio = tg_hp_after / tg_hp_max

            if ch_ratio < tg_ratio:
                # Target won; no rank swap
                target._dominance_wins = getattr(target, '_dominance_wins', 0) + 1
            else:
                # Challenger won; swap ranks
                bucket[challenger_idx - 1], bucket[challenger_idx] = \
                    bucket[challenger_idx], bucket[challenger_idx - 1]
                challenger._dominance_wins = getattr(challenger, '_dominance_wins', 0) + 1
                pack._update_alpha_flags()
            return


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
        creature=None,
        mother_species=female.species,
        father_species=female.species,
        name=f'{female.species}_egg',
        description=f'Egg from a {female.species}',
        weight=0.5,
        value=0,
    )
    egg._pack_ref = pack
    egg._is_monster_egg = True
    # Monster eggs use a fixed gestation period of 30 days (same default
    # as creatures). Stored as a real-time tick target for the sim's
    # daily lifecycle pass to advance via tick_gestation.
    egg.gestation_period = 30
    tile.inventory.items.append(egg)


def hatch_monster_egg(egg, game_map, location):
    """Hatch a monster egg into a live Monster, placed in the pack
    referenced by the egg. Returns the newborn Monster or None.

    Called from the simulation's daily lifecycle pass for eggs with
    _is_monster_egg=True (the creature lifecycle pass handles normal
    creature eggs separately).
    """
    from classes.monster import Monster
    from classes.pack import Pack
    species = egg.mother_species or 'grey_wolf'
    pack_ref = getattr(egg, '_pack_ref', None)
    # Prefer the referenced pack; if it no longer exists, find or create
    # a solitary pack at the hatch location.
    if pack_ref is None or pack_ref.size == 0:
        pack_ref = Pack(species=species, territory_center=location,
                        game_map=game_map)
    import random as _rng
    sex = _rng.choice(('male', 'female'))
    child = Monster(
        current_map=game_map,
        location=location,
        species=species,
        sex=sex,
        age=0,
    )
    pack_ref.add_member(child)
    return child, pack_ref
