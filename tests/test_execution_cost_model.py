"""Tests for the per-fill, per-market execution cost model.

Pins the audit's C3 finding: a winner produces 3 commissioned exits, FX
round-trips cost real money, and Indian STT / UK stamp duty matter at €50.
"""
from __future__ import annotations

from scripts.execution_cost_model import (
    book_trade_cost,
    fill_cost,
    load_cost_config,
)


# ---------------------------------------------------------------------------
# Single-fill mechanics
# ---------------------------------------------------------------------------


def test_us_buy_50eur_charges_at_least_the_commission_minimum():
    """At €50 notional, 2 bps commission is €0.01 — the €1 floor must win."""
    f = fill_cost(notional_eur=50.0, side="BUY", market="US")
    assert f.commission_eur >= 1.0, (
        "Commission minimum must dominate at small notional; got "
        f"{f.commission_eur}"
    )
    # Half-spread = 50 * 3 / 10000 / 2 = €0.0075
    assert abs(f.spread_eur - (50.0 * 3.0 / 10_000 / 2)) < 1e-6
    # Slippage = 50 * 2 / 10000 = €0.01
    assert abs(f.slippage_eur - (50.0 * 2.0 / 10_000)) < 1e-6
    # Total must include the minimum commission, slippage and spread.
    assert f.total_eur > 1.0


def test_india_sell_includes_stt_uk_buy_includes_stamp():
    """India STT (~10 bps) applies on SELLS only; UK stamp (50 bps) on BUYS only."""
    in_sell = fill_cost(notional_eur=10_000.0, side="SELL", market="IN")
    in_buy = fill_cost(notional_eur=10_000.0, side="BUY", market="IN")
    assert in_sell.exchange_fee_eur > in_buy.exchange_fee_eur, (
        "Indian SELL must be more expensive than BUY (STT)"
    )
    gb_buy = fill_cost(notional_eur=10_000.0, side="BUY", market="GB")
    gb_sell = fill_cost(notional_eur=10_000.0, side="SELL", market="GB")
    assert gb_buy.exchange_fee_eur > gb_sell.exchange_fee_eur, (
        "UK BUY must be more expensive than SELL (stamp duty)"
    )
    # Sanity: UK stamp is 50 bps -> €50 on €10k.
    assert abs(gb_buy.exchange_fee_eur - 50.0) < 1e-6


def test_unknown_market_uses_conservative_fallback():
    f = fill_cost(notional_eur=50.0, side="BUY", market="XX")
    assert f.commission_eur >= 1.5  # fallback minimum is €1.50
    assert f.spread_eur > 0.0


# ---------------------------------------------------------------------------
# Lifecycle: 3-fill TP1+TP2+runner winner must cost more than 1-fill stop
# ---------------------------------------------------------------------------


def test_winner_three_legs_costs_more_than_stop_one_leg_us():
    """The booking plan fires 3-4 commissioned fills; a stop fires 2. The
    audit C3 finding is exactly this: a single flat cost deduction hides the
    multi-leg drain."""
    winner = book_trade_cost(
        alloc_eur=50.0, market="US",
        leg_fractions=[("BUY", 1.0), ("SELL", 0.5), ("SELL", 0.3), ("SELL", 0.2)],
    )
    stopped = book_trade_cost(
        alloc_eur=50.0, market="US",
        leg_fractions=[("BUY", 1.0), ("SELL", 1.0)],
    )
    assert winner.n_fills == 4
    assert stopped.n_fills == 2
    assert winner.total_eur > stopped.total_eur, (
        "TP1+TP2+runner winner must charge more total than a stopped trade "
        "because it fires more commissioned legs."
    )


def test_fx_charged_on_non_eur_markets_only():
    """A €-investor pays FX round-trip on non-EUR markets; not on Xetra."""
    us = book_trade_cost(
        alloc_eur=50.0, market="US",
        leg_fractions=[("BUY", 1.0), ("SELL", 1.0)],
    )
    de = book_trade_cost(
        alloc_eur=50.0, market="DE",
        leg_fractions=[("BUY", 1.0), ("SELL", 1.0)],
    )
    assert us.fx_rt_eur > 0
    assert de.fx_rt_eur == 0.0


def test_us_round_trip_cost_can_exceed_gross_edge_at_50eur():
    """C3 Monte Carlo killer: at €50 notional with the booking plan, the
    cost regularly exceeds the cited ~€0.62 gross per-trade edge. We pin
    that "exceeds" outcome here so a future cost-model change can't quietly
    re-claim economic edge."""
    winner = book_trade_cost(
        alloc_eur=50.0, market="US",
        leg_fractions=[("BUY", 1.0), ("SELL", 0.5), ("SELL", 0.3), ("SELL", 0.2)],
    )
    gross_eur_edge = 0.62  # from the audit Monte Carlo
    assert winner.total_eur > gross_eur_edge, (
        f"Cost {winner.total_eur:.2f} must exceed cited gross edge "
        f"€{gross_eur_edge} at €50 notional — this is the C3 invariant."
    )


def test_india_round_trip_includes_stt_and_fx():
    """India trade pays STT on the SELL legs plus FX both ways."""
    in_trade = book_trade_cost(
        alloc_eur=50.0, market="IN",
        leg_fractions=[("BUY", 1.0), ("SELL", 0.5), ("SELL", 0.5)],
    )
    assert in_trade.fx_rt_eur > 0, "India trade must charge FX round-trip"
    # SELL legs charged ≥ 10 bps STT each.
    sell_fees = sum(f.exchange_fee_eur for f in in_trade.fills if f.side == "SELL")
    assert sell_fees > 0.0, "India SELLs must charge STT/regulatory fees"


def test_config_loader_returns_table_with_known_markets():
    cfg = load_cost_config()
    for m in ("US", "IN", "JP", "KR", "GB", "DE", "FR", "NL", "CH", "AU", "CA"):
        assert m in cfg, f"market {m} missing from cost table"
        assert "commission_bps" in cfg[m]
        assert "fx_rt_bps" in cfg[m]
