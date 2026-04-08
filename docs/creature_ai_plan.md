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
- **Rumors system** — creatures pass sentiments about third parties, probabilistic gossip,
  weighted array of inherited impressions. Reputation precedes you.
- **Temporal inputs** — stat deltas over N ticks (HP change, distance to threat change) give
  the net trajectory awareness without recurrent architecture
- **Batched inference at runtime** — gather all creature observations into one matrix, single
  forward pass, distribute results. Keeps performance linear and fast
- **NumPy for inference** — small feedforward net (3 layers, 64-128 neurons), no PyTorch
  dependency at runtime
- **Stat-weighted decision tables as fallback** — usable immediately while ML is in development
- **Curiosity as default behavior** — unfamiliarity breeds curiosity, not hostility.
  Creatures with little information about others or surroundings are rewarded for
  exploration and information-gathering. Hostility requires a basis: negative
  relationship, bad rumor, territorial trigger, fear, or being attacked first.
  Curiosity score: `1 / (1 + interactions_with_target)` — high for strangers,
  decays as familiarity grows. Bases for forming opinions:
  1. Direct interaction history (relationships)
  2. Inherited reputation (rumors system)
  3. Observable traits (species, equipment, witnessed behavior)
  4. Territorial instinct (per-species configuration)

## Stat System Summary (completed)
- D&D-style modifiers: `(stat - 10) // 2` across all derived formulas
- Speed in TPS: `max(0, 4 + agl_mod)`, interval = 1/TPS
- Stamina system replaces attack speed: MAX_STAMINA, STAM_REGEN, action costs
- HP regen: fibonacci sequence after delay, capped at 15% HP_MAX/sec
- Timed event system on Trackable: register_tick(name, interval, callback)
- Two resolution systems:
  - **d20 contests** (both roll): accuracy vs dodge/block, stealth vs detection,
    intimidation vs fear, deception vs detection, grapple
  - **DC resist checks** (passive): armor, stagger, magic, poison, disease
- Dodge/block require SIGHT_RANGE — can't defend what you can't see
- Persuasion enhances interaction rewards, not an opposed check
- Grapple: max(STR, AGL) vs max(STR, AGL-1) for defender
- LOOT_GINI: Gini coefficient from LCK for loot generation
- Additive stacking only, never multiplicative

## Implementation Roadmap
1. ~~Review creature stats, derived stats, contests, and all existing mechanics~~
2. Add stable UID to Trackable (incrementing int, pickle-safe, reset on load)
3. Add relationships dict to Creature ({uid: (score, count)})
4. Add rumors system (inherited sentiments, probabilistic gossip)
5. Define action space — all possible creature behaviors
6. Define interaction mechanics — what happens per action (stat contests, outcomes)
7. Define observation space — creature inputs (stats, HP%, nearby creatures, relationships,
   terrain, deltas)
8. Define reward function hierarchy (survival -> HP/gold/allies -> proxy rewards)
9. Build headless simulation mode (game loop without rendering)
10. Build random arena generator (varied maps, obstacles, creature compositions)
11. Implement observation gathering + batched input vector assembly
12. Implement neural net inference engine (NumPy matrix multiplies)
13. Implement RL training harness (PPO/DQN, Gym-compatible environment)
14. Train + evaluate — validate emergent behavior differences across stat profiles
15. Integrate trained model as NeuralBehavior.think() module
16. Implement stat-weighted decision tables as interim/fallback behavior
