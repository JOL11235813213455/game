from classes.creature import Stat

PLAYABLE: dict[str, dict] = {
    "human": {
        Stat.STR: 5, Stat.CON: 5, Stat.INT: 5, Stat.AGL: 5
        ,Stat.PER: 5, Stat.CHR: 5, Stat.LCK: 5, Stat.HD: 8
    },
    "scavenger": {
        Stat.STR: 5, Stat.CON: 5, Stat.INT: 5, Stat.AGL: 6
        ,Stat.PER: 7, Stat.CHR: 4, Stat.LCK: 5, Stat.HD: 8
    },
    "cultist": {
        Stat.STR: 4, Stat.INT: 9, Stat.AGL: 5
        ,Stat.CHR: 8, Stat.LCK: 8, Stat.PER: 6, Stat.HD: 6
    },
    "mutant": {
        Stat.STR: 10, Stat.CON: 9, Stat.AGL: 3
        ,Stat.INT: 2, Stat.PER: 4, Stat.CHR: 1, Stat.HD: 10
    },
    "wraith": {
        Stat.STR: 3, Stat.INT: 10, Stat.AGL: 10
        ,Stat.LCK: 9, Stat.PER: 10, Stat.CHR: 5, Stat.HD: 4
    },
    "automaton": {
        Stat.STR: 12, Stat.CON: 14, Stat.AGL: 2
        ,Stat.INT: 6, Stat.PER: 8, Stat.CHR: 0, Stat.LCK: 1, Stat.HD: 12
    },
    "hollow": {
        Stat.STR: 8, Stat.CON: 10, Stat.AGL: 2
        ,Stat.INT: 1, Stat.PER: 2, Stat.CHR: 0, Stat.LCK: 2, Stat.HD: 10
    },
}

NONPLAYABLE: dict[str, dict] = {
    # --- Tiny ---
    "locust": {
        Stat.STR: 1, Stat.CON: 1, Stat.AGL: 12
        ,Stat.PER: 6, Stat.HD: 2
    },
    "cockroach": {
        Stat.STR: 1, Stat.CON: 4, Stat.AGL: 9
        ,Stat.PER: 5, Stat.LCK: 8, Stat.HD: 2
    },
    "spider": {
        Stat.STR: 1, Stat.CON: 2, Stat.AGL: 10
        ,Stat.PER: 7, Stat.HD: 2
    },
    "rat": {
        Stat.STR: 2, Stat.CON: 2, Stat.AGL: 9
        ,Stat.PER: 8, Stat.LCK: 4, Stat.HD: 3
    },
    "crow": {
        Stat.STR: 1, Stat.CON: 1, Stat.AGL: 11
        ,Stat.INT: 5, Stat.PER: 10, Stat.HD: 2
    },

    # --- Small ---
    "rabbit": {
        Stat.STR: 1, Stat.CON: 2, Stat.AGL: 12
        ,Stat.PER: 9, Stat.LCK: 6, Stat.HD: 3
    },
    "snake": {
        Stat.STR: 2, Stat.CON: 3, Stat.AGL: 8
        ,Stat.PER: 7, Stat.HD: 4
    },
    "cat": {
        Stat.STR: 2, Stat.CON: 3, Stat.AGL: 12
        ,Stat.PER: 10, Stat.LCK: 7, Stat.HD: 4
    },
    "fox": {
        Stat.STR: 3, Stat.CON: 3, Stat.AGL: 11
        ,Stat.INT: 5, Stat.PER: 10, Stat.LCK: 6, Stat.HD: 4
    },

    # --- Medium ---
    "dog": {
        Stat.STR: 5, Stat.CON: 4, Stat.AGL: 8
        ,Stat.PER: 10, Stat.HD: 6
    },
    "coyote": {
        Stat.STR: 4, Stat.CON: 4, Stat.AGL: 9
        ,Stat.PER: 9, Stat.LCK: 4, Stat.HD: 6
    },
    "deer": {
        Stat.STR: 3, Stat.CON: 4, Stat.AGL: 11
        ,Stat.PER: 8, Stat.HD: 5
    },
    "boar": {
        Stat.STR: 8, Stat.CON: 8, Stat.AGL: 5
        ,Stat.PER: 4, Stat.HD: 8
    },

    # --- Large ---
    "wolf": {
        Stat.STR: 8, Stat.CON: 6, Stat.AGL: 9
        ,Stat.INT: 4, Stat.PER: 10, Stat.HD: 8
    },
    "mountain_lion": {
        Stat.STR: 9, Stat.CON: 6, Stat.AGL: 11
        ,Stat.PER: 10, Stat.LCK: 4, Stat.HD: 8
    },
    "bear": {
        Stat.STR: 14, Stat.CON: 12, Stat.AGL: 4
        ,Stat.PER: 6, Stat.HD: 12
    },
    "dire_wolf": {
        Stat.STR: 12, Stat.CON: 9, Stat.AGL: 8
        ,Stat.INT: 5, Stat.PER: 11, Stat.HD: 10
    },
}

SPECIES = {**PLAYABLE, **NONPLAYABLE}
