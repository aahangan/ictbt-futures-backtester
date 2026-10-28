"""Download multi-year CME 1m bars for NQ and ES from Databento into data_db/.

    pip install databento
    export DATABENTO_API_KEY=db-...
    python scripts/fetch_databento.py --start 2021-01-01 --end 2026-10-01          # prints cost, asks first
    python run.py --data data_db

Uses the continuous front-month (`NQ.c.0`, `ES.c.0`, rolled by calendar). Writes 1m bars, plus 5m and 1h
bars resampled from them, with bar-open timestamps in ET (the convention ictbt expects).
"""
import argparse
import os
from pathlib import Path

import databento as db
import pandas as pd

OUT = Path(__file__).resolve().parent.parent / "data_db"
SYMBOLS = {"NQ": "NQ.c.0", "ES": "ES.c.0"}


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    return agg.dropna(subset=["open"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--yes", action="store_true", help="skip the cost confirmation")
    a = ap.parse_args()

    client = db.Historical(os.environ["DATABENTO_API_KEY"])
    params = dict(dataset="GLBX.MDP3", symbols=list(SYMBOLS.values()), stype_in="continuous",
                  schema="ohlcv-1m", start=a.start, end=a.end)
    cost = client.metadata.get_cost(**params)
    print(f"Estimated cost: ${cost:.2f}")
    if not a.yes and input("Download? [y/N] ").strip().lower() != "y":
        return

    data = client.timeseries.get_range(**params).to_df()
    OUT.mkdir(exist_ok=True)
    for name, sym in SYMBOLS.items():
        df = data[data["symbol"] == sym][["open", "high", "low", "close", "volume"]].astype(float)
        df.index = df.index.tz_convert("America/New_York")   # ts_event = bar open
        df.index.name = "ts"
        df = df.sort_index()
        for tag, frame in [("1m", df), ("5m", resample(df, "5min")), ("1h", resample(df, "1h"))]:
            frame.to_csv(OUT / f"{name}_{tag}.csv")
        print(f"{name}: {len(df):,} 1m bars {df.index[0]} -> {df.index[-1]}")


if __name__ == "__main__":
    main()
