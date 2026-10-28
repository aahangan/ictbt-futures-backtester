"""Pattern definitions. Each function documents *when* its output becomes knowable.

Convention: index i is a bar-open timestamp; bar i is known at the close of bar i.
"""
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

SESSION_SHIFT = pd.Timedelta(hours=6)   # 18:00 ET -> 00:00, so daily/4h bins start at the Globex open


# ---------- basics ----------

def atr(df: pd.DataFrame, n: int) -> np.ndarray:
    """Simple-average true range. atr[i] uses bars <= i (known at close of i)."""
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    return pd.Series(tr).rolling(n, min_periods=1).mean().values


def trading_day(ts: pd.DatetimeIndex) -> np.ndarray:
    """Futures trading day: a session starting 18:00 ET belongs to the next calendar date."""
    return (ts + SESSION_SHIFT).normalize().values


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample to a higher timeframe with bins anchored at the 18:00 ET Globex open.

    Adds `end` = bin start + rule: the earliest time the bar is complete. A bar may be
    used by a base bar only if base_close_time >= end.
    """
    src_bar = df.index.to_series().diff().mode().iloc[0]
    shifted = df.copy()
    shifted["last_open"] = shifted.index
    shifted.index = shifted.index + SESSION_SHIFT
    agg = shifted.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last",
                                      "last_open": "max"}).dropna()
    agg.index = agg.index - SESSION_SHIFT
    # Source bars can straddle bins (Yahoo's 1h feed mixes :00 and :30 bars), so a bin is only
    # complete once its last member bar has closed.
    agg["end"] = np.maximum(agg.index + pd.Timedelta(rule), agg["last_open"] + src_bar)
    agg = agg.drop(columns="last_open")
    # a partially-observed final bin is not complete; drop it so it can never leak
    last_data = df.index[-1] + (df.index[-1] - df.index[-2])
    return agg[agg["end"] <= last_data]


# ---------- swings ----------

def swing_points(df: pd.DataFrame, k: int):
    """Fractal pivots: high[i] strictly greater than the k highs on each side.

    Returns (is_high, is_low) boolean arrays indexed by pivot bar i. A pivot at i is only
    *confirmed* at the close of bar i+k -- the engine must use it no earlier.
    """
    h, l = df["high"].values, df["low"].values
    n = len(h)
    is_hi = np.zeros(n, bool)
    is_lo = np.zeros(n, bool)
    for i in range(k, n - k):
        win_h = np.concatenate([h[i - k:i], h[i + 1:i + k + 1]])
        win_l = np.concatenate([l[i - k:i], l[i + 1:i + k + 1]])
        is_hi[i] = h[i] > win_h.max()
        is_lo[i] = l[i] < win_l.min()
    return is_hi, is_lo


# ---------- fair value gaps ----------

@dataclass
class FVG:
    idx: int            # index of the 3rd candle; known at its close
    bull: bool
    bottom: float
    top: float
    end: Optional[pd.Timestamp] = None   # for HTF gaps: completion time of the 3rd candle


def detect_fvgs(df: pd.DataFrame, min_size: Optional[np.ndarray] = None) -> List[FVG]:
    """Three-candle gap. Bullish: low[i] > high[i-2] -> zone [high[i-2], low[i]].
    Bearish: high[i] < low[i-2] -> zone [high[i], low[i-2]]."""
    h, l = df["high"].values, df["low"].values
    out = []
    for i in range(2, len(h)):
        thr = 0.0 if min_size is None else min_size[i]
        if l[i] > h[i - 2] and l[i] - h[i - 2] >= thr:
            out.append(FVG(i, True, h[i - 2], l[i]))
        elif h[i] < l[i - 2] and l[i - 2] - h[i] >= thr:
            out.append(FVG(i, False, h[i], l[i - 2]))
    return out


# ---------- HTF bias (step 1) ----------

def fvg_bias(htf: pd.DataFrame, lookback: int, max_age: int) -> pd.Series:
    """Per HTF bar: +1 bullish / -1 bearish / 0 unclear, from FVG respect & disrespect.

    On each bar, every tracked FVG the bar trades into is classified:
      * disrespected  -> close beyond the far edge (bull gap: close < bottom). Gap is removed.
      * respected     -> traded into the gap but closed back on its own side
                         (bull gap: close > top). Counted once per gap.
    bull points = respected bull gaps + disrespected bear gaps; bear points mirror that.
    Bias = sign(bull - bear) over the last `lookback` HTF bars. Value at bar j is
    known at htf.end[j].
    """
    fvgs = detect_fvgs(htf)
    by_idx = {}
    for g in fvgs:
        by_idx.setdefault(g.idx, []).append(g)
    h, l, c = htf["high"].values, htf["low"].values, htf["close"].values
    active, respected_once = [], set()
    pts = np.zeros(len(htf))
    for j in range(len(htf)):
        score = 0
        keep = []
        for g in active:
            if j - g.idx > max_age:
                continue
            touched = l[j] <= g.top and h[j] >= g.bottom
            if g.bull:
                if c[j] < g.bottom:
                    score -= 1
                    continue
                if touched and c[j] > g.top and id(g) not in respected_once:
                    score += 1
                    respected_once.add(id(g))
            else:
                if c[j] > g.top:
                    score += 1
                    continue
                if touched and c[j] < g.bottom and id(g) not in respected_once:
                    score -= 1
                    respected_once.add(id(g))
            keep.append(g)
        active = keep + by_idx.get(j, [])   # gaps formed on bar j are tracked from j+1
        pts[j] = score
    rolled = pd.Series(pts).rolling(lookback, min_periods=1).sum().values
    return pd.Series(np.sign(rolled), index=pd.DatetimeIndex(htf["end"].values))


def combined_bias(htf_src: pd.DataFrame, tfs, lookback, max_age, min_agree) -> pd.Series:
    """Top-down bias: trend only if >= min_agree TFs agree and none oppose. Else 0 = range."""
    series = [fvg_bias(resample(htf_src, tf), lookback, max_age) for tf in tfs]
    allt = sorted(set().union(*[s.index for s in series]))
    frame = pd.concat([s[~s.index.duplicated(keep="last")].reindex(allt, method="ffill") for s in series], axis=1).fillna(0)
    bull = (frame > 0).sum(axis=1)
    bear = (frame < 0).sum(axis=1)
    out = np.where((bull >= min_agree) & (bear == 0), 1, np.where((bear >= min_agree) & (bull == 0), -1, 0))
    return pd.Series(out, index=frame.index)


def htf_fvgs_with_fill(htf: pd.DataFrame) -> List[dict]:
    """HTF FVGs with the time they appear (`start`) and the time they are fully filled (`filled`).
    Fully filled = price trades through the whole zone (bull gap: low <= bottom)."""
    out = []
    h, l = htf["high"].values, htf["low"].values
    ends = htf["end"].values
    for g in detect_fvgs(htf):
        filled = None
        for j in range(g.idx + 1, len(htf)):
            if (g.bull and l[j] <= g.bottom) or (not g.bull and h[j] >= g.top):
                filled = pd.Timestamp(ends[j])
                break
        out.append(dict(bull=g.bull, bottom=g.bottom, top=g.top,
                        start=pd.Timestamp(ends[g.idx]), filled=filled))
    return out


def asof_values(series: pd.Series, times: pd.DatetimeIndex, default=0) -> np.ndarray:
    """For each time t, the last series value whose index (availability time) <= t."""
    s = series[~series.index.duplicated(keep="last")].sort_index()
    pos = np.searchsorted(s.index.values, times.values, side="right") - 1
    vals = s.values
    return np.where(pos >= 0, vals[np.clip(pos, 0, None)], default)
