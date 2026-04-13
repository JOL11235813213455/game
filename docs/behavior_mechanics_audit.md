# Creature Behavior vs Mechanics vs Rewards Audit

Comprehensive mapping of every creature behavior against its mechanical
implementation, observation signals, reward signals, and curriculum integration.

Generated 2026-04-13. Update when actions, signals, or curriculum change.

---

## MOVEMENT & EXPLORATION

| Behavior | Action | Impl | Preconditions | Arena | Obs Signals | Reward Signals | Unlock | Signal Stage | Gaps |
|----------|--------|------|---------------|-------|-------------|----------------|--------|-------------|------|
| Walk (8 dirs) | MOVE_N–NW (0–7) | `_movement.py:move()` | <200% carry, tile walkable | Yes | spatial_walls, spatial_features, item/food direction | exploration (+0.2/tile), failed_actions (-0.5 wall hit) | S1 | S1 | None |
| Run (auto) | MOVE_N–NW (0–7) | `_movement.py:run()` via `_should_run()` | Stamina >=3, hostile in sight | Yes | stamina_ratio, per_engaged threat | exploration, hp (avoids damage) | S1 (auto) | S1 | No explicit run reward |
| Sneak (toggle) | SET_SNEAK (8) | `_movement.py:sneak()` | Stamina >=1, movement_mode='sneak' | Yes | self_status | exploration | S3 | S3 | **No stealth success reward** |
| Flee | FLEE (26) | `_movement.py:flee()` | Stamina >=3, target creature | Yes | per_engaged threat | hp (avoids damage) | S11 | S11 | None |
| Follow | FOLLOW (27) | `_movement.py:follow()` | Target creature in sight | Yes | per_engaged distance | exploration | S4 | S4 | No explicit follow reward |
| Water/Drowning | Passive tick | `_movement.py:_do_water_tick()` | Liquid tile, depth >= size clearance | Yes (pond) | in_deep_water, nearest_deep_water_dist, can_swim | water_danger (-3.0 submerged, -proximity near) | S1 | S1 | **No swimming mechanic; can_swim never set** |

## COMBAT

| Behavior | Action | Impl | Preconditions | Arena | Obs Signals | Reward Signals | Unlock | Signal Stage | Gaps |
|----------|--------|------|---------------|-------|-------------|----------------|--------|-------------|------|
| Melee Attack | MELEE_ATTACK (9) | `_combat.py:melee_attack()` | Target adj, stamina >=5 | Yes (weapons) | per_engaged threat, self_combat | damage_dealt (log), kills (3.0), xp (10) | S11 | S11 | None |
| Ranged Attack | RANGED_ATTACK (10) | `_combat.py:ranged_attack()` | Bow + ammo, target in range | Yes (bows + arrows) | ammo_qty, weapon_range | damage_dealt, kills, xp | S11 | S11 | None |
| Grapple | GRAPPLE (11) | `_combat.py:grapple()` | Target adj, stamina >=15 | Yes | target STR/AGL | reputation (+/-), kills | S11 | S11 | High stamina cost |
| Cast Spell | CAST_SPELL (12) | `_combat.py:cast_spell()` | Spell known, mana >= cost | Partial (humans know 4 spells via species) | known_spells, mana_ratio | damage_dealt, kills, hp (heals) | S11 | S11 | INT requirements may block some creatures |
| Block Stance | BLOCK_STANCE (31) | `_utility.py:enter_block_stance()` | Item in HAND_L or HAND_R | Yes (shields) | self_status blocking | hp (reduced damage) | S11 | S11 | No explicit block reward |
| Exit Block | EXIT_BLOCK (32) | `_utility.py:exit_block_stance()` | Currently blocking | Yes | self_status | None | S11 | S11 | Housekeeping |
| Set Trap | SET_TRAP (30) | `_utility.py:set_trap()` | Trap item in inventory | Yes (snare traps on hunting tiles) | tile trap_dc | exploration (implicit) | S11 | S11 | **Creator not immune to own trap** |
| Push | PUSH (35) | `_utility.py:push()` | Target adj, stamina >=3, STR contest | Yes | target STR | reputation (-3.0 target) | S11 | S11 | Can push into water/hazards |
| Death | Passive (HP<=0) | `_combat.py:die()` | HP drops to 0 | Yes | alive flag | death (-20.0 first, -1.0 ongoing) | S11+ | S11 | Items drop on tile |

## INVENTORY & EQUIPMENT

| Behavior | Action | Impl | Preconditions | Arena | Obs Signals | Reward Signals | Unlock | Signal Stage | Gaps |
|----------|--------|------|---------------|-------|-------------|----------------|--------|-------------|------|
| Pickup Item | PICKUP (20) | `_inventory.py:pickup()` | Item on tile, weight fits | Yes (dense items) | item/food direction, tile_items, nearest_food_dist | pickup_success (+0.3), inventory, gold | S2 | S2 | No-op on empty tile (not penalized) |
| Pickup Gold | Implicit in PICKUP | `_inventory.py:pickup_gold()` | Gold on tile | Yes (20 surface + all buried) | tile_deep gold | gold (3.0 scale) | S2 | S2 | None |
| Smart Drop | DROP (21) | `_inventory.py:smart_drop()` | Items in inventory | Yes | carried/carry_max, item values | encumbrance_relief, inventory (negative) | S2 | S5 (encumbrance) | Drops lowest value/weight; never drops equipped |
| Auto-Equip | Implicit on PICKUP | `_inventory.py:_try_auto_equip()` | Equippable item, better than current | Yes | equipment slots, eq_kpi | equipment_upgrade (+0.5 log), equipment | S5 | S5 | **NN-only; player excluded** |
| Use Item | USE_ITEM (22) | `_inventory.py:use_item()` | Consumable in inventory | Yes (food, potions) | consumable count, hunger | hunger (+1.0 eating), hp (heal), stamina/mana restore | S3 | S3 | No-op if no consumable (not penalized) |

## ECONOMY

| Behavior | Action | Impl | Preconditions | Arena | Obs Signals | Reward Signals | Unlock | Signal Stage | Gaps |
|----------|--------|------|---------------|-------|-------------|----------------|--------|-------------|------|
| Harvest | HARVEST (38) | `_utility.py:harvest()` | Resource tile, amount > 0 | Yes (5 resource types) | tile resource_type/amount | inventory, xp (+2), purpose_proximity | S5 | S5 | None |
| Farm | FARM (40) | `_utility.py:farm()` | Farmable tile, stamina >=2 | Yes (farming tiles) | tile growth_rate | inventory (future harvest) | S5 | S5 | No direct reward; investment action |
| Dig | DIG (34) | `_utility.py:dig()` | Shovel, buried gold/items | Yes (5 shovels, buried gold everywhere) | tile buried_gold flag | gold, inventory | S5 | S5 | None |
| Process | PROCESS (41) | `_utility.py:process()` | Crafting tile, recipe ingredients | Yes (raw materials on crafting tiles) | tile_purpose, inventory | inventory, xp (+3) | S6 | S6 | First matching recipe used |
| Craft | CRAFT (36) | `_utility.py:craft()` | Completed ItemFrame | Yes (3 pre-filled frames) | inventory ItemFrames | inventory | S6 | S6 | Rare in training |
| Disassemble | DISASSEMBLE (37) | `_utility.py:disassemble()` | ItemFrame with ingredients | Yes | inventory ItemFrames | inventory (ingredients restored) | S6 | S6 | Undo mechanic |
| Job | JOB (39) | `_utility.py:do_job()` | Job assigned, workplace tile, work hours | Yes (60% have jobs) | self_schedule, at_workplace | wage (log), gold, xp | S7 | S7 | Off-hours attempt silently fails |
| Trade | TRADE (15) | `_social.py:auto_trade()` | Target adj, gold/items | Yes (all have gold) | self_economy, per_engaged wealth | trade (surplus), gold, reputation (+2), social_success, xp (+1) | S8 | S8 | Loan fallback if buyer broke |
| Bribe | BRIBE (16) | `_social.py:bribe()` | Target adj, items to offer | Yes | per_engaged relationship | reputation, social_success | S8 | S10 | Threshold scales with relationship |
| Steal | STEAL (17) | `_social.py:steal()` | Target adj, target has items | Yes | per_engaged, stealth/deception | reputation (-8 caught), social_success (silent success) | S8 | S10 | **Successful steal has no reward signal** |

## SOCIAL & RELATIONSHIPS

| Behavior | Action | Impl | Preconditions | Arena | Obs Signals | Reward Signals | Unlock | Signal Stage | Gaps |
|----------|--------|------|---------------|-------|-------------|----------------|--------|-------------|------|
| Intimidate | INTIMIDATE (13) | `_social.py:intimidate()` | Target in sight, sentient | Yes | per_engaged, my intimidation | reputation, social_success | S10 | S10 | None |
| Deceive | DECEIVE (14) | `_social.py:deceive()` | Target in sight | Yes | per_engaged, my deception | reputation (on fail only), social_success | S10 | S10 | **Successful deception silent** |
| Share Rumor | SHARE_RUMOR (18) | `_social.py:share_rumor()` | Target in sight | Yes | per_engaged relationship | reputation (+1 both), social_success | S10 | S10 | None |
| Talk | TALK (19) | `_conversation.py:start_conversation()` | Target in sight | Partial (no dialogue trees in training) | per_engaged | reputation, social_success | S10 | S10 | **Dialogue trees not loaded in arena** |
| Call Backup | CALL_BACKUP (28) | `_utility.py:call_backup()` | Allies within hearing | Yes (pre-seeded relationships) | hearing section, ally count | reputation (+1 responders), allies | S10 | S10 | None |
| Record Interaction | Implicit (all social) | `_relationships.py` via GRAPH | Any creature interaction | Yes | per_engaged sentiment | reputation, allies | S1 (passive) | S10 | None |
| Rumor System | Implicit (share/solicit) | GRAPH.add_rumor() | Rumor received | Yes | per_engaged rumor_opinion | reputation (indirect) | S10 | S10 | Decay via tick; no explicit rumor reward |
| Loans | Implicit in auto_trade | `_relationships.py:give_loan()` | Seller likes buyer, buyer broke | Yes (via trade fallback) | self_economy debt/disposable | debt (2.0 reduction reward), gold | S8 | S8 | **No REPAY action; loans accumulate** |

## SURVIVAL (Passive Mechanics)

| Mechanic | Trigger | Impl | Obs Signals | Reward Signals | Curriculum | Gaps |
|----------|---------|------|-------------|----------------|------------|------|
| Hunger Drain | Tick (1000ms) | `_regen.py:_do_hunger_tick()` | self_hunger (6 floats) | hunger (±), death at HP=0 | S3+ (hunger_drain=True) | None |
| Well-Fed Regen Bonus | hunger >= 0.75 | `_regen.py` hunger_regen_bonus | hunger value | hp, stamina, mana (faster regen) | S3+ | None |
| Starvation Damage | hunger <= -0.5 | `_regen.py:_do_hunger_tick()` | hunger, hp_ratio | hp (negative), death | S3+ | Logarithmic drain |
| HP Regen (Fibonacci) | Tick (1000ms) | `_regen.py:_do_hp_regen()` | hp_ratio, regen state | hp (positive) | S1 | Encumbrance penalty applied |
| Stamina Regen | Tick (1000ms) | `_regen.py:_do_stamina_regen()` | stamina_ratio | Implicit (enables actions) | S1 | Encumbrance penalty applied |
| Mana Regen | Tick (1000ms) | `_regen.py:_do_mana_regen()` | mana_ratio | Implicit (enables spells) | S1 | Encumbrance penalty applied |
| Encumbrance | Passive (weight > capacity) | `_regen.py:encumbrance_penalty()` S-curve | carried/carry_max | encumbrance_relief, regen penalties | S5+ | 0% at <=100%, 50% at 115%, 95% at 130% |
| Encumbrance Movement | Passive (>200% weight) | `_movement.py:move()` | carried/carry_max | failed_actions (can't move) | S1 | Movement blocked at 200% |
| Fatigue/Sleep Debt | Daily tick | External loop calls add_sleep_debt() | sleep_debt, fatigue_level | fatigue (-1.5), sleep_quality (+1.0) | S9+ (fatigue_enabled) | **Daily tick not called in RL loop** |
| Drowning | Tick (100ms) | `_movement.py:_do_water_tick()` | in_deep_water, is_drowning | water_danger (-3.0), hp (damage), death | S1 | **No escape; can_swim never set** |

## REPRODUCTION & LIFECYCLE

| Behavior | Action | Impl | Preconditions | Arena | Obs Signals | Reward Signals | Unlock | Signal Stage | Gaps |
|----------|--------|------|---------------|-------|-------------|----------------|--------|-------------|------|
| Pair (Propose) | PAIR (42) | `_reproduction.py:propose_pairing()` | Male+female adult, adj, same species, willing | Yes (diverse sex/age) | per_engaged sex/age/fertility | life_goals (+2.0), reputation (+5/+3) | S12 | S12 | None |
| Egg Gestation | Passive (mother carries) | Egg in inventory | Mother accepted pairing | Yes | self_status pregnant, inventory egg | None until hatch | S12 | S12 | **Egg never hatches in RL loop** |
| Egg Hatch | External trigger | `Egg.hatch()` | gestation_days threshold | Partial | creature count | life_goals (+1.0) | S12 | S12 | **hatch() not called by training loop** |
| Fecundity Curve | Implicit in pairing | `_reproduction.py:fecundity()` | Female age 18+ | Yes | target fertility signals | life_goals (via successful pair) | S12 | S12 | None |
| Aging | **NOT IMPLEMENTED** | No tick | — | — | age observed but static | — | — | — | **Age never increments in training** |

## CRITICAL GAPS (Sorted by Impact)

### High Impact (Blocks Curriculum Stages)

1. **Egg gestation/hatch not called in RL loop** — S12 (Lifecycle) trains PAIR but
   never completes the reproduction cycle. life_goals reward for hatching unreachable.
   Fix: call `_tick_lifecycle_day()` at day boundaries in headless.py step().

2. **Fatigue daily tick not called** — S9 (Schedule) enables fatigue but
   `add_sleep_debt()` never fires. SLEEP has no pressure to learn against.
   Fix: call daily fatigue tick in headless.py step() at day boundaries.

3. **Age never ticks** — S12+ lifecycle mechanics (menopause, OLD_MIN, youth)
   never activate. Fix: increment age at day boundaries.

### Medium Impact (Weakens Learning)

4. **Successful steal/deceive have no reward signal** — NN learns "don't do these"
   because only failure penalizes. Fix: add `stealth_success` signal (+0.5) for
   successful steal, successful deceive, and undetected sneak-past-hostile.

5. **No swimming mechanic** — can_swim never set; water is always a death trap
   with no escape. Fix: grant can_swim after surviving N ticks in water, or
   via a learnable skill check.

6. **Dialogue trees not loaded in training** — TALK succeeds but does nothing
   meaningful. Fix: load DB dialogue or generate simple training dialogues.

7. **No REPAY_LOAN action** — loans accumulate indefinitely; debt signal fires
   but creature can't act on it. Fix: auto-repay in trade, or add explicit action.

### Low Impact (Polish)

8. **Trap creator not immune to own trap** — can walk into own trap next tick.
9. **No explicit stealth reward** — sneak mode has no signal advantage over walk.
10. **Movement silent-fail on over-encumbrance** — animation plays but position unchanged.
11. **Observation masks untested in training** — masks spawned but never verified.
12. **Sound emission has no RL signal** — creatures emit sounds but no reward for silence.
