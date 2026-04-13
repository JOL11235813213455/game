from __future__ import annotations
import random
from classes.stats import Stat
from classes.inventory import Weapon, Consumable
from classes.relationship_graph import GRAPH


class SocialMixin:
    """Social interaction methods for Creature."""

    def _check_deceit_revelation(self, partner):
        """Check if this social interaction reveals any deceptions.

        When creature B (self) interacts with creature C (partner),
        C may reveal deceptions perpetrated against B by a third
        party A. Requirements:
          - C has interacted at least once with deceiver A
          - C likes B more than A
          - C's detection beats A's deception (d20 contest, A absent)

        On revelation: deceiver A takes -10 sentiment hit from B
        (2x the normal caught-deceiving penalty), and the lie is cleared.
        """
        deceits = GRAPH.deceits_against(self.uid)
        if not deceits:
            return
        partner_rels = GRAPH.edges_from(partner.uid)
        partner_opinion_of_self = partner_rels.get(self.uid)
        if partner_opinion_of_self is None:
            return
        partner_likes_me = partner_opinion_of_self[0]

        for deceiver_uid in list(deceits.keys()):
            partner_opinion_of_deceiver = partner_rels.get(deceiver_uid)
            if partner_opinion_of_deceiver is None:
                continue
            if partner_opinion_of_deceiver[1] < 1:
                continue
            if partner_likes_me <= partner_opinion_of_deceiver[0]:
                continue
            # C likes B more than A and has interacted with A —
            # roll C's detection vs A's (absent) deception
            from classes.stats import Stat as _S
            import random as _rand
            c_roll = partner.stats.active[_S.DETECTION]() + _rand.randint(1, 20)
            # Use the deceiver's deception stat if available, else use 10
            from classes.trackable import Trackable
            from classes.creature import Creature as _Creature
            deceiver = None
            for obj in Trackable.all_instances():
                if isinstance(obj, _Creature) and obj.uid == deceiver_uid:
                    deceiver = obj
                    break
            if deceiver is None or not deceiver.is_alive:
                GRAPH.reveal_deceit(deceiver_uid, self.uid)
                continue
            a_deception = deceiver.stats.active[_S.DECEPTION]() + _rand.randint(1, 20)
            if c_roll > a_deception:
                GRAPH.reveal_deceit(deceiver_uid, self.uid)
                self.record_interaction(deceiver, -10.0)
                deceiver.record_interaction(self, -3.0)

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
            self._social_wins = getattr(self, '_social_wins', 0) + 1
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
        """Attempt to deceive another creature during social interaction.

        Requires active social context (TALK or TRADE in progress).
        Uses d20 + DECEPTION vs d20 + DETECTION.

        Familiarity modifier: abs(sentiment) * 0.15 added to target's
        detection — people who know you well are harder to fool.

        On success:
          1. Relationship manipulation: negative→neutral, positive→boost
          2. Poison target's most-favored relationship with a nasty rumor
          3. Record deception for potential future revelation

        Returns dict: success, margin, reason.
        """
        result = {'success': False, 'margin': 0, 'reason': ''}

        if not self.can_see(target):
            result['reason'] = 'out_of_range'
            return result

        # Gate: must be in active social interaction with target
        active = getattr(self, '_active_social_target', None)
        if active is None or (hasattr(active, 'uid') and active.uid != target.uid):
            result['reason'] = 'no_social_context'
            return result

        # Familiarity modifier
        rel = GRAPH.get_edge(target.uid, self.uid)
        familiarity_bonus = abs(rel[0]) * 0.15 if rel else 0.0

        won, margin = self.stats.contest(target.stats, 'deception_vs_detection')
        adjusted_margin = margin - familiarity_bonus
        won = adjusted_margin > 0
        result['margin'] = margin

        if won:
            result['success'] = True
            self._social_wins = getattr(self, '_social_wins', 0) + 1

            # 1. Relationship manipulation
            my_rel = GRAPH.get_edge(target.uid, self.uid)
            if my_rel is not None:
                if my_rel[0] < 0:
                    # Reset negative relationship to neutral
                    adjustment = -my_rel[0]
                    target.record_interaction(self, adjustment)
                else:
                    # Boost positive relationship
                    target.record_interaction(self, 3.0)
            else:
                target.record_interaction(self, 3.0)

            # 2. Poison target's most-favored relationship
            target_rels = GRAPH.edges_from(target.uid)
            best_friend_uid = None
            best_sentiment = -999.0
            for uid, r in target_rels.items():
                if uid != self.uid and r[0] > best_sentiment:
                    best_sentiment = r[0]
                    best_friend_uid = uid
            if best_friend_uid is not None and best_sentiment > 0:
                rumor_sentiment = -best_sentiment * 2.0
                GRAPH.add_rumor(target.uid, best_friend_uid,
                                self.uid, rumor_sentiment,
                                0.8, 0)

            # 3. Record deception for future revelation
            GRAPH.record_deceit(self.uid, target.uid, 0)
        else:
            result['reason'] = 'detected'
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

    def auto_trade(self, target) -> dict:
        """Gold-denominated auto-trade with an adjacent target.

        Closes the economy loop: the NN picks ``Action.TRADE`` and the
        system chooses direction, item, and price. This is a thin
        orchestration layer over the real pricing engine in
        :mod:`classes.valuation` — it picks who buys what, then delegates
        to :func:`~classes.valuation.compute_trade_price` for feasibility
        and price, and to :mod:`classes.market` for cleared-price memory.

        Direction selection (in priority order):

          1. **Buy food.** If self is hungry (< 0.3) and target has food
             items, try the most valuable one that's feasible.
          2. **Sell goods.** Otherwise, walk self's stackables by
             descending item.value and find the first one
             compute_trade_price says is feasible with this buyer.

        On success, a single unit is moved between stacks (so
        multi-quantity inventories aren't dumped wholesale), the
        computed price is transferred as gold, the buyer's
        ``_item_prices`` gets the cost basis so resale has a floor, the
        market EMA is updated with the cleared price, and both sides
        record a positive interaction. The caller receives the trade
        dict plus the computed surplus so the reward layer can use
        :func:`~classes.valuation.trade_reward` to convert surplus to a
        per-tick RL signal.

        Returns dict:
            success: bool
            direction: 'bought' or 'sold'
            item: the transferred item (a new 1-quantity stack if split)
            price: float — gold that actually moved
            surplus: float — self's share of the bargain surplus
                (positive for a good deal, zero for break-even)
            reason: str — on failure
        """
        import copy as _copy
        from classes.inventory import Stackable
        from classes.valuation import compute_trade_price
        from classes.market import observe_trade

        result = {'success': False}

        if target is None or target is self or not getattr(target, 'is_alive', False):
            result['reason'] = 'invalid_target'
            return result
        if self._sight_distance(target) > 1:
            result['reason'] = 'not_adjacent'
            return result

        def _execute(seller, buyer, item, deal: dict) -> dict:
            """Transfer one unit of item for deal['price'] gold.

            Handles stack splitting, gold transfer, cost-basis tracking
            on the buyer side, market EMA update, and sentiment."""
            price = deal['price']
            # Round price to int gold (the economy is integer-denominated)
            gold_int = max(1, int(round(price)))
            if getattr(buyer, 'gold', 0) < gold_int:
                return {'success': False, 'reason': 'buyer_broke'}

            # Transfer one unit out of the stack
            if getattr(item, 'quantity', 1) > 1:
                item.quantity -= 1
                unit = _copy.copy(item)
                unit.quantity = 1
            else:
                seller.inventory.items.remove(item)
                unit = item
            buyer.inventory.items.append(unit)

            # Transfer gold
            buyer.gold = int(buyer.gold) - gold_int
            seller.gold = int(getattr(seller, 'gold', 0)) + gold_int

            # Buyer's cost basis — preserves the 'won't sell below paid' floor
            # for future resale attempts.
            if hasattr(buyer, '_item_prices'):
                buyer._item_prices[id(unit)] = float(gold_int)

            # Record cleared trade in the global market tape
            observe_trade(getattr(unit, 'name', ''), float(gold_int))

            # Sentiment
            seller.record_interaction(buyer, 2.0)
            buyer.record_interaction(seller, 2.0)
            return {
                'success': True,
                'item': unit,
                'price': float(gold_int),
            }

        # ---- 1. BUY path: self is hungry, target has food ----
        if getattr(self, 'hunger', 0.0) < 0.3:
            food_candidates = sorted(
                [i for i in target.inventory.items
                 if getattr(i, 'is_food', False)
                 and isinstance(i, Stackable)
                 and getattr(i, 'value', 0) > 0],
                key=lambda i: i.value, reverse=True
            )
            for food_item in food_candidates:
                deal = compute_trade_price(food_item, target, self)  # target=seller, self=buyer
                if not deal['feasible']:
                    continue
                if self.gold < max(1, int(round(deal['price']))):
                    continue
                tx = _execute(seller=target, buyer=self, item=food_item, deal=deal)
                if not tx['success']:
                    continue
                # Accumulate surplus for the RL reward signal
                self._trade_surplus_accumulated = (
                    getattr(self, '_trade_surplus_accumulated', 0.0)
                    + deal['buyer_surplus']
                )
                target._trade_surplus_accumulated = (
                    getattr(target, '_trade_surplus_accumulated', 0.0)
                    + deal['seller_surplus']
                )
                self._social_wins = getattr(self, '_social_wins', 0) + 1
                self.gain_exp(1)
                result.update(tx)
                result['direction'] = 'bought'
                result['surplus'] = deal['buyer_surplus']
                return result

        # ---- 2. SELL path: self has sellable goods, target will buy ----
        sellable = sorted(
            [i for i in self.inventory.items
             if isinstance(i, Stackable) and getattr(i, 'value', 0) > 0],
            key=lambda i: i.value, reverse=True
        )
        for item in sellable:
            deal = compute_trade_price(item, self, target)  # self=seller, target=buyer
            if not deal['feasible']:
                continue
            if getattr(target, 'gold', 0) < max(1, int(round(deal['price']))):
                continue
            tx = _execute(seller=self, buyer=target, item=item, deal=deal)
            if not tx['success']:
                continue
            self._trade_surplus_accumulated = (
                getattr(self, '_trade_surplus_accumulated', 0.0)
                + deal['seller_surplus']
            )
            target._trade_surplus_accumulated = (
                getattr(target, '_trade_surplus_accumulated', 0.0)
                + deal['buyer_surplus']
            )
            self._social_wins = getattr(self, '_social_wins', 0) + 1
            self.gain_exp(1)
            result.update(tx)
            result['direction'] = 'sold'
            result['surplus'] = deal['seller_surplus']
            return result

        # ---- 3. LOAN fallback: buyer wants item but can't afford it ----
        # If a trade failed because the buyer was broke, the seller can
        # offer a micro-loan so the transaction still happens. This
        # exercises the debt signal and teaches credit dynamics.
        # Only fires when both sides have a non-negative relationship.
        if not result.get('success'):
            for item in sellable[:3]:
                deal = compute_trade_price(item, self, target)
                if not deal['feasible']:
                    continue
                price = max(1, int(round(deal['price'])))
                buyer_gold = getattr(target, 'gold', 0)
                if buyer_gold >= price:
                    continue  # can afford — not a loan case
                shortfall = price - buyer_gold
                # Seller must like the buyer enough to extend credit
                rel = self.get_relationship(target)
                if rel is None or rel[0] < 0:
                    continue
                # Loan the shortfall to the buyer, then execute the trade
                if hasattr(self, 'give_loan') and self.gold >= shortfall:
                    self.give_loan(target, shortfall, daily_rate=0.05, now=0)
                    tx = _execute(seller=self, buyer=target, item=item, deal=deal)
                    if tx['success']:
                        self._trade_surplus_accumulated = (
                            getattr(self, '_trade_surplus_accumulated', 0.0)
                            + deal['seller_surplus']
                        )
                        target._trade_surplus_accumulated = (
                            getattr(target, '_trade_surplus_accumulated', 0.0)
                            + deal['buyer_surplus']
                        )
                        self._social_wins = getattr(self, '_social_wins', 0) + 1
                        self.gain_exp(1)
                        result.update(tx)
                        result['direction'] = 'sold_on_credit'
                        result['surplus'] = deal['seller_surplus']
                        result['loan_amount'] = shortfall
                        return result

        result['reason'] = 'no_acceptable_trade'
        return result

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
            self._social_wins = getattr(self, '_social_wins', 0) + 1
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

    def steal(self, target, item=None) -> dict:
        """Attempt to steal from another creature.

        Auto-resolves the best item to steal:
          1. Gold (steal up to 50% of target's gold)
          2. Unequipped items, highest value first
          3. Equipped items (much harder: -8 contest penalty)

        Familiarity modifier: abs(sentiment) * 0.15 added to target's
        detection roll — people who know you well notice theft more.

        Uses stealth vs detection if unseen, deception vs detection if
        seen. Returns dict: success, reason, stolen_value.
        """
        result = {'success': False, 'reason': '', 'stolen_value': 0.0}

        if self._sight_distance(target) > 1:
            result['reason'] = 'not_adjacent'
            return result

        # Auto-resolve what to steal: gold → unequipped by value → equipped
        stealing_gold = False
        stealing_equipped = False
        if item is None:
            target_gold = getattr(target, 'gold', 0)
            if target_gold > 0:
                stealing_gold = True
                item = None  # gold path
            else:
                equipped_set = set(target.equipment.values())
                unequipped = sorted(
                    [i for i in target.inventory.items if i not in equipped_set],
                    key=lambda i: getattr(i, 'value', 0), reverse=True
                )
                if unequipped:
                    item = unequipped[0]
                else:
                    equipped_list = sorted(
                        [i for i in equipped_set if i is not None],
                        key=lambda i: getattr(i, 'value', 0), reverse=True
                    )
                    if equipped_list:
                        item = equipped_list[0]
                        stealing_equipped = True
                    else:
                        result['reason'] = 'nothing_to_steal'
                        return result

        if item is not None and not stealing_gold:
            if item not in target.inventory.items:
                result['reason'] = 'item_not_found'
                return result
            if not self.can_carry(item):
                result['reason'] = 'too_heavy'
                return result
            if item in set(target.equipment.values()):
                stealing_equipped = True

        # Familiarity modifier: knowing someone well makes theft harder
        rel = GRAPH.get_edge(target.uid, self.uid)
        familiarity_bonus = abs(rel[0]) * 0.15 if rel else 0.0

        # Contest: stealth if unseen, deception if seen
        # Equipped items add -8 penalty to attacker
        equip_penalty = -8 if stealing_equipped else 0
        if target.can_see(self):
            won, margin = self.stats.contest(target.stats, 'deception_vs_detection')
        else:
            won, margin = self.stats.contest(target.stats, 'stealth_vs_detection')
        adjusted_margin = margin + equip_penalty - familiarity_bonus
        won = adjusted_margin > 0

        if won:
            result['success'] = True
            self._social_wins = getattr(self, '_social_wins', 0) + 1
            if stealing_gold:
                amount = max(1, int(target.gold * random.uniform(0.1, 0.5)))
                target.gold -= amount
                self.gold = getattr(self, 'gold', 0) + amount
                result['stolen_value'] = float(amount)
            else:
                target.inventory.items.remove(item)
                if stealing_equipped:
                    for slot, eq in target.equipment.items():
                        if eq is item:
                            target.equipment[slot] = None
                            break
                self.inventory.items.append(item)
                result['stolen_value'] = float(getattr(item, 'value', 1))
            self._stolen_value = getattr(self, '_stolen_value', 0.0) + result['stolen_value']
        else:
            result['reason'] = 'caught'
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
        ) if GRAPH.get_edge(self.uid, subject_uid) is not None else 0.1

        target.receive_rumor(self, subject_uid, sentiment, confidence, tick)

        # Sharing is a social interaction
        self.record_interaction(target, 1.0)
        target.record_interaction(self, 1.0)
        self._social_wins = getattr(self, '_social_wins', 0) + 1
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
        for uid, rel in GRAPH.edges_from(self.uid).items():
            # Weak = low count (1-3) and small sentiment magnitude
            if 1 <= rel[1] <= 3 and abs(rel[0]) < 5:
                candidates.append(uid)

        if not candidates:
            return False

        subject_uid = random.choice(candidates)

        # Does the target know anything about this subject?
        target_rel = GRAPH.get_edge(target.uid, subject_uid)
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
