# Comprehensive Comparison of RPG Attribute/Stat Systems

---

## 1. Dungeons & Dragons (5th Edition)

**Primary Attributes (6):** STR, DEX, CON, INT, WIS, CHA

**Scale:** 1–30 (typically 3–20 for player characters; 20 is the normal cap, though some features push to 30)

**Modifier Formula:** `modifier = floor((score - 10) / 2)`

| Score | Modifier |
|-------|----------|
| 1     | -5       |
| 8     | -1       |
| 10    | +0       |
| 14    | +2       |
| 18    | +4       |
| 20    | +5       |

**Attributes:**

- **Strength (STR)** — Melee attack/damage rolls, carrying capacity (STR x 15 lbs), Athletics checks, jump distance, grapple/shove. Governs heavy armor eligibility (minimum STR to avoid speed penalty).
- **Dexterity (DEX)** — Ranged attack/damage, finesse melee weapons, Armor Class (when wearing light/medium armor or none), initiative rolls, Acrobatics, Sleight of Hand, Stealth checks. Widely considered the strongest stat due to breadth of use.
- **Constitution (CON)** — Hit points (modifier added per level, retroactively), concentration saving throws for spellcasters, resistance to poison/disease/exhaustion. No skills are keyed to CON. Cannot be used as a dump stat by any class.
- **Intelligence (INT)** — Spellcasting stat for Wizards, Artificers. Arcana, History, Investigation, Nature, Religion checks. Relatively narrow; often a dump stat for non-INT casters.
- **Wisdom (WIS)** — Spellcasting stat for Clerics, Druids, Rangers. Perception (the single most-rolled skill), Insight, Survival, Medicine, Animal Handling. Wisdom saving throws are extremely common (charm, fear, many high-level effects).
- **Charisma (CHA)** — Spellcasting stat for Bards, Paladins, Sorcerers, Warlocks. Persuasion, Deception, Intimidation, Performance. Some class features key off CHA (Paladin's aura, Sorcerer's metamagic DC).

**Derived Stats:**
- Hit Points: CON modifier x level + class hit die rolls
- Armor Class: varies by armor type; DEX modifier is the most common contributor
- Initiative: DEX modifier (+ possible features)
- Saving Throws: each of the 6 stats has its own save; proficiency in 2 is granted by class
- Passive Perception: 10 + WIS modifier + proficiency (if proficient)
- Spell Save DC: 8 + proficiency bonus + casting stat modifier
- Spell Attack: proficiency bonus + casting stat modifier

**Design Notes:** D&D 5e has a flat modifier curve. The bounded accuracy system means a +1 is always meaningful. The 6-stat model is the most influential in RPG history and is the template many systems react to or simplify.

---

## 2. Fallout S.P.E.C.I.A.L.

**Primary Attributes (7):** Strength, Perception, Endurance, Charisma, Intelligence, Agility, Luck

**Scale:** 1–10 (base); can be boosted to 11+ via items, perks, chems. At character creation you typically distribute 28 points across 7 stats (Fallout 3/NV) or 21 points (Fallout 4, starting from 1 each).

**Attributes:**

- **Strength (S)** — Melee/unarmed damage, carry weight (150 + 10 x STR in FNV), weapon strength requirements.
- **Perception (P)** — Ranged weapon accuracy (VATS hit chance), detection of traps/enemies, lockpicking access (FO4 perk gate), compass detection range. In classic Fallout (1/2), governed Sequence (turn order).
- **Endurance (E)** — Hit points per level, resistance to poison/radiation, sprint AP cost (FO4). In FO1/2: base HP = 15 + (2 x EN) + STR, and HP per level = EN/2 (rounded down) + 3.
- **Charisma (C)** — NPC disposition, companion limit (FO4), speech check modifiers, barter prices. Historically the dump stat because speech skill could compensate.
- **Intelligence (I)** — Skill points per level (FO1/2/3/NV: base + IN/2 per level). In FO4: directly scales XP gain (+3% per point). The "meta" stat in most Fallout games because more skill points compound.
- **Agility (A)** — Action Points in VATS (base AP = 65 + 3 x AG in FO3), sneak effectiveness, movement speed (slight). Critical for VATS-heavy builds.
- **Luck (L)** — Critical hit chance (base crit% = LK in classic Fallout), random event frequency, gambling outcomes. In FO4: critical meter fill rate. Affects loot quality in some titles.

**Derived Stats (Classic Fallout 1/2):**
- Hit Points: 15 + (2 x EN) + ST
- Action Points: 5 + AG/2
- Carry Weight: 25 + 25 x ST (lbs)
- Sequence: 2 x PE
- Healing Rate: EN/3 (rounded down), min 1
- Critical Chance: LK%
- Melee Damage: ST - 5 (min 1)
- Armor Class: AG (base)

**Design Notes:** SPECIAL is notable for Luck being a first-class attribute rather than an afterthought. Intelligence is historically overpowered because it multiplies skill point gains. Fallout 4's perk chart (where each stat gates a column of 10 perks) was a major structural innovation tying stats directly to perk access rather than derived formulas.

---

## 3. GURPS (Generic Universal Roleplaying System)

**Primary Attributes (4):** ST, DX, IQ, HT

**Scale:** Human average is 10. Practical range 1–20+, no hard cap. Each point above/below 10 costs/refunds character points (CP). ST and HT cost 10 CP/level; DX and IQ cost 20 CP/level (because they each feed multiple derived stats).

**Attributes:**

- **Strength (ST)** — Melee damage (via Thrust and Swing damage tables), lifting/carrying capacity (Basic Lift = ST^2/5 lbs), hit points (defaults to ST). Cheap relative to DX/IQ.
- **Dexterity (DX)** — Base for all physical skills (combat, acrobatics, stealth, craft). Every physical skill defaults to DX +/- some modifier. Governs Basic Speed (with HT). Expensive because raising DX raises the default of every DX-based skill.
- **Intelligence (IQ)** — Base for all mental/social skills (science, languages, magic, social manipulation). Perception and Will default to IQ. Raising IQ raises defaults for all IQ-based skills. Equally expensive as DX.
- **Health (HT)** — Resistance to disease, poison, stunning, knockdown, death. Governs Fatigue Points (default = HT). Feeds Basic Speed. HT rolls determine consciousness and death at negative HP.

**Derived Stats (can be bought up/down independently):**

| Derived Stat | Default | Cost to Modify |
|---|---|---|
| Hit Points (HP) | ST | 2 CP/level |
| Will | IQ | 5 CP/level |
| Perception (Per) | IQ | 5 CP/level |
| Fatigue Points (FP) | HT | 3 CP/level |
| Basic Speed | (HT + DX) / 4 | 5 CP per 0.25 |
| Basic Move | floor(Basic Speed) | 5 CP/level |
| Damage (Thrust) | table lookup by ST | -- |
| Damage (Swing) | table lookup by ST | -- |

**Example Damage Table (selection):**

| ST | Thrust | Swing |
|----|--------|-------|
| 10 | 1d-2   | 1d    |
| 13 | 1d     | 2d-1  |
| 16 | 1d+1   | 2d+2  |
| 20 | 2d-1   | 3d+2  |

**Design Notes:** GURPS is the most modular system here. Having only 4 primary stats keeps the core simple, but the derived stats (especially Per and Will being decoupled from IQ) allow fine-grained customization. The point-buy system with different costs per stat is an elegant balancing mechanism -- DX and IQ cost double because they're inherently more valuable.

---

## 4. The Elder Scrolls (Morrowind/Oblivion vs. Skyrim)

### Morrowind & Oblivion (8 Attributes)

**Primary Attributes:** Strength, Intelligence, Willpower, Agility, Speed, Endurance, Personality, Luck

**Scale:** 1–100 (most start around 30–50, cap at 100 without exploits)

- **Strength** — Melee damage, carry weight, weapon durability. Governs skills: Blade, Blunt, Hand-to-Hand.
- **Intelligence** — Maximum Magicka (Magicka = INT x multiplier based on birthsign/race). Governs Alchemy, Conjuration, Mysticism.
- **Willpower** — Magicka regeneration rate, spell resistance, resistance to stagger. Governs Destruction, Alteration, Restoration.
- **Agility** — Hit chance (Morrowind's to-hit formula depends heavily on AGI), dodge/block chance. Governs Security, Sneak, Marksman.
- **Speed** — Movement speed (walk/run/swim). Governs Athletics, Acrobatics, Light Armor.
- **Endurance** — Hit points per level (CRITICAL: in Morrowind, HP per level = END/10, calculated at level-up, not retroactive). Fatigue pool. Governs Heavy Armor, Block, Armorer.
- **Personality** — NPC disposition, barter prices, persuasion success. Governs Speechcraft, Mercantile, Illusion.
- **Luck** — Subtle bonus to everything. Adds (LCK - 50) x 0.4 to all skill checks. No skills governed.

**Derived Stats:**
- Health: Base (race) + END/10 per level (Morrowind, not retroactive)
- Magicka: INT x multiplier (1.0 base, up to 3.0 with Atronach birthsign)
- Fatigue: ST + WIL + AGI + END; affects literally every action's success chance
- Encumbrance: 5 x STR

### Skyrim (Simplified)

Bethesda removed all 8 attributes in Skyrim. The system was reduced to:

- **Health** — Hit points. +10 per level-up if chosen.
- **Magicka** — Spell resource pool. +10 per level-up if chosen.
- **Stamina** — Sprint, power attacks, carry weight (+5 carry per point). +10 per level-up if chosen.

Each level-up, you choose one of the three to increase by 10, plus pick one perk from skill trees.

**Design Notes:** The Elder Scrolls series is the best case study in attribute simplification over time. Morrowind had 8 attributes, 27 skills, and complex derived stats. Skyrim collapsed attributes entirely into 3 resource pools. The Morrowind/Oblivion "governing attribute" mechanic (each attribute linked to 3 skills) created perverse incentives (efficient leveling). Skyrim's simplification was commercially successful but reduced build variety.

---

## 5. Dark Souls / From Software (Soulsborne)

**Primary Attributes (9, using Dark Souls III):**

**Scale:** Each starts at a class-dependent value (typically 7–15). Soft caps create diminishing returns. Hard cap is 99.

- **Vigor (VIG)** — Hit points. Soft cap at 27 (1000 HP), second soft cap at 50 (1300 HP), steep falloff after. The most universally important stat.
- **Attunement (ATT)** — Spell slots (discrete thresholds: 10=1, 14=2, 18=3, 24=4, 30=5) and FP (mana) pool. Also slightly affects casting speed.
- **Endurance (END)** — Stamina pool (attacks, rolls, blocks, sprinting). Soft cap at 40. One of the tightest-capped stats.
- **Vitality (VIT)** — Equip load (determines roll speed: <30% fast, <70% medium, >=70% fat roll). Also physical defense. Distinct from Vigor.
- **Strength (STR)** — Damage scaling for STR weapons (scaling grades: S/A/B/C/D/E). Two-handing multiplies effective STR by 1.5. Soft caps at 40/60.
- **Dexterity (DEX)** — Damage scaling for DEX weapons, casting speed (up to soft cap). Gates weapon requirements for katanas, curved swords, bows.
- **Intelligence (INT)** — Sorcery/crystal magic scaling, staff catalyst scaling. Soft cap at 40, 60 for crystal sorceries.
- **Faith (FTH)** — Miracle/lightning scaling, talisman/chime catalyst scaling. Soft cap at 40.
- **Luck (LCK)** — Item discovery (drop rates), bleed/poison buildup, Hollow-infused weapon scaling. Niche stat.

**Weapon Scaling System:** Each weapon has letter grades (S > A > B > C > D > E) for each relevant stat. The scaling multiplier is applied to your stat value to compute bonus damage:

```
Total Damage = Base Damage + (Scaling Multiplier x Stat Bonus)
```

**Soft Cap Pattern:**
- 1–20: good returns
- 20–40: best returns
- 40–60: diminished returns
- 60–99: minimal returns

**Design Notes:** Notable for its soft cap design which naturally creates build specialization. The split between VIG/VIT/END for three different "toughness" concepts (health, equip load, stamina) is unusually granular. Weapon scaling grades create an elegant bridge between stats and equipment.

---

## 6. Diablo (II / III / IV)

### Diablo II

**Primary Attributes (4):** Strength, Dexterity, Vitality, Energy

**Scale:** Start around 15–25 (class-dependent). 5 stat points per level. No cap.

- **Strength** — Melee damage (minor), gear requirements (primary purpose). Most endgame armor needs 150+ STR.
- **Dexterity** — Attack rating (hit chance), block chance, ranged damage, gear requirements for DEX-based items.
- **Vitality** — Hit points and stamina. The "correct" dump target for most builds after meeting gear requirements.
- **Energy** — Mana pool. Generally a trap stat because mana potions and mana leech exist.

### Diablo III

Simplified to: **Strength, Dexterity, Intelligence, Vitality**

Each class has a "primary stat" (STR for Barbarian/Crusader, DEX for Monk/Demon Hunter, INT for Wizard/Witch Doctor) that provides +1% damage per point + a defensive bonus. Stats scale into the thousands via gear.

**Design Notes:** Diablo demonstrates the ARPG approach where stats are secondary to gear. The "invest minimum to meet gear requirements, dump everything else in VIT" meta of Diablo II reveals what happens when stats primarily gate equipment. For a tile-based RPG, the Diablo approach works best when loot is the primary progression axis.

---

## 7. Other Notable Systems

### Pillars of Eternity (6 Attributes)

**MIG, CON, DEX, PER, INT, RES** — Scale 3–18 (creation), modifier = (stat - 10) x 3% per point.

The revolutionary design principle: **every stat is useful for every class**.

- **Might (MIG)** — ALL damage and healing (physical and magical). A wizard benefits as much as a fighter.
- **Constitution (CON)** — Health and Fortitude defense.
- **Dexterity (DEX)** — Action speed (how fast you act, not accuracy). Affects cast time, attack speed, recovery.
- **Perception (PER)** — Accuracy (to-hit), Reflex defense, interrupt. In PoE2, became the critical hit stat.
- **Intellect (INT)** — Area of effect size, duration of abilities (buffs AND debuffs). A fighter's abilities lasting longer is as valuable as a wizard's fireball covering more area.
- **Resolve (RES)** — Concentration (resist interrupts), Will defense, deflection. The "tank" stat.

**Why It Matters:** Pillars solved the dump stat problem by decoupling stats from class archetypes. Might governs ALL damage, not just physical, so a mage wants Might. Intellect governs AoE and duration, so a fighter wants Intellect. Arguably the most balanced attribute system in RPG history.

### Shadowrun (Physical/Mental Split)

**Physical:** Body, Agility, Reaction, Strength
**Mental:** Willpower, Logic, Intuition, Charisma
**Special:** Edge (luck/plot armor), Magic or Resonance

Scale 1–6 for humans (racial maximums vary). Uses dice pools: stat + skill = number of d6s rolled, count 5s and 6s as hits.

Notable for the **Reaction/Intuition split** (physical reflexes vs mental awareness) as an alternative to a single DEX stat. Derived defense: Dodge = Reaction + Intuition, Soak = Body + Armor.

### World of Darkness / Storyteller System (9 Attributes)

Three categories x three tiers:

|           | Physical   | Social       | Mental       |
|-----------|-----------|--------------|--------------|
| **Power** | Strength  | Charisma     | Intelligence |
| **Finesse**| Dexterity | Manipulation | Wits         |
| **Resistance**| Stamina | Composure    | Resolve      |

Scale 1–5 (dots). The 3x3 grid is the most elegant organizational framework of any RPG. Each row represents a type of capability (power/finesse/resistance), each column a domain (physical/social/mental).

**Design takeaway:** The power/finesse/resistance taxonomy is extremely useful for designing balanced stats. If your stat system has a "power" stat for physical but not mental, or a "resistance" stat for mental but not physical, you may have a gap.

---

## Cross-Comparison Table

This maps equivalent concepts across systems. Parentheses indicate partial/indirect coverage. "—" means no equivalent.

| Concept | D&D 5e | Fallout SPECIAL | GURPS | Elder Scrolls (MW) | Dark Souls III | Diablo II | Pillars of Eternity | World of Darkness |
|---|---|---|---|---|---|---|---|---|
| **Raw Physical Power** | STR | Strength | ST | Strength | STR | Strength | Might* | Strength |
| **Agility / Dexterity** | DEX | Agility | DX | Agility | DEX | Dexterity | Dexterity** | Dexterity |
| **Toughness / Endurance** | CON | Endurance | HT | Endurance | VIG + VIT | Vitality | Constitution | Stamina |
| **Mental Acuity** | INT | Intelligence | IQ | Intelligence | INT | (Energy) | Intellect*** | Intelligence |
| **Perception / Awareness** | WIS (partial) | Perception | Per (derived) | — | — | — | Perception | Wits |
| **Social / Charisma** | CHA | Charisma | (IQ-based skills) | Personality | — | — | (Resolve, partial) | Charisma + Manipulation |
| **Willpower / Resolve** | WIS (partial) | — | Will (derived) | Willpower | — | — | Resolve | Resolve + Composure |
| **Luck** | — | Luck | (Advantage) | Luck | LCK | — | — | — |
| **Speed / Movement** | — | (Agility) | Basic Move (derived) | Speed | (END) | — | (DEX) | — |
| **Magic Power** | (casting stat varies) | — | (IQ) | INT + Willpower | INT / FTH | (Energy) | Might* | — |
| **Health Pool** | CON -> HP | END -> HP | ST -> HP | END -> HP | VIG -> HP | VIT -> HP | CON -> HP | Stamina -> Health |
| **Stamina / Fatigue** | — | (AP from AGL) | HT -> FP | ST+WIL+AGI+END | END -> Stamina | (VIT) | — | — |
| **Mana / Spell Resource** | (class-dependent) | — | (FP) | INT -> Magicka | ATT -> FP | Energy -> Mana | — | — |
| **Equip Load / Carry** | STR | Strength | ST | Strength | VIT | Strength | — | — |

\* Pillars' Might governs ALL damage/healing (physical and magical), deliberately breaking the STR/INT split.
\** Pillars' DEX governs action speed, NOT accuracy (which is Perception).
\*** Pillars' Intellect governs AoE and duration, NOT damage.

---

## Design Observations

### Common Patterns

1. **Almost every system has some form of:** physical power, agility, toughness, and a mental stat. These four are the irreducible core (GURPS proves you can build a complete system from just these).

2. **The most debated splits are:**
   - WIS vs INT vs PER — Is awareness physical or mental? Is willpower its own stat? D&D bundles perception into Wisdom; GURPS and Pillars separate it; Shadowrun splits it into Intuition vs Logic.
   - CHA as a stat — Many systems include it; many players dump it. Pillars removed it entirely. World of Darkness splits it three ways.
   - Luck — Only Fallout and Dark Souls make it a primary investment. Most systems either exclude it or make it a minor derived stat.

3. **Derived stats are where the real design happens.** The primary stats are just inputs. What makes a system interesting is how HP, damage, speed, accuracy, defense, and resource pools are calculated from those inputs.

4. **Three approaches to preventing stat stacking:**
   - Linear + hard cap (D&D): simple but creates binary "maxed or not"
   - Soft caps (Dark Souls): natural build diversity, requires careful tuning
   - Escalating cost (GURPS): mathematically elegant, best for point-buy

5. **The dump stat problem:** If any stat is clearly worse, experienced players will minimize it. Solutions:
   - Make every stat affect every class (Pillars of Eternity)
   - Gate perks/abilities behind stat thresholds (Fallout 4)
   - Price stats by power level (GURPS)
   - Make derived defenses require diverse stats (Pillars: Fortitude from MIG+CON, Reflex from DEX+PER, Will from INT+RES)

### Relevant to a Tile-Based RPG

- **4–6 primary stats is the sweet spot.** Fewer than 4 lacks meaningful choice. More than 6 creates stats players don't understand or care about.
- **Every stat should affect at least 2 gameplay systems.** If a stat only does one thing, it becomes either mandatory or a dump stat.
- **Pillars' approach** of decoupling stats from archetypes is worth considering. "Might = all damage" is more interesting for build diversity than "Strength = physical damage, Intelligence = magic damage."
- **For tile-based games specifically:** movement range, sight range, and area of effect are visible tactical quantities that map naturally to stats (SPD/AGL, PER, INT). These don't exist as clearly in non-tile-based games.
- **Derived stats should be transparent.** Players should see exactly how their primary stats translate to HP, damage, accuracy, etc.
- **The World of Darkness 3x3 grid** (power/finesse/resistance across physical/social/mental) is an excellent framework for checking that your stats are balanced and comprehensive. If you have power+finesse for physical but only one mental stat, you may have a gap.
