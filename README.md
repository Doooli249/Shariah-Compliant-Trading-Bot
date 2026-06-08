
# Shariah-Compliant Algorithmic Trading Bot

An algorithmic trading bot built for halal cryptocurrency trading,
deployed on a live DigitalOcean VPS.

## About
Most trading bots have no ethical screening — this one does. Built around
a custom 43-coin halal-screened universe that excludes cryptocurrencies
associated with interest-bearing products, gambling, or other haram
financial activities. Designed for spot-only trading with no leverage
or margin.

## Features
- Custom 43-coin Shariah-compliant screened universe
- Momentum breakout strategy on 15-minute candles
- Connects to Coinbase Advanced Trade API
- Deployed and running on DigitalOcean VPS (Ubuntu)
- Paper trading mode for strategy validation before live deployment
- Spot-only — no leverage, no margin, no shorting

## Stack
- Python
- Coinbase Advanced Trade API
- DigitalOcean VPS (Ubuntu)
- Pandas, NumPy

## Status
Paper trading — strategy validation in progress.
