"""
HALAL CRYPTO TRADING BOT — COINBASE ADVANCED TRADE CLIENT
===========================================================
Paper mode  → uses public (unauthenticated) endpoints for price data.
              No API key required. No real orders placed.

Live mode   → uses authenticated endpoints with HMAC-SHA256 (legacy key format:
              UUID key + base64 secret from advanced.coinbase.com → Settings → API).
"""

import hashlib
import hmac as _hmac
import json
import time

import requests

import config
from logger import log_warning

API_BASE = "https://api.coinbase.com"


# ── Auth (live mode only — HMAC-SHA256 legacy key format) ────────────────────

def _auth_headers(method: str, path: str, body: str = "") -> dict:
    """
    Builds HMAC-SHA256 auth headers for the legacy Advanced Trade key format
    (UUID key + base64 secret from advanced.coinbase.com).
    """
    timestamp = str(int(time.time()))
    message   = timestamp + method.upper() + path + body
    signature = _hmac.new(
        config.API_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return {
        "CB-ACCESS-KEY":       config.API_KEY,
        "CB-ACCESS-SIGN":      signature,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "Content-Type":        "application/json",
    }


# ── Request helpers ───────────────────────────────────────────────────────────

def _public_request(path: str, params: dict | None = None) -> dict:
    """Unauthenticated GET — used for paper trading price data."""
    url = f"{API_BASE}{path}"
    try:
        resp = requests.get(url, params=params, timeout=15)
    except requests.RequestException as e:
        raise ConnectionError(f"Network error: {e}") from e

    if resp.status_code == 429:
        log_warning("Rate limit (429) — waiting 60 seconds then retrying...")
        time.sleep(60)
        resp = requests.get(url, params=params, timeout=15)

    resp.raise_for_status()
    return resp.json()


def _authed_request(
    method: str,
    path: str,
    params: dict | None = None,
    body: dict | None = None,
) -> dict:
    """Authenticated request — used for live trading only."""
    body_str = json.dumps(body) if body else ""
    headers  = _auth_headers(method, path, body_str)
    url      = f"{API_BASE}{path}"

    try:
        resp = requests.request(
            method, url, headers=headers, params=params,
            data=body_str if body_str else None, timeout=15,
        )
    except requests.RequestException as e:
        raise ConnectionError(f"Network error: {e}") from e

    if resp.status_code == 401:
        raise PermissionError(
            "401 Unauthorized — check API_KEY and API_SECRET in config.py. "
            "Make sure the key has View + Trade permissions."
        )

    if resp.status_code == 429:
        log_warning("Rate limit (429) — waiting 60 seconds then retrying...")
        time.sleep(60)
        headers = _auth_headers(method, path, body_str)
        resp    = requests.request(
            method, url, headers=headers, params=params,
            data=body_str if body_str else None, timeout=15,
        )

    resp.raise_for_status()
    return resp.json()


# ── Public API ────────────────────────────────────────────────────────────────

def get_candles(pair: str, limit: int = 200) -> dict:
    """
    Returns {"closes": [float, ...], "volumes": [float, ...]} oldest→newest.
    Paper mode: public endpoint (no auth).
    Live mode:  authenticated endpoint.
    """
    params = {"granularity": config.CANDLE_GRANULARITY, "limit": str(limit)}

    if config.PAPER_TRADING:
        path = f"/api/v3/brokerage/market/products/{pair}/candles"
        data = _public_request(path, params)
    else:
        path = f"/api/v3/brokerage/products/{pair}/candles"
        data = _authed_request("GET", path, params=params)

    candles = sorted(data.get("candles", []), key=lambda c: int(c["start"]))
    return {
        "closes":  [float(c["close"])  for c in candles],
        "volumes": [float(c.get("volume", 0.0)) for c in candles],
    }


def get_daily_candles(pair: str, limit: int = 100) -> dict:
    """
    Always fetches ONE_DAY candles regardless of config.CANDLE_GRANULARITY.
    Used by the market regime filter.
    """
    params = {"granularity": "ONE_DAY", "limit": str(limit)}

    if config.PAPER_TRADING:
        path = f"/api/v3/brokerage/market/products/{pair}/candles"
        data = _public_request(path, params)
    else:
        path = f"/api/v3/brokerage/products/{pair}/candles"
        data = _authed_request("GET", path, params=params)

    candles = sorted(data.get("candles", []), key=lambda c: int(c["start"]))
    return {
        "closes":  [float(c["close"])  for c in candles],
        "volumes": [float(c.get("volume", 0.0)) for c in candles],
    }


def get_account_balances() -> dict[str, float]:
    """Live mode only — returns {currency: available_balance}."""
    data     = _authed_request("GET", "/api/v3/brokerage/accounts")
    balances = {}
    for account in data.get("accounts", []):
        currency  = account.get("currency", "")
        available = float(
            account.get("available_balance", {}).get("value", 0) or 0
        )
        if available > 0.0001:
            balances[currency] = available
    return balances


def place_market_buy(pair: str, usd_amount: float) -> dict:
    """Live mode only — market IOC buy using quote_size (USD amount)."""
    order_id = f"halal_{pair.replace('-', '_')}_{int(time.time())}"
    body = {
        "client_order_id":     order_id,
        "product_id":          pair,
        "side":                "BUY",
        "order_configuration": {
            "market_market_ioc": {"quote_size": str(round(usd_amount, 2))}
        },
    }
    return _authed_request("POST", "/api/v3/brokerage/orders", body=body)


def place_market_sell(pair: str, coin_amount: float) -> dict:
    """Live mode only — market IOC sell using base_size (coin amount)."""
    order_id = f"halal_{pair.replace('-', '_')}_{int(time.time())}"
    body = {
        "client_order_id":     order_id,
        "product_id":          pair,
        "side":                "SELL",
        "order_configuration": {
            "market_market_ioc": {"base_size": str(round(coin_amount, 8))}
        },
    }
    return _authed_request("POST", "/api/v3/brokerage/orders", body=body)


def get_order_book(pair: str, depth: int = 5) -> dict:
    """
    Returns top-of-book imbalance data.
    {"bid_volume", "ask_volume", "imbalance", "spread_pct", "best_bid", "best_ask"}
    imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol), range -1 to +1
    """
    params = {"product_id": pair, "limit": str(depth)}

    if config.PAPER_TRADING:
        path = "/api/v3/brokerage/market/product_book"
        data = _public_request(path, params)
    else:
        path = "/api/v3/brokerage/product_book"
        data = _authed_request("GET", path, params=params)

    pricebook  = data.get("pricebook", {})
    bids       = pricebook.get("bids", [])
    asks       = pricebook.get("asks", [])

    bid_vol  = sum(float(b.get("size", 0)) for b in bids[:depth])
    ask_vol  = sum(float(a.get("size", 0)) for a in asks[:depth])
    best_bid = float(bids[0]["price"]) if bids else 0.0
    best_ask = float(asks[0]["price"]) if asks else 0.0
    mid      = (best_bid + best_ask) / 2 if best_bid and best_ask else 0.0
    total    = bid_vol + ask_vol

    return {
        "bid_volume": round(bid_vol, 4),
        "ask_volume": round(ask_vol, 4),
        "imbalance":  round((bid_vol - ask_vol) / total, 4) if total > 0 else 0.0,
        "spread_pct": round((best_ask - best_bid) / mid * 100, 4) if mid > 0 else 0.0,
        "best_bid":   best_bid,
        "best_ask":   best_ask,
    }


def place_limit_buy(pair: str, usd_amount: float, limit_price: float) -> dict:
    """Live mode only — GTC limit buy using quote_size (USD)."""
    order_id = f"halal_{pair.replace('-', '_')}_{int(time.time())}"
    body = {
        "client_order_id":     order_id,
        "product_id":          pair,
        "side":                "BUY",
        "order_configuration": {
            "limit_limit_gtc": {
                "quote_size":  str(round(usd_amount, 2)),
                "limit_price": str(round(limit_price, 8)),
                "post_only":   False,
            }
        },
    }
    return _authed_request("POST", "/api/v3/brokerage/orders", body=body)


def place_limit_sell(pair: str, coin_amount: float, limit_price: float) -> dict:
    """Live mode only — GTC limit sell using base_size (coin amount)."""
    order_id = f"halal_{pair.replace('-', '_')}_{int(time.time())}"
    body = {
        "client_order_id":     order_id,
        "product_id":          pair,
        "side":                "SELL",
        "order_configuration": {
            "limit_limit_gtc": {
                "base_size":   str(round(coin_amount, 8)),
                "limit_price": str(round(limit_price, 8)),
                "post_only":   False,
            }
        },
    }
    return _authed_request("POST", "/api/v3/brokerage/orders", body=body)


def cancel_order(order_id: str) -> dict:
    """Live mode only — cancel a single open order."""
    return _authed_request(
        "POST",
        "/api/v3/brokerage/orders/batch_cancel",
        body={"order_ids": [order_id]},
    )
