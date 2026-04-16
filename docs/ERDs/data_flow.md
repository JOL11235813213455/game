# Data Flow ERD

## Startup Sequence

```mermaid
sequenceDiagram
    participant M as main.py
    participant DB as data/db.py
    participant SQLite as game.db
    participant Classes as classes/*

    M->>DB: load()
    DB->>SQLite: connect + _migrate()
    DB->>DB: _load_species() -> SPECIES, PLAYABLE, NONPLAYABLE
    DB->>DB: _load_monster_species() -> MONSTER_SPECIES
    DB->>DB: _load_items() -> ITEMS, STRUCTURES
    DB->>DB: _load_sprites() -> SPRITE_DATA
    DB->>DB: _load_tile_templates() -> TILE_TEMPLATES
    DB->>DB: _load_maps() -> MAPS (creates Map, Tile instances)
    DB->>DB: _load_animations() -> ANIMATIONS, ANIM_BINDINGS
    DB->>DB: _load_composites() -> COMPOSITES, COMPOSITE_ANIMS, COMPOSITE_ANIM_BINDINGS
    DB-->>M: globals populated

    M->>Classes: make_map(cols, rows) -> Map with Tiles
    M->>Classes: Creature(map, location, species='human', stats)
    Note over Classes: Creature.__init__ reads SPECIES<br/>for sprite/scale, builds Stats object
    M->>Classes: Creature(map, location, species, behavior=RandomWanderBehavior())
```

## Game Loop — Per Frame

```mermaid
graph TD
    LOOP[Frame Start] --> EVENTS[Process Events]
    EVENTS --> |QUIT| EXIT[Exit]
    EVENTS --> |KEYDOWN| INPUT{Which state?}

    INPUT --> |save_ui open| SAVEUI[SaveLoadUI.handle_event]
    INPUT --> |paused| MENU[Menu Navigation]
    INPUT --> |gameplay| GAME_INPUT[Movement / Enter / Exit / Zoom]

    SAVEUI --> |loaded| RESTORE[Swap player, reset NPC timers]

    LOOP --> UPDATE[Update Phase]
    UPDATE --> CLOCK[GameClock.update dt]
    UPDATE --> MOVE[Player movement from held keys]
    MOVE --> |Creature.move| COLLISION[Check walkable + bounds + colliders]
    UPDATE --> NPC_UPDATE[Creature.update for behavior creatures]
    NPC_UPDATE --> |behavior.think| NPC_MOVE[Creature.move]
    UPDATE --> ANIM[AnimationState.update dt_ms]

    LOOP --> RENDER[Render Phase]
    RENDER --> TILES[draw_map_row for each Y]
    TILES --> TILE_SPRITE[resolve tile sprite + animation]
    TILE_SPRITE --> CACHE1[sprite_cache.get_tiled / get_scaled]

    RENDER --> SPRITES[Sort WorldObjects by Y, z_index]
    SPRITES --> SURFACE[obj.make_surface block_size]
    SURFACE --> |simple| CACHE2[sprite_cache.get_scaled]
    SURFACE --> |composite| CACHE3[sprite_cache.get_composite / get_composite_anim_frame]

    SPRITES --> SHADOW[make_shadow per sprite]
    SPRITES --> HIGHLIGHT[apply_top_highlight per sprite]

    RENDER --> AMBIENT[draw_ambient_overlay hour]
    RENDER --> HUD[draw_hud player stats]
    RENDER --> CLOCK_DISP[Format time + moon phase]

    style LOOP fill:#4a6,color:#fff
    style RENDER fill:#46a,color:#fff
    style UPDATE fill:#a64,color:#fff
```

## Save / Load Flow

```mermaid
sequenceDiagram
    participant UI as SaveLoadUI
    participant S as main/save.py
    participant P as pickle
    participant T as Trackable
    participant WO as WorldObject

    Note over UI,WO: SAVE
    UI->>S: create_save(player, name, file_id)
    S->>T: all_instances()
    T-->>S: all tracked objects
    S->>P: pickle.dumps({player, objects})
    S->>S: INSERT INTO saves

    Note over UI,WO: LOAD
    UI->>S: load_save(save_id)
    S->>S: SELECT data FROM saves
    S->>WO: _by_map.clear()
    S->>P: pickle.loads(blob)
    P-->>S: {player, objects}
    S->>S: _held = objects (prevent GC)
    loop each object
        S->>T: type(obj)._instances.add(obj)
        S->>WO: _by_map[id(map)].add(obj)
    end
    S-->>UI: player
```

## Monster Tick Flow (headless simulation)

Monsters tick alongside creatures each `Simulation.step()`. The
per-step flow:

```mermaid
sequenceDiagram
    participant SIM as Simulation.step
    participant MT as monster_tick
    participant PN as PackNet (NN or heuristic)
    participant MN as MonsterNet (NN or heuristic)
    participant MD as dispatch_monster
    participant P as Pack
    participant T as MonsterTrainer (optional)

    SIM->>MT: run if sim.monsters non-empty
    MT->>PN: pack NN refresh (slow cadence, ~2s)
    PN-->>P: broadcast_signals on change (sleep/alert/cohesion/roles)
    MT->>MN: batch inference (stacked obs + masks)
    MN-->>MT: action probs per monster
    loop each monster
        MT->>MD: dispatch_monster(action, context)
        MD-->>MT: result {success, damage, hunger_restored, target, ...}
        MT->>P: on_creature_spotted, on_member_state (events)
    end
    MT->>MT: pack housekeeping (split, merge, challenge, egg lay)
    SIM->>SIM: for m in sim.monsters: m.process_ticks(now)
    SIM->>SIM: sweep dead monsters + empty packs
    SIM->>T: on_step(sim, signal_scales) (only if trainer attached)
    T->>T: compute reward delta, buffer per-monster rollout
    T-->>T: trigger PPO / REINFORCE update when buffer full
```

## Training Freeze Toggle Flow (curriculum stages 15-25)

Training runners (run_mappo / run_ppo) read stage config and wire
monsters + optimizer behavior accordingly.

```mermaid
graph TD
    STAGE[_load_curriculum_stage<br/>stage_number] --> FLAGS{stage flags}
    FLAGS -->|monsters_enabled| INJECT[_inject_monsters<br/>spawn_monsters_for_stage]
    FLAGS -->|creature_frozen| SKIP_C[Skip CreatureNet + GoalNet<br/>PPO update]
    FLAGS -->|monster_trainable| MK_TRAINER[Build MonsterTrainer<br/>load pretrained .npz if exists<br/>attach_to_sim]
    FLAGS -->|pack_trainable| PACK_FLAG[MonsterTrainer.pack_trainable=True<br/>REINFORCE enabled]
    INJECT --> SIM[Simulation constructor<br/>arena.monsters + arena.packs]
    MK_TRAINER --> SIM
    SIM --> LOOP[Per-step: monster_tick, reward collection,<br/>optional PPO/REINFORCE updates]
    LOOP --> EXPORT[End of phase:<br/>monster_trainer.export_weights]

    style STAGE fill:#4a6,color:#fff
    style SKIP_C fill:#a64,color:#fff
    style MK_TRAINER fill:#a4a,color:#fff
```

## Sprite Rendering Pipeline

```mermaid
graph LR
    WO[WorldObject.make_surface] --> HAS_COMP{composite_name?}

    HAS_COMP -->|yes| COMP_ANIM{_composite_anim?}
    COMP_ANIM -->|yes| PRE[get_composite_anim_frame<br/>pre-rendered frame list]
    COMP_ANIM -->|no| STATIC[get_composite<br/>static cached pose]
    PRE --> FLIP{flip_h?}
    STATIC --> FLIP
    FLIP -->|yes| MIRROR[pygame.transform.flip]
    FLIP -->|no| RESULT

    HAS_COMP -->|no| SIMPLE[_resolve_sprite_name]
    SIMPLE --> SPRITE_DATA[SPRITE_DATA lookup]
    SPRITE_DATA --> SCALED[get_scaled w, h, block_size]
    SCALED --> AP[Compute action_point offset]
    AP --> RESULT[surface + blit offset]

    subgraph sprite_cache.py
        PRE
        STATIC
        SCALED
    end

    style WO fill:#4a6,color:#fff
    style RESULT fill:#46a,color:#fff
```
