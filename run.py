"""Run the strategy, its ablations and a random-entry control; write REPORT.md + equity.png.

    python run.py                       # Yahoo demo data in data/
    python run.py --data path/to/dir    # your own NQ_5m.csv / ES_5m.csv (and optional NQ_1h.csv)
"""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ictbt import Config, Instrument, run
from ictbt.data import load_pair
from ictbt.metrics import breakdown, summarize

ROOT = Path(__file__).resolve().parent


def fmt(s: dict) -> dict:
    if s.get("trades", 0) == 0:
        return dict(trades=0)
    ci = s["expectancy_r_ci95"]
    return {
        "trades": s["trades"], "win %": f"{s['win_rate']:.0%}", "exp R": f"{s['expectancy_r']:+.2f}",
        "exp R 95% CI": f"[{ci[0]:+.2f}, {ci[1]:+.2f}]", "exp $": f"{s['expectancy_usd']:+.0f}",
        "PF": f"{s['profit_factor']:.2f}", "Sharpe": f"{s['sharpe_daily_ann']:.2f}",
        "max DD": f"{s['max_dd_pct']:.1%}", "net $": f"{s['total_pnl']:+,.0f}",
    }


def table(rows: dict) -> str:
    df = pd.DataFrame({k: fmt(v) for k, v in rows.items()}).T
    return df.to_markdown()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--random-seeds", type=int, default=200)
    args = ap.parse_args()

    nq, es, htf = load_pair(args.data)
    base = Config()
    res = run(nq, es, base, htf)
    S = summarize(res)

    # time-ordered halves (no parameters were fit, so both halves are out-of-sample for the rules)
    days = res.equity.index
    mid = days[len(days) // 2]
    halves = {}
    for name, m in [("first half", nq.index < mid), ("second half", nq.index >= mid)]:
        r = run(nq[m], es[m], base, htf)
        halves[name] = summarize(r)

    ablations = {
        "baseline (all rules)": S,
        "IFVG trigger only": summarize(run(nq, es, base.with_(triggers=("ifvg",)), htf)),
        "wick trigger only": summarize(run(nq, es, base.with_(triggers=("wick",)), htf)),
        "SMT trigger only": summarize(run(nq, es, base.with_(triggers=("smt",)), htf)),
        "confluence >= 1": summarize(run(nq, es, base.with_(min_confluence=1), htf)),
        "confluence >= 3": summarize(run(nq, es, base.with_(min_confluence=3), htf)),
        "no HTF bias / range filter": summarize(run(nq, es, base.with_(use_bias_filter=False), htf)),
        "min R:R 2.0": summarize(run(nq, es, base.with_(min_rr=2.0), htf)),
    }
    costs = {
        "zero costs": summarize(run(nq, es, base.with_(slippage_ticks_market=0, instrument=Instrument(commission_rt=0.0)), htf)),
        "baseline costs (1 tick, $1.50 RT)": S,
        "2 ticks slippage": summarize(run(nq, es, base.with_(slippage_ticks_market=2), htf)),
        "4 ticks slippage": summarize(run(nq, es, base.with_(slippage_ticks_market=4), htf)),
    }

    # random-entry control: same session, risk rules, stop and nearest-liquidity target logic
    rand = []
    rand_curves = []
    for seed in range(args.random_seeds):
        r = run(nq, es, base.with_(random_entries=True, use_bias_filter=False, random_seed=seed), htf)
        s = summarize(r)
        if s.get("trades"):
            rand.append(s["expectancy_r"])
            rand_curves.append(r.equity)
    rand = np.array(rand)
    pctile = float((rand < S["expectancy_r"]).mean()) if len(rand) else float("nan")

    # chart
    fig, ax = plt.subplots(figsize=(9, 4.2), dpi=130)
    rc = pd.concat(rand_curves, axis=1).ffill()
    ax.fill_between(rc.index, rc.quantile(0.05, axis=1), rc.quantile(0.95, axis=1), color="#bbb", alpha=0.5,
                    label="random entries, 5–95%")
    ax.plot(rc.index, rc.median(axis=1), color="#888", lw=1, label="random entries, median")
    ax.plot(res.equity.index, res.equity.values, color="#1f5fbf", lw=2, label="strategy")
    ax.axhline(base.starting_equity, color="#444", lw=0.6, ls=":")
    ax.set_title("NQ ICT strategy vs random-entry control (MNQ, $50k, 1% risk)")
    ax.set_ylabel("equity ($)")
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(ROOT / "equity.png")

    tr = res.trades
    trades_md = tr[["entry_time", "direction", "trigger", "confluence", "mode", "target_name", "exit_reason",
                    "contracts", "pnl", "r"]].assign(
        direction=lambda d: d.direction.map({1: "long", -1: "short"}),
        pnl=lambda d: d.pnl.round(0), r=lambda d: d.r.round(2)).to_markdown(index=False)

    span = f"{nq.index[0]:%Y-%m-%d} → {nq.index[-1]:%Y-%m-%d}"
    md = f"""# Backtest report — NQ (MNQ) ICT strategy with ES SMT

Data: {span}, {S['days']} trading days of 5-minute NQ and ES futures bars (Yahoo continuous front month),
HTF bias from 1-hour NQ bars. Rules: see RULES.md. Costs: {base.slippage_ticks_market} tick slippage on market
orders and stops, ${base.instrument.commission_rt:.2f}/contract round trip, targets fill only on a 1-tick trade-through,
same-bar stop+target resolves to the stop.

## Headline

{table({"strategy": S})}

* Trades: **{S['trades']}** over {S['days']} days ({S['trades_per_day']:.2f}/day). Signals generated: {res.signals}.
* Expectancy: **{S['expectancy_r']:+.2f} R** per trade (${S['expectancy_usd']:+.0f}), t-stat {S['t_stat_r']:.2f}.
* Sharpe (daily P&L, annualised): **{S['sharpe_daily_ann']:.2f}**. Max drawdown: **{S['max_dd_pct']:.1%}** (${S['max_dd_usd']:,.0f}).
* Random-entry control ({len(rand)} seeds): median expectancy {np.median(rand):+.2f} R, 5–95% range
  [{np.percentile(rand, 5):+.2f}, {np.percentile(rand, 95):+.2f}] R. The strategy beats **{pctile:.0%}** of random runs.

![equity](equity.png)

## Is it robust?

**Time split** (no parameters were fit to this data, so both halves are out-of-sample for the rules):

{table(halves)}

**Ablations** — remove or tighten one rule at a time:

{table(ablations)}

**Cost sensitivity:**

{table(costs)}

## Where the trades come from

By trigger:

{breakdown(tr, 'trigger').round(2).to_markdown()}

By bias mode:

{breakdown(tr, 'mode').round(2).to_markdown()}

By target:

{breakdown(tr, 'target_name').round(2).to_markdown()}

By exit:

{breakdown(tr, 'exit_reason').round(2).to_markdown()}

Signals rejected before entry: {dict(res.skips)}

## Caveats

* **Sample size.** {S['trades']} trades is far too few to separate edge from luck — look at the CI width
  on expectancy. Yahoo only serves ~60 days of 5m bars. Load 3–5 years of 1m data
  (Databento, FirstRate, or a broker export) with `python run.py --data <dir>` before drawing any conclusion.
* **No red-folder news levels** in this run (no calendar file supplied; see `Config.news_file`).
* **Continuous-contract rolls** are unadjusted in the Yahoo feed; a roll inside the window can create a fake gap.
* Limit-order entries at OTE (rule 7, second branch) are not modelled; all entries are market on the next bar.

## All trades

{trades_md}
"""
    (ROOT / "REPORT.md").write_text(md)
    print(table({"strategy": S}))
    print(f"\nrandom control median {np.median(rand):+.2f}R; strategy percentile {pctile:.0%}")
    print("\nhalves\n" + table(halves))
    print("\nablations\n" + table(ablations))
    print("\ncosts\n" + table(costs))
    print("\nskips", dict(res.skips))


if __name__ == "__main__":
    main()
