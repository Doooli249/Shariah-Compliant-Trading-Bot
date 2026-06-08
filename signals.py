"""
HALAL CRYPTO TRADING BOT — SIGNAL GENERATOR (Dual RSI Crossover)
=================================================================
Based on CGA-Agent paper (dual RSI crossover) + EMA/VWAP scalping research
+ IEEE trading review. Designed to fire multiple times per day on 5-min candles.

BUY requires ALL of:
  1. Fast RSI (7) crosses ABOVE slow RSI (14) — fresh bullish momentum shift
  2. Stochastic RSI K < 50 — entering from below mid, not already overbought
  3. Price above VWAP (if USE_VWAP_FILTER) — volume-weighted bullish bias
  4. Not already holding this coin

Signal strength:
  STRONG = RSI crossover + VWAP bullish + EMA aligned (fast EMA > slow EMA)
  WEAK   = RSI crossover + VWAP bullish, EMA not yet aligned

SELL triggers on ANY of:
  1. Fast RSI crosses BELOW slow RSI — bearish momentum shift
  2. Stochastic RSI K > 80 AND K crosses below D — overbought exit
  3. Stop loss: price dropped STOP_LOSS_PCT% below entry
  4. Fast RSI > RSI_OVERBOUGHT (70) — momentum exhausted

HOLD: none of the above.
"""

from datetime import datetime

import config
from indicators import (
    calculate_rsi_fast_slow,
    calculate_ema_crossover,
    calculate_stoch_rsi,
    calculate_vwap,
)


def get_signal(
    closes: list[float],
    volumes: list[float],
    pair: str,
    current_price: float,
    entry_price: float | None,
    already_holding: bool,
    ob_signal: str | None = None,
    entry_time_iso: str | None = None,
) -> dict:
    """
    Returns signal dict with action, rsi_fast, rsi_slow, stoch_k,
    signal_strength, reason, stop_loss.

    closes        — confirmed closed candles only (closes[:-1] from bot.py)
    volumes       — matching volumes for closed candles
    current_price — live execution price (closes[-1] from bot.py)
    entry_price   — price at open; None if not holding
    already_holding — True if a position is open for this coin
    """
    rsi_data   = calculate_rsi_fast_slow(closes, config.RSI_FAST_PERIOD, config.RSI_SLOW_PERIOD)
    ema_data   = calculate_ema_crossover(closes, config.EMA_FAST, config.EMA_SLOW)
    stoch_data = calculate_stoch_rsi(closes, config.STOCH_RSI_PERIOD, config.STOCH_RSI_K, config.STOCH_RSI_D)
    vwap       = calculate_vwap(closes, volumes) if config.USE_VWAP_FILTER and volumes else None

    if rsi_data is None or stoch_data is None:
        return _signal(pair, "HOLD", None, None, None, "NONE", "Insufficient data for indicators")

    rsi_fast     = rsi_data["fast"]
    rsi_slow     = rsi_data["slow"]
    stoch_k      = stoch_data["k"]
    stoch_d      = stoch_data["d"]
    stoch_k_prev = stoch_data["k_prev"]
    stoch_d_prev = stoch_data["d_prev"]

    # ── Stop loss (highest priority) ──────────────────────────────────────────
    if entry_price and entry_price > 0:
        drop_pct = (entry_price - current_price) / entry_price
        if drop_pct >= config.STOP_LOSS_PCT:
            return _signal(
                pair, "SELL", rsi_fast, rsi_slow, stoch_k, "NONE",
                f"Stop loss: {drop_pct*100:.1f}% drop from entry ${entry_price:,.4f} "
                f"(limit: {config.STOP_LOSS_PCT*100:.0f}%)",
                stop_loss=True,
            )

    # ── SELL conditions (any triggers) ────────────────────────────────────────

    # Fast RSI crosses below slow RSI
    if rsi_data["fast_prev"] >= rsi_data["slow_prev"] and rsi_fast < rsi_slow:
        if entry_time_iso is not None:
            minutes_held = (datetime.now() - datetime.fromisoformat(entry_time_iso)).total_seconds() / 60
            if minutes_held < config.MIN_HOLD_MINUTES:
                return _signal(
                    pair, "HOLD", rsi_fast, rsi_slow, stoch_k, "NONE",
                    f"⏳ Too early to sell — held only {minutes_held:.0f} min (min: {config.MIN_HOLD_MINUTES})",
                )
        if rsi_fast >= config.RSI_MOMENTUM_MAX:
            return _signal(
                pair, "HOLD", rsi_fast, rsi_slow, stoch_k, "NONE",
                f"⚠️ RSI in neutral zone (RSI{config.RSI_FAST_PERIOD}={rsi_fast:.1f}) — ignoring crossover",
            )
        return _signal(
            pair, "SELL", rsi_fast, rsi_slow, stoch_k, "NONE",
            f"RSI bearish crossover (RSI{config.RSI_FAST_PERIOD} {rsi_fast:.1f} "
            f"crossed below RSI{config.RSI_SLOW_PERIOD} {rsi_slow:.1f})",
        )

    # Stochastic RSI overbought exit: K > 80 and K crosses below D
    if stoch_k > 80 and stoch_k_prev >= stoch_d_prev and stoch_k < stoch_d:
        return _signal(
            pair, "SELL", rsi_fast, rsi_slow, stoch_k, "NONE",
            f"StochRSI overbought exit (K={stoch_k:.1f} > 80, crossed below D={stoch_d:.1f})",
        )

    # Fast RSI momentum exhausted
    if rsi_fast > config.RSI_OVERBOUGHT:
        return _signal(
            pair, "SELL", rsi_fast, rsi_slow, stoch_k, "NONE",
            f"Fast RSI overbought (RSI{config.RSI_FAST_PERIOD}={rsi_fast:.1f} > {config.RSI_OVERBOUGHT})",
        )

    # ── BUY conditions ────────────────────────────────────────────────────────
    rsi_bullish_cross = (
        rsi_data["fast_prev"] < rsi_data["slow_prev"]
        and rsi_fast > rsi_slow
    )

    if rsi_bullish_cross:

        if rsi_fast <= config.RSI_MOMENTUM_MIN:
            return _signal(
                pair, "HOLD", rsi_fast, rsi_slow, stoch_k, "NONE",
                f"⚠️ RSI in neutral zone (RSI{config.RSI_FAST_PERIOD}={rsi_fast:.1f}) — ignoring crossover",
            )

        if already_holding:
            return _signal(
                pair, "HOLD", rsi_fast, rsi_slow, stoch_k, "NONE",
                f"RSI bullish crossover but already holding",
            )

        if stoch_k >= 50:
            return _signal(
                pair, "HOLD", rsi_fast, rsi_slow, stoch_k, "NONE",
                f"RSI crossover but StochK={stoch_k:.1f} ≥ 50 — not entering oversold enough",
            )

        # Order book imbalance filter
        if config.USE_ORDER_BOOK_FILTER and ob_signal is not None and ob_signal != "BUY_PRESSURE":
            return _signal(
                pair, "HOLD", rsi_fast, rsi_slow, stoch_k, "NONE",
                f"RSI crossover but order book: {ob_signal} (need BUY_PRESSURE)",
            )

        if config.USE_VWAP_FILTER and vwap is not None and current_price < vwap:
            return _signal(
                pair, "HOLD", rsi_fast, rsi_slow, stoch_k, "NONE",
                f"RSI crossover but price below VWAP "
                f"(${current_price:,.4f} < ${vwap:,.4f})",
            )

        above_vwap  = vwap is None or current_price >= vwap
        ema_aligned = ema_data is not None and ema_data["aligned"]

        if above_vwap and ema_aligned:
            strength = "STRONG"
            vwap_str = f"${vwap:,.4f}" if vwap else "N/A"
            conf = (
                f"RSI{config.RSI_FAST_PERIOD}={rsi_fast:.1f} crossed RSI{config.RSI_SLOW_PERIOD}={rsi_slow:.1f} | "
                f"StochK={stoch_k:.1f} | VWAP: ABOVE (${current_price:,.4f} > {vwap_str}) | EMA: ALIGNED"
            )
        else:
            strength = "WEAK"
            vwap_lbl = "ABOVE" if above_vwap else "N/A"
            ema_lbl  = "ALIGNED" if ema_aligned else "NOT ALIGNED"
            conf = (
                f"RSI{config.RSI_FAST_PERIOD}={rsi_fast:.1f} crossed RSI{config.RSI_SLOW_PERIOD}={rsi_slow:.1f} | "
                f"StochK={stoch_k:.1f} | VWAP: {vwap_lbl} | EMA: {ema_lbl}"
            )

        return _signal(
            pair, "BUY", rsi_fast, rsi_slow, stoch_k, strength,
            f"Dual RSI crossover ({strength}) | {conf}",
        )

    # ── HOLD ──────────────────────────────────────────────────────────────────
    vwap_lbl = ""
    if vwap is not None:
        side     = "ABOVE" if current_price >= vwap else "BELOW"
        vwap_lbl = f" | VWAP: {side} (${vwap:,.4f})"
    return _signal(
        pair, "HOLD", rsi_fast, rsi_slow, stoch_k, "NONE",
        f"No crossover | RSI{config.RSI_FAST_PERIOD}={rsi_fast:.1f} "
        f"RSI{config.RSI_SLOW_PERIOD}={rsi_slow:.1f} StochK={stoch_k:.1f}{vwap_lbl}",
    )


def _signal(
    pair: str,
    action: str,
    rsi_fast: float | None,
    rsi_slow: float | None,
    stoch_k: float | None,
    signal_strength: str,
    reason: str,
    stop_loss: bool = False,
) -> dict:
    return {
        "pair":            pair,
        "action":          action,
        "rsi_fast":        rsi_fast,
        "rsi_slow":        rsi_slow,
        "stoch_k":         stoch_k,
        "signal_strength": signal_strength,
        "reason":          reason,
        "stop_loss":       stop_loss,
    }
