from __future__ import annotations


class RelationshipsMixin:
    """Relationship tracking and loan methods for Creature."""

    def record_interaction(self, other, score: float):
        """Record an interaction with another creature.

        Args:
            other: the creature interacted with
            score: positive = good, negative = bad
        """
        uid = other.uid
        if uid in self.relationships:
            rel = self.relationships[uid]
            rel[0] += score       # sentiment
            rel[1] += 1           # count
            if score < rel[2]:
                rel[2] = score    # min_score
            if score > rel[3]:
                rel[3] = score    # max_score
        else:
            self.relationships[uid] = [score, 1, score, score]

    def get_relationship(self, other):
        """Return (sentiment, count, min_score, max_score) or None."""
        return self.relationships.get(other.uid)

    def relationship_confidence(self, other) -> float:
        """Return 0.0–1.0 confidence based on interaction count."""
        rel = self.relationships.get(other.uid)
        if rel is None:
            return 0.0
        return rel[1] / (rel[1] + 5)

    def curiosity_toward(self, other) -> float:
        """Return curiosity score (high for strangers, decays with familiarity)."""
        rel = self.relationships.get(other.uid)
        if rel is None:
            return 1.0
        return 1 / (1 + rel[1])

    # -- Rumors -------------------------------------------------------------

    def receive_rumor(self, source, subject_uid: int,
                      sentiment: float, confidence: float, tick: int):
        """Receive a rumor about a third party from a source creature."""
        entry = (source.uid, sentiment, confidence, tick)
        if subject_uid in self.rumors:
            self.rumors[subject_uid].append(entry)
        else:
            self.rumors[subject_uid] = [entry]

    def rumor_opinion(self, subject_uid: int, current_tick: int,
                      decay_rate: float = 0.001) -> float:
        """Compute weighted opinion of a creature based on rumors.

        Weights: source_trust * confidence * time_decay.
        Returns 0.0 if no rumors exist.
        """
        rumors = self.rumors.get(subject_uid)
        if not rumors:
            return 0.0
        total_weight = 0.0
        weighted_sentiment = 0.0
        for source_uid, sentiment, confidence, tick in rumors:
            source_rel = self.relationships.get(source_uid)
            if source_rel is not None:
                # Trust the source based on our relationship with them
                source_trust = max(0.0, source_rel[0] / (abs(source_rel[0]) + 5))
            else:
                source_trust = 0.1  # slight trust for strangers
            age = current_tick - tick
            time_decay = 1 / (1 + decay_rate * age)
            weight = source_trust * confidence * time_decay
            weighted_sentiment += sentiment * weight
            total_weight += abs(weight)
        if total_weight == 0:
            return 0.0
        return weighted_sentiment / total_weight

    # -- Loans / Debt -------------------------------------------------------

    def give_loan(self, borrower, amount: float,
                  daily_rate: float = 0.05, now: int = 0) -> bool:
        """Lend gold to another creature.

        Args:
            borrower: creature receiving the loan
            amount: gold amount
            daily_rate: daily interest rate (0.05 = 5% per day)
            now: current game tick (for interest calculation)

        Returns True if loan was given.
        """
        if self.gold < amount or amount <= 0:
            return False

        self.gold -= int(amount)
        borrower.gold += int(amount)

        loan = {'principal': amount, 'rate': daily_rate, 'originated': now}
        borrower.loans[self.uid] = loan
        self.loans_given[borrower.uid] = loan

        # Lending is a positive social act
        self.record_interaction(borrower, 2.0)
        borrower.record_interaction(self, 3.0)
        return True

    def debt_owed_to(self, lender_uid: int, now: int) -> float:
        """Calculate total debt owed to a specific lender including interest."""
        loan = self.loans.get(lender_uid)
        if loan is None:
            return 0.0
        days = max(0, (now - loan['originated']) / 86_400_000)
        return loan['principal'] * (1 + loan['rate']) ** days

    def total_debt(self, now: int) -> float:
        """Total debt across all lenders."""
        return sum(self.debt_owed_to(uid, now) for uid in self.loans)

    def disposable_wealth(self, now: int) -> float:
        """Gold minus total debt. Can be negative (underwater)."""
        return self.gold - self.total_debt(now)

    def repay_loan(self, lender, amount: float, now: int) -> dict:
        """Repay part or all of a loan.

        Returns dict: paid, remaining, fully_repaid.
        """
        result = {'paid': 0.0, 'remaining': 0.0, 'fully_repaid': False}

        if lender.uid not in self.loans:
            return result

        owed = self.debt_owed_to(lender.uid, now)
        payment = min(amount, self.gold, owed)

        if payment <= 0:
            result['remaining'] = owed
            return result

        self.gold -= int(payment)
        lender.gold += int(payment)
        result['paid'] = payment

        remaining = owed - payment
        result['remaining'] = remaining

        if remaining <= 0.5:  # close enough to zero — clear the loan
            del self.loans[lender.uid]
            if self.uid in lender.loans_given:
                del lender.loans_given[self.uid]
            result['fully_repaid'] = True
            # Repaying in full is a positive act
            self.record_interaction(lender, 2.0)
            lender.record_interaction(self, 2.0)
        else:
            # Update principal to remaining balance
            self.loans[lender.uid]['principal'] = remaining
            self.loans[lender.uid]['originated'] = now  # reset clock

        return result

    def collect_debt(self, borrower, now: int) -> dict:
        """Attempt to collect on a loan. Borrower pays what they can.

        If borrower can't pay, negative sentiment. If they pay, positive.
        Returns dict: collected, remaining, defaulted.
        """
        result = {'collected': 0.0, 'remaining': 0.0, 'defaulted': False}

        if borrower.uid not in self.loans_given:
            return result

        owed = borrower.debt_owed_to(self.uid, now)
        result['remaining'] = owed

        if borrower.gold >= owed:
            # Full payment
            repay = borrower.repay_loan(self, owed, now)
            result['collected'] = repay['paid']
            result['remaining'] = repay['remaining']
        elif borrower.gold > 0:
            # Partial payment
            repay = borrower.repay_loan(self, borrower.gold, now)
            result['collected'] = repay['paid']
            result['remaining'] = repay['remaining']
            # Partial payment strains relationship
            self.record_interaction(borrower, -1.0)
            borrower.record_interaction(self, -1.0)
        else:
            # Default — can't pay anything
            result['defaulted'] = True
            self.record_interaction(borrower, -5.0)
            borrower.record_interaction(self, -3.0)

        return result
