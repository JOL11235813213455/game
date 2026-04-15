"""
Batched NN inference for NPC behavior.

Instead of running one forward pass per creature per behavior tick,
collects all creatures that need decisions this frame and runs a
single batched forward pass. ~3-5x faster on CPU for 20+ creatures.

Usage:
    batcher = BatchBehavior(net, goal_net)
    # Each frame:
    batcher.tick(creatures, now, cols, rows)
"""
from __future__ import annotations
import numpy as np
from classes.creature_net import CreatureNet
from classes.actions import dispatch, compute_dynamic_mask


class BatchBehavior:
    """Collects creatures needing NN decisions, batches inference."""

    def __init__(self, net: CreatureNet, goal_net=None,
                 temperature: float = 1.0):
        self.net = net
        self.goal_net = goal_net
        self.temperature = temperature

    def tick(self, creatures: list, now: int, cols: int, rows: int):
        """Run batched inference for all creatures that need a behavior decision."""
        from classes.observation import build_observation
        from classes.stats import Stat

        # Collect creatures that need decisions (alive, have behavior tick due)
        pending = []
        obs_list = []
        mask_list = []
        for c in creatures:
            if not c.is_alive:
                continue
            # Check if behavior tick is due
            entry = c._timed_events.get('behavior')
            if entry is None:
                continue
            interval, last_fire, callback = entry
            if now - last_fire < interval:
                continue
            # Build observation + mask
            obs = build_observation(c, cols, rows, observation_tick=now)
            obs_arr = np.array(obs, dtype=np.float32)
            dyn_mask = compute_dynamic_mask(c, {'cols': cols, 'rows': rows, 'now': now})
            pending.append(c)
            obs_list.append(obs_arr)
            mask_list.append(dyn_mask)

        if not pending:
            return

        # Batch forward pass
        obs_batch = np.stack(obs_list)
        probs_batch = self.net.forward(obs_batch)

        # Apply masks and sample actions
        for i, c in enumerate(pending):
            probs = probs_batch[i].copy()
            mask = mask_list[i]
            probs *= mask
            total = probs.sum()
            if total > 0:
                probs /= total
            else:
                probs = mask / mask.sum() if mask.sum() > 0 else np.ones_like(probs) / len(probs)

            if self.temperature != 1.0 and self.temperature > 0:
                logits = np.log(probs + 1e-8) / self.temperature
                logits -= logits.max()
                probs = np.exp(logits)
                probs /= probs.sum()

            action_idx = int(np.random.choice(len(probs), p=probs))

            # Find target
            target = None
            from classes.creature import Creature
            for other in Creature.on_same_map(c.current_map):
                if other is not c and c.can_see(other):
                    target = other
                    break

            dispatch(c, action_idx, {
                'cols': cols, 'rows': rows,
                'target': target, 'now': now,
            })

            # Mark behavior tick as fired
            c._timed_events['behavior'][1] = now
