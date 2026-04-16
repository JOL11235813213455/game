# Monsters & Packs ERD

Monsters are a parallel entity hierarchy to creatures. They share
combat/movement/regen infrastructure via mixin reuse (no inheritance
from Creature) and are coordinated by a `Pack` class that holds its
own NN.

## Entity Relationships

```mermaid
erDiagram
    monster_species ||--o{ monster_species_stats : "stats"
    monster_species ||--o{ MONSTER : "instances"
    items ||--o{ monster_species : "natural_weapon_key"

    PACK ||--o{ MONSTER : "members_m + members_f"
    PACK }o--|| monster_species : "species config"
    MONSTER ||--o{ MEAT : "drops on die()"

    CREATURE ||--o{ MEAT : "drops on die()"
    CREATURE }o--o{ MEAT : "EAT via use_item"

    monster_species {
        TEXT name PK
        TEXT sprite_name
        TEXT composite_name
        REAL tile_scale
        TEXT size
        REAL meat_value
        TEXT diet
        TEXT compatible_tile
        INTEGER split_size
        REAL territory_size
        INTEGER territory_scales
        TEXT dominance_type
        INTEGER collapse_on_alpha_death
        TEXT active_hours
        INTEGER swimming
        INTEGER ambush_tactics
        INTEGER protect_young
        TEXT natural_weapon_key
        TEXT egg_sprite
        TEXT model_name
        INTEGER model_version
    }

    monster_species_stats {
        TEXT species_name PK
        TEXT stat PK
        INTEGER value
    }

    MONSTER {
        int uid
        str species
        str sex
        int age
        str size
        float meat_value
        str diet
        int split_size
        float territory_size_max
        bool territory_scales
        str dominance_type
        bool collapse_on_alpha_death
        str active_hours
        bool can_swim
        bool ambush_tactics
        bool protect_young
        str natural_weapon_key
        Pack pack
        int rank
        bool is_alpha
        float pack_sleep_signal
        float pack_alert_level
        float pack_cohesion
        str pack_role
        MapKey pack_target_position
        bool is_fleeing
    }

    PACK {
        int uid
        str species
        MapKey territory_center
        Map game_map
        list members_m
        list members_f
        dict seen_creatures
        dict member_state
        float sleep_signal
        float alert_level
        float cohesion
        dict role_fractions
    }

    MEAT {
        str species
        float meat_value
        int spoil_tick
        bool is_cooked
        bool is_preserved
        bool is_monster_meat
    }
```

## Monster → Pack Relationship

Every monster is a member of exactly one pack. Solitary species
(cave_bear) still live in a size-1 pack. When a pack's alpha dies:

- Species with `collapse_on_alpha_death=True` (bees, army_ants) →
  the pack dissolves; each survivor becomes its own 1-member pack.
- Species with `collapse_on_alpha_death=False` (wolves, orcs) → the
  next-ranked member auto-promotes and the pack persists.

```mermaid
stateDiagram-v2
    [*] --> Active: add_member
    Active --> Active: size < split_size
    Active --> Splitting: size >= split_size
    Splitting --> Active: two subpacks formed
    Active --> Merging: meets compatible small pack
    Merging --> Active: winner absorbs loser
    Active --> Collapsing: alpha dies + collapse_on_alpha_death
    Active --> Active: alpha dies + !collapse (beta promotes)
    Collapsing --> [*]: all members become solitary packs
```

## Territory Math

Effective roaming standard deviation for a pack:

```
if species.territory_scales:
    effective = species.territory_size × (pack.size / max(1, split_size-1))
    effective = max(species.territory_size × 0.1, effective)
else:
    effective = species.territory_size

sampling_std = effective × (1 - cohesion × 0.8)
```

Each monster samples a target position from `N(territory_center, sampling_std)`.
The 3σ practical radius is used for territory overlap checks.

```mermaid
graph LR
    SPECIES[species.territory_size MAX] --> SCALE{territory_scales?}
    SCALE -->|yes| S1[× pack.size / split_size-1]
    SCALE -->|no| S2[fixed]
    S1 --> CLAMP[max 10% floor]
    S2 --> FINAL[effective_territory_size]
    CLAMP --> FINAL
    FINAL --> COH[× 1 - cohesion × 0.8]
    COH --> STD[sampling_std]
    STD --> SAMPLE[N center, sampling_std]
    SAMPLE --> POS[monster target position]
```

## Pack-vs-Pack Interactions

```mermaid
flowchart TD
    MEET[Two packs' territories touch]
    MEET --> SPECIES{Same species?}
    SPECIES -->|no| HOSTILE[Combat on overlap]
    SPECIES -->|yes| SIZE{Combined <= split_size/2?}
    SIZE -->|yes| MERGE[Merge ritual<br/>alpha-vs-alpha fight<br/>winner's pack ranks top]
    SIZE -->|no| HOSTILE
    HOSTILE --> OVERLAP{Territory overlap?}
    OVERLAP -->|no| NEUTRAL[Ignore each other]
    OVERLAP -->|yes| ATTACK[Attack on contact every tick<br/>attrition combat]
```

## Shared Perception

Monsters push perceptions into their pack's shared state; the pack NN
consumes aggregated values on its next tick.

```mermaid
sequenceDiagram
    participant M as Monster (any member)
    participant P as Pack
    participant NN as PackNet

    Note over M,P: Perception events (every monster tick)
    M->>P: on_creature_spotted(uid, x, y, tick)
    M->>P: on_member_state(uid, hp_ratio, x, y, hunger)

    Note over P,NN: Pack NN tick (~every 2s)
    P->>P: aggregate member_state + seen_creatures
    P->>NN: build_pack_observation (14 floats)
    NN-->>P: (sleep, alert, cohesion, role_fractions)
    P->>P: broadcast_signals (delta-threshold)
    P->>M: on_pack_signal(sleep, alert, cohesion, role) if changed
```

## Monster Action Space

```mermaid
graph TD
    subgraph "11 actions (INT-gated mask)"
        A0[0 MOVE]
        A1[1 PATROL]
        A2[2 GUARD]
        A3[3 ATTACK]
        A4[4 PAIR]
        A5[5 EAT]
        A6[6 HOWL]
        A7[7 FLEE]
        A8[8 REST]
        A9[9 PROTECT_EGG]
        A10[10 HARVEST]
    end

    INT{INT score}
    INT -->|1-3 instinct| INST[MOVE / ATTACK / FLEE only]
    INT -->|4-7 feral| FERAL[+ PATROL, GUARD, EAT, REST, PROTECT_EGG]
    INT -->|8-12 aware| AWARE[+ HOWL, PAIR]
    INT -->|13+ cunning| CUN[full set + future goal selection]

    DIET{diet}
    DIET -->|herbivore/omnivore + INT>=4| HARV[HARVEST enabled]
    DIET -->|carnivore or INT<4| NOHARV[HARVEST disabled]

    STAM{stamina}
    STAM -->|<3| NOATK[ATTACK disabled]
    STAM -->|<1| NOFLEE[FLEE disabled]
```

## Death → Meat → Consumption Loop

```mermaid
sequenceDiagram
    participant M as Monster (dying)
    participant T as Tile
    participant C as Creature (eating)
    participant G as RelationshipGraph

    M->>M: die() — HP = 0
    M->>T: drop Meat<br/>species=M.species<br/>meat_value=M.meat_value<br/>spoil_tick=now+48hr<br/>is_monster_meat=True
    M->>M: pack.remove_member(M)

    Note over C,G: Later: creature eats meat
    C->>T: EAT (action or use_item)
    T-->>C: first Meat item
    C->>C: check Meat.is_spoiled(now)
    C->>C: hunger += meat_value
    alt meat.species == C.species (cannibalism)
        C->>G: record_interaction broadcast -15 to witnesses
        C->>C: piety -= 0.1
        C->>C: _cannibalism_events += 1
    end
```

## NN Stack — Monster + Pack

```mermaid
graph TD
    subgraph Inference runtime
        MNN[MonsterNet<br/>73→256→128→64→11<br/>numpy softmax]
        PNN[PackNet<br/>14→64→32→6<br/>numpy sigmoids + softmax]
    end

    subgraph Training
        TMP[TorchMonsterPolicy<br/>actor + critic heads]
        TPP[TorchPackPolicy<br/>actor + critic heads]
        MTR[MonsterTrainer<br/>PPO + REINFORCE]
        TMP --> MTR
        TPP --> MTR
    end

    subgraph Pretrain
        HEUR[heuristic_monster_action<br/>priority cascade]
        HEURP[heuristic_pack_outputs]
        DS[monster_imitation<br/>generate dataset]
        PRETRAIN[monster_pretrain.py<br/>supervised CE + DAgger]
        HEUR --> DS
        HEURP --> DS
        DS --> PRETRAIN
        PRETRAIN -.-> MNN
        PRETRAIN -.-> PNN
    end

    MTR -.export_inference_npz.-> MNN
    MTR -.export_inference_npz.-> PNN
    MNN --> ATK[action mask + softmax + sample]
    PNN --> SIG[sleep/alert/cohesion sigmoids + role softmax]
```

## Curriculum Stages for Monsters

| Stage | Name | Creature | Monster | Pack | Focus |
|---|---|---|---|---|---|
| 15 | M_Survive | frozen | training | n/a | solo hunger + territory |
| 16 | M_Eat | frozen | training | n/a | meat + grazing |
| 17 | M_Hunt | frozen | training | n/a | kill + chase |
| 18 | M_Pack | frozen | training | training | cohesion + coordination |
| 19 | M_Dominance | frozen | training | training | challenges + pairing |
| 20 | M_Lifecycle | frozen | training | training | eggs + splits + merges |
| 21 | C_Predation | **training** | frozen | frozen | threat avoidance + cannibalism penalty |
| 22 | C_Ecosystem | **training** | frozen | frozen | queen-targeting + territory rumors |
| 23 | Coevo_A | training | training | training | alternating epochs |
| 24 | Coevo_B | training | training | training | league training (if needed) |
| 25 | Final | training | training | training | reduced LR, equilibrium |

## File Reference

| File | Purpose |
|------|---------|
| `src/classes/monster.py` | Monster class (WorldObject-based, reuses mixins) |
| `src/classes/pack.py` | Pack (Trackable) — territory, dominance, signals |
| `src/classes/monster_actions.py` | 11 actions + compute_monster_mask |
| `src/classes/monster_observation.py` | 73-float observation builder |
| `src/classes/monster_dispatch.py` | Action dispatch table |
| `src/classes/monster_runtime.py` | monster_tick + pack housekeeping |
| `src/classes/monster_reward.py` | 16 signals + snapshot |
| `src/classes/monster_heuristic.py` | Priority cascade policies |
| `src/classes/monster_net.py` | MonsterNet numpy inference |
| `src/classes/pack_net.py` | PackNet numpy inference |
| `src/classes/monster_imitation.py` | Dataset generator |
| `src/classes/inventory.py::Meat` | Meat item subclass |
| `editor/simulation/monster_train.py` | MonsterTrainer (PPO + REINFORCE) |
| `editor/simulation/monster_pretrain.py` | Imitation + DAgger pretrain |
| `editor/simulation/league_pool.py` | Snapshot pool for co-evolution |
| `editor/monster_species_tab.py` | Editor tab for monster_species DB |
| `editor/training_pairs_tab.py` | Training pair management |
