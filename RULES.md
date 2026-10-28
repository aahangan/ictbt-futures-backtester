# Committed rules

Each discretionary step of the playbook, written as an exact rule. Parameter names refer to
`ictbt/config.py`. All defaults were fixed before results were looked at. One change was made
after the first run: a key open now counts only on a *retest*. That fixed a bug (the 9:30 bar
always "touches" its own open), not a tuning choice.

Base timeframe: 5-minute bars, timestamped at bar open. A bar is known only at its close.
Decisions are made at a bar's close, and orders fill at the next bar's open.

## Pre-trade

**1. HTF bias (daily → 4H → 1H).** Bars are built from 1H data and anchored at the 18:00 ET Globex open.
* FVG (3 candles): bullish if `low[i] > high[i-2]`, zone `[high[i-2], low[i]]`. Bearish is the mirror.
* Each bar that trades into a tracked gap is classified:
  * *disrespected*: closes beyond the far edge (a bull gap closes below its bottom). The gap is removed.
  * *respected*: traded into the gap but closed back on the gap's own side (a bull gap closes above its top). Each gap counts once.
* Bull points = respected bull gaps + disrespected bear gaps. Bear points are the mirror.
* Per-timeframe bias = sign(bull − bear) over the last `bias_lookback_bars` = 10 bars of that timeframe.
* Overall bias: **trend** if ≥ 2 of 3 timeframes agree and none disagree. Otherwise **range** (step 1a: "can't tell").
* A timeframe's bias becomes usable only once its bar has fully closed.

**1a. Range.** Equilibrium = midpoint of the high/low of the last 16 completed 15m bars (4 hours).
In range mode: long only if close < EQ (discount), short only if close > EQ (premium).

**2. Draws on liquidity (targets).** Each level stays *live* until price trades through it:
* Asia high/low (20:00–24:00 ET), London high/low (02:00–05:00), prior NY RTH high/low (09:30–16:00), prior-day high/low.
  Each level is added only after its window closes and expires after one more trading day.
* Equal highs/lows: two unswept confirmed swing points within 0.10 ATR of each other.
* Unfilled 1H FVGs from the last 5 days. The target is the gap's near edge. A gap counts as filled once price trades through the whole zone.
* Red-folder news highs/lows: high/low of the first 30 minutes after each event, kept for 3 days.
  These need a calendar file (`news_file`), so they are **off by default**.

**3. Key levels (entry zones)**, checked on every bar:
* **OTE**. Long: take the last confirmed swing high H and the latest confirmed swing low L before it.
  The zone is `H − [0.886, 0.618]·(H − L)`. The leg must span ≥ 2 ATR and becomes invalid once price trades below L.
  Shorts are the mirror.
* **Sweep (rejection wick)**. A bar trades through a confirmed swing low or a live session low and closes back above it. Shorts are the mirror.
  Swing = fractal pivot, `swing_k = 3` bars on each side. It is confirmed 3 bars after the pivot.
* **Key opens**: daily (18:00 ET), 09:30, and 10:00. A later bar must retest the open within 0.25 ATR.
* **HTF FVG**: the bar trades into an unfilled 1H FVG that agrees with the trade direction.

**4. Confluence** = number of *distinct* level types (OTE, sweep, key open, HTF FVG) touched during the last
6 bars (30 min), in the trade direction. The minimum is **2**.

## Entry

**5–6. Trigger** on the current bar, in an allowed direction. The first trigger that fires is used:
* **IFVG**: an opposing LTF FVG (≥ 0.10 ATR) formed within the last 12 bars. This bar is the first to close
  through its far edge, and it is a displacement candle (body ≥ 60% of range, in the trade direction).
* **Wick**: the bar's low is inside the OTE zone and its lower wick is ≥ 50% of the bar's range. Shorts are the mirror.
* **SMT**. Bullish: on bar s, one index makes a new 12-bar low and the other does not (NQ vs ES, either way round).
  The trigger fires when a bar within the next 3 bars closes above bar s's high. Each SMT bar is used once.

**7. Entry**: market order, filled at the next bar's open + 1 tick of slippage. Limit entries at OTE are not modelled.

**8. Stop**: beyond the extreme of the last 6 bars (the reaction low/high), plus a 2-tick buffer.
The trade is skipped if the stop is wider than 4 ATR.

**9. Target**: the **nearest** live draw beyond the entry. If that draw is < 1R away, the trade is **skipped**.
It never reaches for a farther target.

Exits: target is a limit order that fills only if price trades 1 tick through it. Stop is a market order: 1 tick of slippage, and it fills at the open if price gaps through.
If the stop and target are both inside one bar, the stop is assumed. Any open position is flattened at 15:55.

## Risk

10. Max 2 trades/day. 11. Win trade 1 → done. 12. Lose trade 1 → trade 2 at 50% risk.
13. Lose trade 2 → done. 14. Fills must land in 09:30–11:00 ET. 15. Risk 1% of *current* equity.
Sizing is in MNQ ($2/pt): `contracts = floor(risk$ / ((stop distance + slippage)·$2 + $1.50 commission))`.
The trade is skipped if this comes to 0 contracts.
