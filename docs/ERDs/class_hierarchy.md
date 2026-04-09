# Class Hierarchy

```mermaid
classDiagram
    Trackable <|-- WorldObject
    Trackable <|-- Inventory
    Trackable <|-- Map
    Trackable <|-- Tile
    Trackable <|-- WorldData

    WorldObject <|-- Creature
    WorldObject <|-- Item
    Item <|-- Stackable
    Item <|-- Equippable
    Item <|-- Structure
    Item <|-- Egg
    Stackable <|-- Consumable
    Stackable <|-- Ammunition
    Equippable <|-- Weapon
    Equippable <|-- Wearable

    class Trackable {
        +uid: int
        +_timed_events: dict
        +register_tick()
        +process_ticks()
        +all_instances()
    }

    class WorldObject {
        +location: MapKey
        +current_map: Map
        +sprite_name: str
        +collision: bool
        +on_map() list
    }

    CombatMixin <|-- Creature
    SocialMixin <|-- Creature
    MovementMixin <|-- Creature
    InventoryMixin <|-- Creature
    ReproductionMixin <|-- Creature
    RelationshipsMixin <|-- Creature
    ConversationMixin <|-- Creature
    UtilityMixin <|-- Creature
    RegenMixin <|-- Creature

    class Creature {
        +name, species, sex, age, size
        +stats: Stats
        +inventory: Inventory
        +equipment: dict
        +relationships, rumors
        +chromosomes, mother_uid, father_uid
        +deity, piety, quest_log
        +gold, loans, loans_given
        +behavior, observation_mask
        +model_name, model_version
        +_history: deque
        creature/ package with mixins
    }

    class CombatMixin { melee_attack, ranged_attack, cast_spell, grapple, die }
    class SocialMixin { intimidate, deceive, trade, bribe, steal, proselytize }
    class MovementMixin { move, enter, exit, flee, follow, run, sneak }
    class InventoryMixin { equip, unequip, pickup, drop, use_item }
    class ReproductionMixin { pairing, pregnancy, eggs, bonding }
    class RelationshipsMixin { interactions, rumors, loans }
    class ConversationMixin { dialogue system }
    class UtilityMixin { search, guard, sleep, fatigue, traps, stances }
    class RegenMixin { HP/stamina/mana regen }

    class Stats {
        +base, mods, active
        +add_mod(), contest()
        +gain_exp()
    }

    class Item {
        +name, value, weight, buffs
        +requirements, action_word
        +effective_kpi(), lifetime_kpi()
    }

    class Egg {
        +creature, live
        +days_with_mother
        +tick_gestation(), hatch()
    }

    class QuestLog {
        +quests: dict
        +accept_quest(), complete_step()
        +evaluate_conditions()
    }

    class WorldData {
        +gods: dict, dichotomies
        +flags: dict
        +record_action(), get_balance()
    }

    Creature --> Stats
    Creature --> Inventory
    Creature --> QuestLog
    WorldData --> God
    Map --> Tile
    Tile --> Inventory
```

## Behavior Modules

```mermaid
classDiagram
    class RandomWanderBehavior { +think() }
    class StatWeightedBehavior { +think() piety-influenced }
    class NeuralBehavior { +net: CreatureNet; +think() }
    class PairedBehavior { +inner; +think() follow partner }
```

## Simulation Stack

```mermaid
classDiagram
    class CreatureNet {
        1464 → 1024 → 512 → 256 → 49
        +forward(), +select_action()
        +save(), +load()
    }
    class TorchCreatureNet {
        Training version with autograd
        +get_action(), +evaluate_actions()
        +export_to_numpy()
    }
    class Simulation { +step() → results }
    class CreatureEnv { Gym single-agent }
    class MultiAgentCreatureEnv { Gym multi-agent }
    class PPO { +update(buffer) }
    class TrainingSink { JSONL writer for analytics }
    PPO --> TorchCreatureNet
    TorchCreatureNet --> CreatureNet : exports weights
    CreatureEnv --> Simulation

    class nn_models_db {
        name, version, weights BLOB
        obs_schema_id, act_schema_id
        training_params, training_stats
    }
    class training_db {
        training_runs, phase_snapshots
        episode_summaries, creature_episodes
        observation_schemas, action_schemas
    }
    TrainingSink --> training_db : post-run summarize
    TorchCreatureNet --> nn_models_db : save/load
```
