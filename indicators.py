"""
HALAL CRYPTO TRADING BOT — TECHNICAL INDICATORS
=================================================
Pure calculation functions. No API calls, no side effects.
Input: list of closing prices (oldest first). Output: indicator values.
"""

import pandas as pd


def calculate_rsi(prices: list[float], period: int = 14) -> float | None:
    """
    Returns RSI (0-100) using Wilder's smoothing, or None if insufficient data.
    Requires at least period+1 data points.
    """
    if len(prices) < period + 1:
        return None

    series = pd.Series(prices, dtype=float)
    delta  = series.diff()

    gains  = delta.where(delta > 0, 0.0)
    losses = (-delta).where(delta < 0, 0.0)

    # Wilder's smoothing: EWM with alpha = 1/period
    avg_gain = gains.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    last_loss = avg_loss.iloc[-1]
    if last_loss == 0:
        return 100.0  # Pure gain period

    rs  = avg_gain.iloc[-1] / last_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return round(float(rsi), 2)


def calculate_macd(
    prices: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict | None:
    """
    Returns MACD dict with current and previous candle values for crossover
    detection, or None if insufficient data.

    Keys: macd, signal, histogram, macd_prev, signal_prev
    Requires at least slow + signal + 1 data points.
    """
    if len(prices) < slow + signal + 1:
        return None

    series      = pd.Series(prices, dtype=float)
    ema_fast    = series.ewm(span=fast,   adjust=False).mean()
    ema_slow    = series.ewm(span=slow,   adjust=False).mean()
    macd_line   = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram   = macd_line - signal_line

    return {
        "macd":        round(float(macd_line.iloc[-1]),   6),
        "signal":      round(float(signal_line.iloc[-1]), 6),
        "histogram":   round(float(histogram.iloc[-1]),   6),
        "macd_prev":   round(float(macd_line.iloc[-2]),   6),
        "signal_prev": round(float(signal_line.iloc[-2]), 6),
    }


def calculate_ema(prices: list[float], period: int) -> float | None:
    """
    Returns EMA for the given period, or None if insufficient data.
    Used for the 200-period trend filter.
    """
    if len(prices) < period:
        return None

    series = pd.Series(prices, dtype=float)
    ema    = series.ewm(span=period, adjust=False).mean()
    return round(float(ema.iloc[-1]), 8)


def calculate_bollinger_bands(
    prices: list[float],
    period: int = 20,
    std_dev: int = 2,
) -> dict | None:
    """
    Returns Bollinger Bands or None if insufficient data.
    Middle = period-SMA. Upper/lower = middle ± (std_dev * rolling std).
    Uses population std (ddof=0) to match standard charting tools.
    """
    if len(prices) < period:
        return None

    series = pd.Series(prices, dtype=float)
    middle = series.rolling(window=period).mean()
    std    = series.rolling(window=period).std(ddof=0)
    upper  = middle + (std_dev * std)
    lower  = middle - (std_dev * std)

    return {
        "upper":  round(float(upper.iloc[-1]),  8),
        "middle": round(float(middle.iloc[-1]), 8),
        "lower":  round(float(lower.iloc[-1]),  8),
    }


def calculate_btc_regime(
    btc_prices: list[float],
    lookback: int = 90,
    bear_threshold: float = 0.20,
) -> str:
    """
    Returns 'BULL', 'BEAR', or 'NEUTRAL' based on BTC price vs lookback days ago.
    BULL    — current price > price lookback days ago
    BEAR    — dropped >= bear_threshold (20%) vs lookback days ago
    NEUTRAL — down but not enough to qualify as BEAR
    """
    if len(btc_prices) < lookback + 1:
        return "NEUTRAL"
    current = btc_prices[-1]
    past    = btc_prices[-(lookback + 1)]
    change  = (current - past) / past
    if current > past:
        return "BULL"
    if change <= -bear_threshold:
        return "BEAR"
    return "NEUTRAL"


def calculate_momentum_score(prices: list[float], lookback: int = 30) -> float | None:
    """
    Percentage return over the last `lookback` candles.
    Formula: (prices[-1] - prices[-lookback]) / prices[-lookback] * 100
    """
    if len(prices) < lookback:
        return None
    return round((prices[-1] - prices[-lookback]) / prices[-lookback] * 100, 4)


def check_volume_confirmation(
    volumes: list[float],
    period: int = 20,
    multiplier: float = 1.5,
) -> bool:
    """
    Returns True if the latest candle volume exceeds multiplier * avg(prior period).
    """
    if not volumes or len(volumes) < period + 1:
        return False
    avg_vol = sum(volumes[-(period + 1):-1]) / period
    if avg_vol <= 0:
        return False
    return volumes[-1] > multiplier * avg_vol


def calculate_volatility(prices: list[float], period: int = 30) -> float:
    """
    Annualized volatility as a percentage.
    Formula: std(pct_changes over period) * sqrt(365) * 100
    """
    if len(prices) < period + 1:
        return 0.0
    series  = pd.Series(prices[-(period + 1):], dtype=float)
    returns = series.pct_change().dropna()
    vol     = float(returns.std()) * (365 ** 0.5) * 100
    return round(vol, 2)


def calculate_dynamic_breakout(prices: list[float], period: int = 20) -> dict | None:
    """
    Returns highest high (resistance) and lowest low (support) over last `period`
    candles, plus their midpoint.
    """
    if len(prices) < period:
        return None
    window     = prices[-period:]
    resistance = max(window)
    support    = min(window)
    return {
        "resistance": round(resistance, 8),
        "support":    round(support, 8),
        "midpoint":   round((resistance + support) / 2, 8),
    }


def macd_bullish_crossover(macd_data: dict) -> bool:
    """
    True ONLY on a fresh crossover: MACD was below signal last candle,
    now above signal this candle. Not simply 'MACD is above signal'.
    """
    return (
        macd_data["macd_prev"] < macd_data["signal_prev"]
        and macd_data["macd"]  > macd_data["signal"]
    )


def macd_bearish_crossover(macd_data: dict) -> bool:
    """
    True ONLY on a fresh crossover: MACD was above signal last candle,
    now below signal this candle.
    """
    return (
        macd_data["macd_prev"] > macd_data["signal_prev"]
        and macd_data["macd"]  < macd_data["signal"]
    )


def check_order_book_imbalance(imbalance: float, threshold: float = 0.15) -> str:
    """
    Classifies order book pressure from bid/ask volume imbalance.
    imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol), range -1 to +1
    """
    if imbalance > threshold:
        return "BUY_PRESSURE"
    if imbalance < -threshold:
        return "SELL_PRESSURE"
    return "NEUTRAL"


def calculate_rsi_fast_slow(
    prices: list[float],
    fast_period: int = 7,
    slow_period: int = 14,
) -> dict | None:
    """
    Returns fast and slow RSI with previous-candle values for crossover detection.
    Keys: fast, slow, fast_prev, slow_prev
    Requires at least slow_period + 2 data points.
    """
    if len(prices) < slow_period + 2:
        return None

    series = pd.Series(prices, dtype=float)
    delta  = series.diff()
    gains  = delta.where(delta > 0, 0.0)
    losses = (-delta).where(delta < 0, 0.0)

    def _rsi_at(avg_g: pd.Series, avg_l: pd.Series, idx: int) -> float:
        loss = avg_l.iloc[idx]
        if loss == 0:
            return 100.0
        return round(float(100.0 - (100.0 / (1.0 + avg_g.iloc[idx] / loss))), 2)

    ag_fast = gains.ewm(alpha=1 / fast_period,  min_periods=fast_period,  adjust=False).mean()
    al_fast = losses.ewm(alpha=1 / fast_period, min_periods=fast_period,  adjust=False).mean()
    ag_slow = gains.ewm(alpha=1 / slow_period,  min_periods=slow_period,  adjust=False).mean()
    al_slow = losses.ewm(alpha=1 / slow_period, min_periods=slow_period,  adjust=False).mean()

    return {
        "fast":      _rsi_at(ag_fast, al_fast, -1),
        "slow":      _rsi_at(ag_slow, al_slow, -1),
        "fast_prev": _rsi_at(ag_fast, al_fast, -2),
        "slow_prev": _rsi_at(ag_slow, al_slow, -2),
    }


def calculate_ema_crossover(
    prices: list[float],
    fast_period: int = 9,
    slow_period: int = 21,
) -> dict | None:
    """
    Returns fast/slow EMA values with crossover flags.
    Keys: fast, slow, fast_prev, slow_prev, bullish_cross, bearish_cross, aligned
    """
    if len(prices) < slow_period + 1:
        return None

    series   = pd.Series(prices, dtype=float)
    ema_fast = series.ewm(span=fast_period, adjust=False).mean()
    ema_slow = series.ewm(span=slow_period, adjust=False).mean()

    fc = round(float(ema_fast.iloc[-1]), 8)
    fp = round(float(ema_fast.iloc[-2]), 8)
    sc = round(float(ema_slow.iloc[-1]), 8)
    sp = round(float(ema_slow.iloc[-2]), 8)

    return {
        "fast":          fc,
        "slow":          sc,
        "fast_prev":     fp,
        "slow_prev":     sp,
        "bullish_cross": fp <= sp and fc > sc,
        "bearish_cross": fp >= sp and fc < sc,
        "aligned":       fc > sc,
    }


def calculate_stoch_rsi(
    prices: list[float],
    rsi_period: int = 14,
    k_period: int = 3,
    d_period: int = 3,
) -> dict | None:
    """
    Stochastic RSI: normalises RSI within its own high/low range.
    Returns {"k": float, "d": float, "k_prev": float, "d_prev": float}
    Values 0-100. K < 20 = oversold, K > 80 = overbought.
    """
    if len(prices) < rsi_period * 2 + k_period + d_period:
        return None

    series = pd.Series(prices, dtype=float)
    delta  = series.diff()
    gains  = delta.where(delta > 0, 0.0)
    losses = (-delta).where(delta < 0, 0.0)

    avg_gain   = gains.ewm(alpha=1 / rsi_period,  min_periods=rsi_period, adjust=False).mean()
    avg_loss   = losses.ewm(alpha=1 / rsi_period, min_periods=rsi_period, adjust=False).mean()
    rs         = avg_gain / avg_loss.replace(0.0, float("inf"))
    rsi_series = 100.0 - (100.0 / (1.0 + rs))

    stoch = rsi_series.rolling(window=rsi_period).apply(
        lambda x: (x[-1] - x.min()) / (x.max() - x.min()) * 100
        if x.max() != x.min() else 50.0,
        raw=True,
    )

    k_line = stoch.rolling(window=k_period).mean()
    d_line = k_line.rolling(window=d_period).mean()

    if pd.isna(k_line.iloc[-1]) or pd.isna(d_line.iloc[-1]):
        return None

    k_prev = float(k_line.iloc[-2]) if not pd.isna(k_line.iloc[-2]) else float(k_line.iloc[-1])
    d_prev = float(d_line.iloc[-2]) if not pd.isna(d_line.iloc[-2]) else float(d_line.iloc[-1])

    return {
        "k":      round(float(k_line.iloc[-1]), 2),
        "d":      round(float(d_line.iloc[-1]), 2),
        "k_prev": round(k_prev, 2),
        "d_prev": round(d_prev, 2),
    }


def calculate_vwap(
    closes: list[float],
    volumes: list[float],
    period: int = 20,
) -> float | None:
    """
    Volume-weighted average price approximation over the last `period` candles.
    Formula: sum(close * volume) / sum(volume)
    Price above VWAP = bullish. Price below VWAP = bearish.
    """
    if len(closes) < period or len(volumes) < period:
        return None

    c = closes[-period:]
    v = volumes[-period:]
    total_vol = sum(v)
    if total_vol <= 0:
        return None

    return round(sum(ci * vi for ci, vi in zip(c, v)) / total_vol, 8)
