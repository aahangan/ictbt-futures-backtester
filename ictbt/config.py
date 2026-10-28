"""Every tunable rule in one place. Defaults are committed *before* looking at results.

See RULES.md for the plain-English version of each parameter.
"""
from dataclasses import dataclass, field, replace
from typing import Optional, Tuple


@dataclass(frozen=True)
class Instrument:
    name: str = "MNQ"
    tick: float = 0.25
    point_value: float = 2.0          # $ per index point (MNQ=2, NQ=20)
    commission_rt: float = 1.50       # $ per contract round trip, incl. exchange/NFA fees


@dataclass(frozen=True)
class Config:
    instrument: Instrument = field(default_factory=Instrument)

    # --- account / risk (rules 10-15) ---
    starting_equity: float = 50_000.0
    risk_pct: float = 0.01                     # rule 15
    second_trade_size: float = 0.5             # rule 12
    max_trades_per_day: int = 2                # rule 10
    entry_window: Tuple[str, str] = ("09:30", "11:00")   # rule 14, fills must land inside [start, end)
    flat_time: str = "15:55"                   # anything still open is closed at market

    # --- fills / costs ---
    slippage_ticks_market: int = 1             # market entries, stops, time exits
    target_trade_through_ticks: int = 1        # limit target fills only if price trades 1 tick beyond
    same_bar_stop_first: bool = True           # if stop & target both inside one bar -> assume stop

    # --- structure ---
    swing_k: int = 3                           # fractal pivot: k bars each side; confirmed k bars later
    atr_len: int = 14
    min_fvg_atr: float = 0.10                  # LTF FVG must be >= 0.10 * ATR
    min_leg_atr: float = 2.0                   # OTE leg must span >= 2 ATR

    # --- HTF bias (step 1) ---
    bias_tfs: Tuple[str, ...] = ("1D", "4h", "1h")
    bias_lookback_bars: int = 10               # FVG respect/disrespect events counted over last N HTF bars
    htf_fvg_max_age: int = 60                  # HTF bars an FVG stays tracked
    bias_min_agree: int = 2                    # >=2 TFs agree and none oppose -> trend, else range

    # --- range mode (step 1a) ---
    range_tf: str = "15min"
    range_lookback_bars: int = 16              # dealing range = last 16 completed 15m bars (4h)

    # --- key levels / confluence (steps 3-4) ---
    ote_low: float = 0.618
    ote_high: float = 0.886
    key_open_tol_atr: float = 0.25             # "touching" a key open = within 0.25 ATR
    daily_open_time: str = "18:00"             # Globex open; set "00:00" for midnight open
    use_htf_fvg_confluence: bool = True
    min_confluence: int = 2                    # step 4: 2+ distinct level types
    setup_window: int = 6                      # bars (30m on 5m) a level touch stays valid for a trigger

    # --- triggers (step 6) ---
    triggers: Tuple[str, ...] = ("ifvg", "wick", "smt")
    ifvg_lookback: int = 12                    # opposing FVG must have formed in last N bars
    ifvg_min_body: float = 0.6                 # displacement: body / range
    wick_min_frac: float = 0.5                 # rejection: wick / range
    smt_lookback: int = 12                     # new N-bar low/high in one index but not the other
    smt_confirm_bars: int = 3                  # confirmation close beyond SMT bar within N bars

    # --- stops / targets (steps 8-9) ---
    stop_buffer_ticks: int = 2
    max_stop_atr: float = 4.0                  # skip if stop wider than 4 ATR
    min_rr: float = 1.0                        # skip if nearest draw < 1R away (we do NOT reach for a farther one)
    eq_tol_atr: float = 0.10                   # equal highs/lows tolerance
    eq_lookback_days: int = 3
    htf_fvg_target_days: int = 5
    news_file: Optional[str] = None            # CSV of red-folder event timestamps (ET)
    news_window_min: int = 30
    news_persist_days: int = 3

    # --- research controls ---
    use_bias_filter: bool = True
    random_entries: bool = False               # control: random bar/direction, same stops/targets/risk
    random_seed: int = 0
    random_entry_prob: float = 0.05

    def with_(self, **kw) -> "Config":
        return replace(self, **kw)
