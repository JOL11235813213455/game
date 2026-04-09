# Stats System ERD

## Four-Layer Architecture

```mermaid
graph TB
    subgraph "Stats Object"
        BASE["base dict<br/>STR, PER, VIT, INT, CHR, LCK, AGL<br/>LVL, EXP, HD<br/>CHP, CUR_STAMINA, CUR_MANA"]
        DERIVED["derived dict<br/>(cache, refreshed on demand)"]
        MODS["mods list<br/>[{source, stat, amount, stackable}, ...]"]
        ACTIVE["active dict<br/>Stat -> callable<br/>active[Stat.X]() = final value"]
    end

    BASE --> |base + sum_mods| ACTIVE
    DERIVED --> |formula + sum_mods| ACTIVE
    MODS --> |sum_mods| ACTIVE

    ACTIVE --> |read by| GAME[Game Systems]

    style ACTIVE fill:#4a6,color:#fff
    style BASE fill:#46a,color:#fff
    style MODS fill:#a64,color:#fff
```

## Active Value Resolution

```mermaid
graph LR
    CALL["active[Stat.MHP]()"] --> IS_BASE{base layer stat?}

    IS_BASE -->|yes| BASE_VAL["base[stat]"]
    BASE_VAL --> ADD_MODS1["+ sum_mods(stat)"]
    ADD_MODS1 --> RESULT[final int value]

    IS_BASE -->|no| FORMULA["DERIVED_FORMULAS[stat]"]
    FORMULA --> |"formula(getter)"| COMPUTED["computed from<br/>active base stats"]
    COMPUTED --> ADD_MODS2["+ sum_mods(stat)"]
    ADD_MODS2 --> RESULT

    style CALL fill:#4a6,color:#fff
    style RESULT fill:#46a,color:#fff
```

## Derived Stat Formula Map

```mermaid
graph TD
    subgraph "Base Stats"
        STR[STR]
        PER[PER]
        VIT[VIT]
        INT_[INT]
        CHR[CHR]
        LCK[LCK]
        AGL[AGL]
    end

    subgraph "Combat"
        STR --> MELEE[MELEE_DMG]
        STR --> BLOCK[BLOCK]
        STR --> CRIT_DMG[CRIT_DMG]
        PER --> RANGED[RANGED_DMG]
        PER --> ACCURACY[ACCURACY]
        PER --> CRIT_DMG
        INT_ --> MAGIC[MAGIC_DMG]
        AGL --> ATK_SPD[ATK_SPEED]
        AGL --> DODGE[DODGE]
        LCK --> CRIT_CH[CRIT_CHANCE]
        VIT --> MHP[MHP]
        VIT --> ARMOR[ARMOR]
    end

    subgraph "Movement"
        AGL --> MOVE[MOVE_SPEED]
        AGL --> STEALTH[STEALTH]
        PER --> SIGHT[SIGHT_RANGE]
        PER --> HEARING[HEARING_RANGE]
        PER --> DETECT[DETECTION]
        STR --> CARRY[CARRY_WEIGHT]
    end

    subgraph "Resources"
        VIT --> MSTAM[MAX_STAMINA]
        AGL --> MSTAM
        INT_ --> MMANA[MAX_MANA]
        INT_ --> MREGEN[MANA_REGEN]
        VIT --> HPREGEN[HP_REGEN]
        AGL --> STAMREG[STAM_REGEN]
    end

    subgraph "Resistance"
        VIT --> POISON[POISON_RESIST]
        VIT --> DISEASE[DISEASE_RESIST]
        INT_ --> MAGRES[MAGIC_RESIST]
        STR --> STAGGER[STAGGER_RESIST]
        CHR --> FEAR[FEAR_RESIST]
    end

    subgraph "Social"
        CHR --> BARTER[BARTER_MOD]
        CHR --> DISP[NPC_DISPOSITION]
        CHR --> COMP[COMPANION_LIMIT]
        CHR --> PERS[PERSUASION]
        INT_ --> PERS
        CHR --> INTIM[INTIMIDATION]
        STR --> INTIM
        CHR --> DECEP[DECEPTION]
        AGL --> DECEP
    end

    subgraph "Loot/Craft"
        LCK --> LOOT[LOOT_QUALITY]
        INT_ --> CRAFT[CRAFT_QUALITY]
        PER --> CRAFT
        STR --> DURAB[DURABILITY_USE]
        INT_ --> XP[XP_MOD]
        LCK --> XP
    end
```

## Opposing Stat Contests

```mermaid
graph LR
    subgraph "Attacker"
        A_STAT["active[atk_stat]()"]
        A_ROLL["+ d20 roll"]
    end

    subgraph "Defender"
        D_STAT["active[def_stat]()"]
        D_ROLL["+ d20 roll"]
    end

    A_STAT --> A_ROLL --> COMPARE{margin = atk - def}
    D_STAT --> D_ROLL --> COMPARE

    COMPARE -->|"> 0"| WIN["(True, margin)"]
    COMPARE -->|"<= 0"| LOSE["(False, margin)"]
```

| Contest Name | Attacker Stat | Defender Stat |
|---|---|---|
| stealth_vs_detection | STEALTH | DETECTION |
| accuracy_vs_dodge | ACCURACY | DODGE |
| persuasion_vs_fear | PERSUASION | FEAR_RESIST |
| intimidation_vs_fear | INTIMIDATION | FEAR_RESIST |
| deception_vs_detection | DECEPTION | DETECTION |
| melee_vs_armor | MELEE_DMG | ARMOR |
| melee_vs_block | MELEE_DMG | BLOCK |
| magic_vs_resist | MAGIC_DMG | MAGIC_RESIST |
| stagger_vs_resist | MELEE_DMG | STAGGER_RESIST |
| poison_vs_resist | MAGIC_DMG | POISON_RESIST |

## Leveling Flow

```mermaid
sequenceDiagram
    participant C as Creature
    participant S as Stats
    participant CB as on_level_up callbacks

    C->>S: gain_exp(amount)
    S->>S: Apply XP_MOD bonus
    S->>S: base[EXP] += effective amount
    S->>S: _reconcile_exp_level()
    alt level increased
        S->>S: unspent_stat_points += levels * 3
        S->>CB: _level_up_heal(stats, old, new)
        CB->>S: add_mod('level_N_hp', MHP, d(HD)+VIT)
        CB->>S: base[CHP] = active[MHP]()
        CB->>S: base[CUR_STAMINA] = active[MAX_STAMINA]()
        CB->>S: base[CUR_MANA] = active[MAX_MANA]()
    end
```
