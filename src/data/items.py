from classes.inventory import Item, ItemType, Slot, StateOfMatter

ITEMS: dict[str, Item] = {
    # --- Weapons: Scavenged, One-Handed ---
    "combat_knife": Item(
        name        = "Combat Knife"
        ,item_type  = ItemType.WEAPON
        ,damage     = 4
        ,value      = 10
        ,weight     = 1
        ,slots      = [Slot.HAND_L, Slot.HAND_R]
    ),
    "shard_blade": Item(
        name        = "Shard Blade"
        ,item_type  = ItemType.WEAPON
        ,damage     = 5
        ,value      = 15
        ,weight     = 2
        ,slots      = [Slot.HAND_L, Slot.HAND_R]
    ),
    "hatchet": Item(
        name        = "Hatchet"
        ,item_type  = ItemType.WEAPON
        ,damage     = 6
        ,value      = 12
        ,weight     = 3
        ,slots      = [Slot.HAND_L, Slot.HAND_R]
    ),
    "tire_iron": Item(
        name        = "Tire Iron"
        ,item_type  = ItemType.WEAPON
        ,damage     = 5
        ,value      = 5
        ,weight     = 4
        ,slots      = [Slot.HAND_L, Slot.HAND_R]
    ),
    "machete": Item(
        name        = "Machete"
        ,item_type  = ItemType.WEAPON
        ,damage     = 7
        ,value      = 20
        ,weight     = 3
        ,slots      = [Slot.HAND_L, Slot.HAND_R]
    ),
    "brass_knuckles": Item(
        name        = "Brass Knuckles"
        ,item_type  = ItemType.WEAPON
        ,damage     = 3
        ,value      = 8
        ,weight     = 1
        ,slots      = [Slot.HANDS]
    ),

    # --- Weapons: Scavenged, Two-Handed ---
    "pipe_wrench": Item(
        name        = "Pipe Wrench"
        ,item_type  = ItemType.WEAPON
        ,damage     = 7
        ,value      = 8
        ,weight     = 5
        ,slots      = [Slot.HAND_L, Slot.HAND_R]
        ,slot_count = 2
    ),
    "rebar_club": Item(
        name        = "Rebar Club"
        ,item_type  = ItemType.WEAPON
        ,damage     = 9
        ,value      = 5
        ,weight     = 6
        ,slots      = [Slot.HAND_L, Slot.HAND_R]
        ,slot_count = 2
    ),

    # --- Weapons: Fallen Tech, One-Handed ---
    "shock_baton": Item(
        name        = "Shock Baton"
        ,item_type  = ItemType.WEAPON
        ,damage     = 7
        ,value      = 40
        ,weight     = 2
        ,slots      = [Slot.HAND_L, Slot.HAND_R]
    ),
    "volt_knife": Item(
        name        = "Volt Knife"
        ,item_type  = ItemType.WEAPON
        ,damage     = 6
        ,value      = 35
        ,weight     = 1
        ,slots      = [Slot.HAND_L, Slot.HAND_R]
    ),
    "rail_pistol": Item(
        name        = "Rail Pistol"
        ,item_type  = ItemType.WEAPON
        ,damage     = 12
        ,value      = 120
        ,weight     = 2
        ,slots      = [Slot.HAND_L, Slot.HAND_R]
    ),

    # --- Weapons: Fallen Tech, Two-Handed ---
    "arc_cutter": Item(
        name        = "Arc Cutter"
        ,item_type  = ItemType.WEAPON
        ,damage     = 12
        ,value      = 60
        ,weight     = 3
        ,slots      = [Slot.HAND_L, Slot.HAND_R]
        ,slot_count = 2
    ),

    # --- Weapons: Occult, One-Handed ---
    "ritual_blade": Item(
        name        = "Ritual Blade"
        ,item_type  = ItemType.WEAPON
        ,damage     = 6
        ,poison     = True
        ,value      = 50
        ,weight     = 2
        ,slots      = [Slot.HAND_L, Slot.HAND_R]
    ),
    "sigil_dagger": Item(
        name        = "Sigil Dagger"
        ,item_type  = ItemType.WEAPON
        ,damage     = 5
        ,poison     = True
        ,value      = 40
        ,weight     = 1
        ,slots      = [Slot.HAND_L, Slot.HAND_R]
    ),

    # --- Weapons: Occult, Two-Handed ---
    "bone_staff": Item(
        name        = "Bone Staff"
        ,item_type  = ItemType.WEAPON
        ,damage     = 8
        ,value      = 35
        ,weight     = 4
        ,slots      = [Slot.HAND_L, Slot.HAND_R]
        ,slot_count = 2
    ),

    # --- Armor: Scavenged ---
    "scrap_vest": Item(
        name        = "Scrap Vest"
        ,item_type  = ItemType.ARMOR
        ,defense    = 3
        ,value      = 20
        ,weight     = 12
        ,slots      = [Slot.CHEST]
    ),
    "wrapped_greaves": Item(
        name        = "Wrapped Greaves"
        ,item_type  = ItemType.ARMOR
        ,defense    = 1
        ,value      = 8
        ,weight     = 4
        ,slots      = [Slot.LEGS]
    ),

    # --- Armor: Fallen Tech ---
    "hazmat_suit": Item(
        name        = "Hazmat Suit"
        ,item_type  = ItemType.ARMOR
        ,defense    = 4
        ,value      = 90
        ,weight     = 18
        ,slots      = [Slot.CHEST]
    ),
    "plating_helm": Item(
        name        = "Plating Helm"
        ,item_type  = ItemType.ARMOR
        ,defense    = 3
        ,value      = 45
        ,weight     = 9
        ,slots      = [Slot.HEAD]
    ),

    # --- Armor: Occult ---
    "sigil_coat": Item(
        name        = "Sigil Coat"
        ,item_type  = ItemType.ARMOR
        ,defense    = 2
        ,value      = 55
        ,weight     = 6
        ,slots      = [Slot.CHEST, Slot.BACK]
    ),
    "marked_hood": Item(
        name        = "Marked Hood"
        ,item_type  = ItemType.ARMOR
        ,defense    = 1
        ,value      = 30
        ,weight     = 2
        ,slots      = [Slot.HEAD]
    ),

    # --- Consumables: Tech ---
    "stim_pack": Item(
        name        = "Stim Pack"
        ,item_type  = ItemType.CONSUMABLE
        ,state      = StateOfMatter.LIQUID
        ,health     = 25
        ,consumable = True
        ,stackable  = True
        ,value      = 20
        ,weight     = 1
    ),
    "rad_tablet": Item(
        name        = "Rad Tablet"
        ,item_type  = ItemType.CONSUMABLE
        ,state      = StateOfMatter.SOLID
        ,health     = 10
        ,consumable = True
        ,stackable  = True
        ,value      = 10
        ,weight     = 0
    ),

    # --- Consumables: Occult ---
    "void_tincture": Item(
        name        = "Void Tincture"
        ,item_type  = ItemType.CONSUMABLE
        ,state      = StateOfMatter.LIQUID
        ,health     = 30
        ,consumable = True
        ,stackable  = True
        ,value      = 35
        ,weight     = 1
    ),
    "corrupted_vial": Item(
        name        = "Corrupted Vial"
        ,item_type  = ItemType.CONSUMABLE
        ,state      = StateOfMatter.LIQUID
        ,poison     = True
        ,consumable = True
        ,stackable  = True
        ,value      = 30
        ,weight     = 1
    ),

    # --- Consumables: Food ---
    "ration": Item(
        name        = "Ration"
        ,item_type  = ItemType.CONSUMABLE
        ,state      = StateOfMatter.SOLID
        ,health     = 5
        ,consumable = True
        ,stackable  = True
        ,value      = 3
        ,weight     = 1
    ),

    # --- Keys / Misc ---
    "relic_shard": Item(
        name        = "Relic Shard"
        ,item_type  = ItemType.KEY
        ,value      = 100
        ,weight     = 1
        ,equippable = False
    ),
    "scrap_metal": Item(
        name        = "Scrap Metal"
        ,item_type  = ItemType.MISC
        ,stackable  = True
        ,value      = 2
        ,weight     = 3
        ,equippable = False
    ),
}
