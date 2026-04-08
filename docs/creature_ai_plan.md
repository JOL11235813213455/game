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

## Relationship & Rumor System (completed)
- **Relationships**: `{uid: [sentiment, count, min_score, max_score]}`
  - sentiment = raw cumulative score
  - count = number of interactions
  - min/max = bounds of individual interaction scores
  - confidence = `count / (count + 5)` (derived, not stored)
  - curiosity = `1 / (1 + count)` (derived, not stored)
- **Rumors**: `{subject_uid: [(source_uid, sentiment, confidence, tick)]}`
  - Inherited opinions weighted by: source trust * confidence * time decay
  - Strangers get slight trust (0.1) for their rumors
  - Direct experience always outweighs rumors over time
- **Interaction depth weights** (score passed to record_interaction):

  | Interaction type            | Depth weight | Sentiment direction      |
  |-----------------------------|-------------|--------------------------|
  | Observed at distance        | +0.5        | neutral                  |
  | Shared space (same area)    | +1          | neutral                  |
  | Talked                      | +2          | variable (persuasion)    |
  | Traded                      | +3          | + if fair, - if exploit  |
  | Healed/helped               | +4          | positive                 |
  | Fought alongside            | +5          | + if survived            |
  | Fought against              | +5          | negative (attacker more) |
  | Stole from                  | +3          | negative for victim      |
  | Betrayed (attack after +)   | +10         | massive negative         |

## Future Model Input Variables (design notes)
Per-creature observation for the RL model:
- Own stats (7 base stats, key derived stats)
- HP%, stamina%, mana%
- Per nearby creature:
  - distance, relative direction
  - species (observable)
  - relationship sentiment, count, min, max (if known)
  - relationship confidence (derived from count)
  - rumor opinion, rumor confidence (if no direct relationship)
  - curiosity score (high for unknowns)
  - observable threat level (equipment, size, species)
- Terrain: tile type, walkability of adjacent tiles
- Temporal: HP delta, stamina delta, distance-to-nearest-threat delta (over N ticks)
- INT-scaled curiosity reward for information gathering

## Implementation Roadmap
1. ~~Review creature stats, derived stats, contests, and all existing mechanics~~
2. ~~Add stable UID to Trackable (incrementing int, pickle-safe, reset on load)~~
3. ~~Add relationships and rumors to Creature~~
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
