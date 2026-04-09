from __future__ import annotations
import random
from classes.stats import Stat
from classes.inventory import Weapon, Consumable


class SocialMixin:
    """Social interaction methods for Creature."""

    def intimidate(self, target) -> dict:
        """Attempt to intimidate another creature.

        Uses d20 + INTIMIDATION vs d20 + FEAR_RESIST.
        Returns dict: success, margin, reason.
        """
        result = {'success': False, 'margin': 0, 'reason': ''}

        # Must be within sight range
        if not self.can_see(target):
            result['reason'] = 'out_of_range'
            return result

        won, margin = self.stats.contest(target.stats, 'intimidation_vs_fear')
        result['margin'] = margin
        if won:
            result['success'] = True
            # Target may accept dominance — slight positive for intimidator
            target.record_interaction(self, -3.0)
            self.record_interaction(target, 1.0)
        else:
            result['reason'] = 'resisted'
            # Both take a social hit
            self.record_interaction(target, -2.0)
            target.record_interaction(self, -1.0)

        return result

    def deceive(self, target) -> dict:
        """Attempt to deceive another creature.

        Uses d20 + DECEPTION vs d20 + DETECTION.
        Returns dict: success, margin, reason.
        """
        result = {'success': False, 'margin': 0, 'reason': ''}

        if not self.can_see(target):
            result['reason'] = 'out_of_range'
            return result

        won, margin = self.stats.contest(target.stats, 'deception_vs_detection')
        result['margin'] = margin
        if won:
            result['success'] = True
            # Victim doesn't know they've been deceived
        else:
            result['reason'] = 'detected'
            # Trust severely damaged
            target.record_interaction(self, -5.0)
            self.record_interaction(target, -1.0)

        return result

    @staticmethod
    def _item_utility(items: list, creature) -> float:
        """Compute total utility of a bundle of items to a creature.

        Base = sum of item values. Adjusted by creature needs:
        - Weapons are worth more if creature has none equipped
        - Consumables worth more if HP is low
        """
        total = 0.0
        for item in items:
            base = getattr(item, 'value', 0)
            # Need-based adjustments
            if isinstance(item, Weapon):
                has_weapon = any(isinstance(e, Weapon) for e in creature.equipment.values())
                if not has_weapon:
                    base *= 1.5
            if isinstance(item, Consumable):
                hp_ratio = creature.stats.active[Stat.HP_CURR]() / max(1, creature.stats.active[Stat.HP_MAX]())
                if hp_ratio < 0.5:
                    base *= 1.5
            total += base
        return total

    def propose_trade(self, target,
                      offered: list, requested: list) -> dict:
        """Propose a trade: self offers items, requests items from target.

        Both sides evaluate utility. Sentiment shifts willingness.
        Persuasion bonus for initiator.
        Returns dict: accepted, counter_offer (list or None), reason.
        """
        result = {'accepted': False, 'counter_offer': None, 'reason': ''}

        if self._sight_distance(target) > 1:
            result['reason'] = 'not_adjacent'
            return result

        # Validate items exist in inventories
        for item in offered:
            if item not in self.inventory.items:
                result['reason'] = 'missing_offered_item'
                return result
        for item in requested:
            if item not in target.inventory.items:
                result['reason'] = 'missing_requested_item'
                return result

        # Compute utility for both sides
        # Target gains offered items, loses requested items
        target_gain = self._item_utility(offered, target)
        target_loss = self._item_utility(requested, target)

        # Self gains requested items, loses offered items
        self_gain = self._item_utility(requested, self)
        self_loss = self._item_utility(offered, self)

        # Sentiment modifier: positive relationship = more generous
        rel = target.get_relationship(self)
        sentiment_bonus = 0.0
        if rel:
            # Normalize sentiment to a small bonus/penalty
            sentiment_bonus = rel[0] / (abs(rel[0]) + 10)  # -1 to +1 range

        # Persuasion bonus for initiator
        persuasion = (self.stats.active[Stat.PERSUASION]() * 0.05)

        # Target's net utility including social factors
        target_net = (target_gain - target_loss) + sentiment_bonus + persuasion

        if target_net >= 0:
            # Accept trade
            result['accepted'] = True
            # Execute the swap
            for item in offered:
                self.inventory.items.remove(item)
                target.inventory.items.append(item)
            for item in requested:
                target.inventory.items.remove(item)
                self.inventory.items.append(item)

            # Fair or exploitative?
            self_net = self_gain - self_loss
            if abs(self_net - target_net) < 2.0:
                # Fair trade
                self.record_interaction(target, 3.0)
                target.record_interaction(self, 3.0)
            else:
                # One side got a better deal
                winner_sentiment = 3.0
                loser_sentiment = -1.0
                if self_net > target_net:
                    self.record_interaction(target, winner_sentiment)
                    target.record_interaction(self, loser_sentiment)
                else:
                    self.record_interaction(target, loser_sentiment)
                    target.record_interaction(self, winner_sentiment)
        else:
            result['reason'] = 'rejected'
            # Walk-away
            self.record_interaction(target, -1.0)
            target.record_interaction(self, -1.0)

        return result

    def bribe(self, target, items: list) -> dict:
        """Offer items as a bribe to shift target's behavior/sentiment.

        Target evaluates bribe value against current disposition.
        Returns dict: accepted, reason.
        """
        result = {'accepted': False, 'reason': ''}

        if self._sight_distance(target) > 1:
            result['reason'] = 'not_adjacent'
            return result

        for item in items:
            if item not in self.inventory.items:
                result['reason'] = 'missing_item'
                return result

        bribe_value = self._item_utility(items, target)

        # Threshold based on target's current sentiment toward self
        rel = target.get_relationship(self)
        threshold = 5.0  # base threshold
        if rel:
            # More negative sentiment = higher bribe needed
            threshold = max(1.0, 5.0 - rel[0] * 0.5)

        if bribe_value >= threshold:
            result['accepted'] = True
            # Transfer items
            for item in items:
                self.inventory.items.remove(item)
                target.inventory.items.append(item)
            # Positive sentiment shift
            target.record_interaction(self, bribe_value * 0.5)
            self.record_interaction(target, 1.0)
        else:
            result['reason'] = 'insufficient_value'
            # Minor negative
            self.record_interaction(target, -0.5)
            target.record_interaction(self, -0.5)

        return result

    def steal(self, target, item) -> dict:
        """Attempt to steal an item from another creature's inventory.

        Uses stealth vs detection if unseen, deception vs detection if seen.
        Returns dict: success, reason.
        """
        result = {'success': False, 'reason': ''}

        if self._sight_distance(target) > 1:
            result['reason'] = 'not_adjacent'
            return result

        if item not in target.inventory.items:
            result['reason'] = 'item_not_found'
            return result

        if not self.can_carry(item):
            result['reason'] = 'too_heavy'
            return result

        # If target can see us, use deception; otherwise stealth
        if target.can_see(self):
            won, _ = self.stats.contest(target.stats, 'deception_vs_detection')
        else:
            won, _ = self.stats.contest(target.stats, 'stealth_vs_detection')

        if won:
            result['success'] = True
            target.inventory.items.remove(item)
            self.inventory.items.append(item)
            # Victim doesn't know (unless detected later)
        else:
            result['reason'] = 'caught'
            # Caught stealing — severe trust damage
            target.record_interaction(self, -8.0)
            self.record_interaction(target, -2.0)

        return result

    def share_rumor(self, target, subject_uid: int,
                    sentiment: float, tick: int) -> bool:
        """Share a rumor about a third party with another creature.

        CHR scales gossip success. Returns True if rumor was shared.
        """
        if not self.can_see(target):
            return False

        # CHR check: higher CHR = more convincing gossip
        chr_mod = (self.stats.active[Stat.CHR]() - 10) // 2
        # Base 60% chance + 5% per CHR mod
        chance = min(0.95, max(0.1, 0.6 + chr_mod * 0.05))
        if random.random() > chance:
            return False

        confidence = self.relationship_confidence(
            type('_', (), {'uid': subject_uid})()  # dummy for lookup
        ) if subject_uid in self.relationships else 0.1

        target.receive_rumor(self, subject_uid, sentiment, confidence, tick)

        # Sharing is a social interaction
        self.record_interaction(target, 1.0)
        target.record_interaction(self, 1.0)
        return True

    def solicit_rumor(self, target, tick: int) -> bool:
        """Ask another creature for gossip about someone you barely know.

        Targets creatures you have a weak/shallow opinion of but aren't strangers.
        Returns True if a rumor was received.
        """
        if not self.can_see(target):
            return False

        # Find a subject we have a weak opinion of
        candidates = []
        for uid, rel in self.relationships.items():
            # Weak = low count (1-3) and small sentiment magnitude
            if 1 <= rel[1] <= 3 and abs(rel[0]) < 5:
                candidates.append(uid)

        if not candidates:
            return False

        subject_uid = random.choice(candidates)

        # Does the target know anything about this subject?
        target_rel = target.relationships.get(subject_uid)
        if target_rel is None:
            return False

        # CHR-scaled success
        chr_mod = (self.stats.active[Stat.CHR]() - 10) // 2
        chance = min(0.9, max(0.2, 0.5 + chr_mod * 0.05))
        if random.random() > chance:
            return False

        confidence = target_rel[1] / (target_rel[1] + 5)
        self.receive_rumor(target, subject_uid, target_rel[0], confidence, tick)

        # Social interaction
        self.record_interaction(target, 0.5)
        target.record_interaction(self, 0.5)
        return True

    def proselytize(self, target) -> dict:
        """Attempt to convert another creature to your deity.

        Uses CHR contest. Target must have no deity or low piety.
        Returns dict: success, reason.
        """
        result = {'success': False, 'reason': ''}

        if self.deity is None:
            result['reason'] = 'no_deity'
            return result

        if not self.can_see(target):
            result['reason'] = 'out_of_range'
            return result

        # Can't convert someone already on your god
        if target.deity == self.deity:
            result['reason'] = 'same_deity'
            return result

        # Target must have no god OR low piety to be susceptible
        if target.deity is not None and target.piety > 0.2:
            result['reason'] = 'target_devout'
            return result

        # CHR contest: persuasion-like
        chr_mod = (self.stats.active[Stat.CHR]() - 10) // 2
        target_resist = (target.stats.active[Stat.INT]() - 10) // 2
        roll = random.randint(1, 20) + chr_mod
        dc = 10 + target_resist

        if roll >= dc:
            result['success'] = True
            target.deity = self.deity
            target.piety = 0.1  # start with small piety
            self.record_interaction(target, 3.0)
            target.record_interaction(self, 2.0)
        else:
            result['reason'] = 'resisted'
            self.record_interaction(target, -0.5)
            target.record_interaction(self, -0.5)

        return result
