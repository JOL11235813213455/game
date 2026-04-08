# Master ERD — Module Relationships

Links to scoped diagrams:

- [Class Hierarchy](class_hierarchy.md) — inheritance tree for all game classes
- [Import Dependencies](import_dependencies.md) — which files import from which
- [Data Flow](data_flow.md) — how data moves at runtime (load, update, render, save)
- [Stats System](stats_system.md) — stat layers, derived formulas, opposing stat contests

## High-Level Module Map

```mermaid
graph TB
    subgraph Entry
        MAIN[main.py<br/>game loop]
    end

    subgraph classes/
        TRACK[trackable.py<br/>Trackable]
        WO[world_object.py<br/>WorldObject]
        CREA[creature.py<br/>Creature]
        STATS[stats.py<br/>Stat, Stats]
        INV[inventory.py<br/>Item hierarchy, Inventory]
        MAPS[maps.py<br/>Map, Tile, MapKey, Bounds]
        ANIM[animation.py<br/>AnimationState]
        LVL[levels.py<br/>exp/level math]
    end

    subgraph main/
        CFG[config.py<br/>screen, zoom, constants]
        REND[rendering.py<br/>draw_map_row, draw_hud]
        SCACHE[sprite_cache.py<br/>sprite/composite caching]
        LIGHT[lighting.py<br/>ambient, shadows, highlights]
        GCLOCK[game_clock.py<br/>GameClock]
        MGEN[map_gen.py<br/>make_map]
        SAVE[save.py<br/>pickle serialization]
        SAVEUI[save_ui.py<br/>SaveLoadUI modal]
    end

    subgraph data/
        DB[db.py<br/>load, migrate, globals]
        SEED[seed.py<br/>canonical schema]
    end

    MAIN --> CREA
    MAIN --> STATS
    MAIN --> INV
    MAIN --> WO
    MAIN --> MAPS
    MAIN --> LVL
    MAIN --> DB
    MAIN --> CFG
    MAIN --> REND
    MAIN --> MGEN
    MAIN --> SAVEUI
    MAIN --> GCLOCK
    MAIN --> LIGHT

    CREA --> WO
    CREA --> STATS
    CREA --> INV
    CREA --> MAPS
    CREA -.-> DB

    WO --> TRACK
    WO --> ANIM
    WO -.-> DB
    WO -.-> SCACHE
    WO -.-> CFG

    INV --> WO
    INV --> TRACK
    MAPS --> TRACK
    MAPS --> INV
    STATS --> LVL

    REND --> MAPS
    REND --> SCACHE
    REND --> CFG
    REND -.-> STATS
    REND -.-> LVL
    REND -.-> DB

    SCACHE -.-> DB
    SCACHE -.-> CFG

    LIGHT --> GCLOCK

    SAVEUI --> SAVE
    SAVEUI --> CFG
    SAVE --> TRACK
    SAVE -.-> WO

    DB --> STATS
    DB --> INV
    DB -.-> MAPS

    style MAIN fill:#4a6,color:#fff
    style DB fill:#a64,color:#fff
    style TRACK fill:#46a,color:#fff
```

**Legend:** Solid arrows = top-level imports. Dashed arrows = deferred/local imports (to avoid circular deps).
