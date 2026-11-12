"""Backdated xAI API list price versus a retrieved subscription plan price.

Rates are USD per 1M tokens. A turn uses the schedule row for its model whose
effective time is the latest one at or before the turn. `costUsdTicks` is not
a list price. A missing dated row stays unknown.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from token_history import parse_time

# Release notes, 12 Aug 2026: grok-4.6 is $2 / $0.50 / $6 below 200k prompt
# tokens and $4 / $1 / $12 at or above. The same note on 21 Sep 2026 gives
# grok-4.7 those rates. Local ledgers name the Build session grok-4.x-build.
# Grok 4.7 Fast is not a public API price, so it is not used here.
# https://docs.x.ai/developers/release-notes
# The pricing page dated 29 Sep 2026 still shows these rates, plus the other
# public models from that page only.
# https://docs.x.ai/developers/pricing
_MILLION = Decimal(1_000_000)
_CENT = Decimal("0.01")

PUBLISHED_SCHEDULE: tuple[dict[str, Any], ...] = (
    {
        "models": ("grok-4.6", "grok-4.6-build"),
        "effective": "2026-08-12T00:00:00Z",
        "threshold": 200_000,
        "input": "2.00",
        "cached": "0.50",
        "output": "6.00",
        "long_input": "4.00",
        "long_cached": "1.00",
        "long_output": "12.00",
    },
    {
        "models": ("grok-4.7", "grok-4.7-build"),
        "effective": "2026-09-21T00:00:00Z",
        "threshold": 200_000,
        "input": "2.00",
        "cached": "0.50",
        "output": "6.00",
        "long_input": "4.00",
        "long_cached": "1.00",
        "long_output": "12.00",
    },
    {
        "models": ("grok-4.5", "grok-4.5-build"),
        "effective": "2026-09-29T00:00:00Z",
        "threshold": 200_000,
        "input": "2.00",
        "cached": "0.30",
        "output": "6.00",
        "long_input": "4.00",
        "long_cached": "0.60",
        "long_output": "12.00",
    },
    {
        "models": ("grok-4.3",),
        "effective": "2026-09-29T00:00:00Z",
        "threshold": 200_000,
        "input": "1.25",
        "cached": "0.20",
        "output": "2.50",
        "long_input": "2.50",
        "long_cached": "0.40",
        "long_output": "5.00",
    },
    {
        "models": ("grok-build-0.1",),
        "effective": "2026-09-29T00:00:00Z",
        "threshold": 200_000,
        "input": "1.00",
        "cached": "0.20",
        "output": "2.00",
        "long_input": "2.00",
        "long_cached": "0.40",
        "long_output": "4.00",
    },
)

# The local billing log has credit percents and no dollar plan price.
# The Grok Bot FAQ does not state a SuperGrok Heavy dollar amount.
PUBLISHED_PLANS: tuple[dict[str, Any], ...] = ()


def _money(amount: Decimal) -> float:
    cents = amount.quantize(_CENT, rounding=ROUND_HALF_UP)
    return float(cents)


def _rate(model: str, when, schedule: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
    chosen = None
    chosen_at = None
    for row in schedule:
        names = row.get("models") or ()
        if model not in names and model != row.get("model"):
            continue
        effective = parse_time(row.get("effective"))
        if effective is None or when < effective:
            continue
        if chosen_at is None or effective >= chosen_at:
            chosen = row
            chosen_at = effective
    return chosen


def _side(rates: dict[str, Any], long_context: bool, key: str) -> Decimal:
    name = f"long_{key}" if long_context else key
    return Decimal(str(rates[name]))


def turn_api_usd(event: dict[str, Any], schedule: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> Decimal | None:
    """List-price dollars for one counted turn, or None when it cannot be priced."""
    model = str(event.get("model") or "").strip()
    when = parse_time(event.get("ended_at"))
    if not model or when is None:
        return None
    rates = _rate(model, when, schedule)
    if rates is None:
        return None
    has_input = event.get("input_tokens") is not None
    has_output = event.get("output_tokens") is not None
    if not has_input and not has_output:
        return None
    try:
        incoming = int(event.get("input_tokens") or 0)
        outgoing = int(event.get("output_tokens") or 0)
    except (TypeError, ValueError):
        return None
    cached_raw = event.get("cached_tokens")
    if cached_raw is None:
        cached = 0
    else:
        try:
            cached = int(cached_raw)
        except (TypeError, ValueError):
            return None
        if cached > incoming:
            return None
    threshold = int(rates.get("threshold") or 0)
    long_context = threshold > 0 and incoming >= threshold
    uncached = incoming - cached
    amount = (
        Decimal(uncached) * _side(rates, long_context, "input")
        + Decimal(cached) * _side(rates, long_context, "cached")
        + Decimal(outgoing) * _side(rates, long_context, "output")
    ) / _MILLION
    return amount


def stamp_api_usd(
    events: list[dict[str, Any]],
    schedule: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> list[dict[str, Any]]:
    sheet = schedule if schedule is not None else PUBLISHED_SCHEDULE
    stamped: list[dict[str, Any]] = []
    for event in events:
        row = dict(event)
        amount = turn_api_usd(row, sheet)
        row["api_usd"] = None if amount is None else format(amount, "f")
        stamped.append(row)
    return stamped


def _overlaps(start, end, period: dict[str, Any]) -> bool:
    period_start = parse_time(period.get("start"))
    period_end = parse_time(period.get("end"))
    if period_start is None:
        return False
    if start is not None and period_end is not None and period_end <= start:
        return False
    if end is not None and period_start >= end:
        return False
    return True


def subscription_usd(
    plans: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    *,
    start: str | None = None,
    end: str | None = None,
) -> Decimal | None:
    """Sum dated plan prices for periods the window covers. Missing prices stay unknown."""
    rows = list(plans or [])
    if not rows:
        return None
    window_start = parse_time(start)
    window_end = parse_time(end)
    chosen = [row for row in rows if _overlaps(window_start, window_end, row)]
    if not chosen:
        return None
    total = Decimal(0)
    for row in chosen:
        if row.get("usd") is None:
            return None
        total += Decimal(str(row["usd"]))
    return total


def cost_summary(
    events: list[dict[str, Any]],
    plans: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    *,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """API total, subscription dollars, and the difference for one window."""
    priced = Decimal(0)
    priced_turns = 0
    unpriced = 0
    for event in events:
        raw = event.get("api_usd")
        if raw is None:
            unpriced += 1
            continue
        priced += Decimal(str(raw))
        priced_turns += 1
    if events and priced_turns == 0:
        api: float | None = None
        api_amount = None
    else:
        api_amount = priced
        api = _money(priced)
    plan_amount = subscription_usd(plans, start=start, end=end)
    plan = None if plan_amount is None else _money(plan_amount)
    difference = None
    if api_amount is not None and plan_amount is not None:
        difference = _money(api_amount - plan_amount)
    return {
        "api": api,
        "subscription": plan,
        "difference": difference,
        "unpriced_turns": unpriced,
        "priced_turns": priced_turns,
    }
