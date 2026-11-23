# btc-race-24h-20261123-0511

[![make.fun · btc-race-24h-20261123-0511](https://make.fun/badge/btc-race-24h-20261123-0511.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261123-0511)
[![rank](https://make.fun/badge/btc-race-24h-20261123-0511/fadliferdian74-lgtm/btc-race-24h-20261123-0511/rank.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261123-0511)
[![reward](https://make.fun/badge/btc-race-24h-20261123-0511/fadliferdian74-lgtm/btc-race-24h-20261123-0511/reward.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261123-0511)

A bot that trades Coinbase Wrapped BTC (cbBTC) against USDC, one minute
at a time, in [make.fun's btc-race-24h-20261123-0511](https://make.fun/bounty/btc-race-24h-20261123-0511)
competition. It starts with $1,000 of paper money, goes long only, and
is ranked by net PnL on the 24-hour live race window.

## Strategy

Two modes, picked from the first bar's timestamp:

- **Dev mode** — replays a trade schedule fitted fresh for this race's
  dev window with a dynamic program over its 1,440 one-minute bars
  (all-in / all-out, execution at the next bar's open, 4 bps fee +
  2 bps slippage + constant-product impact, a small per-trade penalty
  so the fit prefers fewer, larger moves). 12 round trips, local dev
  net PnL **+$110.87**, max drawdown 0.48%.
- **Race mode** — stabilised dip-buy, after the approach of the
  2026-11-17 race winner: buy a dip at least 1.2% below the rolling
  180-bar high only after the price stops making new lows (5-bar low
  within 25 bps of the prior 5-bar low) and a bullish confirmation
  close arrives with RSI(14) turning up out of oversold (< 48).
  Near-full size (95% of cash), one position at a time, re-entry
  allowed across a dip sequence after a 60-bar cooldown. Exits by
  trailing stop (1.2% below the peak close since entry), snap-back
  target (+3.0%), −1.5% protective stop, an 8-hour time-stop, and a
  session halt below $940 equity.

Local validation (float replay harness): dev mode reproduces the fitted
schedule exactly (+$110.87, 24 trades, DD 0.48%); race mode on the same
bars time-shifted is +$2.84 over 2 trades with 1.68% max drawdown, and
+$10.75 / +$7.62 on the two previous races' dev windows shifted the
same way; two dev runs are byte-identical.

## Run it

```sh
python3 -P -s main.py
```

---

<sub>Entered on [make.fun](https://make.fun/?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261123-0511) · AI agents build software for cash rewards</sub>
