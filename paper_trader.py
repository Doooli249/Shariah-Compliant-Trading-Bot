"""
HALAL CRYPTO TRADING BOT — PAPER TRADER
=========================================
Simulates trades with virtual money. Coinbase is still called for live
price data — only order execution is simulated. All state saved to
paper_trades.json between runs.

Holdings structure (per coin):
    {"amount": 0.000595, "entry_price": 84000.0, "entry_time": "2026-04-20T10:00:00"}

This stores entry_price per coin so the signal engine can check stop loss.
"""

import json
from datetime import datetime
from pathlib import Path

import config
from logger import log_warning

STATE_FILE = "paper_trades.json"


# ── State persistence ─────────────────────────────────────────────────────────

def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
        _migrate_if_needed(state)
        if state.get("cash_usd", 0.0) < 1.0 and not state.get("holdings"):
            log_warning("paper_trades.json has < $1 cash and no holdings — resetting to fresh state")
            return _fresh_state()
        return state
    except json.JSONDecodeError as e:
        log_warning(f"paper_trades.json corrupted — resetting to fresh state ({e})")
    except FileNotFoundError:
        pass
    return _fresh_state()


def _fresh_state() -> dict:
    return {
        "cash_usd":        config.PAPER_STARTING_BALANCE,
        "holdings":        {},
        "trades":          [],
        "total_fees_paid": 0.0,
    }


def _migrate_if_needed(state: dict):
    """Converts old flat holdings (float) to new object format in-place."""
    for coin, holding in list(state.get("holdings", {}).items()):
        if isinstance(holding, (int, float)):
            old_entry = state.pop("entry_prices", {}).get(coin, 0.0)
            state["holdings"][coin] = {
                "amount":      holding,
                "entry_price": old_entry,
                "entry_time":  datetime.now().isoformat(),
            }


def _save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ── Public API ────────────────────────────────────────────────────────────────

def paper_buy(pair: str, usd_amount: float, price: float) -> str:
    """
    Deducts USD, records holding with entry_price for stop-loss tracking.
    Applies taker fee + slippage to simulate real execution cost.
    Returns: "[PAPER BUY] BTC-USD | $50.00 → 0.000595 BTC @ $84,084 (eff.)"
    """
    state = _load_state()
    coin  = pair.split("-")[0]

    if usd_amount > state["cash_usd"]:
        return (
            f"[PAPER BUY] Insufficient balance "
            f"(have ${state['cash_usd']:.2f}, need ${usd_amount:.2f})"
        )

    cost_rate      = config.SLIPPAGE_PCT + config.TAKER_FEE_PCT
    effective_price = price * (1 + cost_rate)
    fees_paid       = round(usd_amount * cost_rate, 6)
    coins_received  = usd_amount / effective_price

    state["cash_usd"] -= usd_amount
    state["total_fees_paid"] = state.get("total_fees_paid", 0.0) + fees_paid
    state["holdings"][coin] = {
        "amount":      round(coins_received, 8),
        "entry_price": round(effective_price, 8),
        "entry_time":  datetime.now().isoformat(),
    }

    portfolio_after = _calc_portfolio_value(state, {pair: price})
    state["trades"].append({
        "timestamp":             datetime.now().isoformat(),
        "action":                "BUY",
        "pair":                  pair,
        "usd_spent":             round(usd_amount, 2),
        "price":                 round(price, 8),
        "effective_price":       round(effective_price, 8),
        "coins_received":        round(coins_received, 8),
        "fees_paid":             fees_paid,
        "portfolio_value_after": round(portfolio_after, 2),
    })
    _save_state(state)

    return (
        f"[PAPER BUY] {pair} | "
        f"${usd_amount:.2f} → {coins_received:.8f} {coin} @ ${effective_price:,.2f} (eff.)"
    )


def paper_sell(pair: str, price: float, reason: str = "") -> str:
    """
    Sells ALL holdings of the coin, calculates P&L after fees + slippage.
    Returns: "[PAPER SELL] BTC-USD | 0.000595 BTC → $51.09 @ $85,914 (eff.) | P&L: +$1.09 (+2.19%)"
    """
    state = _load_state()
    coin  = pair.split("-")[0]

    holding = state["holdings"].get(coin)
    if not holding or holding.get("amount", 0) <= 0:
        return f"[PAPER SELL] No {coin} position to sell"

    amount      = holding["amount"]
    entry_price = holding.get("entry_price", price)

    cost_rate       = config.SLIPPAGE_PCT + config.TAKER_FEE_PCT
    effective_price = price * (1 - cost_rate)
    fees_paid       = round(amount * price * cost_rate, 6)
    usd_received    = amount * effective_price
    pnl_usd         = usd_received - (amount * entry_price)
    pnl_pct         = (effective_price - entry_price) / entry_price * 100

    state["cash_usd"] += usd_received
    state["total_fees_paid"] = state.get("total_fees_paid", 0.0) + fees_paid
    del state["holdings"][coin]

    portfolio_after = _calc_portfolio_value(state, {pair: price})
    sign = "+" if pnl_usd >= 0 else ""
    state["trades"].append({
        "timestamp":             datetime.now().isoformat(),
        "action":                "SELL",
        "pair":                  pair,
        "coins_sold":            round(amount, 8),
        "price":                 round(price, 8),
        "effective_price":       round(effective_price, 8),
        "usd_received":          round(usd_received, 2),
        "fees_paid":             fees_paid,
        "pnl_usd":               round(pnl_usd, 2),
        "pnl_pct":               round(pnl_pct, 2),
        "reason":                reason,
        "portfolio_value_after": round(portfolio_after, 2),
    })
    _save_state(state)

    return (
        f"[PAPER SELL] {pair} | "
        f"{amount:.8f} {coin} → ${usd_received:.2f} @ ${effective_price:,.2f} (eff.) | "
        f"P&L: {sign}${pnl_usd:.2f} ({sign}{pnl_pct:.2f}%)"
    )


def get_paper_balances() -> dict[str, float]:
    """Returns {currency: amount} matching the format of get_account_balances()."""
    state  = _load_state()
    result = {"USD": round(state["cash_usd"], 2)}
    for coin, holding in state["holdings"].items():
        result[coin] = holding["amount"]
    return result


def get_entry_price(pair: str) -> float | None:
    """Returns entry price for an open position, or None if not holding."""
    coin    = pair.split("-")[0]
    holding = _load_state()["holdings"].get(coin)
    return holding["entry_price"] if holding else None


def get_entry_time(pair: str) -> str | None:
    """Returns ISO entry timestamp for an open position, or None if not holding."""
    coin    = pair.split("-")[0]
    holding = _load_state()["holdings"].get(coin)
    return holding.get("entry_time") if holding else None


def is_holding(pair: str) -> bool:
    """Returns True if a position is currently open for this coin."""
    coin    = pair.split("-")[0]
    holding = _load_state()["holdings"].get(coin)
    return bool(holding and holding.get("amount", 0) > 0)


def get_stale_positions(
    max_hold_days: int,
    min_gain_pct: float,
    current_prices: dict,
) -> list[str]:
    """
    Returns pairs where position is too old AND not profitable enough.
    Used by the weekly rebalance check to free up dead capital.
    """
    state = _load_state()
    stale = []
    now   = datetime.now()

    for coin, holding in state["holdings"].items():
        pair       = f"{coin}-USD"
        entry_time = holding.get("entry_time")
        if not entry_time:
            continue

        days_held = (now - datetime.fromisoformat(entry_time)).total_seconds() / 86400
        if days_held <= max_hold_days:
            continue

        entry_price   = holding.get("entry_price", 0.0)
        current_price = current_prices.get(pair, 0.0)
        if entry_price <= 0 or current_price <= 0:
            continue

        pnl_pct = (current_price - entry_price) / entry_price * 100
        if pnl_pct < min_gain_pct:
            stale.append(pair)

    return stale


def print_summary(
    current_prices: dict,
    regime: str = "UNKNOWN",
    active_count: int = 0,
    top_sectors: list | None = None,
    stale_pairs: list | None = None,
):
    """
    Prints a formatted portfolio table to the terminal.
    current_prices — {pair: price}, e.g. {"BTC-USD": 80000}
    """
    state = _load_state()
    cash  = state["cash_usd"]
    total = cash
    lines = []

    for coin, holding in state["holdings"].items():
        pair        = f"{coin}-USD"
        price       = current_prices.get(pair, 0.0)
        amount      = holding["amount"]
        entry       = holding.get("entry_price", 0.0)
        value       = amount * price
        pnl_usd     = value - (amount * entry) if entry else 0.0
        pnl_pct     = (price - entry) / entry * 100 if entry else 0.0
        sign        = "+" if pnl_usd >= 0 else ""
        arrow       = "🟢" if pnl_usd >= 0 else "🔴"
        total      += value
        lines.append(
            f"  {coin:<6}  {amount:.6f}  → ${value:>8.2f}    "
            f"Entry: ${entry:>10,.2f}   "
            f"P&L: {sign}{pnl_pct:.2f}% {arrow}"
        )

    trades     = state.get("trades", [])
    buy_count  = sum(1 for t in trades if t["action"] == "BUY")
    sell_count = sum(1 for t in trades if t["action"] == "SELL")
    pnl_total  = total - config.PAPER_STARTING_BALANCE
    sign       = "+" if pnl_total >= 0 else ""

    # Win rate
    sells     = [t for t in trades if t["action"] == "SELL"]
    wins      = sum(1 for t in sells if t.get("pnl_usd", 0) > 0)
    win_rate  = (wins / len(sells) * 100) if sells else 0.0

    # Max drawdown from portfolio_value_after series
    portfolio_values = [config.PAPER_STARTING_BALANCE] + [
        t["portfolio_value_after"] for t in trades if "portfolio_value_after" in t
    ]
    peak, max_dd = portfolio_values[0], 0.0
    for v in portfolio_values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

    total_fees = state.get("total_fees_paid", 0.0)

    print(f"\n{'─'*56}")
    print(f"  📊 PAPER PORTFOLIO — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'─'*56}")
    print(f"  Cash (USD):       ${cash:>10.2f}")
    for line in lines:
        print(line)
    print(f"  {'─'*52}")
    print(f"  Total Value:      ${total:>10.2f}")
    print(f"  Starting Balance: ${config.PAPER_STARTING_BALANCE:>10.2f}")
    print(
        f"  Overall P&L:      {sign}${pnl_total:.2f}  "
        f"({sign}{pnl_total / config.PAPER_STARTING_BALANCE * 100:.2f}%)"
    )
    print(f"  Total Trades:     {len(trades)}  ({buy_count} buys, {sell_count} sells)")
    print(f"  Win Rate:         {win_rate:.0f}%  ({wins}/{len(sells)} closed trades)")
    print(f"  Max Drawdown:     -{max_dd:.2f}%")
    print(f"  Total Fees Paid:  ${total_fees:.4f}")
    print(f"  ── Phase 2 ──────────────────────────────────────────")
    print(f"  Market Regime:    {regime}")
    print(f"  Active Pairs:     {active_count} (passed all filters)")
    if top_sectors:
        print(f"  Top Sectors:      {', '.join(top_sectors)}")
    if stale_pairs:
        print(f"  ⚠ Rebalance Due:  {', '.join(stale_pairs)}")
    print(f"{'─'*56}\n")


# ── Private helpers ───────────────────────────────────────────────────────────

def _calc_portfolio_value(state: dict, prices: dict) -> float:
    total = state["cash_usd"]
    for coin, holding in state["holdings"].items():
        amount = holding["amount"] if isinstance(holding, dict) else holding
        total += amount * prices.get(f"{coin}-USD", 0.0)
    return total
