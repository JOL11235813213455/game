# Creature AI Implementation Plan

## Approach
Single shared neural net for all creatures. Stats are input features, so behavioral
differentiation emerges from stat profiles rather than hardcoded archetypes. Trained
via reinforcement learning in headless multi-agent simulations.

## Key Design Decisions
- **One net, many creatures** — no separate models per species/archetype
- **Stats drive behavior** — high-STR creatures discover fighting is effective, high-CHR
  discover social strategies, because the game mechanics reward what their stats are good at
- **Relationships tracked per creature** — `{uid: [sentiment, count, min_score, max_score]}`
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
- Grapple: max(STR, AGL) vs max(STR, AGL-1) for defender; stamina-out = lose
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

## Action Space

### Movement
| Action       | Target         | Stamina cost                    | Notes                              |
|--------------|----------------|---------------------------------|------------------------------------|
| Walk         | adjacent tile  | 0 (unless encumbered)           | Current move system                |
| Run          | adjacent tile  | per-second cost, reduced by VIT | 150% speed                         |
| Sneak        | adjacent tile  | small cost                      | STEALTH active, reduced speed      |

- **Overencumbered**: speed halved for every 10% over CARRY_WEIGHT
- Movement is real-time, interval derived from MOVE_SPEED (TPS)

### Combat
| Action        | Target              | Cost        | Notes                                    |
|---------------|---------------------|-------------|------------------------------------------|
| Melee attack  | adjacent creature   | stamina     | Weapon-defined timing, anim, hitbox=tile  |
| Ranged attack | creature in range   | stamina     | accuracy_at_distance, reload timer        |
| Cast spell    | varies by spell     | mana        | Can be dodged unless spell is undodgeable |
| Block (stance)| self                | passive drain | Continuous; enables block contest       |
| Dodge (stance)| self                | per-dodge   | Continuous; default active defense        |
| Grapple       | adjacent creature   | high stamina | max(STR,AGL) vs max(STR,AGL-1); stamina-out loses |

- **No cooldown** on melee or spells (gated by stamina/mana)
- **Ranged reload**: weapon-specific timer (e.g. pistol: 13 shots then 3s reload)
- **Dodge/block require SIGHT_RANGE** — must see attacker
- **Block/dodge are continuous stances**, not per-attack reactions
- Melee: one action type, weapon defines characteristics (timing, damage, animation)

### Social
| Action        | Target           | Cost | Notes                                       |
|---------------|------------------|------|---------------------------------------------|
| Talk          | nearby creature  | none | Opens social menu with context management   |
| Intimidate    | nearby creature  | none | d20 contest vs FEAR_RESIST                  |
| Deceive       | nearby creature  | none | d20 contest vs DETECTION                    |
| Trade         | nearby creature  | none | Negotiation via utility scoring             |
| Share rumor   | nearby creature  | none | CHR scales gossip probability               |
| Steal         | nearby creature  | none | Deception during trade, or sneak + separate |
| Bribe         | nearby creature  | items/gold | Offer valuables to shift behavior; pairs with intimidation |
| Seduce        | nearby creature  | none       | CHR contest; affects pairing, loyalty, manipulation       |

- **Failed persuasion/intimidation** carries social cost (negative interaction recorded)
- **Talk** opens sub-menu (SQL-driven context management)
- **Bribe** — available standalone or as response to intimidation; value function determines if bundle is enough

### Utility
| Action        | Target           | Cost         | Notes                              |
|---------------|------------------|--------------|------------------------------------|
| Use item      | self/other       | varies       | Consumables, equipment             |
| Pick up       | item on tile     | none         |                                    |
| Drop          | item in inventory| none         |                                    |
| Wait/observe  | none             | none         | Gather info, recover stamina       |
| Enter/exit    | tile link        | none         | Already implemented                |
| Guard         | tile/creature    | stamina drain| Territorial, defensive posture     |
| Follow        | creature         | movement cost| Stay near target                   |
| Flee          | away from threat | run cost     | Move away at max speed             |
| Search tile   | current tile     | none         | Peek into tile inventory (ore, gold, items auto-spawn) |
| Search world  | map              | movement     | Pathfinding A→B across maps        |
| Hunt          | creature/area    | movement     | Track and pursue prey              |
| Set trap      | tile             | stamina+item | Trap = tile property + item type; for hunting and guard |
| Call backup   | allies in hearing range | none  | Responders within HEARING_RANGE of caller; filter by relationship + species |
| Sleep/rest    | safe location    | none         | Day/night cycle; debuffs stack without sleep (see below) |
| Pair/bond     | creature         | none         | Mating/bonding action; species-centric behavior        |

- **Sleep deprivation debuffs** (stacking):
  1. Mild fatigue — minor stat reduction
  2. Exhaustion — significant stat penalties, reduced stamina regen
  3. Severe — hallucinations (reduced detection/accuracy), impaired judgment
  4. Collapse — forced sleep, creature is vulnerable
- **Day/night cycle** drives sleep as a survival pressure
- **Pairing** — bonding/mating action, strengthens relationship, species-specific behavior

## Negotiation System (design)
The model outputs **utility scores** per action, not deterministic decisions.
Two creatures negotiate by comparing utility values:

1. Each creature's model scores possible outcomes
2. Sentiment modifier shifts willingness (friends accept worse deals)
3. INT-scaled noise (high INT = rational, low INT = impulsive)
4. Iterative counter-offers until both scores positive or walk-away
5. Failed negotiation = negative social interaction recorded

Example — trade:
```
A offers 5 gold for sword
  A's utility: "sword worth 8 to me, losing 5 gold costs 5" → net +3
  B's utility: "sword costs me 6, gaining 5 gold worth 5" → net -1
  B counters: 7 gold
  A's utility: net +1 (still positive) → accepts
```

This generalizes beyond trade:
- **Pre-combat sizing up**: both score fight/flee/talk, interaction is emergent
- **Alliance formation**: both score "cooperate" based on shared enemies, trust
- **Territory disputes**: utility of holding ground vs conflict cost

## Interaction Mechanics

### Melee Attack
1. Stamina check: `cost = max(5, weapon_base_cost - dmod(STR))` → fail if insufficient
2. Can defender see attacker? (SIGHT_RANGE - attacker's STEALTH)
   - **Yes**: defender chooses dodge, block, or flee
   - **No**: auto-hit (ambush)
3. If dodge: `d20 + MELEE_DMG vs d20 + DODGE` (MELEE_DMG is attack stat for melee, not ACCURACY)
   If block: `d20 + MELEE_DMG vs d20 + BLOCK` (requires shield)
   If flee: defender attempts to move away; if attacker faster, hit lands
4. Hit lands → `resist_check(weapon_dc vs ARMOR)` — weapon_dc is weapon property
5. Damage = `dmod(STR) + weapon_mod + weapon_dice + (LCK+1)/(LCK+2) chance of STR again`
6. Crit check: roll under CRIT_CHANCE% → max damage + dmod(STR) + lucky STR
7. Stagger check: `resist_check(weapon_impact vs STAGGER_RESIST)` — weapon_impact is a weapon property (warhammer > dagger)
8. Defender calls `on_hit(now)` → resets HP regen timer
9. **Interactions**: defender records negative. Attacker: no auto-sentiment, but attacking
   someone with positive history = betrayal (massive negative both sides).
   Witnesses update impressions of both creatures.

### Ranged Attack
1. Stamina check + ammo check → reload timer if magazine empty (weapon-specific)
2. `accuracy_at_distance(tiles)` → probability roll for hit
3. If defender can see attacker: dodge contest (block unlikely vs projectile)
4. Hit → same armor/damage/crit/stagger chain as melee
5. Damage = weapon_mod + ammo_mod + weapon_dice (STR only if weapon requires it, e.g. bow)
6. **Interactions**: if defender can see attacker, record negative interaction for defender.
   Attacker: no auto-sentiment. Witnesses update impressions.
7. **Equipment**: requires weapon in appropriate slot + ammunition type match

### Cast Spell
1. Mana check: `cost = spell_mana_cost`
2. If dodgeable spell: accuracy vs dodge contest
   If undodgeable: auto-lands, straight to resist
3. `resist_check(spell_dc vs MAGIC_RESIST)`
4. If lands: apply effect (damage, debuff, heal, etc.)
5. Spell-specific secondary resists (poison_dc vs POISON_RESIST, etc.)
6. **Interactions**: offensive spells record negative for target (if aware).
   Healing spells record positive. Witnesses update impressions.

### Grapple
1. High stamina cost to initiate
2. Contest: `d20 + max(STR, AGL) vs d20 + max(STR, AGL-1)` (defender slight disadvantage on agility escape)
3. If grapple succeeds: both locked, stamina drains each tick
4. First to run out of stamina loses
5. Loser: prone, vulnerable, skip next action
6. **Interactions**: negative for both, but **loser takes extra social hit** — losing a grapple
   is a dominance display. Witnesses (especially same species, opposite sex) update
   impressions: winner gains status, loser loses status.

### Intimidate
1. `d20 + INTIMIDATION vs d20 + FEAR_RESIST`
2. **Success**: target's behavior shifts (flee, submit, concede).
   Probabilistic: target may believe bully was right → chance of **positive** registration
   for intimidator (dominance accepted). Negative for target.
3. **Failure**: negative interaction for BOTH (intimidator looks weak, target is annoyed)
4. **Bribe response**: target can counter with bribe offer using value function

### Deceive
1. `d20 + DECEPTION vs d20 + DETECTION`
2. **Success**: target believes false info
   - In trade: unfair exchange accepted
   - In rumor: fake rumor planted
   - In pickpocket: theft unnoticed
3. **Failure**: negative interaction, trust severely damaged.
   If during trade: trade cancelled + relationship hit.

### Trade (Negotiation)
1. Both creatures' models score the proposed exchange (utility vectors)
2. Sentiment modifier: friends shift willingness up
3. Persuasion bonus for initiator enhances perceived value
4. Counter-offer loop until agreement or walk-away
5. **Fair trade**: +3 sentiment both sides
6. **Exploitative**: +3 exploiter, -3 victim (if realized later via INT check)
7. **Walk-away**: -1 sentiment both sides

### Search Tile
1. Reveals tile inventory (auto-spawned: ore, gold, items)
2. Hidden items: `d20 + DETECTION vs hidden_dc`
3. LOOT_GINI affects quality/rarity of spawned items

### Hunt
1. Track: DETECTION + PER to locate prey
2. Approach: `stealth_vs_detection` contest
3. Engage: combat or trap trigger
4. Success: food/materials/XP

### Set Trap
1. Requires trap item in inventory
2. Placed as tile property
3. Trap stealth = CRAFT_QUALITY + trap item quality
4. Trigger: creature enters tile → `trap_dc vs appropriate resist`
5. Types: hunting (food/capture) or guard (defense/alarm)

### Sleep/Rest
1. Creature judges location safety (model decision)
2. Sleep state: vulnerable, no dodge/block, reduced DETECTION
3. Stamina + mana fully restored over sleep duration
4. Sleep debt cleared based on duration
5. Interrupted: partial recovery + groggy debuff

### Call Backup
1. Broadcast within caller's shout radius
2. Potential responders check: is caller within MY HEARING_RANGE?
3. Filter: relationship sentiment > threshold, species/racial affinity, own safety
4. Responders move toward caller
5. **Interactions**: responding to a call = large positive for caller toward responder.
   Fighting alongside = +5 sentiment (fought alongside weight).
   **Killing an enemy for someone** = massive positive.
   **Dying in battle for someone** = permanent positive legacy (recorded even after death,
   carried as rumor by survivors — "they died fighting for X").

### Bribe
1. Offer items/gold to target
2. Target's model evaluates: value of bribe vs current intent
3. Especially relevant as response to intimidation
4. Accepted: positive interaction, behavior shift
5. Rejected: minor negative, items returned

### Seduce
1. `d20 + PERSUASION vs d20 + FEAR_RESIST` (or a new WILLPOWER-like check?)
2. Modified by: species compatibility, existing relationship, sex match for species
3. **Success**: large positive sentiment, potential pairing, loyalty shift
   Target may switch allegiances, share secrets, grant access
4. **Failure**: negative interaction (awkward), possible intimidation/hostility trigger
5. Can be used manipulatively — seduce then betray is ultimate betrayal weight

## Species Configuration (design)
- **Sex**: creature attribute, affects pairing, display behavior, territorial competition
- **Species preferences**: preferred/hated species (dropdown in editor)
- **General proclivities**: aggression baseline, sociability, territoriality, curiosity modifier
- **Prudishness**: species default (0.0–1.0), stored per creature, shifts with experience.
  Gates seduce/pairing behavior. High = harder to seduce, less likely to initiate,
  may react negatively to attempts. Shifts down with successful seduction,
  shifts up witnessing negative pairing outcomes.
- These are species-level defaults that individual creatures can deviate from via experience

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
4. ~~Define action space~~
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
