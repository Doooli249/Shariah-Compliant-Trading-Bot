# 🕌 Halal Crypto Trading Bot

A fully automated, Shariah-compliant cryptocurrency trading bot. Runs locally on your Mac as a terminal process. Trades 20 pre-screened halal coins on Coinbase using RSI + MACD signals with a built-in stop loss.

**Default mode: Paper Trading** (fake money). You control when to go live.

---

## Halal Compliance Built In

The bot enforces these rules before every single trade — they cannot be bypassed by config:

- ✅ Spot trading only (no margin, no leverage, no futures, no derivatives)
- ✅ No shorting — BUY and SELL only
- ✅ No interest-bearing or staking interactions
- ✅ Only the 20 pre-screened halal coins (see `config.py`)
- ✅ No single coin can exceed 25% of your portfolio
- ✅ No averaging down — won't buy a coin you already hold
- ✅ 8% stop loss — exits automatically if a trade moves against you

Every blocked trade is logged with `🚫 HALAL BLOCK:` and a reason.

> Note: Always verify coin eligibility with a qualified Islamic finance scholar. Rulings can vary by region and madhab.

---

## Step 1 — Install Python

Download and install **Python 3.11 or later** from [python.org](https://www.python.org/downloads/).

Verify it works:
```bash
python3 --version
```
You should see something like `Python 3.11.x`.

---

## Step 2 — Download the Project

The files should already be in a folder on your computer. Open Terminal and navigate to that folder:

```bash
cd ~/cryptohalal-stock-bot
```

---

## Step 3 — Install Dependencies

```bash
pip install -r requirements.txt
```

This installs: pandas, requests, schedule, PyJWT, cryptography, colorlog.

---

## Step 4 — Get Coinbase API Keys

1. Go to [advanced.coinbase.com](https://advanced.coinbase.com)
2. Click **Settings** (top right) → **API** → **New API Key**
3. Permissions: check **"View"** and **"Trade"** ONLY
   - ⚠️ Do **NOT** check "Transfer" — the bot never needs it
4. Save your **API Key** and **API Secret** — you only see the secret once
5. Open `config.py` and paste them in:

```python
API_KEY    = "organizations/xxx/apiKeys/your-key-here"
API_SECRET = """-----BEGIN EC PRIVATE KEY-----
your
multiline
key
here
-----END EC PRIVATE KEY-----"""
```

The API Secret is a multi-line PEM key. Include the `-----BEGIN` and `-----END` lines exactly as shown.

---

## Step 5 — Run in Paper Mode (default)

Make sure `PAPER_TRADING = True` in `config.py` (it is by default). Then run:

```bash
python bot.py
```

You'll see the startup banner, then the bot will check all 20 pairs immediately. Example output:

```
============================================================
  🕌  HALAL CRYPTO TRADING BOT
============================================================
  Mode:          PAPER TRADING
  Pairs:         20 halal coins
  Interval:      every 60 minutes
  Strategy:      RSI(14) + MACD(12,26,9)
  Stop loss:     8% below entry
  Trend filter:  ON — buy only above 200 EMA
  Trade size:    $50 per signal
============================================================

[2026-04-20 10:00:01] [BTC-USD] HOLD: No signal (RSI: 52.3)
[2026-04-20 10:00:02] [ETH-USD] HOLD: No signal (RSI: 48.1)
[2026-04-20 10:00:03] [SOL-USD] 🟢 BUY: RSI oversold (33.2) + MACD bullish crossover
[2026-04-20 10:00:03] [SOL-USD] Bought 0.33445678 SOL @ $149.50 (spent $50.00)
...

============================================================
  📊  PAPER PORTFOLIO SUMMARY
============================================================
  Cash (USD):       $  950.00
  SOL     0.334456  @ $149.50       = $  50.01  (+$0.01)
────────────────────────────────────────────────────────────
  Total value:      $ 1000.01
  P&L vs start:     +$0.01  (+0.0%)
============================================================
```

The bot then waits 60 minutes and runs again automatically. Press **Ctrl+C** to stop.

---

## Step 6 — Watch the Logs

**Terminal output**: coloured by signal type
- 🟢 Green = BUY signal
- 🔴 Red = SELL signal
- Gray = HOLD (no action)
- 🚫 Bold red = Halal compliance block

**Log file**: everything is also saved to `bot.log` (plain text, no colour codes).

**Trade history**: every paper trade is saved to `paper_trades.json`. You can open this file to review all your simulated trades and your running P&L.

---

## Step 7 — Go Live (when ready)

Only switch to live trading after reviewing at least **2 weeks of paper trading results**.

1. Check `paper_trades.json` — are the signals making sense?
2. Open `config.py` and make two changes:
   ```python
   PAPER_TRADING     = False
   DEFAULT_TRADE_USD = 25.0   # Start small — $25 per trade
   ```
3. Run the bot:
   ```bash
   python bot.py
   ```
4. You'll see a 10-second countdown. Press **Ctrl+C** to cancel at any time.
5. The bot will place real orders on Coinbase.

**Recommended**: start with `DEFAULT_TRADE_USD = 25` and monitor for a week before increasing.

---

## Signal Logic

**BUY** — all four must be true:
1. RSI below 35 (coin is oversold)
2. MACD line crosses above signal line (fresh bullish crossover)
3. You don't already hold this coin (no averaging down)
4. Price is above the 200-period EMA (not buying into a downtrend)

**SELL** — any one triggers:
1. RSI above 65 (coin is overbought)
2. MACD line crosses below signal line (fresh bearish crossover)
3. Price drops 8% below your entry price (stop loss)

**HOLD**: none of the above conditions met.

---

## Configuration

All settings are in `config.py`. The only things you should ever change:

| Setting | Default | Description |
|---------|---------|-------------|
| `PAPER_TRADING` | `True` | Switch to `False` for live trading |
| `DEFAULT_TRADE_USD` | `50.0` | USD per trade |
| `RSI_BUY_BELOW` | `35` | RSI threshold to consider buying |
| `RSI_SELL_ABOVE` | `65` | RSI threshold to consider selling |
| `STOP_LOSS_PCT` | `0.08` | 8% stop loss |
| `USE_TREND_FILTER` | `True` | Only buy above 200 EMA |
| `CHECK_INTERVAL_MINUTES` | `60` | How often to run (minutes) |
| `PAPER_STARTING_BALANCE` | `1000.0` | Virtual starting cash |

---

## File Overview

```
bot.py              — Main engine. Entry point.
config.py           — Your settings. Only file you need to edit.
indicators.py       — RSI + MACD calculations (pure functions)
signals.py          — Combines indicators into BUY/SELL/HOLD
coinbase_client.py  — Coinbase API calls (candles, orders, balances)
halal_guard.py      — Compliance enforcement (cannot be bypassed)
paper_trader.py     — Simulated trades with JSON state
logger.py           — Coloured terminal + file logging
paper_trades.json   — Auto-created: all paper trade history
bot.log             — Auto-created: full log archive
```

---

## VPS Deployment (Run 24/7 on a Server)

Running the bot on your Mac means it stops when you close the lid. A cheap VPS keeps it running continuously with no interruptions.

### Step 1 — Create a DigitalOcean Droplet

1. Sign up at [digitalocean.com](https://digitalocean.com)
2. Click **Create → Droplets**
3. Choose **Ubuntu 24.04 LTS**
4. Size: **Basic → Regular → $6/mo** (1 GB RAM, 1 vCPU — more than enough)
5. Choose the datacenter closest to you
6. Add your SSH key or choose a password
7. Click **Create Droplet**

### Step 2 — Connect and Set Up

```bash
# From your Mac terminal — replace with your droplet's IP
ssh root@YOUR_DROPLET_IP

# Install Python and pip
apt update && apt install -y python3 python3-pip

# Upload your bot files (run this from your Mac, not the server)
scp -r ~/cryptohalal-stock-bot root@YOUR_DROPLET_IP:/root/
```

### Step 3 — Install Dependencies on the Server

```bash
# On the server
cd /root/cryptohalal-stock-bot
pip3 install -r requirements.txt
```

### Step 4 — Run the Bot Continuously

```bash
# Start the bot in the background — survives SSH disconnect
nohup python3 bot.py > /dev/null 2>&1 &

# Confirm it's running
ps aux | grep bot.py
```

To stop it:
```bash
kill $(pgrep -f bot.py)
```

### Step 5 — Check Logs Remotely

```bash
# Tail the live log from your Mac
ssh root@YOUR_DROPLET_IP "tail -f /root/cryptohalal-stock-bot/bot.log"

# View last 50 lines
ssh root@YOUR_DROPLET_IP "tail -50 /root/cryptohalal-stock-bot/bot.log"

# Copy paper_trades.json to your Mac to review
scp root@YOUR_DROPLET_IP:/root/cryptohalal-stock-bot/paper_trades.json ~/Desktop/
```

### Step 6 — Auto-restart on Reboot (Recommended)

```bash
# On the server — create a systemd service
cat > /etc/systemd/system/halalbot.service << EOF
[Unit]
Description=Halal Crypto Trading Bot
After=network.target

[Service]
WorkingDirectory=/root/cryptohalal-stock-bot
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

systemctl enable halalbot
systemctl start halalbot

# Check status
systemctl status halalbot
```

With this setup the bot restarts automatically if it crashes or if the server reboots.

---

## Troubleshooting

**`401 Unauthorized`** — Your API key or secret is wrong. Re-paste from Coinbase.

**`No candle data returned`** — The pair may not be available on Coinbase in your region, or it's temporarily unavailable. The bot skips it and continues.

**Bot shows all HOLD** — This is normal. RSI + MACD only signal when the market is at an extreme. In a calm market, HOLD is the correct action.

**`paper_trades.json` missing** — Created automatically on the first paper trade.

---

## Halal Coin Rationale

| Coin | Why Included |
|------|-------------|
| BTC | Decentralized, no riba, store of value — accepted by majority of scholars |
| ETH | Smart contract utility — widely accepted (spot only, no staking) |
| SOL | Fast utility transactions — generally accepted |
| ADA | Ethical roadmap, transparent, peer-reviewed — generally accepted |
| DOT | Interoperability protocol — generally accepted |
| AVAX | DApp platform, real utility — generally accepted |
| LINK | Oracle data utility — generally accepted |
| ATOM | Cross-chain utility — generally accepted |
| XLM | Financial inclusion, cross-border payments — generally accepted |
| ALGO | **Official Shariyah Review Bureau (SRB) certification (2020)** |
| POL | ETH scaling utility — generally accepted |
| LTC | Payments, Bitcoin fork — generally accepted |
| XRP | Cross-border remittances — generally accepted |
| BCH | Payments, Bitcoin fork — generally accepted |
| NEAR | Smart contracts, utility — generally accepted |
| FIL | Decentralised storage utility — generally accepted |
| HBAR | Enterprise blockchain utility — generally accepted |
| APT | Modern smart contracts — generally accepted |
| ARB | ETH Layer 2 utility — generally accepted |
| GRT | Data indexing infrastructure — generally accepted |

**Never included**: DOGE, SHIB, or any meme coin. USDT, USDC, or any stablecoin. WBTC or any wrapped token. Any interest-bearing DeFi token.
