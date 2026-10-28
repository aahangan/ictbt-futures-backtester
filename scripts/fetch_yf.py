"""Download free NQ/ES futures bars from Yahoo Finance into data/.

Yahoo limits intraday history (5m: ~60 days, 1h: ~730 days), so this is a demo
dataset. Re-running appends, so running this weekly grows the 5m history.
For real research, export 1m bars from Databento / FirstRate / your
broker and load them with ictbt.data.load_csv.
"""
import warnings
warnings.filterwarnings("ignore")
import pandas as pd
import yfinance as yf
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data"
OUT.mkdir(exist_ok=True)

for sym, name in [("NQ=F", "NQ"), ("ES=F", "ES")]:
    for interval, period in [("5m", "60d"), ("1h", "730d")]:
        df = yf.download(sym, period=period, interval=interval, progress=False, auto_adjust=False)
        df.columns = [c[0].lower() for c in df.columns]
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        df.index = df.index.tz_convert("America/New_York")
        df.index.name = "ts"
        path = OUT / f"{name}_{interval}.csv"
        if path.exists():   # append: Yahoo only serves a rolling window, so keep what we already have
            old = pd.read_csv(path, index_col=0)
            old.index = pd.to_datetime(old.index, utc=True).tz_convert("America/New_York")
            df = pd.concat([old, df])
            df = df[~df.index.duplicated(keep="last")].sort_index()
        df.to_csv(path)
        print(f"{path.name}: {len(df)} bars {df.index.min()} -> {df.index.max()}")
