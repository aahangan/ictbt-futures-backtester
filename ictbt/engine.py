"""Event-driven backtest. One pass over bars; at the close of bar t the engine may only use
information knowable at that moment, and any order it places fills on bar t+1 or later.

Look-ahead guards, in one place:
  * swing pivots are used only k bars after the pivot (confirmation)
  * HTF bias / range / HTF FVGs are looked up by their completion time (`end`) <= bar close
  * session levels are added only after their window has closed
  * sizing, stop, target, R:R filter all use close[t]; the fill is open[t+1] + slippage
tests/test_lookahead.py checks this empirically by truncating the future.
"""
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from .config import Config
from . import features as F


def _mins(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


ASIA = (_mins("20:00"), _mins("24:00"))
LONDON = (_mins("02:00"), _mins("05:00"))
RTH = (_mins("09:30"), _mins("16:00"))
ETH_END = _mins("18:00")   # minutes < 18:00 belong to the same trading day's daytime


@dataclass
class Level:
    name: str
    price: float
    is_high: bool          # True: a buy-side draw (above price) / False: sell-side
    day: int               # trading-day ordinal it formed on
    live: bool = True


@dataclass
class Trade:
    day: pd.Timestamp
    n_today: int
    direction: int
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    entry: float
    stop: float
    target: float
    target_name: str
    contracts: int
    risk_usd: float
    trigger: str
    confluence: str
    mode: str
    exit_time: Optional[pd.Timestamp] = None
    exit: Optional[float] = None
    exit_reason: str = ""
    pnl: float = 0.0
    r: float = 0.0


@dataclass
class Result:
    trades: pd.DataFrame
    equity: pd.Series             # equity after each trading day
    skips: Counter
    cfg: Config
    signals: int = 0


class DayRisk:
    """Rules 10-13."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.results: List[float] = []

    def can_trade(self) -> bool:
        r = self.results
        if len(r) >= self.cfg.max_trades_per_day:
            return False
        if len(r) == 1 and r[0] > 0:        # won trade 1 -> done
            return False
        return True

    def size_mult(self) -> float:
        return self.cfg.second_trade_size if (self.results and self.results[0] <= 0) else 1.0


def run(nq: pd.DataFrame, es: pd.DataFrame, cfg: Config = Config(), htf_src: Optional[pd.DataFrame] = None,
        news: Optional[pd.DatetimeIndex] = None) -> Result:
    inst = cfg.instrument
    tick = inst.tick
    n = len(nq)
    idx = nq.index
    bar = (idx[1:] - idx[:-1]).to_series().mode().iloc[0]
    close_t = idx + bar
    o, h, l, c = (nq[k].values for k in ("open", "high", "low", "close"))
    esh, esl = es["high"].values, es["low"].values
    tod = (idx.hour * 60 + idx.minute).values
    tday = F.trading_day(idx)
    _, day_ord = np.unique(tday, return_inverse=True)
    A = F.atr(nq, cfg.atr_len)

    # ---- structure (causal by construction / confirmation delay) ----
    is_hi, is_lo = F.swing_points(nq, cfg.swing_k)
    ltf_fvgs = {}
    for g in F.detect_fvgs(nq, cfg.min_fvg_atr * A):
        ltf_fvgs.setdefault(g.idx, []).append(g)

    src = htf_src if htf_src is not None else nq
    src = src[src.index < idx[-1] + bar]          # never let the HTF feed run past the base data
    bias = F.asof_values(F.combined_bias(src, cfg.bias_tfs, cfg.bias_lookback_bars, cfg.htf_fvg_max_age,
                                         cfg.bias_min_agree), close_t, default=0)
    rng = F.resample(nq, cfg.range_tf)
    eq_s = pd.Series(((rng["high"].rolling(cfg.range_lookback_bars, min_periods=1).max()
                       + rng["low"].rolling(cfg.range_lookback_bars, min_periods=1).min()) / 2).values,
                     index=pd.DatetimeIndex(rng["end"].values))
    eq = F.asof_values(eq_s, close_t, default=np.nan)
    first = idx[0] - pd.Timedelta(days=cfg.htf_fvg_target_days)
    htf_gaps = [g for g in F.htf_fvgs_with_fill(F.resample(src, "1h")) if g["start"] >= first]

    N = cfg.smt_lookback
    pl_nq = pd.Series(l).rolling(N).min().shift(1).values
    pl_es = pd.Series(esl).rolling(N).min().shift(1).values
    ph_nq = pd.Series(h).rolling(N).max().shift(1).values
    ph_es = pd.Series(esh).rolling(N).max().shift(1).values
    smt_bull = ((l < pl_nq) & (esl >= pl_es)) | ((esl < pl_es) & (l >= pl_nq))
    smt_bear = ((h > ph_nq) & (esh <= ph_es)) | ((esh > ph_es) & (h <= ph_nq))

    news_ts = np.array(sorted(news.values)) if news is not None and len(news) else np.array([], "datetime64[ns]")

    rnd = np.random.default_rng(cfg.random_seed)
    w0, w1, flat = _mins(cfg.entry_window[0]), _mins(cfg.entry_window[1]), _mins(cfg.flat_time)
    daily_open_m = _mins(cfg.daily_open_time)

    # ---- state ----
    swings_hi, swings_lo = [], []          # dicts: price, idx, swept
    levels: List[Level] = []
    key_opens = {}
    acc = {}                               # running session extremes
    touches = {1: [set() for _ in range(n)], -1: [set() for _ in range(n)]}
    smt_used = set()
    equity = cfg.starting_equity
    trades: List[Trade] = []
    skips = Counter()
    signals = 0
    pos: Optional[Trade] = None
    pending: Optional[dict] = None
    risk = DayRisk(cfg)
    eq_by_day = {}

    def upd(key, hi, lo):
        a = acc.get(key)
        acc[key] = (hi, lo) if a is None else (max(a[0], hi), min(a[1], lo))

    def close_pos(t, price, reason):
        nonlocal pos, equity
        p = pos
        p.exit_time, p.exit, p.exit_reason = idx[t], price, reason
        gross = (price - p.entry) * p.direction * inst.point_value * p.contracts
        p.pnl = gross - inst.commission_rt * p.contracts
        p.r = p.pnl / p.risk_usd
        equity += p.pnl
        risk.results.append(p.pnl)
        trades.append(p)
        pos = None

    for t in range(n):
        new_day = t == 0 or day_ord[t] != day_ord[t - 1]
        if new_day:
            if t > 0:
                eq_by_day[pd.Timestamp(tday[t - 1])] = equity
                if "day" in acc:
                    hi, lo = acc["day"]
                    levels += [Level("PDH", hi, True, day_ord[t - 1]), Level("PDL", lo, False, day_ord[t - 1])]
            acc = {}
            key_opens = {}
            risk = DayRisk(cfg)
            pending = None
            levels = [lv for lv in levels if lv.live and day_ord[t] - lv.day <= 1]

        m = tod[t]
        # ---- add session levels whose window has closed before this bar opens ----
        if "asia" in acc and not (ASIA[0] <= m < ASIA[1]) and "asia_done" not in acc:
            hi, lo = acc["asia"]
            levels += [Level("AsiaH", hi, True, day_ord[t]), Level("AsiaL", lo, False, day_ord[t])]
            acc["asia_done"] = (0, 0)
        if "london" in acc and m >= LONDON[1] and m < ETH_END and "london_done" not in acc:
            hi, lo = acc["london"]
            levels += [Level("LondonH", hi, True, day_ord[t]), Level("LondonL", lo, False, day_ord[t])]
            acc["london_done"] = (0, 0)
        if "rth" in acc and m >= RTH[1] and m < ETH_END and "rth_done" not in acc:
            hi, lo = acc["rth"]
            levels += [Level("NYH", hi, True, day_ord[t]), Level("NYL", lo, False, day_ord[t])]
            acc["rth_done"] = (0, 0)
        if "daily" not in key_opens and (m == daily_open_m or (new_day and daily_open_m == ETH_END)):
            key_opens["daily"] = (o[t], t)
        if m == _mins("09:30"):
            key_opens["0930"] = (o[t], t)
        if m == _mins("10:00"):
            key_opens["1000"] = (o[t], t)

        # ---- 1. fill a pending order at this bar's open ----
        if pending is not None and pos is None:
            pd_ = pending
            pending = None
            if w0 <= m < w1 and risk.can_trade():
                d = pd_["dir"]
                fill = o[t] + d * cfg.slippage_ticks_market * tick
                if (fill - pd_["stop"]) * d <= 0 or (pd_["target"] - fill) * d <= 0:
                    skips["gapped_through"] += 1
                else:
                    pos = Trade(pd.Timestamp(tday[t]), len(risk.results) + 1, d, pd_["signal_time"], idx[t], fill,
                                pd_["stop"], pd_["target"], pd_["target_name"], pd_["contracts"], pd_["risk_usd"],
                                pd_["trigger"], pd_["confluence"], pd_["mode"])

        # ---- 2. manage open position on this bar ----
        if pos is not None:
            d = pos.direction
            if m >= flat and m < ETH_END or new_day:
                close_pos(t, o[t] - d * cfg.slippage_ticks_market * tick, "time")
            else:
                stop_hit = (l[t] <= pos.stop) if d > 0 else (h[t] >= pos.stop)
                tt = cfg.target_trade_through_ticks * tick
                tgt_hit = (h[t] >= pos.target + tt) if d > 0 else (l[t] <= pos.target - tt)
                if stop_hit and (not tgt_hit or cfg.same_bar_stop_first):
                    px = min(pos.stop, o[t]) if d > 0 else max(pos.stop, o[t])
                    close_pos(t, px - d * cfg.slippage_ticks_market * tick, "stop")
                elif tgt_hit:
                    px = max(pos.target, o[t]) if d > 0 else min(pos.target, o[t])
                    close_pos(t, px, "target")

        # ---- 3. bar t is now closed: update knowledge ----
        upd("day", h[t], l[t])
        if ASIA[0] <= m < ASIA[1]:
            upd("asia", h[t], l[t])
        if LONDON[0] <= m < LONDON[1]:
            upd("london", h[t], l[t])
        if RTH[0] <= m < RTH[1]:
            upd("rth", h[t], l[t])

        tol = cfg.key_open_tol_atr * A[t]
        # sweeps of confirmed swings and live session levels (rejection-wick level type)
        for sw in swings_lo:
            if not sw["swept"] and l[t] < sw["price"]:
                sw["swept"] = True
                if c[t] > sw["price"]:
                    touches[1][t].add("sweep")
        for sw in swings_hi:
            if not sw["swept"] and h[t] > sw["price"]:
                sw["swept"] = True
                if c[t] < sw["price"]:
                    touches[-1][t].add("sweep")
        for lv in levels:
            if not lv.live:
                continue
            if lv.is_high and h[t] > lv.price:
                lv.live = False
                if c[t] < lv.price:
                    touches[-1][t].add("sweep")
            elif not lv.is_high and l[t] < lv.price:
                lv.live = False
                if c[t] > lv.price:
                    touches[1][t].add("sweep")

        k = cfg.swing_k
        if t - k >= 0:
            if is_hi[t - k]:
                swings_hi.append(dict(price=h[t - k], idx=t - k, swept=False))
            if is_lo[t - k]:
                swings_lo.append(dict(price=l[t - k], idx=t - k, swept=False))
        horizon = t - int(cfg.eq_lookback_days * 24 * 60 / (bar.total_seconds() / 60))
        swings_hi = [s for s in swings_hi if s["idx"] >= horizon or not s["swept"]][-200:]
        swings_lo = [s for s in swings_lo if s["idx"] >= horizon or not s["swept"]][-200:]

        # key opens: only a *retest* counts -- the bar that sets the open trivially touches it
        for v, t_set in key_opens.values():
            if t > t_set and l[t] - tol <= v <= h[t] + tol:
                touches[1][t].add("key_open")
                touches[-1][t].add("key_open")

        # OTE zones off the most recent confirmed leg
        ote = {1: _ote_zone(swings_hi, swings_lo, 1, l, h, t, A[t], cfg),
               -1: _ote_zone(swings_hi, swings_lo, -1, l, h, t, A[t], cfg)}
        for d in (1, -1):
            z = ote[d]
            if z and l[t] <= z[1] and h[t] >= z[0]:
                touches[d][t].add("ote")

        now = close_t[t]
        live_gaps = [g for g in htf_gaps if g["start"] <= now and (g["filled"] is None or g["filled"] > now)
                     and now - g["start"] <= pd.Timedelta(days=cfg.htf_fvg_target_days)]
        if cfg.use_htf_fvg_confluence:
            for g in live_gaps:
                if l[t] <= g["top"] and h[t] >= g["bottom"]:
                    touches[1 if g["bull"] else -1][t].add("htf_fvg")

        # ---- 4. look for a new signal (only if flat, nothing pending, and allowed) ----
        if pos is not None or pending is not None or t + 1 >= n:
            continue
        m_next = tod[t + 1]
        if not (w0 <= m_next < w1) or day_ord[t + 1] != day_ord[t] or not risk.can_trade():
            continue

        dirs = []
        if cfg.random_entries:
            if rnd.random() < cfg.random_entry_prob:
                dirs = [(int(rnd.choice([1, -1])), "random", "", "random")]
        else:
            allowed = _allowed_dirs(bias[t], c[t], eq[t], cfg.use_bias_filter)
            for d in allowed:
                trig = _trigger(d, t, o, h, l, c, ltf_fvgs, ote[d], smt_bull if d > 0 else smt_bear, smt_used, cfg)
                if not trig:
                    continue
                lo_ = max(0, t - cfg.setup_window + 1)
                conf = set().union(*touches[d][lo_:t + 1])
                if trig == "wick":
                    conf.add("ote")
                if len(conf) < cfg.min_confluence:
                    skips["low_confluence"] += 1
                    continue
                mode = "trend" if bias[t] != 0 else "range"
                dirs.append((d, trig, "+".join(sorted(conf)), mode))
                break

        for d, trig, conf, mode in dirs:
            signals += 1
            lo_ = max(0, t - cfg.setup_window + 1)
            stop = (l[lo_:t + 1].min() - cfg.stop_buffer_ticks * tick) if d > 0 else \
                   (h[lo_:t + 1].max() + cfg.stop_buffer_ticks * tick)
            ref = c[t]
            dist = (ref - stop) * d
            if dist <= 0:
                skips["bad_stop"] += 1
                continue
            if dist > cfg.max_stop_atr * A[t]:
                skips["stop_too_wide"] += 1
                continue
            tname, tgt = _nearest_target(d, ref, levels, swings_hi, swings_lo, live_gaps, news_ts, now, idx, h, l,
                                         A[t], cfg)
            if tgt is None:
                skips["no_target"] += 1
                continue
            if (tgt - ref) * d < cfg.min_rr * dist:
                skips["rr_below_min"] += 1
                continue
            risk_usd = equity * cfg.risk_pct * risk.size_mult()
            per_contract = (dist + cfg.slippage_ticks_market * tick) * inst.point_value + inst.commission_rt
            contracts = int(risk_usd // per_contract)
            if contracts < 1:
                skips["size_zero"] += 1
                continue
            pending = dict(dir=d, stop=stop, target=tgt, target_name=tname, contracts=contracts,
                           risk_usd=contracts * per_contract, trigger=trig, confluence=conf, mode=mode,
                           signal_time=idx[t])
            break

    if pos is not None:
        close_pos(n - 1, c[-1], "eod_data")
    eq_by_day[pd.Timestamp(tday[-1])] = equity

    tdf = pd.DataFrame([t.__dict__ for t in trades])
    return Result(tdf, pd.Series(eq_by_day).sort_index(), skips, cfg, signals)


def _allowed_dirs(b, close, eq, use_bias):
    if not use_bias:
        return [1, -1]
    if b > 0:
        return [1]
    if b < 0:
        return [-1]
    if np.isnan(eq):
        return []
    return [1] if close < eq else ([-1] if close > eq else [])


def _ote_zone(sh, sl, d, l, h, t, atr_t, cfg):
    """Long: last confirmed swing high H and the latest confirmed swing low before it.
    Zone = H - [0.886, 0.618] * (H - L). Invalid once price trades below L."""
    if not sh or not sl:
        return None
    if d > 0:
        H = sh[-1]
        prior = [s for s in sl if s["idx"] < H["idx"]]
        if not prior:
            return None
        L = prior[-1]
        R = H["price"] - L["price"]
        if R < cfg.min_leg_atr * atr_t or l[H["idx"]:t + 1].min() < L["price"]:
            return None
        return (H["price"] - cfg.ote_high * R, H["price"] - cfg.ote_low * R)
    L = sl[-1]
    prior = [s for s in sh if s["idx"] < L["idx"]]
    if not prior:
        return None
    H = prior[-1]
    R = H["price"] - L["price"]
    if R < cfg.min_leg_atr * atr_t or h[L["idx"]:t + 1].max() > H["price"]:
        return None
    return (L["price"] + cfg.ote_low * R, L["price"] + cfg.ote_high * R)


def _trigger(d, t, o, h, l, c, ltf_fvgs, ote, smt, smt_used, cfg):
    rng = h[t] - l[t]
    if rng <= 0:
        return None
    if "ifvg" in cfg.triggers and t >= 1:
        body = abs(c[t] - o[t]) / rng
        if (c[t] - o[t]) * d > 0 and body >= cfg.ifvg_min_body:
            for j in range(max(2, t - cfg.ifvg_lookback), t):
                for g in ltf_fvgs.get(j, ()):
                    if d > 0 and not g.bull and c[t] > g.top >= c[t - 1]:
                        return "ifvg"
                    if d < 0 and g.bull and c[t] < g.bottom <= c[t - 1]:
                        return "ifvg"
    if "wick" in cfg.triggers and ote:
        if d > 0 and ote[0] <= l[t] <= ote[1] and (min(o[t], c[t]) - l[t]) / rng >= cfg.wick_min_frac:
            return "wick"
        if d < 0 and ote[0] <= h[t] <= ote[1] and (h[t] - max(o[t], c[t])) / rng >= cfg.wick_min_frac:
            return "wick"
    if "smt" in cfg.triggers:
        for s in range(max(0, t - cfg.smt_confirm_bars), t):
            if smt[s] and s not in smt_used and ((d > 0 and c[t] > h[s]) or (d < 0 and c[t] < l[s])):
                smt_used.add(s)
                return "smt"
    return None


def _nearest_target(d, ref, levels, sh, sl, gaps, news_ts, now, idx, h, l, atr_t, cfg):
    """Step 9: nearest live draw on liquidity strictly beyond the reference price."""
    cands = []
    for lv in levels:
        if lv.live and lv.is_high == (d > 0):
            cands.append((lv.name, lv.price))
    # equal highs / lows among unswept confirmed swings
    tol = cfg.eq_tol_atr * atr_t
    pool = [s for s in (sh if d > 0 else sl) if not s["swept"]]
    for i in range(len(pool)):
        for j in range(i + 1, len(pool)):
            if abs(pool[i]["price"] - pool[j]["price"]) <= tol:
                p = max(pool[i]["price"], pool[j]["price"]) if d > 0 else min(pool[i]["price"], pool[j]["price"])
                cands.append(("EQH" if d > 0 else "EQL", p))
    for g in gaps:
        edge = g["bottom"] if d > 0 else g["top"]
        cands.append(("HTF_FVG", edge))
    if len(news_ts):
        lo = np.datetime64(now - pd.Timedelta(days=cfg.news_persist_days))
        for ev in news_ts[(news_ts >= lo) & (news_ts <= np.datetime64(now))]:
            ev = pd.Timestamp(ev)
            m = (idx >= ev) & (idx < ev + pd.Timedelta(minutes=cfg.news_window_min)) & (idx + (idx[1] - idx[0]) <= now)
            if m.any():
                cands.append(("NEWS", h[m].max() if d > 0 else l[m].min()))
    beyond = [(nm, p) for nm, p in cands if (p - ref) * d > 0]
    if not beyond:
        return None, None
    return min(beyond, key=lambda x: (x[1] - ref) * d)
