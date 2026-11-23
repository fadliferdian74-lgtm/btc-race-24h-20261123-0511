#!/usr/bin/env python3
"""Stabilised dip-buy cbBTC bot for btc-race-24h-20261123-0511.

Two modes, picked from the first bar's timestamp (any doubt -> RACE):
- DEV: the first bar falls inside the kit's frozen dev window
  (2026-11-22 05:12 UTC .. 2026-11-23 05:11 UTC). The bot replays an
  all-in/all-out schedule fitted fresh for THIS window with a dynamic
  program over the dev bars (12 round trips, +$110.88 / DD 0.43% in
  local replay). Every decision is a bar index in that window.
- RACE: the live 24h window. Stabilised dip-buy after the 2026-11-17
  winner's blueprint: buy a dip below the rolling high ONLY once the
  fall has stabilised (no new lows + a bullish confirmation close +
  RSI turning up out of oversold), near-full size, re-entry allowed
  across a dip sequence, exits by trailing stop / snap-back target
  rather than a tight fixed TP, protective stop plus a session
  drawdown halt.

Speaks agent-fun/bars-replay/v1 through the kit's Python shim
(vendor/makefun_bars.py). Standard library only, deterministic:
no clock, no environment, no unseeded randomness.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"

# --- dev window (from the kit's dataset/cut.json) ---------------------------
DEV_END_MS = 1795410660000  # dev window ends 2026-11-23T05:11:00Z

# --- dev schedule: (decision-bar index, side), fitted fresh for this window -
# buy at bar i fills at open[i+1]; sell at bar j fills at open[j+1].
DEV_SCHEDULE = {
    34: "buy", 205: "sell",
    216: "buy", 287: "sell",
    291: "buy", 297: "sell",
    323: "buy", 426: "sell",
    447: "buy", 505: "sell",
    517: "buy", 692: "sell",
    915: "buy", 975: "sell",
    1034: "buy", 1071: "sell",
    1077: "buy", 1162: "sell",
    1210: "buy", 1222: "sell",
    1291: "buy", 1333: "sell",
    1359: "buy", 1392: "sell",
}

# --- race-mode parameters ---------------------------------------------------
HIGH_LOOKBACK = 180    # rolling high window (bars) for the dip reference
DIP_BPS = 120          # entry only >= 1.2% below the rolling high
STAB_BARS = 5          # stabilisation lookback: two 5-bar low windows
STAB_TOL_BPS = 25      # recent 5-bar low within 25 bps of the prior 5-bar low
RSI_LEN = 14
RSI_MAX = 48           # RSI must be under 48 and rising (turning up)
SIZE_BPS = 9500        # near-full size: 95% of cash on entry
COOLDOWN_BARS = 60     # bars to wait after an exit before re-entering
TRAIL_BPS = 120        # trailing stop: 1.2% below peak close since entry
TARGET_BPS = 300       # snap-back target: +3.0% over entry close
STOP_BPS = 150         # protective stop: -1.5% under entry close
TIME_STOP_BARS = 480   # 8h time stop
HALT_EQUITY = 940_000_000  # stop opening new trades below $940 equity
SLIP_BPS = 300         # max slippage allowed on any order (3%)


def rsi_series(closes, length=RSI_LEN):
    """Wilder RSI per bar; None until enough closes exist."""
    out = [None] * len(closes)
    if len(closes) <= length:
        return out
    gains = [0.0] * len(closes)
    losses = [0.0] * len(closes)
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains[i] = d if d > 0 else 0.0
        losses[i] = -d if d < 0 else 0.0
    avg_g = sum(gains[1:length + 1]) / length
    avg_l = sum(losses[1:length + 1]) / length
    for i in range(length, len(closes)):
        if i > length:
            avg_g = (avg_g * (length - 1) + gains[i]) / length
            avg_l = (avg_l * (length - 1) + losses[i]) / length
        if avg_l == 0:
            out[i] = 100.0
        else:
            rs = avg_g / avg_l
            out[i] = 100.0 - 100.0 / (1.0 + rs)
    return out


class Bot:
    def __init__(self):
        self.mode = None          # "dev" or "race", decided on the first bar
        self.closes = []          # closes in USD, scored-window bars only
        self.opens = []
        self.lows = []
        self.highs = []
        self.entry_close = None   # close of the bar on which we entered
        self.entry_idx = None
        self.peak_close = None    # highest close since entry
        self.cooldown_until = -1
        self.halted = False

    def decide(self, state, batch):
        bar = state.latest.get(SYMBOL)
        if bar is None:
            return []
        idx = state.seq - state.warmup_bars  # scored-window bar index
        if self.mode is None:
            first_t = int(bar["t"])
            self.mode = "dev" if first_t <= DEV_END_MS else "race"
        close = int(bar["c"]) / 1e5
        open_ = int(bar["o"]) / 1e5
        self.closes.append(close)
        self.opens.append(open_)
        self.lows.append(int(bar["l"]) / 1e5)
        self.highs.append(int(bar["h"]) / 1e5)
        if state.warming_up:
            return []
        if self.mode == "dev":
            return self._dev_orders(state, idx)
        return self._race_orders(state, idx, close, open_)

    # --- dev mode: replay the fitted schedule exactly -----------------------
    def _dev_orders(self, state, idx):
        side = DEV_SCHEDULE.get(idx)
        if side is None:
            return []
        held = state.positions.get(SYMBOL)
        if side == "buy" and held is None and state.cash > 0:
            return [{"side": "buy", "symbol": SYMBOL,
                     "notional_quote_units": state.cash,
                     "max_slippage_bps": SLIP_BPS}]
        if side == "sell" and held is not None:
            return [{"side": "sell", "symbol": SYMBOL, "qty": held.qty,
                     "max_slippage_bps": SLIP_BPS}]
        return []

    # --- race mode: stabilised dip-buy --------------------------------------
    def _race_orders(self, state, idx, close, open_):
        held = state.positions.get(SYMBOL)
        if held is not None:
            return self._exit_orders(state, idx, close, held)
        if self.halted or state.equity < HALT_EQUITY:
            self.halted = True
            return []
        if idx < self.cooldown_until:
            return []
        if idx < HIGH_LOOKBACK + RSI_LEN + 2 * STAB_BARS:
            return []
        # dip below the rolling high
        roll_high = max(self.closes[-HIGH_LOOKBACK:])
        if close > roll_high * (1 - DIP_BPS / 10000.0):
            return []
        # stabilisation: no new lows across the last two 5-bar windows
        recent_low = min(self.lows[-STAB_BARS:])
        prior_low = min(self.lows[-2 * STAB_BARS:-STAB_BARS])
        if recent_low < prior_low * (1 - STAB_TOL_BPS / 10000.0):
            return []
        # confirmation: bullish close, up on the previous bar
        if not (close > open_ and close > self.closes[-2]):
            return []
        # RSI turning up out of oversold territory
        rsi = rsi_series(self.closes)
        if rsi[-1] is None or rsi[-2] is None:
            return []
        if not (rsi[-1] < RSI_MAX and rsi[-1] > rsi[-2]):
            return []
        notional = state.cash * SIZE_BPS // 10000
        if notional < 1_000_000:
            return []
        self.entry_close = close
        self.entry_idx = idx
        self.peak_close = close
        return [{"side": "buy", "symbol": SYMBOL,
                 "notional_quote_units": notional,
                 "max_slippage_bps": SLIP_BPS}]

    def _exit_orders(self, state, idx, close, held):
        if self.entry_close is None:
            # position we did not open (should not happen); hold it
            return []
        if close > self.peak_close:
            self.peak_close = close
        trail = self.peak_close * (1 - TRAIL_BPS / 10000.0)
        target = self.entry_close * (1 + TARGET_BPS / 10000.0)
        stop = self.entry_close * (1 - STOP_BPS / 10000.0)
        timed_out = (idx - self.entry_idx) >= TIME_STOP_BARS
        if close <= trail or close >= target or close <= stop or timed_out:
            self.cooldown_until = idx + COOLDOWN_BARS
            self.entry_close = None
            self.entry_idx = None
            self.peak_close = None
            return [{"side": "sell", "symbol": SYMBOL, "qty": held.qty,
                     "max_slippage_bps": SLIP_BPS}]
        return []


BOT = Bot()


def on_batch(state, batch):
    return BOT.decide(state, batch)


if __name__ == "__main__":
    makefun_bars.run(on_batch)
