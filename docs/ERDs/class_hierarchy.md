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
        +_history: deque
    }

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
        1454 → 1024 → 512 → 256 → 49
        +forward(), +select_action()
        +save(), +load()
    }
    class Simulation { +step() → results }
    class CreatureEnv { Gym single-agent }
    class MultiAgentCreatureEnv { Gym multi-agent }
    class PPOTrainer { +update(buffer) }
    PPOTrainer --> CreatureNet
    CreatureEnv --> Simulation
```
