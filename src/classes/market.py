"""
Global market-price memory.

A simple exponentially-weighted moving average of cleared trade prices
per item type. This is the cheapest possible market-feedback layer:

* Subjective valuation (``worth_to_creature``) stays personal.
* Bargaining (``compute_trade_price``) stays pairwise.
* But every cleared trade updates a shared "market tape" keyed by
  item name. ``compute_trade_price`` consults that tape as a neutral
  price anchor, pulling both buyer and seller valuations toward the
  market consensus with a tunable weight.

This gives us price *fluctuation* without any additional infrastructure
(no shops, no caravans, no auction houses). When food is scarce and
buyers are hungry, cleared prices drift up → the EMA drifts up → new
trades fire at higher prices → hungry farmers earn more → they pay
down debts and the pressure equalizes. When wheat is abundant, the
opposite happens. All of it emerges from a one-line EMA update.

Market memory is per-item-name (a module-level dict), but the design
would naturally extend to per-map or per-region tables if we wanted
spatial price arbitrage later.

Seed prices come from ``item.value`` — canonical static values in
the DB act as the prior. The first trade of an item initializes its
EMA entry; every subsequent trade pulls the EMA toward the cleared
price by a small alpha so the market moves smoothly rather than
spiking on outliers.

Design notes
------------
* **Alpha is small** (default 0.2) because individual trades are
  noisy. A hungry buyer overpaying for bread shouldn't move the
  market price dramatically by itself.
* **EMA initializes to ``item.value``** on first observation — the
  seed from the item catalog.
* **Volume counter** tracks how many trades have fired for each item.
  Prices with very low volume are less trusted (``confidence`` scales
  with ``ln(1 + volume)``) so the anchoring weight in
  ``compute_trade_price`` is reduced for thin markets.
* **Reset on test runs** — ``reset_market()`` lets tests run with
  deterministic starting state.
"""
from __future__ import annotations
import math


# item_name -> {'ema': float, 'volume': int, 'last_tick': int}
_MARKET: dict[str, dict] = {}


# How fast the EMA moves. Small alpha = smoother, slower response.
EMA_ALPHA = 0.2

# How strongly compute_trade_price anchors to market vs individual
# valuation (0 = ignore market, 1 = use only market).
MARKET_ANCHOR_WEIGHT = 0.3


def observe_trade(item_name: str, cleared_price: float, tick: int = 0) -> None:
    """Record a cleared trade in the market tape.

    Call this after any successful trade swap, with the agreed-upon
    price (not seller_min or buyer_max — the actual gold that moved).
    Updates the EMA and increments the volume counter.
    """
    if cleared_price <= 0:
        return
    entry = _MARKET.get(item_name)
    if entry is None:
        _MARKET[item_name] = {
            'ema': float(cleared_price),
            'volume': 1,
            'last_tick': tick,
        }
        return
    entry['ema'] = EMA_ALPHA * cleared_price + (1.0 - EMA_ALPHA) * entry['ema']
    entry['volume'] += 1
    entry['last_tick'] = tick


def market_price(item_name: str, seed: float = None) -> float | None:
    """Current market EMA for an item, or ``seed`` if never traded.

    Pass ``seed=item.value`` to fall back to the catalog price for
    items the market hasn't seen yet. Returns ``None`` only when no
    entry exists and no seed is provided.
    """
    entry = _MARKET.get(item_name)
    if entry is None:
        return seed
    return entry['ema']


def market_confidence(item_name: str) -> float:
    """How much weight to give the market price relative to individual
    valuation. Scales with ln(1 + volume), capped at 1.0.

    Thin markets (few trades) have lower confidence — the EMA is noisy
    so we trust individual valuations more. Thick markets (many trades)
    have high confidence — the EMA is well-supported.
    """
    entry = _MARKET.get(item_name)
    if entry is None:
        return 0.0
    return min(1.0, math.log(1 + entry['volume']) / math.log(1 + 50))


def market_anchor(item_name: str, individual_value: float) -> float:
    """Blend an individual valuation with the market price.

    Returns ``(1 - w) * individual + w * market``, where ``w`` is
    ``MARKET_ANCHOR_WEIGHT * confidence``. Falls back to the individual
    valuation when no market data exists.
    """
    market = market_price(item_name)
    if market is None:
        return individual_value
    w = MARKET_ANCHOR_WEIGHT * market_confidence(item_name)
    return (1.0 - w) * individual_value + w * market


def reset_market() -> None:
    """Clear all market state. Intended for tests and new episodes."""
    _MARKET.clear()


def market_snapshot() -> dict:
    """Return a copy of the full market state — used for observability,
    training analytics, and tests."""
    return {name: dict(entry) for name, entry in _MARKET.items()}
