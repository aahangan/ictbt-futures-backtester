# Backtest report — NQ (MNQ) ICT strategy with ES SMT

Data: 2026-08-19 → 2026-10-28, 50 trading days of 5-minute NQ and ES futures bars (Yahoo continuous front month),
HTF bias from 1-hour NQ bars. Rules: see RULES.md. Costs: 1 tick slippage on market
orders and stops, $1.50/contract round trip, targets fill only on a 1-tick trade-through,
same-bar stop+target resolves to the stop.

## Headline

|          |   trades | win %   |   exp R | exp R 95% CI   |   exp $ |   PF |   Sharpe | max DD   |   net $ |
|:---------|---------:|:--------|--------:|:---------------|--------:|-----:|---------:|:---------|--------:|
| strategy |       23 | 30%     |   -0.13 | [-0.64, +0.48] |     -27 |  0.9 |    -0.44 | -6.2%    |    -614 |

* Trades: **23** over 50 days (0.46/day). Signals generated: 49.
* Expectancy: **-0.13 R** per trade ($-27), t-stat -0.42.
* Sharpe (daily P&L, annualised): **-0.44**. Max drawdown: **-6.2%** ($-3,244).
* Random-entry control (200 seeds): median expectancy -0.23 R, 5–95% range
  [-0.70, +0.54] R. The strategy beats **58%** of random runs.

![equity](equity.png)

## Is it robust?

**Time split** (no parameters were fit to this data, so both halves are out-of-sample for the rules):

|             |   trades | win %   |   exp R | exp R 95% CI   |   exp $ |   PF |   Sharpe | max DD   |   net $ |
|:------------|---------:|:--------|--------:|:---------------|--------:|-----:|---------:|:---------|--------:|
| first half  |       11 | 55%     |    0.32 | [-0.44, +1.13] |    +141 | 1.67 |     2.19 | -1.8%    |  +1,552 |
| second half |       12 | 8%      |   -0.54 | [-1.00, +0.33] |    -150 | 0.47 |    -2.74 | -3.9%    |  -1,794 |

**Ablations** — remove or tighten one rule at a time:

|                            |   trades | win %   |   exp R | exp R 95% CI   |   exp $ |   PF |   Sharpe | max DD   |   net $ |
|:---------------------------|---------:|:--------|--------:|:---------------|--------:|-----:|---------:|:---------|--------:|
| baseline (all rules)       |       23 | 30%     |   -0.13 | [-0.64, +0.48] |     -27 | 0.9  |    -0.44 | -6.2%    |    -614 |
| IFVG trigger only          |        8 | 25%     |   -0.14 | [-1.00, +1.07] |     -75 | 0.76 |    -0.68 | -3.5%    |    -602 |
| wick trigger only          |        5 | 20%     |   -0.42 | [-1.02, +0.75] |    -191 | 0.49 |    -1.65 | -2.8%    |    -956 |
| SMT trigger only           |       16 | 25%     |   -0.2  | [-0.85, +0.58] |     -48 | 0.83 |    -0.63 | -4.6%    |    -761 |
| confluence >= 1            |       31 | 26%     |   -0.18 | [-0.67, +0.38] |     -52 | 0.81 |    -1.02 | -7.9%    |  -1,598 |
| confluence >= 3            |        7 | 14%     |   -0.3  | [-1.00, +1.08] |    -134 | 0.63 |    -1.08 | -3.5%    |    -936 |
| no HTF bias / range filter |       33 | 36%     |    0.19 | [-0.38, +0.84] |    +114 | 1.44 |     1.68 | -8.2%    |  +3,760 |
| min R:R 2.0                |       13 | 23%     |   -0.04 | [-0.78, +0.97] |     +22 | 1.08 |     0.23 | -5.3%    |    +290 |

**Cost sensitivity:**

|                                   |   trades | win %   |   exp R | exp R 95% CI   |   exp $ |   PF |   Sharpe | max DD   |   net $ |
|:----------------------------------|---------:|:--------|--------:|:---------------|--------:|-----:|---------:|:---------|--------:|
| zero costs                        |       23 | 30%     |   -0.11 | [-0.64, +0.51] |     -22 | 0.92 |    -0.36 | -6.2%    |    -498 |
| baseline costs (1 tick, $1.50 RT) |       23 | 30%     |   -0.13 | [-0.64, +0.48] |     -27 | 0.9  |    -0.44 | -6.2%    |    -614 |
| 2 ticks slippage                  |       23 | 30%     |   -0.14 | [-0.65, +0.47] |     -30 | 0.89 |    -0.49 | -6.2%    |    -680 |
| 4 ticks slippage                  |       23 | 30%     |   -0.15 | [-0.66, +0.45] |     -35 | 0.87 |    -0.59 | -6.4%    |    -810 |

## Where the trades come from

By trigger:

| trigger   |   trades |   win_rate |   exp_r |   pnl |
|:----------|---------:|-----------:|--------:|------:|
| smt       |       13 |       0.31 |   -0.21 |  -854 |
| ifvg      |        8 |       0.25 |   -0.14 |  -205 |
| wick      |        2 |       0.5  |    0.47 |   445 |

By bias mode:

| mode   |   trades |   win_rate |   exp_r |   pnl |
|:-------|---------:|-----------:|--------:|------:|
| range  |       17 |       0.29 |   -0.11 |  -330 |
| trend  |        6 |       0.33 |   -0.18 |  -284 |

By target:

| target_name   |   trades |   win_rate |   exp_r |     pnl |
|:--------------|---------:|-----------:|--------:|--------:|
| EQL           |        7 |       0    |   -0.9  | -2086.5 |
| HTF_FVG       |        7 |       0.57 |    0.73 |  2239   |
| AsiaL         |        4 |       0.25 |    0.01 |   221   |
| LondonL       |        2 |       0.5  |   -0.01 |  -115   |
| AsiaH         |        1 |       1    |    0.19 |    94   |
| EQH           |        1 |       0    |   -1    |  -497   |
| NYH           |        1 |       0    |   -1.01 |  -469.5 |

By exit:

| exit_reason   |   trades |   win_rate |   exp_r |     pnl |
|:--------------|---------:|-----------:|--------:|--------:|
| stop          |       15 |        0   |   -1    | -5942.5 |
| target        |        6 |        1   |    2.02 |  5382.5 |
| time          |        2 |        0.5 |   -0.06 |   -54   |

Signals rejected before entry: {'no_target': 15, 'low_confluence': 19, 'rr_below_min': 10, 'stop_too_wide': 1}

## Caveats

* **Sample size.** 23 trades is far too few to separate edge from luck — look at the CI width
  on expectancy. Yahoo only serves ~60 days of 5m bars. Load 3–5 years of 1m data
  (Databento, FirstRate, or a broker export) with `python run.py --data <dir>` before drawing any conclusion.
* **No red-folder news levels** in this run (no calendar file supplied; see `Config.news_file`).
* **Continuous-contract rolls** are unadjusted in the Yahoo feed; a roll inside the window can create a fake gap.
* Limit-order entries at OTE (rule 7, second branch) are not modelled; all entries are market on the next bar.

## All trades

| entry_time          | direction   | trigger   | confluence                 | mode   | target_name   | exit_reason   |   contracts |   pnl |     r |
|:--------------------|:------------|:----------|:---------------------------|:-------|:--------------|:--------------|------------:|------:|------:|
| 2026-08-19 09:40:00 | short       | ifvg      | key_open+ote               | trend  | LondonL       | target        |           1 |   316 |  0.99 |
| 2026-08-25 10:40:00 | long        | smt       | key_open+sweep             | range  | AsiaH         | time          |           2 |    94 |  0.19 |
| 2026-08-26 10:10:00 | short       | smt       | key_open+sweep             | range  | AsiaL         | stop          |           4 |  -422 | -1    |
| 2026-08-31 09:40:00 | short       | ifvg      | key_open+ote+sweep         | trend  | AsiaL         | stop          |           2 |  -474 | -0.99 |
| 2026-09-02 09:45:00 | short       | wick      | key_open+ote               | trend  | HTF_FVG       | target        |           8 |   904 |  1.92 |
| 2026-09-03 10:35:00 | short       | ifvg      | htf_fvg+key_open+ote       | trend  | EQL           | stop          |           3 |  -468 | -1    |
| 2026-09-04 10:10:00 | short       | smt       | key_open+ote               | range  | AsiaL         | target        |           5 |  1485 |  3.05 |
| 2026-09-08 10:25:00 | long        | smt       | htf_fvg+key_open           | range  | HTF_FVG       | target        |           2 |   403 |  1.02 |
| 2026-09-10 10:10:00 | long        | smt       | key_open+ote               | range  | HTF_FVG       | target        |           5 |   652 |  1.32 |
| 2026-09-11 09:50:00 | short       | wick      | key_open+ote               | range  | HTF_FVG       | stop          |           6 |  -459 | -0.98 |
| 2026-09-17 10:45:00 | short       | smt       | key_open+ote               | range  | HTF_FVG       | stop          |           7 |  -480 | -1.02 |
| 2026-09-24 10:15:00 | short       | smt       | key_open+ote               | range  | EQL           | stop          |           6 |  -462 | -1.01 |
| 2026-09-24 10:45:00 | short       | ifvg      | htf_fvg+key_open+ote+sweep | range  | EQL           | stop          |           2 |  -247 | -0.99 |
| 2026-09-29 09:55:00 | long        | smt       | htf_fvg+key_open           | range  | NYH           | stop          |           3 |  -470 | -1.01 |
| 2026-10-01 10:35:00 | long        | smt       | htf_fvg+key_open           | range  | EQH           | stop          |           2 |  -497 | -1    |
| 2026-10-05 10:00:00 | short       | smt       | htf_fvg+key_open+sweep     | range  | EQL           | stop          |           3 |  -448 | -0.99 |
| 2026-10-05 10:35:00 | short       | ifvg      | key_open+ote               | range  | EQL           | stop          |           2 |  -182 | -0.98 |
| 2026-10-08 10:40:00 | short       | ifvg      | htf_fvg+key_open+ote       | range  | HTF_FVG       | target        |           4 |  1622 |  3.84 |
| 2026-10-13 10:20:00 | short       | smt       | htf_fvg+key_open           | range  | EQL           | time          |           4 |  -148 | -0.31 |
| 2026-10-19 10:35:00 | short       | ifvg      | key_open+sweep             | range  | AsiaL         | stop          |           2 |  -368 | -1    |
| 2026-10-21 10:10:00 | short       | ifvg      | htf_fvg+key_open+sweep     | range  | HTF_FVG       | stop          |           2 |  -404 | -1    |
| 2026-10-26 09:45:00 | short       | smt       | key_open+ote               | trend  | LondonL       | stop          |           2 |  -431 | -1    |
| 2026-10-26 10:35:00 | short       | smt       | htf_fvg+key_open+ote+sweep | trend  | EQL           | stop          |           1 |  -131 | -0.99 |
