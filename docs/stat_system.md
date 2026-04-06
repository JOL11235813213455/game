# Stat System Design

## Primary Stats (7)

| Stat | Abbr | Description |
|------|------|-------------|
| Strength | STR | Physical power, melee force, carrying capacity |
| Perception | PER | Awareness, accuracy, detection, sight range |
| Vitality | VIT | Toughness, health, stamina, poison/disease resistance |
| Intelligence | INT | Mental acuity, magic power, crafting, AoE/duration |
| Charisma | CHR | Social influence, barter prices, NPC disposition, companion loyalty |
| Luck | LCK | Critical chance, loot quality, random event outcomes |
| Agility | AGL | Speed, evasion, stealth, attack speed, action economy |

**Scale:** TBD (e.g. 1-10 like SPECIAL, 1-20 like D&D, or 3-18 point-buy)

---

## Derived Stats


do i want a stamina system, based on proportion of wright in inventory

trinity of weight, speed, and stamina drain

HUD!


### Combat

| Derived Stat | Formula | Feeds From | Description |
|---|---|---|---|
| Max HP | base + VIT * multiplier per level | VIT | Total hit points; VIT is the primary driver |
| Current HP | -- | (Max HP) | Current health, decremented by damage |
| Melee Damage | weapon base + STR modifier | STR | Bonus physical damage on melee attacks |
| Ranged Damage | weapon base + PER modifier | PER | Bonus damage on ranged attacks (accuracy = power for ranged) |
| Magic Damage | spell base + INT modifier | INT | Bonus damage/healing on spells and abilities |
| Attack Speed | base + AGL modifier | AGL | How quickly attacks/actions resolve; recovery between actions |
| Accuracy | base + PER modifier | PER | To-hit chance on attacks |
| Critical Chance | base% + LCK modifier | LCK | Chance to land a critical hit |
| Critical Damage | base multiplier + STR or PER bonus | LCK, STR/PER | Damage multiplier on critical hits |
| Dodge / Evasion | base + AGL modifier | AGL | Chance to avoid incoming attacks entirely |
| Armor | equipment-based + VIT modifier (minor) | VIT, gear | Flat damage reduction from equipment |
| Block | shield base + STR modifier | STR | Damage absorbed when blocking |

### Movement / Exploration

| Derived Stat | Formula | Feeds From | Description |
|---|---|---|---|
| Move Speed | base + AGL modifier | AGL | Tiles per turn or movement delay reduction |
| Sight Range | base + PER modifier | PER | Detection radius on map; how far you spot enemies/items |
| Stealth | base + AGL modifier | AGL | Ability to avoid detection by NPCs |
| Detection | base + PER modifier | PER | Ability to spot stealthed/hidden creatures or traps |
| Carry Weight | base + STR * multiplier | STR | Max encumbrance before movement penalty |
hearing perception

### Resources

| Derived Stat | Formula | Feeds From | Description |
|---|---|---|---|
| Max Stamina | base + VIT modifier + AGL modifier | VIT, AGL | Resource for sprinting, dodging, power attacks |
| Max Mana | base + INT * multiplier | INT | Resource pool for spells and abilities |
| Mana Regen | base + INT modifier (minor) | INT | Rate of mana recovery over time |
| HP Regen | base + VIT modifier (minor) | VIT | Natural health recovery rate |
| Stamina Regen | base + AGL modifier | AGL | Rate of stamina recovery |

### Resistance / Defense

| Derived Stat | Formula | Feeds From | Description |
|---|---|---|---|
| Poison Resist | base + VIT modifier | VIT | Chance or reduction against poison effects |
| Disease Resist | base + VIT modifier | VIT | Resistance to disease/debuffs |
| Magic Resist | base + INT modifier | INT | Reduction against magical damage/effects |
| Stagger Resist | base + STR modifier | STR | Resistance to knockback/stagger/interrupt |
| Fear Resist | base + CHR modifier | CHR | Resistance to fear, intimidation, morale effects |

### Social / Economy

| Derived Stat | Formula | Feeds From | Description |
|---|---|---|---|
| Barter Modifier | base + CHR modifier | CHR | Buy/sell price adjustment |
| NPC Disposition | base + CHR modifier | CHR | Starting attitude of NPCs |
| Companion Limit | 1 + CHR / threshold | CHR | Max number of active companions |
| Persuasion | base + CHR + INT modifier | CHR, INT | Speech check success (convince through charm or logic) |
| Intimidation | base + CHR + STR modifier | CHR, STR | Threaten/coerce success |
| Deception | base + CHR + AGL modifier | CHR, AGL | Lie/bluff success |

### Loot / Crafting

| Derived Stat | Formula | Feeds From | Description |
|---|---|---|---|
| Loot Quality | base + LCK modifier | LCK | Rarity/quality of drops |
| Craft Quality | base + INT modifier + PER modifier | INT, PER | Quality of crafted items; chance of bonus properties |
| Durability Use | base - STR modifier (minor) | STR | Rate weapons/armor degrade (stronger = more efficient use) |

### Progression

| Derived Stat | Formula | Feeds From | Description |
|---|---|---|---|
| Level | derived from XP | (XP) | Current level |
| XP | cumulative | -- | Experience points earned |
| Hit Dice | class/species-based | -- | Die rolled for HP per level (d6, d8, d10, etc.) |
| XP Modifier | base + INT modifier (minor) + LCK modifier (minor) | INT, LCK | Bonus XP from encounters (learn faster, lucky breaks) |

---

## Stat-to-System Matrix

Every stat should touch multiple systems to avoid dump stats:

| Stat | Combat | Movement | Resources | Defense | Social | Loot/Craft |
|------|--------|----------|-----------|---------|--------|------------|
| **STR** | melee dmg, block, crit dmg | carry weight | -- | stagger resist | intimidation | durability use |
| **PER** | ranged dmg, accuracy | sight range, detection | -- | -- | -- | craft quality |
| **VIT** | max HP | -- | max stamina, HP regen | poison/disease resist, armor (minor) | -- | -- |
| **INT** | magic dmg, AoE/duration | -- | max mana, mana regen | magic resist | persuasion | craft quality, XP mod |
| **CHR** | -- | -- | -- | fear resist | barter, disposition, companions, persuasion, intimidation, deception | -- |
| **LCK** | crit chance | -- | -- | -- | -- | loot quality, XP mod |
| **AGL** | attack speed, dodge | move speed, stealth | max stamina, stamina regen | -- | deception | -- |

---

## Current Codebase Mapping

Existing `Stat` enum values that need updating:

| Current | New |
|---------|-----|
| CON (constitution) | VIT (vitality) |
| ARM (armor) | derived from gear, remove as primary stat |
| All others | match (STR, PER, INT, CHR, AGL, LCK already exist) |

Derived stats to add: MHP and CHP already exist. Need to add stamina, mana, and the modifier calculations as mechanics are built out.
