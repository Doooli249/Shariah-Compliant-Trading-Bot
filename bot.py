"""
HALAL CRYPTO TRADING BOT — MAIN ENGINE (Phase 2)
==================================================
Entry point. Run with: python bot.py

Phase 2 two-pass cycle:
  Pass 1 — fetch candles for ALL pairs (needed for momentum ranking)
  Pass 2 — process signals only for pairs that pass:
             1. Market regime filter (no BUY in BEAR market)
             2. Momentum ranking (top MAX_ACTIVE_PAIRS by 30-candle return)
             3. Sector rotation (top TOP_SECTORS_COUNT sectors)

Per-pair pipeline:
  1. Check stop loss using closed candles + live price
  2. Calculate RSI + MACD + Bollinger + Dynamic Breakout
  3. Volume confirmation on BUY signals
  4. Volatility-adjusted position sizing
  5. Halal compliance check (cannot be bypassed)
  6. Execute paper or live trade

All 7 Phase 2 upgrades are individually toggleable in config.py.
"""

import json
import time
from datetime import datetime

import schedule

import coinbase_client as cb
import config
import logger as log
from halal_guard import check_trade
from indicators import (
    calculate_btc_regime,
    calculate_momentum_score,
    calculate_volatility,
    check_order_book_imbalance,
)
from paper_trader import (
    get_entry_price,
    get_entry_time,
    get_paper_balances,
    get_stale_positions,
    is_holding,
    paper_buy,
    paper_sell,
    print_summary,
)
from signals import get_signal

_LIVE_ENTRY_FILE = "active_stops.json"

# Global flag set by check_market_regime() each cycle
BUYS_SUSPENDED = False

# Pending limit orders — persists between cycles
# Paper: key = pair (BUY) or "SELL_{pair}" (SELL)
# Live:  key = exchange order_id
_pending_orders: dict[str, dict] = {}


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    _print_banner()

    if not config.PAPER_TRADING:
        print("\n  ⚠️  LIVE TRADING MODE — real money will be used.")
        print("  Starting in 10 seconds. Press Ctrl+C to cancel.\n")
        try:
            for i in range(10, 0, -1):
                print(f"  {i}...", end="\r", flush=True)
                time.sleep(1)
            print()
        except KeyboardInterrupt:
            print("\n  Cancelled. Exiting.")
            return

    run_cycle()

    schedule.every(config.CHECK_INTERVAL_MINUTES).minutes.do(run_cycle)

    if config.USE_REBALANCE:
        schedule.every(config.REBALANCE_INTERVAL_DAYS).days.do(run_rebalance)

    log.log_info(
        f"Min hold: {config.MIN_HOLD_MINUTES}min | "
        f"RSI momentum filter: {config.RSI_MOMENTUM_MIN}-{config.RSI_MOMENTUM_MAX}"
    )
    log.log_info(
        f"Scheduler active — signal cycle every {config.CHECK_INTERVAL_MINUTES} min"
        + (f", rebalance every {config.REBALANCE_INTERVAL_DAYS} days" if config.USE_REBALANCE else "")
        + ". Press Ctrl+C to stop."
    )

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        log.log_info("Bot stopped by user.")


# ── Upgrade 1: Market Regime Filter ──────────────────────────────────────────

def check_market_regime() -> str:
    global BUYS_SUSPENDED

    if not config.USE_REGIME_FILTER:
        BUYS_SUSPENDED = False
        return "UNKNOWN"

    try:
        data       = cb.get_daily_candles("BTC-USD", limit=config.REGIME_LOOKBACK_DAYS + 5)
        btc_prices = data["closes"]
        regime     = calculate_btc_regime(
            btc_prices, config.REGIME_LOOKBACK_DAYS, config.BEAR_MARKET_THRESHOLD
        )
    except Exception as e:
        log.log_warning(f"Regime check failed ({e}) — defaulting to NEUTRAL")
        BUYS_SUSPENDED = False
        return "NEUTRAL"

    if regime == "BEAR":
        BUYS_SUSPENDED = True
        log.log_regime(f"BEAR MARKET — BTC down ≥{config.BEAR_MARKET_THRESHOLD*100:.0f}% "
                       f"over {config.REGIME_LOOKBACK_DAYS} days. BUY signals suspended.")
    else:
        BUYS_SUSPENDED = False
        log.log_info(f"Market regime: {regime}")

    return regime


# ── Upgrade 2: Momentum Ranking ───────────────────────────────────────────────

def rank_pairs_by_momentum(closes_map: dict[str, list[float]]) -> list[str]:
    if not config.USE_MOMENTUM_RANKING:
        return list(closes_map.keys())

    scores = {}
    for pair, closes in closes_map.items():
        score = calculate_momentum_score(closes, config.MOMENTUM_LOOKBACK_CANDLES)
        if score is not None:
            scores[pair] = score

    ranked = sorted(scores, key=lambda p: scores[p], reverse=True)
    top    = ranked[:config.MAX_ACTIVE_PAIRS]

    top5_names = [p.split("-")[0] for p in top[:5]]
    log.log_momentum(
        f"Top momentum pairs: {', '.join(top5_names)}… "
        f"({len(top)} of {len(scores)} ranked)"
    )
    return top


# ── Upgrade 4: Sector Rotation ────────────────────────────────────────────────

def get_top_sectors(closes_map: dict[str, list[float]]) -> list[str]:
    if not config.USE_SECTOR_ROTATION:
        return list(config.COIN_SECTORS.keys())

    sector_scores: dict[str, float] = {}
    for sector, pairs in config.COIN_SECTORS.items():
        scores = [
            s for p in pairs
            if p in closes_map
            for s in [calculate_momentum_score(closes_map[p], config.MOMENTUM_LOOKBACK_CANDLES)]
            if s is not None
        ]
        if scores:
            sector_scores[sector] = sum(scores) / len(scores)

    ranked  = sorted(sector_scores, key=lambda s: sector_scores[s], reverse=True)
    top     = ranked[:config.TOP_SECTORS_COUNT]
    log.log_sector(f"Top sectors: {', '.join(top)}")
    return top


# ── Upgrade C: Position Scoring ──────────────────────────────────────────────

def calculate_position_score(
    current_pnl_pct: float,    # decimal: 0.02 for 2% gain
    hours_held: float,
    current_volatility: float, # decimal annualised: 0.80 for 80%
) -> float:
    """
    Score = (pnl * 2) - (hours * 0.15) - (vol * 0.3)
    More negative = exit sooner. Threshold defined by POSITION_EXIT_THRESHOLD.
    """
    return (current_pnl_pct * 2.0) - (hours_held * 0.15) - (current_volatility * 0.3)


# ── Upgrade 5: Volatility-Based Position Sizing ──────────────────────────────

def get_position_size(pair: str, base_amount: float, prices: list[float]) -> float:
    if not config.USE_VOLATILITY_SIZING:
        return base_amount

    vol = calculate_volatility(prices, config.VOLATILITY_PERIOD)

    if vol < 50:
        multiplier = 1.2
    elif vol < 100:
        multiplier = 1.0
    elif vol < 150:
        multiplier = 0.75
    else:
        multiplier = 0.5

    size = round(min(max(base_amount * multiplier, config.MIN_TRADE_USD), base_amount * 1.5), 2)
    log.log_sizing(pair, f"${size:.2f} (volatility: {vol:.0f}%, multiplier: {multiplier}x)")
    return size


# ── Upgrade 6: Weekly Rebalance ───────────────────────────────────────────────

def run_rebalance():
    if not config.USE_REBALANCE:
        return

    log.log_rebalance(f"Running rebalance check (max hold: {config.MAX_HOLD_DAYS}d, "
                      f"min gain: {config.MIN_GAIN_TO_HOLD_PCT}%)…")

    balances   = get_paper_balances() if config.PAPER_TRADING else {}
    held_coins = [k for k in balances if k != "USD"]

    current_prices: dict[str, float] = {}
    for coin in held_coins:
        pair = f"{coin}-USD"
        try:
            data                 = cb.get_candles(pair, limit=5)
            current_prices[pair] = data["closes"][-1]
        except Exception as e:
            log.log_warning(f"Could not fetch price for {pair}: {e}")

    stale = get_stale_positions(config.MAX_HOLD_DAYS, config.MIN_GAIN_TO_HOLD_PCT, current_prices)

    if not stale:
        log.log_rebalance("No stale positions found.")
        return

    for pair in stale:
        price = current_prices.get(pair, 0.0)
        if price <= 0:
            continue
        if config.PAPER_TRADING:
            result = paper_sell(pair, price, "Rebalance: stale position")
            log.log_rebalance(f"Exiting {pair} — {result}")
        else:
            coin   = pair.split("-")[0]
            bal    = balances.get(coin, 0.0)
            result = cb.place_market_sell(pair, bal)
            log.log_rebalance(f"Live exit {pair}: {result}")
            _clear_live_entry_price(coin)

    log.log_rebalance(f"Rebalance complete — {len(stale)} position(s) exited.")


# ── Upgrade B: Pending limit order management ────────────────────────────────

def _check_pending_orders(current_prices: dict):
    """Check pending limit orders each cycle — fill or cancel on timeout."""
    if not _pending_orders:
        return

    now       = time.time()
    to_remove = []

    for order_key, order in list(_pending_orders.items()):
        pair        = order["pair"]
        coin        = order["coin"]
        limit_price = order["limit_price"]
        elapsed     = now - order["placed_at"]
        current_p   = current_prices.get(pair, 0.0)

        if order["is_paper"]:
            if order["side"] == "BUY":
                if current_p > 0 and current_p <= limit_price * 1.001:
                    result = paper_buy(pair, order["usd_amount"], limit_price)
                    log.log_info(f"[{pair}] ✅ [PAPER] Limit BUY filled @ ${limit_price:,.4f} | {result}")
                    to_remove.append(order_key)
                elif elapsed >= config.LIMIT_ORDER_TIMEOUT_SECONDS:
                    log.log_info(f"[{pair}] ⏱️ [PAPER] Limit BUY expired (${limit_price:,.4f})")
                    to_remove.append(order_key)
            else:  # SELL
                if current_p > 0 and current_p >= limit_price * 0.999:
                    balances = get_paper_balances()
                    if balances.get(coin, 0.0) > 0:
                        result = paper_sell(pair, limit_price, order.get("reason", "Limit sell"))
                        log.log_info(f"[{pair}] ✅ [PAPER] Limit SELL filled @ ${limit_price:,.4f} | {result}")
                    to_remove.append(order_key)
                elif elapsed >= config.LIMIT_ORDER_TIMEOUT_SECONDS:
                    log.log_info(f"[{pair}] ⏱️ [PAPER] Limit SELL expired (${limit_price:,.4f})")
                    to_remove.append(order_key)
        else:
            if elapsed >= config.LIMIT_ORDER_TIMEOUT_SECONDS:
                try:
                    cb.cancel_order(order_key)
                    log.log_info(f"[{pair}] ⏱️ Limit {order['side']} expired — cancelled (id: {order_key})")
                except Exception as e:
                    log.log_warning(f"[{pair}] Cancel order {order_key} failed: {e}")
                to_remove.append(order_key)

    for key in to_remove:
        _pending_orders.pop(key, None)


# ── Main cycle ────────────────────────────────────────────────────────────────

def run_cycle():
    log.log_info(
        f"{'─'*55}\n"
        f"  Cycle: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"{'─'*55}"
    )

    # ── 1. Market regime ──────────────────────────────────────────────────────
    regime = check_market_regime()

    # ── 2. First pass: fetch candles for all pairs ────────────────────────────
    if config.USE_SCALP_MODE:
        log.log_info("⚡ SCALP MODE — 8 pairs, 5min candles, 0% fees")
        pairs_to_fetch = config.SCALP_PAIRS
    else:
        pairs_to_fetch = config.TRADING_PAIRS

    all_candles: dict[str, dict] = {}
    current_prices: dict[str, float] = {}

    for pair in pairs_to_fetch:
        try:
            data               = cb.get_candles(pair, limit=config.CANDLES_TO_FETCH)
            all_candles[pair]  = data
            current_prices[pair] = data["closes"][-1]
        except Exception as e:
            log.log_error(pair, f"Candle fetch failed — skipping: {e}")

    closes_map = {p: d["closes"] for p, d in all_candles.items()}

    # ── 3. Check pending limit orders ────────────────────────────────────────
    _check_pending_orders(current_prices)

    # ── 5. Select active pairs (momentum + sector filters) ────────────────────
    active_pairs = rank_pairs_by_momentum(closes_map)

    top_sectors: list[str] = []
    if config.USE_SECTOR_ROTATION:
        top_sectors    = get_top_sectors(closes_map)
        sector_pairs   = {p for s in top_sectors for p in config.COIN_SECTORS.get(s, [])}
        pre_filter_len = len(active_pairs)
        active_pairs   = [p for p in active_pairs if p in sector_pairs]
        log.log_sector(
            f"{len(active_pairs)} pairs pass momentum + sector filters "
            f"(was {pre_filter_len} after momentum)"
        )
    else:
        top_sectors = list(config.COIN_SECTORS.keys())

    # ── 4. Signal + execution pass ────────────────────────────────────────────
    for pair in active_pairs:
        if pair not in all_candles:
            continue
        try:
            _process_pair(pair, all_candles[pair], current_prices)
        except Exception as exc:
            log.log_error(pair, f"Unhandled error — skipping: {exc}")

    # ── 5. Summary ────────────────────────────────────────────────────────────
    if config.PAPER_TRADING:
        stale = (
            get_stale_positions(config.MAX_HOLD_DAYS, config.MIN_GAIN_TO_HOLD_PCT, current_prices)
            if config.USE_REBALANCE else []
        )
        print_summary(
            current_prices,
            regime=regime,
            active_count=len(active_pairs),
            top_sectors=top_sectors,
            stale_pairs=stale,
        )

    log.log_info(f"Cycle complete. Next check in {config.CHECK_INTERVAL_MINUTES} minutes.\n")


# ── Per-pair logic ────────────────────────────────────────────────────────────

def _process_pair(pair: str, candle_data: dict, current_prices: dict):
    closes  = candle_data["closes"]
    volumes = candle_data["volumes"]

    if not closes:
        log.log_error(pair, "No candle data — skipping")
        return

    current_price  = closes[-1]
    signal_closes  = closes[:-1]
    signal_volumes = volumes[:-1] if volumes else []
    coin           = pair.split("-")[0]

    if config.PAPER_TRADING:
        already_holding = is_holding(pair)
        entry_price     = get_entry_price(pair)
        entry_time_iso  = get_entry_time(pair)
        balances        = get_paper_balances()
    else:
        balances        = cb.get_account_balances()
        already_holding = balances.get(coin, 0.0) > 0
        entry_price     = _load_live_entry_prices().get(coin)
        entry_time_iso  = None

    # ── Skip if a limit order is already pending for this pair ────────────────
    if config.USE_LIMIT_ORDERS and (pair in _pending_orders or f"SELL_{pair}" in _pending_orders):
        log.log_hold(pair, "Limit order pending — skipping signal")
        return

    # ── Upgrade C: Position scoring exit ─────────────────────────────────────
    if already_holding and config.USE_POSITION_SCORING and entry_price:
        pnl_pct    = (current_price - entry_price) / entry_price
        hours_held = 0.0
        if entry_time_iso:
            try:
                held_secs  = (datetime.now() - datetime.fromisoformat(entry_time_iso)).total_seconds()
                hours_held = held_secs / 3600
            except Exception:
                pass
        vol_decimal = calculate_volatility(signal_closes, config.VOLATILITY_PERIOD) / 100.0
        score       = calculate_position_score(pnl_pct, hours_held, vol_decimal)

        if score < config.POSITION_EXIT_THRESHOLD:
            reason = (
                f"📊 POSITION SCORE EXIT: score={score:.2f} "
                f"(held {hours_held:.1f}h, PnL: {pnl_pct*100:.2f}%, "
                f"vol: {vol_decimal*100:.0f}%) — threshold: {config.POSITION_EXIT_THRESHOLD}"
            )
            log.log_sell(pair, reason)
            _handle_sell(pair, coin, current_price, {"reason": reason, "stop_loss": False}, balances, current_prices)
            return

    # ── Upgrade A: Order book fetch ───────────────────────────────────────────
    ob_data   = None
    ob_signal = None
    if config.USE_ORDER_BOOK_FILTER or config.USE_LIMIT_ORDERS:
        try:
            ob_data   = cb.get_order_book(pair, depth=config.ORDER_BOOK_DEPTH)
            ob_signal = check_order_book_imbalance(ob_data["imbalance"], config.ORDER_BOOK_IMBALANCE_THRESHOLD)
            if config.USE_ORDER_BOOK_FILTER:
                log.log_info(f"[{pair}] 📖 Order Book: {ob_signal} ({ob_data['imbalance']:.3f})")
        except Exception as e:
            log.log_warning(f"[{pair}] Order book fetch failed ({e}) — skipping filter")

    # ── Signal generation ─────────────────────────────────────────────────────
    signal   = get_signal(signal_closes, signal_volumes, pair, current_price, entry_price, already_holding, ob_signal, entry_time_iso)
    action   = signal["action"]
    reason   = signal["reason"]
    strength = signal.get("signal_strength", "NONE")

    if action == "HOLD":
        log.log_hold(pair, reason)
    elif action == "SELL":
        _handle_sell(pair, coin, current_price, signal, balances, current_prices)
    elif action == "BUY":
        if BUYS_SUSPENDED:
            log.log_hold(pair, f"BUY blocked — bear market ({reason})")
        else:
            _handle_buy(pair, coin, current_price, reason, strength, ob_data, balances, current_prices, signal_closes)


def _handle_sell(pair, coin, price, signal, balances, current_prices):
    reason    = signal["reason"]
    stop_loss = signal.get("stop_loss", False)

    if stop_loss:
        log.log_sell(pair, f"⛔ STOP LOSS — {reason}")
    else:
        log.log_sell(pair, reason)

    if balances.get(coin, 0.0) <= 0:
        log.log_info(f"[{pair}] No {coin} position to sell — skipping")
        return

    allowed, _ = check_trade("SELL", pair, 0.0, balances, current_prices)
    if not allowed:
        return

    coin_amount = balances[coin]

    if config.USE_LIMIT_ORDERS:
        limit_price = round(price * (1 + config.LIMIT_ORDER_OFFSET_PCT), 8)
        if config.PAPER_TRADING:
            _pending_orders[f"SELL_{pair}"] = {
                "side": "SELL", "pair": pair, "coin": coin,
                "limit_price": limit_price, "coin_amount": coin_amount,
                "placed_at": time.time(), "is_paper": True, "reason": reason,
            }
            log.log_info(f"[{pair}] 📋 [PAPER] Limit SELL queued @ ${limit_price:,.4f}")
        else:
            result   = cb.place_limit_sell(pair, coin_amount, limit_price)
            order_id = (result.get("success_response") or {}).get("order_id", f"sell_{pair}_{int(time.time())}")
            _pending_orders[order_id] = {
                "side": "SELL", "pair": pair, "coin": coin,
                "limit_price": limit_price, "coin_amount": coin_amount,
                "placed_at": time.time(), "is_paper": False, "reason": reason,
            }
            log.log_info(f"[{pair}] 📋 Limit SELL placed @ ${limit_price:,.4f} (id: {order_id})")
    else:
        if config.PAPER_TRADING:
            result = paper_sell(pair, price, reason)
            log.log_info(f"[{pair}] {result}")
        else:
            result = cb.place_market_sell(pair, coin_amount)
            log.log_info(f"[{pair}] Live sell placed: {result}")
            _clear_live_entry_price(coin)


def _handle_buy(pair, coin, price, reason, strength, ob_data, balances, current_prices, closes):
    if config.USE_PCT_SIZING:
        cash      = balances.get("USD", 0.0)
        base_size = cash * config.SIGNAL_CAPITAL_PCT
        base_size = max(base_size, config.MIN_TRADE_USD)
        base_size = min(base_size, config.DEFAULT_TRADE_USD * 3)
        if strength == "WEAK":
            base_size *= 0.5
    else:
        if strength == "WEAK":
            base_size = config.REDUCED_TRADE_USD * 0.5
        elif pair in config.REDUCED_PAIRS:
            base_size = config.REDUCED_TRADE_USD
        else:
            base_size = config.DEFAULT_TRADE_USD
    usd_to_spend = get_position_size(pair, base_size, closes)
    usd_to_spend = min(usd_to_spend, balances.get("USD", 0.0))

    if usd_to_spend < config.MIN_TRADE_USD:
        log.log_warning(
            f"[{pair}] Skipping — insufficient USD "
            f"(${usd_to_spend:.2f} < ${config.MIN_TRADE_USD:.2f})"
        )
        return

    allowed, _ = check_trade("BUY", pair, usd_to_spend, balances, current_prices)
    if not allowed:
        return

    if config.USE_LIMIT_ORDERS:
        ref_price   = (ob_data["best_ask"] if ob_data and ob_data.get("best_ask") else price)
        limit_price = round(ref_price * (1 - config.LIMIT_ORDER_OFFSET_PCT), 8)
        if config.PAPER_TRADING:
            _pending_orders[pair] = {
                "side": "BUY", "pair": pair, "coin": coin,
                "limit_price": limit_price, "usd_amount": usd_to_spend,
                "placed_at": time.time(), "is_paper": True,
            }
            log.log_buy(pair, f"📋 [PAPER] Limit BUY queued @ ${limit_price:,.4f} ({strength}) — {reason}")
        else:
            result   = cb.place_limit_buy(pair, usd_to_spend, limit_price)
            order_id = (result.get("success_response") or {}).get("order_id", f"buy_{pair}_{int(time.time())}")
            _pending_orders[order_id] = {
                "side": "BUY", "pair": pair, "coin": coin,
                "limit_price": limit_price, "usd_amount": usd_to_spend,
                "placed_at": time.time(), "is_paper": False,
            }
            log.log_buy(pair, f"📋 Limit BUY placed @ ${limit_price:,.4f} (id: {order_id}) — {reason}")
    else:
        log.log_buy(pair, f"{reason} — spending ${usd_to_spend:.2f} @ ${price:,.2f}")
        if config.PAPER_TRADING:
            result = paper_buy(pair, usd_to_spend, price)
            log.log_info(f"[{pair}] {result}")
        else:
            result = cb.place_market_buy(pair, usd_to_spend)
            log.log_info(f"[{pair}] Live buy placed: {result}")
            _save_live_entry_price(coin, price)


# ── Banner ────────────────────────────────────────────────────────────────────

def _flag(enabled: bool) -> str:
    return "✅ ON" if enabled else "⬜ OFF"

def _print_banner():
    mode = "PAPER TRADING" if config.PAPER_TRADING else "⚠️  LIVE TRADING"
    print(f"\n{'='*62}")
    print(f"  🕌  HALAL CRYPTO TRADING BOT — Phase 2")
    print(f"{'='*62}")
    print(f"  Mode:          {mode}")
    if config.USE_SCALP_MODE:
        print(f"  ⚡ SCALP MODE: {len(config.SCALP_PAIRS)} pairs, 0% fees (Coinbase One)")
    else:
        print(f"  Pairs:         {len(config.TRADING_PAIRS)} halal coins")
    print(f"  Interval:      every {config.CHECK_INTERVAL_MINUTES} minutes")
    print(f"  Strategy:      Dual RSI({config.RSI_FAST_PERIOD}/{config.RSI_SLOW_PERIOD}) + StochRSI({config.STOCH_RSI_PERIOD}) + EMA({config.EMA_FAST}/{config.EMA_SLOW}) + VWAP")
    print(f"  Stop loss:     {config.STOP_LOSS_PCT*100:.0f}% below entry")
    print(f"  Trade size:    ${config.DEFAULT_TRADE_USD:.0f} strong / ${config.REDUCED_TRADE_USD:.0f} weak signal")
    print(f"{'─'*62}")
    print(f"  Filters & Features:")
    print(f"    Market Regime Filter:   {_flag(config.USE_REGIME_FILTER)} (BTC {config.REGIME_LOOKBACK_DAYS}d lookback, {config.BEAR_MARKET_THRESHOLD*100:.0f}% bear threshold)")
    print(f"    Momentum Ranking:       {_flag(config.USE_MOMENTUM_RANKING)} (top {config.MAX_ACTIVE_PAIRS} of {len(config.TRADING_PAIRS)} pairs)")
    print(f"    VWAP Filter:            {_flag(config.USE_VWAP_FILTER)}")
    print(f"    Sector Rotation:        {_flag(config.USE_SECTOR_ROTATION)}")
    print(f"    Volatility Sizing:      {_flag(config.USE_VOLATILITY_SIZING)}")
    print(f"    Monthly Rebalance:      {_flag(config.USE_REBALANCE)} (every {config.REBALANCE_INTERVAL_DAYS} days)")
    print(f"    PCT Sizing:             {_flag(config.USE_PCT_SIZING)} ({config.SIGNAL_CAPITAL_PCT*100:.0f}% of cash, cap ${config.DEFAULT_TRADE_USD*3:.0f})")
    print(f"    Order Book Filter:      {_flag(config.USE_ORDER_BOOK_FILTER)} (depth={config.ORDER_BOOK_DEPTH}, threshold={config.ORDER_BOOK_IMBALANCE_THRESHOLD})")
    print(f"    Limit Orders:           {_flag(config.USE_LIMIT_ORDERS)} ({config.LIMIT_ORDER_OFFSET_PCT*100:.3f}% offset, {config.LIMIT_ORDER_TIMEOUT_SECONDS}s timeout)")
    print(f"    Position Scoring:       {_flag(config.USE_POSITION_SCORING)} (exit threshold: {config.POSITION_EXIT_THRESHOLD})")
    print(f"{'='*62}\n")


# ── Live entry price tracking ─────────────────────────────────────────────────

def _load_live_entry_prices() -> dict:
    try:
        with open(_LIVE_ENTRY_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_live_entry_price(coin: str, price: float):
    prices       = _load_live_entry_prices()
    prices[coin] = price
    with open(_LIVE_ENTRY_FILE, "w") as f:
        json.dump(prices, f, indent=2)


def _clear_live_entry_price(coin: str):
    prices = _load_live_entry_prices()
    prices.pop(coin, None)
    with open(_LIVE_ENTRY_FILE, "w") as f:
        json.dump(prices, f, indent=2)


if __name__ == "__main__":
    main()
