---
name: trackable_pattern
description: Everything that holds game state must extend Trackable — singletons, managers, registries, all of it
type: feedback
---

Everything should be a subclass of Trackable unless there's a strong architectural reason not to. This includes singleton instances called once. The save system pickles Trackable.all_instances() and that should capture the entire world state with no special cases.

**Why:** Keeps save/load dead simple. No explicit serialize/deserialize methods, no special-case wiring in save.py. One pickle sweep gets everything.

**How to apply:** When creating any new class that holds game state (relationship graphs, world data, market state, quest registries, etc.), extend Trackable. For singletons where module-level references exist (like GRAPH), add a _rebind_after_load() function that points the module reference at the unpickled instance.
