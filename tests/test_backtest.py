from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ictbt import Config, run
from ictbt import features as F
from ictbt.data import load_pair
from ictbt.engine import DayRisk

DATA = Path(__file__).resolve().parent.parent / "data"
COLS = ["signal_time", "entry_time", "direction", "entry", "stop", "target", "contracts", "exit_time", "exit", "pnl"]


@pytest.fixture(scope="module")
def pair():
    if not (DATA / "NQ_5m.csv").exists():
        pytest.skip("run scripts/fetch_yf.py first")
    return load_pair(DATA)


@pytest.fixture(scope="module")
def full(pair):
    return run(*pair[:2], Config(), pair[2])


# ---------- look-ahead ----------

@pytest.mark.parametrize("frac", [0.3, 0.5, 0.7, 0.9])
def test_truncating_the_future_changes_nothing_before_the_cut(pair, full, frac):
    """If any decision peeked ahead, cutting the data off at T would change trades taken before T."""
    nq, es, htf = pair
    cut = nq.index[int(len(nq) * frac)]
    part = run(nq[nq.index < cut], es[es.index < cut], Config(), htf[htf.index < cut])
    a = full.trades[full.trades.exit_time < cut][COLS].reset_index(drop=True)
    b = part.trades[part.trades.exit_reason != "eod_data"][COLS].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)


def test_scrambling_the_future_changes_nothing_before_the_cut(pair, full):
    nq, es, htf = pair
    cut = nq.index[len(nq) // 2]
    rng = np.random.default_rng(1)

    def scramble(df):
        df = df.copy()
        m = df.index >= cut
        noise = rng.normal(0, 50, m.sum()).cumsum()
        for col in ("open", "high", "low", "close"):
            df.loc[m, col] = df.loc[m, col].values + noise
        return df

    alt = run(scramble(nq), scramble(es), Config(), scramble(htf))
    a = full.trades[full.trades.exit_time < cut][COLS].reset_index(drop=True)
    b = alt.trades[alt.trades.exit_time < cut][COLS].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)


def test_fills_happen_after_signal(full):
    tr = full.trades
    assert (tr.entry_time > tr.signal_time).all()
    assert (tr.exit_time >= tr.entry_time).all()


# ---------- rules ----------

def test_session_and_daily_limits(full):
    tr = full.trades
    t = tr.entry_time.dt.hour * 60 + tr.entry_time.dt.minute
    assert ((t >= 570) & (t < 660)).all()
    eq_before = Config().starting_equity + tr.pnl.cumsum().shift(fill_value=0)
    for _, day in tr.groupby("day"):
        assert len(day) <= 2
        if len(day) == 2:
            assert day.iloc[0].pnl <= 0                       # only trade again after a loss
            second = day.index[1]
            assert tr.risk_usd[second] <= 0.005 * eq_before[second] + 1e-9   # trade 2 at half size


def test_risk_never_exceeds_one_percent(full):
    tr = full.trades
    eq_before = Config().starting_equity + tr.pnl.cumsum().shift(fill_value=0)
    assert (tr.risk_usd <= eq_before * 0.01 + 1e-9).all()


def test_day_risk_state_machine():
    cfg = Config()
    r = DayRisk(cfg)
    assert r.can_trade() and r.size_mult() == 1.0
    r.results.append(100)
    assert not r.can_trade()                                   # won trade 1
    r = DayRisk(cfg)
    r.results.append(-100)
    assert r.can_trade() and r.size_mult() == 0.5              # lost trade 1 -> half size
    r.results.append(-50)
    assert not r.can_trade()                                   # lost trade 2


# ---------- pattern definitions ----------

def _bars(rows, start="2026-01-05 09:30"):
    idx = pd.date_range(start, periods=len(rows), freq="5min")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)


def test_fvg_definition():
    df = _bars([(10, 11, 9, 10.5), (10.5, 14, 10.4, 13.8), (13.8, 15, 12, 14.5),   # bull gap 11..12
                (14, 14.2, 8, 8.5), (8.5, 8.6, 7, 7.2), (7, 7.5, 6, 6.2)])          # bear gap 7.5..8
    gaps = F.detect_fvgs(df)
    assert any(g.bull and g.idx == 2 and (g.bottom, g.top) == (11, 12) for g in gaps)
    assert any((not g.bull) and g.idx == 5 and (g.bottom, g.top) == (7.5, 8) for g in gaps)


def test_swing_requires_k_bars_each_side():
    highs = [1, 2, 3, 9, 3, 2, 1]
    df = _bars([(h, h, h - 0.5, h) for h in highs])
    is_hi, _ = F.swing_points(df, 3)
    assert is_hi[3] and is_hi.sum() == 1
    is_hi2, _ = F.swing_points(df.iloc[:6], 3)                 # right side incomplete -> no pivot
    assert not is_hi2.any()


def test_resample_end_waits_for_straddling_bar():
    idx = pd.DatetimeIndex(["2026-01-05 09:00", "2026-01-05 09:30", "2026-01-05 10:30", "2026-01-05 11:30"])
    df = pd.DataFrame(dict(open=1.0, high=2.0, low=0.5, close=1.5), index=idx)
    out = F.resample(df, "1h")
    # the 10:00 bin holds the 10:30 bar, which covers until 11:30 under a 1h source bar
    assert out.loc["2026-01-05 10:00", "end"] == pd.Timestamp("2026-01-05 11:30")
