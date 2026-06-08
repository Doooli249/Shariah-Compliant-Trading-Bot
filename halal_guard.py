"""
HALAL CRYPTO TRADING BOT — HALAL COMPLIANCE GUARD
===================================================
Last gate before money moves. Enforces Islamic finance rules
independently of everything the signal engine already checked.

Rules hardcoded here — not in config, not negotiable:
  - NEVER margin, leverage, futures, derivatives, staking
  - NEVER trade a pair not on the halal whitelist
  - NEVER average down (buy when already holding)
  - NEVER exceed 25% portfolio concentration per coin

Block messages always start with: 🚫 HALAL BLOCK:
"""

import config
from logger import log_block

_FORBIDDEN = {"SHORT", "MARGIN", "LEVERAGE", "FUTURES", "DERIVATIVE", "STAKE"}


def check_trade(
    action: str,
    pair: str,
    usd_amount: float,
    balances: dict,
    current_prices: dict,
) -> tuple[bool, str]:
    """
    Returns (is_allowed, reason).
    is_allowed=False means the trade must be blocked.

    balances       — {currency: amount}, e.g. {"USD": 850, "BTC": 0.001}
    current_prices — {pair: price},      e.g. {"BTC-USD": 80000}
    """
    action_upper = action.upper()

    # ── Forbidden action types ────────────────────────────────────────────────
    if action_upper in _FORBIDDEN:
        msg = f"Action '{action}' is forbidden under halal compliance rules"
        log_block(pair, msg)
        return False, msg

    # ── Pair must be on halal whitelist ───────────────────────────────────────
    if pair not in config.TRADING_PAIRS:
        msg = f"Pair not on halal whitelist"
        log_block(pair, msg)
        return False, msg

    coin = pair.split("-")[0]

    if action_upper == "BUY":
        usd_balance = balances.get("USD", 0.0)

        # ── Sufficient USD balance ────────────────────────────────────────────
        if usd_amount > usd_balance:
            msg = (
                f"Insufficient USD balance "
                f"(have ${usd_balance:.2f}, need ${usd_amount:.2f})"
            )
            log_block(pair, msg)
            return False, msg

        # ── No averaging down ─────────────────────────────────────────────────
        if balances.get(coin, 0.0) > 0:
            msg = f"Already holding {coin} — averaging down is not allowed"
            log_block(pair, msg)
            return False, msg

        # ── Max 25% concentration ─────────────────────────────────────────────
        portfolio_value = calculate_portfolio_value(balances, current_prices)
        if portfolio_value > 0:
            current_coin_usd = balances.get(coin, 0.0) * current_prices.get(pair, 0.0)
            new_coin_usd     = current_coin_usd + usd_amount
            new_pct          = new_coin_usd / (portfolio_value + usd_amount)
            if new_pct > config.MAX_POSITION_PCT:
                msg = (
                    f"Would exceed {config.MAX_POSITION_PCT*100:.0f}% position limit "
                    f"({new_pct*100:.1f}% after buy)"
                )
                log_block(pair, msg)
                return False, msg

    return True, "Halal compliance check passed"


def calculate_portfolio_value(balances: dict, prices: dict) -> float:
    """
    Total portfolio value in USD.
    balances — {currency: amount}
    prices   — {pair: price} e.g. {"BTC-USD": 80000}
    """
    total = balances.get("USD", 0.0)
    for coin, amount in balances.items():
        if coin == "USD":
            continue
        price  = prices.get(f"{coin}-USD", 0.0)
        total += amount * price
    return total
