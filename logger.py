"""
HALAL CRYPTO TRADING BOT — LOGGER
===================================
All output goes through here. Terminal output is colored by signal type.
File output (bot.log) strips ANSI codes for clean archival.
"""

import logging
import re
from logging.handlers import RotatingFileHandler

import colorlog

# ANSI color codes embedded in messages (for terminal)
GREEN    = "\033[92m"
RED      = "\033[91m"
GRAY     = "\033[90m"
YELLOW   = "\033[93m"
BOLD_RED = "\033[1;91m"
RESET    = "\033[0m"

_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


class _StripAnsiFormatter(logging.Formatter):
    """File formatter that removes ANSI escape codes."""
    def format(self, record):
        msg = super().format(record)
        return _ANSI_RE.sub("", msg)


def _make_logger() -> logging.Logger:
    log = logging.getLogger("halal_bot")
    if log.handlers:
        return log  # Already configured (e.g. re-import)
    log.setLevel(logging.DEBUG)

    # Terminal handler — colorlog colors by level, messages may embed ANSI
    ch = colorlog.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(colorlog.ColoredFormatter(
        "%(log_color)s[%(asctime)s]%(reset)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors={
            "DEBUG":    "white",
            "INFO":     "white",
            "WARNING":  "yellow",
            "ERROR":    "red",
            "CRITICAL": "bold_red",
        },
        reset=True,
    ))

    # File handler — strip ANSI, rotate at 10 MB
    fh = RotatingFileHandler("bot.log", maxBytes=10 * 1024 * 1024, backupCount=3)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(_StripAnsiFormatter(
        "[%(asctime)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    log.addHandler(ch)
    log.addHandler(fh)
    return log


_log = _make_logger()


# ── Public helpers ────────────────────────────────────────────────────────────

def log_buy(pair: str, msg: str):
    _log.info(f"{GREEN}[{pair}] 🟢 BUY: {msg}{RESET}")

def log_sell(pair: str, msg: str):
    _log.info(f"{RED}[{pair}] 🔴 SELL: {msg}{RESET}")

def log_hold(pair: str, msg: str):
    _log.info(f"{GRAY}[{pair}] HOLD: {msg}{RESET}")

def log_block(pair: str, msg: str):
    _log.critical(f"{BOLD_RED}🚫 HALAL BLOCK: [{pair}] {msg}{RESET}")

def log_error(pair: str, msg: str):
    _log.error(f"[{pair}] ERROR: {msg}")

def log_info(msg: str):
    _log.info(msg)

def log_warning(msg: str):
    _log.warning(f"{YELLOW}{msg}{RESET}")

# ── Phase 2 log helpers ───────────────────────────────────────────────────────

BLUE = "\033[94m"
CYAN = "\033[96m"

def log_regime(msg: str):
    _log.info(f"{YELLOW}🐻 {msg}{RESET}")

def log_momentum(msg: str):
    _log.info(f"{BLUE}📊 {msg}{RESET}")

def log_sector(msg: str):
    _log.info(f"{YELLOW}🏆 {msg}{RESET}")

def log_sizing(pair: str, msg: str):
    _log.info(f"{CYAN}📐 [{pair}] {msg}{RESET}")

def log_rebalance(msg: str):
    _log.info(f"{YELLOW}🔄 {msg}{RESET}")

def log_breakout(pair: str, msg: str):
    _log.info(f"{GREEN}⚡ [{pair}] {msg}{RESET}")
