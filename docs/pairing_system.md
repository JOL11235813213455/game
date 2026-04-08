# Pairing, Genetics & Gender Dynamics

## Genetics

### Chromosome Structure
- Each creature has **two chromosomes**, each with **14 genes** (2 per base stat)
- Gene values: 0–15 (4 bits each)
- Males carry **XY** (X from mother, Y from father)
- Females carry **XX** (one X from each parent)
- Gene positions: 0–1 → STR, 2–3 → VIT, 4–5 → AGL, 6–7 → PER, 8–9 → INT, 10–11 → CHR, 12–13 → LCK

### Sex-Linked Stat Biases
- **Y chromosome** carries slight bias toward STR, INT, PER (male-favored stats)
- **Second X chromosome** carries slight bias toward VIT, AGL, CHR (female-favored stats)
- **LCK** encoded on **both X and Y** chromosomes — not sex-linked
- These are statistical tendencies, not hard caps — individual variation is wide

### Inheritance (Mendelian)
- Offspring gets one gene from each parent per position
- Which gene from each parent is random (50/50)
- **Dominance**: higher value at each position is expressed
- Stat influence: sum of dominant values at each stat's positions, scaled to modify species base stats by approximately -3 to +3

### Mutation
- ~2% chance per gene position to randomize the value
- Creates rare stat outliers

### Inbreeding (Graduated Severity)
- Creatures who share a **common ancestor within 3 generations** suffer **deleterious effects**
- Detection: trace `mother_uid` and `father_uid` up to 3 levels for both parents
- Severity scales with **closeness of shared ancestor**:
  - **1 (siblings)**: 20% bad mutation rate per gene
  - **2 (share grandparent)**: 12% bad mutation rate
  - **3 (share great-grandparent)**: 7% bad mutation rate
  - **0 (no shared ancestor)**: normal 2% mutation rate
- Bad mutations are biased toward lower gene values (0–7 instead of 0–15)
- Stored on creature as `inbred: bool` for downstream behavioral/social effects
- **Design intent**: limited genetic stock naturally encourages cross-species pairing
  (abominations) as the lesser evil vs severe inbreeding depression

### Stat Derivation for NPCs
- Genetics primarily determines base stats (STR, VIT, AGL, PER, INT, CHR, LCK)
- Species base stats serve as the foundation; genetic expression shifts them
- Derived stats follow from base stats via existing formulas

### Storage
- Chromosomes stored as list of ints (compact)
- `mother_uid` and `father_uid` stored on creature
- `genetics` field on creature

## Pairing

### Requirements
- Must be male + female
- Both must be **18+ game days old** (adult)
- Female cannot be made pregnant while pregnant
- Male cooldown: **1 game day** (tracked via Trackable timer)
- female cooldown: hatching birthing egg + 1 day
- Minimum positive relationship required — OR barter — OR grapple

### Species Compatibility (Knockout Probability)
Species match acts as a **knockout gate** — checked before any other desirability factor.
- **Same species**: 100% pass (species is not a positive factor, just not a blocker)
- **Different species**: **1% pass** (99% immediate rejection regardless of other factors)
- **Abomination male + non-abomination female**: **0% pass** (never willing)
- **Non-abomination male + abomination female**: **0.5% pass**
- **Abomination + abomination**: **100% pass** (treated as same species)

Only after the species gate passes do the other desirability factors (stats, wealth,
reputation, relationship, prudishness) get evaluated via the trade-based proposal system.

### Proposal as Trade
- Modeled as a virtual trade using existing `propose_trade` mechanics
- Male "offers" a pairing valued by his **desirability**:
  - Stats (STR, CHR weighted heavily)
  - Wealth (inventory value)
  - Reputation (total positive sentiment from others)
  - **Species match** (strongly favors same-species)
- Female evaluates via utility scoring:
  - Sentiment modifier (relationship depth)
  - Inverse of prudishness as acceptance modifier
  - Persuasion bonus from male
  - Fecundity affects willingness (lower fecundity = lower drive)

### Male Willingness
- Inverse of prudishness
- Prioritizes more attractive females
- Increases attempts when perceiving more attractive rival males nearby
- Decreases attempts when surrounded by less attractive males

### Female Willingness
- Requires strength/depth of positive relationship + inverse of prudishness
- Reduces standards when seeing more attractive rival women nearby
- Increases standards when perceiving less attractive rival women
- Prioritizes more attractive males

### Mutual Amorous State
- After willing pairing, both creatures **travel and work together**
- Effectively blend skills and resources
- Shared behavioral goals

### The Act
- A tent sprite pops up to block visibility during the act
- Small HP + stamina cost for the male
- Produces **favorable interactions/rumors from all witnesses** (for willing pairings)

### Forced Encounters (Grapple)
- Male can grapple an unwilling female
- Male **will not** attempt if he perceives witnesses who might rescue via backup call
- Female can call for backup during grapple
- Male will **never** do more than grapple to win the encounter
- **Witness reactions** based on perception of both parties:
  - Witness favors male → **neutral**, don't record the interaction
  - Witness favors female over male → **negative** for male
  - Witness strongly hates female AND loves male → **positive** (rare edge case)
- No forced encounters under age 18

## Pregnancy

### Duration
- **30 game days** of gestation

### Mother's Debuffs (duration of pregnancy)
- Debuff to HP regen
- Debuff to stamina regen
- Debuff to mana regen
- Debuff to agility
- Move speed: **-1 TPS**
- Cannot become pregnant again during pregnancy

### Mother's Buffs (duration of pregnancy)
- Positive interaction enhancer for all creatures **except** other pregnant women
- Increased rate/quality of loot (LOOT_GINI bonus)

### Maternal Stat Buff to Egg
- Egg carried by mother for the full 30 days → **bonus to one or more base stats** of the child
- Abandoned eggs (dropped/stolen) do **not** get this buff
- Time with mother is tracked; partial time = partial buff

### Egg Drop Rules
- Mother **always drops** the egg immediately if offspring will be an abomination
- Mother loses egg → **reputational penalty** + **psychic reward function penalty**

## Egg

### Nature
- An egg is a **special Item** that contains a **full Creature** (unhatched)
- The creature inside has full genetics, stats (at level 0), parents, species
- The egg is essentially a sprite wrapper around the pre-born creature
- The creature inside has **no capability**: no movement, speech, barter, or any action

### Lifecycle
- Can be: carried, dropped, stolen, bought/sold, **eaten**
- Has a **live** status — eggs can periodically stop growing (die)
- Dead eggs remain as items but never hatch
- After 30 days (if alive), egg hatches:
  - If in inventory: drops to tile, then hatches
  - Creature appears on the tile it hatched in

### Eating Eggs
- Any creature can eat an egg
- Eating an egg **of the eater's own species** = **MAJOR reputational event**
  - All witnesses record massive negative
  - Witnesses spread this via rumors — it propagates widely
  - This is one of the most severe social events in the system

### World Limits
- Quiet cap on total eggs in the world (hard number or % of adults)
- Prevents population explosion

## Hatching

### Child at Birth
- Level 0, all level-dependent stats reflect that
- Base stats fully formed via genetics + maternal buff (if applicable)
- Age 0
- Species: same as parents (or "abomination" if cross-species)

### Parent Bonding
- Parents **present at hatching** gain massive positive deep association with the child
- The child will share this positive association via rumors
- Parents present add positive sentiments of children to their own records
- Parents **always side with their children** if they were present at hatching

### Collision
- Children cannot collide with their mother or father until they are adults (18 days)

## Age System

### Age Bands (species-dependent thresholds)
- **Child**: 0–17 game days (cannot pair, vulnerable)
- **Adult**: 18+ game days (can pair, full agency)
- **Old**: species-dependent threshold (reduced fecundity, eventual death?)

### Fecundity (female-only)
- Curve starting at **1.0 at age 18**
- Stays high through prime adulthood
- **Drops sharply** in late adulthood
- Reaches **0.0** at old age threshold
- Affects willingness to pair and probability of successful conception

### Age-Based Behavioral Modifiers
- Older creatures more likely to **deceive/intimidate/swindle** children (<18)
- **Mothers** (who brought children to term) are **kinder to children** overall
- Older women are **more deceptive/hostile** toward younger adult women who are **as/more attractive** and still **fertile**
- Older men treat younger women **favorably** with a direct inverse response curve to age gap

## Gender Dynamics Summary

### Female Competition
- Women reduce standards for men when they can see **more attractive** women nearby
- Women increase standards when perceiving **less attractive** women nearby
- Older women hostile to younger attractive fertile women

### Male Competition
- Men increase pairing attempts when seeing **more attractive** rival men (competitive drive)
- Men decrease attempts when surrounded by **less attractive** men (complacency)

### Universal
- Both sexes **prioritize more attractive** partners
- Attractiveness = utility function of stats, wealth, reputation, species
- Species match is the **strongest** single factor in desirability

### Parental Behavior
- Parents who witnessed hatching **always** side with their children
- Mothers who brought children to term are **kinder to all children**
- Children inherit parental association as deep positive sentiment + spread via rumors

## New Behaviors

### solicit_rumor
- Characters will specifically ask for gossip within hearing range
- Targets: creatures the character has a **weak and/or shallow opinion** of
- Will not solicit rumors about **total strangers** (need at least some awareness)
- Uses CHR-scaled probability (same as share_rumor)
- Purpose: gather information about acquaintances before interacting

## Implementation Notes

### Cooldowns via Trackable Timer
- Male pairing cooldown: `register_tick('pair_cooldown', 1_day_ms, callback)`
- Female pregnancy: full 30-day tick with debuffs applied on start, removed on hatch
- Both use the existing timed event system

### Desirability Function
Species is a **knockout gate**, not a weighted factor. After gate passes:
```
desirability(creature, evaluator):
    # Species gate already passed before this is called
    stat_score = weighted_sum(STR, CHR, VIT, AGL, ...)  # sex-dependent weights
    wealth = inventory_value + equipment_value
    reputation = sum of positive sentiments from others / total relationships
    return stat_score * 0.4 + wealth * 0.3 + reputation * 0.3
```

### Egg as Item Subclass
- New class: `Egg(Item)` with `creature` field, `live` bool, `days_with_mother` int
- Special methods: `hatch()`, `die()`, `tick_gestation()`
- Override `inventoriable = True` for pickup/trade
