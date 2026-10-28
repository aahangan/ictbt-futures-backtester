"""Bar loading. All timestamps become tz-naive America/New_York *bar-open* times.

A bar stamped t covers [t, t+bar) and is only knowable at t+bar. Everything
downstream relies on that convention.
"""
from pathlib import Path
from typing import Optional

import pandas as pd

NY = "America/New_York"
_TS_COLS = ("ts", "timestamp", "datetime", "date", "time")


def load_csv(path, tz: Optional[str] = None) -> pd.DataFrame:
    """Load OHLCV bars. `tz` is the zone of naive timestamps in the file (default: already NY or tz-aware)."""
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    ts_col = next(c for c in _TS_COLS if c in df.columns)
    raw = df[ts_col].astype(str)
    if raw.str.contains(r"(?:[+-]\d{2}:?\d{2}|Z)$").all():      # offsets present (may change with DST)
        ts = pd.to_datetime(raw, utc=True)
    else:
        ts = pd.to_datetime(raw).dt.tz_localize(tz or NY, ambiguous="infer", nonexistent="shift_forward")
    ts = ts.dt.tz_convert(NY).dt.tz_localize(None)
    out = df[["open", "high", "low", "close"]].astype(float)
    out["volume"] = df["volume"].astype(float) if "volume" in df.columns else 0.0
    out.index = pd.DatetimeIndex(ts, name="ts")
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def align(primary: pd.DataFrame, secondary: pd.DataFrame) -> tuple:
    """Inner-join two instruments on bar timestamps so SMT compares the same bars."""
    idx = primary.index.intersection(secondary.index)
    return primary.loc[idx].copy(), secondary.loc[idx].copy()


def bar_delta(df: pd.DataFrame) -> pd.Timedelta:
    return df.index.to_series().diff().mode().iloc[0]


def load_pair(data_dir, base="5m", htf="1h"):
    d = Path(data_dir)
    nq, es = align(load_csv(d / f"NQ_{base}.csv"), load_csv(d / f"ES_{base}.csv"))
    htf_path = d / f"NQ_{htf}.csv"
    nq_htf = load_csv(htf_path) if htf and htf_path.exists() else None
    return nq, es, nq_htf
