from __future__ import annotations


class ConversationMixin:
    """Dialogue and conversation methods for Creature."""

    def start_conversation(self, target, conversation: str = None) -> list:
        """Start a conversation with another creature.

        Finds matching root dialogue nodes filtered by species/creature/conditions.
        Returns list of available root node dicts, or empty if none match.
        """
        from data.db import DIALOGUE, DIALOGUE_ROOTS

        if not self.can_see(target):
            return []

        # Determine which conversation trees to search
        if conversation:
            candidates = DIALOGUE_ROOTS.get(conversation, [])
        else:
            # Search all conversation trees for matching roots
            candidates = []
            for conv_roots in DIALOGUE_ROOTS.values():
                candidates.extend(conv_roots)

        available = []
        for node_id in candidates:
            node = DIALOGUE.get(node_id)
            if node is None:
                continue
            if not self._dialogue_matches(node, target):
                continue
            available.append(node)

        if available:
            self.dialogue = {
                'target_uid': target.uid,
                'conversation': conversation or available[0]['conversation'],
                'current_node_id': None,
            }
            # Record social interaction for starting a conversation
            self.record_interaction(target, 1.0)
            target.record_interaction(self, 1.0)

        return available

    def advance_dialogue(self, node_id: int, target) -> list:
        """Select a dialogue node and get its children (next options).

        Applies any effects/behavior from the selected node. Handles
        two special effects:

          * ``goto``: jumps to a different conversation tree. Returns
            the filtered roots of the target conversation.
          * ``auto_advance``: marks this node as a branch (no UI
            presentation). Automatically advances into the first
            matching child and returns *that* node's children.
            Chains through consecutive branch nodes.

        Returns list of available child node dicts.
        """
        from data.db import DIALOGUE, DIALOGUE_ROOTS

        node = DIALOGUE.get(node_id)
        if node is None:
            return []

        # Update conversation state
        if self.dialogue:
            self.dialogue['current_node_id'] = node_id

        # Apply effects
        self._apply_dialogue_effects(node, target)

        effects = node.get('effects', {})

        # goto: jump to a different conversation's matching roots.
        # Effect value is the target conversation name.
        if 'goto' in effects:
            target_conv = effects['goto']
            root_ids = DIALOGUE_ROOTS.get(target_conv, [])
            new_roots = []
            for rid in root_ids:
                r = DIALOGUE.get(rid)
                if r and self._dialogue_matches(r, target):
                    new_roots.append(r)
            if new_roots:
                if self.dialogue:
                    self.dialogue['conversation'] = target_conv
                return new_roots
            # No valid roots in target conversation = end
            self.end_conversation()
            return []

        # Get filtered children
        children = []
        for child_id in node['children']:
            child = DIALOGUE.get(child_id)
            if child and self._dialogue_matches(child, target):
                children.append(child)

        # auto_advance: branch node — skip straight into the first
        # matching child. Recurses so a chain of branches collapses
        # into the first presentable node's children.
        if effects.get('auto_advance') and children:
            return self.advance_dialogue(children[0]['id'], target)

        # No children = end of conversation
        if not children:
            self.end_conversation()

        return children

    def end_conversation(self):
        """End the current conversation."""
        self.dialogue = None

    def _dialogue_matches(self, node: dict, target) -> bool:
        """Check if a dialogue node matches the current context.

        Filters on species, creature_key, and JSON conditions.
        """
        # Species filter
        if node['species'] and node['species'] != (target.species or ''):
            return False

        # Creature key filter (specific NPC)
        if node['creature_key'] and node['creature_key'] != target.name:
            return False

        # Character conditions (checked against the initiator/player,
        # plus a handful that reference the target creature or
        # relationship state between the two).
        from classes.stats import Stat
        for key, val in node['char_conditions'].items():
            if key == 'level_min':
                if self.stats.base.get(Stat.LVL, 0) < val:
                    return False
            elif key == 'level_max':
                if self.stats.base.get(Stat.LVL, 0) > val:
                    return False
            elif key == 'sex':
                if self.sex != val:
                    return False
            elif key == 'species':
                if self.species != val:
                    return False
            elif key == 'rel_min':
                # Initiator's sentiment toward target must be >= val.
                # Missing edge = 0.0 (neutral).
                from classes.relationship_graph import GRAPH
                edge = GRAPH.get_edge(self.uid, target.uid)
                current = edge[0] if edge else 0.0
                if current < val:
                    return False
            elif key == 'rel_max':
                from classes.relationship_graph import GRAPH
                edge = GRAPH.get_edge(self.uid, target.uid)
                current = edge[0] if edge else 0.0
                if current > val:
                    return False
            elif key == 'has_item':
                # Initiator must carry an item whose name matches val.
                if not any(getattr(i, 'name', '') == val
                           for i in self.inventory.items):
                    return False
            elif key == 'lacks_item':
                if any(getattr(i, 'name', '') == val
                       for i in self.inventory.items):
                    return False
            elif key == 'profession':
                # Target creature's job must match val. Forward-compat
                # with future profession system; today job may be None.
                if getattr(target, 'job', None) != val:
                    return False
            elif key == 'lifecycle_state':
                # Target creature's lifecycle state must match val.
                # Forward-compat with Phase 2 lifecycle FSM — today
                # creatures have no explicit lifecycle attr so we
                # default to 'adult' and let the guard be a no-op
                # for pre-FSM creatures.
                state = getattr(target, 'lifecycle_state', 'adult')
                if state != val:
                    return False
            elif key == 'gold_min':
                if self.gold < val:
                    return False

        # Quest conditions (checked against initiator's quest log)
        for key, val in node['quest_conditions'].items():
            state = self.quest_log.get_quest_state(key)
            if state is None and val == 'active':
                return False
            if state is not None and state.value != val:
                return False

        # World conditions (checked against WorldData flags if available)
        if node['world_conditions']:
            from classes.gods import WorldData
            from classes.trackable import Trackable
            world = None
            for obj in Trackable.all_instances():
                if isinstance(obj, WorldData):
                    world = obj
                    break
            if world:
                for key, val in node['world_conditions'].items():
                    if world.get_flag(key) != val:
                        return False

        return True

    def _apply_dialogue_effects(self, node: dict, target):
        """Apply effects from a selected dialogue node."""
        effects = node.get('effects', {})
        if not effects:
            return

        # Give item to player
        if 'give_item' in effects:
            from data.db import ITEMS
            item_template = ITEMS.get(effects['give_item'])
            if item_template:
                # Clone the item (simple approach: same type, same args)
                import copy
                new_item = copy.copy(item_template)
                self.inventory.items.append(new_item)

        # Take item from player
        if 'take_item' in effects:
            item_name = effects['take_item']
            for item in list(self.inventory.items):
                if item.name == item_name:
                    self.inventory.items.remove(item)
                    break

        # Sentiment shift
        if 'sentiment' in effects:
            self.record_interaction(target, effects['sentiment'])
            target.record_interaction(self, effects['sentiment'])

        # Quest acceptance — effect sets {"start_quest": "quest_name"}
        # The NPC is offering a quest; the speaker (self) accepts it
        # into their own quest log. Looks up the quest definition
        # from QUESTS and calls the quest_log.accept_quest API.
        if 'start_quest' in effects:
            from data.db import QUESTS
            quest_name = effects['start_quest']
            quest_def = QUESTS.get(quest_name)
            if quest_def is not None and hasattr(self, 'quest_log'):
                now = getattr(self, '_last_update_time', 0)
                self.quest_log.accept_quest(quest_name, quest_def, now)

        # Behavior trigger
        behavior = node.get('behavior')
        if behavior == 'trade':
            pass  # Caller handles opening trade UI
        elif behavior == 'attack':
            pass  # Caller handles initiating combat
        elif behavior == 'flee':
            pass  # Caller handles flee logic
