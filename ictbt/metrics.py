import numpy as np
import pandas as pd


def summarize(res, start_equity=None) -> dict:
    tr = res.trades
    eq0 = start_equity or res.cfg.starting_equity
    days = res.equity
    daily_pnl = days.diff().fillna(days.iloc[0] - eq0) if len(days) else pd.Series(dtype=float)
    out = dict(trades=len(tr), days=len(days))
    if not len(tr):
        return out
    pnl, r = tr["pnl"].values, tr["r"].values
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    curve = eq0 + np.concatenate([[0], np.cumsum(pnl)])
    peak = np.maximum.accumulate(curve)
    dd = curve - peak
    sd = daily_pnl.std(ddof=1)
    rng = np.random.default_rng(0)
    boots = [rng.choice(r, len(r)).mean() for _ in range(2000)] if len(r) > 1 else [r.mean()]
    out.update(
        win_rate=float((pnl > 0).mean()),
        avg_win=float(wins.mean()) if len(wins) else 0.0,
        avg_loss=float(losses.mean()) if len(losses) else 0.0,
        expectancy_usd=float(pnl.mean()),
        expectancy_r=float(r.mean()),
        expectancy_r_ci95=(float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))),
        t_stat_r=float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))) if len(r) > 1 and r.std() > 0 else float("nan"),
        profit_factor=float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf"),
        total_pnl=float(pnl.sum()),
        return_pct=float(pnl.sum() / eq0),
        sharpe_daily_ann=float(daily_pnl.mean() / sd * np.sqrt(252)) if sd > 0 else float("nan"),
        max_dd_usd=float(dd.min()),
        max_dd_pct=float((dd / peak).min()),
        trades_per_day=len(tr) / max(len(days), 1),
    )
    return out


def breakdown(tr: pd.DataFrame, col: str) -> pd.DataFrame:
    if not len(tr):
        return pd.DataFrame()
    g = tr.groupby(col)
    return pd.DataFrame(dict(trades=g.size(), win_rate=g["pnl"].apply(lambda x: (x > 0).mean()),
                             exp_r=g["r"].mean(), pnl=g["pnl"].sum())).sort_values("trades", ascending=False)
