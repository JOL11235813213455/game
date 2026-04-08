# Creature AI Implementation Plan

## Approach
Single shared neural net for all creatures. Stats are input features, so behavioral
differentiation emerges from stat profiles rather than hardcoded archetypes. Trained
via reinforcement learning in headless multi-agent simulations.

## Key Design Decisions
- **One net, many creatures** — no separate models per species/archetype
- **Stats drive behavior** — high-STR creatures discover fighting is effective, high-CHR
  discover social strategies, because the game mechanics reward what their stats are good at
- **Relationships tracked per creature** — `{uid: (score: float, count: int)}` — score is
  cumulative sentiment, count is interaction depth
- **Temporal inputs** — stat deltas over N ticks (HP change, distance to threat change) give
  the net trajectory awareness without recurrent architecture
- **Batched inference at runtime** — gather all creature observations into one matrix, single
  forward pass, distribute results. Keeps performance linear and fast
- **NumPy for inference** — small feedforward net (3 layers, 64-128 neurons), no PyTorch
  dependency at runtime
- **Stat-weighted decision tables as fallback** — usable immediately while ML is in development

## Implementation Roadmap
1. Review creature stats, derived stats, contests, and all existing mechanics
2. Add stable UID to Trackable (incrementing int, pickle-safe, reset on load)
3. Add relationships dict to Creature ({uid: (score, count)})
4. Define action space — all possible creature behaviors
5. Define interaction mechanics — what happens per action (stat contests, outcomes)
6. Define observation space — creature inputs (stats, HP%, nearby creatures, relationships,
   terrain, deltas)
7. Define reward function hierarchy (survival -> HP/gold/allies -> proxy rewards)
8. Build headless simulation mode (game loop without rendering)
9. Build random arena generator (varied maps, obstacles, creature compositions)
10. Implement observation gathering + batched input vector assembly
11. Implement neural net inference engine (NumPy matrix multiplies)
12. Implement RL training harness (PPO/DQN, Gym-compatible environment)
13. Train + evaluate — validate emergent behavior differences across stat profiles
14. Integrate trained model as NeuralBehavior.think() module
15. Implement stat-weighted decision tables as interim/fallback behavior
