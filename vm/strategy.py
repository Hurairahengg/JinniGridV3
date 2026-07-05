"""
vm/strategy.py — Pure strategy logic. No I/O, no MT5, no networking.

Contains: Renko builder, HMA computer, slope computer, signal detector, position manager.
Deterministic: same tick stream → same output. Enables independent validation on mother.
"""
import math
from dataclasses import dataclass, field
from typing import Optional, List


# ============================================================
# RENKO BUILDER (Koko clean-mode range bars — matches backtest)
# ============================================================
class RenkoBuilder:
    """
    Feed ticks one at a time. Returns a list of newly-completed bricks
    (0 or more) per feed_tick call. Handles reversals with proper wicks
    via inner brick-consumption loop so single big ticks yield multiple
    clean bricks rather than one giant wick.

    Bit-for-bit compatible with backtest KokoCandleStreamer.
    """

    def __init__(self, brick_size, price_decimals=2, rev_bricks=2.0, clean_mode=True):
        self.rs = float(brick_size)
        self.pd = int(price_decimals)
        self.rev_bricks = float(rev_bricks)
        self.clean_mode = bool(clean_mode)

        self.trend = 0                  # -1 down, 0 uninit, +1 up
        self.level = None               # last close/reference price
        self._has_bar = False
        self._b_high = 0.0
        self._b_low = 0.0
        self._b_vol = 0.0
        self._last_ts = -1

    def feed_tick(self, ts, price, volume=0.0):
        """Feed one tick; returns list of newly-formed bricks (may be empty)."""
        ts = int(ts)
        p = float(price)
        v = float(volume)

        # First tick — anchor to nearest brick level
        if not self._has_bar:
            self.level = round(round(p / self.rs) * self.rs, self.pd)
            self._b_high = self.level
            self._b_low = self.level
            self._b_vol = v
            self._has_bar = True
            return []

        # Aggregate tick
        self._b_vol += v
        if p > self._b_high:
            self._b_high = p
        if p < self._b_low:
            self._b_low = p

        # Consume bricks until price fits within tolerance
        out = []
        rs = self.rs
        pd = self.pd
        rev_dist = self.rev_bricks * rs

        while True:
            lvl = self.level

            if self.trend == 1:
                cont_t = round(lvl + rs, pd)
                if p >= cont_t:
                    bo, bc = lvl, cont_t
                    bh, bl = bc, self._b_low
                    out.append(self._emit(ts, bo, bh, bl, bc))
                    self.level = cont_t
                    self._b_high = self.level
                    self._b_low = self.level
                    self._b_vol = 0.0
                    continue
                rev_t = round(lvl - rev_dist, pd)
                if p <= rev_t:
                    if self.clean_mode:
                        bc = rev_t
                        bo = round(rev_t + rs, pd)
                        bh = self._b_high
                        bl = bc
                    else:
                        bo = lvl
                        bc = rev_t
                        bh = self._b_high
                        bl = bc
                    out.append(self._emit(ts, bo, bh, bl, bc))
                    self.trend = -1
                    self.level = rev_t
                    self._b_high = self.level
                    self._b_low = self.level
                    self._b_vol = 0.0
                    continue
                break

            elif self.trend == -1:
                cont_t = round(lvl - rs, pd)
                if p <= cont_t:
                    bo, bc = lvl, cont_t
                    bh, bl = self._b_high, bc
                    out.append(self._emit(ts, bo, bh, bl, bc))
                    self.level = cont_t
                    self._b_high = self.level
                    self._b_low = self.level
                    self._b_vol = 0.0
                    continue
                rev_t = round(lvl + rev_dist, pd)
                if p >= rev_t:
                    if self.clean_mode:
                        bc = rev_t
                        bo = round(rev_t - rs, pd)
                        bh = bc
                        bl = self._b_low
                    else:
                        bo = lvl
                        bc = rev_t
                        bh = bc
                        bl = self._b_low
                    out.append(self._emit(ts, bo, bh, bl, bc))
                    self.trend = 1
                    self.level = rev_t
                    self._b_high = self.level
                    self._b_low = self.level
                    self._b_vol = 0.0
                    continue
                break

            else:  # trend == 0
                up_t = round(lvl + rs, pd)
                if p >= up_t:
                    bo, bc = lvl, up_t
                    bh, bl = bc, self._b_low
                    out.append(self._emit(ts, bo, bh, bl, bc))
                    self.trend = 1
                    self.level = up_t
                    self._b_high = self.level
                    self._b_low = self.level
                    self._b_vol = 0.0
                    continue
                down_t = round(lvl - rs, pd)
                if p <= down_t:
                    bo, bc = lvl, down_t
                    bh, bl = self._b_high, bc
                    out.append(self._emit(ts, bo, bh, bl, bc))
                    self.trend = -1
                    self.level = down_t
                    self._b_high = self.level
                    self._b_low = self.level
                    self._b_vol = 0.0
                    continue
                break

        return out

    def _emit(self, ts, o, h, l, c):
        pd = self.pd
        # Guarantee strict-increasing timestamps
        ts2 = self._last_ts + 1 if ts <= self._last_ts else ts
        self._last_ts = ts2
        return {
            "time": ts2,
            "open": round(o, pd),
            "high": round(h, pd),
            "low": round(l, pd),
            "close": round(c, pd),
            "volume": round(self._b_vol, 2),
        }


# ============================================================
# HMA COMPUTER (rolling, exact)
# ============================================================
class HMAComputer:
    """
    Computes HMA on a growing closes list. Not incremental (recomputes on
    each call) but only touches the tail — fast enough for live trading
    at range-bar frequency. Matches backtest math bit-for-bit.
    """

    def __init__(self, period):
        self.period = int(period)
        self.half = max(1, self.period // 2)
        self.sqrt_p = max(1, int(round(math.sqrt(self.period))))

    def _wma(self, arr, p):
        n = len(arr)
        if n < p:
            return None
        ws = p * (p + 1) / 2.0
        s = 0.0
        for k in range(p):
            s += arr[n - p + k] * (k + 1)
        return s / ws

    def value_at(self, closes, end_idx):
        """HMA value at closes[end_idx]. Returns None if not enough history."""
        sub = closes[:end_idx + 1]
        return self._compute(sub)

    def _compute(self, closes):
        p = self.period
        n = len(closes)
        if n < p + self.sqrt_p:
            return None
        diff_series = []
        for i in range(n - self.sqrt_p, n):
            wh = self._wma(closes[max(0, i - self.half + 1):i + 1], self.half)
            wf = self._wma(closes[max(0, i - p + 1):i + 1], p)
            if wh is None or wf is None:
                return None
            diff_series.append(2 * wh - wf)
        return self._wma(diff_series, self.sqrt_p)

    def series(self, closes, tail_count):
        """
        Return HMA values for the LAST tail_count positions of closes.
        Leading entries may be None if history is insufficient.
        """
        results = []
        n = len(closes)
        for k in range(tail_count):
            end = n - (tail_count - 1 - k)
            if end <= 0:
                results.append(None)
                continue
            results.append(self._compute(closes[:end]))
        return results


# ============================================================
# SIGNAL / EXIT SPEC
# ============================================================
@dataclass
class Signal:
    direction: int                    # 1 LONG, -1 SHORT
    entry_price: float
    sl_price: float
    entry_brick_index: int            # absolute across the run
    entry_brick: dict                 # full OHLC dict
    main_ma_value: float
    fast_ma_value: float
    main_slope_value: float
    fast_slope_value: float
    confirmation_streak: int
    filters_passed: dict = field(default_factory=dict)


@dataclass
class ExitSignal:
    reason: str                       # "SL_HIT" | "DYN_MA_EXIT" | "TIMEOUT"
    exit_price: float
    exit_brick: dict


# ============================================================
# STRATEGY STATE MACHINE
# ============================================================
class Strategy:
    """
    NY HMA-21 F14 double-slope. Locked constants match backtest.

    Usage:
        strat = Strategy(config)
        # for each new brick:
        signal = strat.on_new_brick(brick, absolute_index)
        # if in trade, also:
        exit_sig = strat.on_new_brick_for_exit(brick, absolute_index)
    """
    # ============================================================
# STRATEGY STATE MACHINE — LOCKED CONSTANTS (do not edit)
# ============================================================
class Strategy:
    """
    NY HMA-21 F14 double-slope. ALL params are constants — locked to backtest.
    Only session hours/days are configurable per VM (via session_cfg).

    If you want a different strategy, subclass. Don't edit these constants.
    """

    # ---------- LOCKED STRATEGY CONSTANTS ----------
    MAIN_MA_TYPE          = "HMA"
    MAIN_MA_PERIOD        = 21
    FAST_MA_PERIOD        = 14
    CONF_STREAK           = 3
    FAST_SLOPE_MODE       = "threshold_med"
    FAST_SLOPE_LOOKBACK   = 20
    FAST_SLOPE_THR_PCT    = 0.15
    MAIN_SLOPE_MODE       = "any_positive"
    MAIN_SLOPE_LOOKBACK   = 10
    SL_TYPE               = "trade_bar_extreme"
    TP_TYPE               = "dyn_fast_ma"
    RETRIG_TYPE           = "fast_ma_reset"
    MAX_FORWARD_BRICKS    = 200
    RENKO_REV_BRICKS      = 2.0
    RENKO_CLEAN_MODE      = True

    def __init__(self, session_cfg):
        # Only session is configurable per-VM
        self.main_period = self.MAIN_MA_PERIOD
        self.fast_period = self.FAST_MA_PERIOD
        self.conf_streak = self.CONF_STREAK
        self.fast_slope_thr = self.FAST_SLOPE_THR_PCT
        self.fast_slope_lb = self.FAST_SLOPE_LOOKBACK
        self.main_slope_lb = self.MAIN_SLOPE_LOOKBACK
        self.max_fwd = self.MAX_FORWARD_BRICKS

        self.main_hma = HMAComputer(self.main_period)
        self.fast_hma = HMAComputer(self.fast_period)

        # Session (configurable per VM)
        self.session_hours = set(range(session_cfg["start_hour"], session_cfg["end_hour"] + 1))
        wd_map = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
        self.session_days = {wd_map[d] for d in session_cfg["days"]}

        # State
        self.long_armed = True
        self.short_armed = True
        self.bars = []
        self.abs_start_index = 0

    def prepend_history(self, bars, abs_start_index=0):
        """Bulk-load warmup bars before entering live. Called once."""
        self.bars = list(bars)
        self.abs_start_index = int(abs_start_index)

    def _abs_to_local(self, abs_idx):
        return abs_idx - self.abs_start_index

    def _cst_hour(self, unix_ts):
        """
        Convert unix timestamp to (central_hour, central_weekday).
        Uses IANA timezone `America/Chicago` — auto-handles CST↔CDT.
        OS timezone is IGNORED. Backtest and live use identical semantics.
        """
        from datetime import datetime, timezone
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        utc = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
        central = utc.astimezone(ZoneInfo("America/Chicago"))
        return central.hour, central.weekday()

    def _in_session(self, unix_ts):
        h, wd = self._cst_hour(unix_ts)
        return (h in self.session_hours) and (wd in self.session_days)

    def _check_signal(self, live_session_active):
        """Returns a Signal or None. Assumes self.bars is up-to-date."""
        bars = self.bars
        n = len(bars)
        # Need enough closes for MA + slope + confirmation streak
        need = max(self.main_period + self.main_slope_lb + self.conf_streak,
                   self.fast_period + self.fast_slope_lb + self.conf_streak) + 5
        if n < need:
            return None

        closes = [b["close"] for b in bars]
        # We need values at the last (conf_streak + max(slope_lb)) positions
        tail_count = max(self.conf_streak, self.fast_slope_lb, self.main_slope_lb) + 5
        main_hist = self.main_hma.series(closes, tail_count)
        fast_hist = self.fast_hma.series(closes, tail_count)

        i = tail_count - 1
        m_v = main_hist[i]
        f_v = fast_hist[i]
        if m_v is None or f_v is None:
            return None

        cur_close = closes[-1]
        last_bar = bars[-1]

        # Re-arm gate: last brick closed opposite side of fast MA
        if not self.long_armed and cur_close < f_v:
            self.long_armed = True
        if not self.short_armed and cur_close > f_v:
            self.short_armed = True

        # Wall-clock session must be active
        if not live_session_active:
            return None
        # Bar-time session (belt-and-suspenders)
        if not self._in_session(last_bar["time"]):
            return None

        # Confirmation streak
        long_ok = False
        short_ok = False
        if self.long_armed:
            ok = True
            for k in range(self.conf_streak):
                mv = main_hist[i - k]
                fv = fast_hist[i - k]
                cv = closes[-(k + 1)]
                if mv is None or fv is None or cv <= mv or cv <= fv:
                    ok = False
                    break
            if ok:
                long_ok = True

        if self.short_armed and not long_ok:
            ok = True
            for k in range(self.conf_streak):
                mv = main_hist[i - k]
                fv = fast_hist[i - k]
                cv = closes[-(k + 1)]
                if mv is None or fv is None or cv >= mv or cv >= fv:
                    ok = False
                    break
            if ok:
                short_ok = True

        direction = 1 if long_ok else (-1 if short_ok else 0)
        if direction == 0:
            return None

        # Fast slope
        past_fast = fast_hist[i - self.fast_slope_lb]
        if past_fast is None or past_fast == 0:
            return None
        fast_slope = (f_v - past_fast) / past_fast * 100.0
        if direction == 1 and fast_slope <= self.fast_slope_thr:
            return None
        if direction == -1 and fast_slope >= -self.fast_slope_thr:
            return None

        # Main slope (any_positive)
        past_main = main_hist[i - self.main_slope_lb]
        if past_main is None or past_main == 0:
            return None
        main_slope = (m_v - past_main) / past_main * 100.0
        if direction == 1 and main_slope <= 0:
            return None
        if direction == -1 and main_slope >= 0:
            return None

        # All filters passed
        entry_price = last_bar["close"]
        sl_price = last_bar["low"] if direction == 1 else last_bar["high"]

        return Signal(
            direction=direction,
            entry_price=entry_price,
            sl_price=sl_price,
            entry_brick_index=self.abs_start_index + n - 1,
            entry_brick=dict(last_bar),
            main_ma_value=m_v,
            fast_ma_value=f_v,
            main_slope_value=main_slope,
            fast_slope_value=fast_slope,
            confirmation_streak=self.conf_streak,
            filters_passed={
                "confirmation": True,
                "position_filter": True,
                "fast_slope": True,
                "main_slope": True,
                "rearm_gate": True,
            },
        )

    def _check_exit(self, position):
        """
        position is a dict:
            { "direction": ±1, "sl_price": float, "entry_abs_index": int }
        Returns ExitSignal or None.
        """
        bars = self.bars
        n = len(bars)
        last = bars[-1]

        # SL check (pessimistic priority)
        if position["direction"] == 1 and last["low"] <= position["sl_price"]:
            return ExitSignal("SL_HIT", position["sl_price"], dict(last))
        if position["direction"] == -1 and last["high"] >= position["sl_price"]:
            return ExitSignal("SL_HIT", position["sl_price"], dict(last))

        # Dynamic exit via fast MA
        closes = [b["close"] for b in bars]
        fast = self.fast_hma._compute(closes)
        if fast is not None:
            if position["direction"] == 1 and last["close"] < fast:
                return ExitSignal("DYN_MA_EXIT", last["close"], dict(last))
            if position["direction"] == -1 and last["close"] > fast:
                return ExitSignal("DYN_MA_EXIT", last["close"], dict(last))

        # Timeout
        cur_abs = self.abs_start_index + n - 1
        if cur_abs - position["entry_abs_index"] >= self.max_fwd:
            return ExitSignal("TIMEOUT", last["close"], dict(last))

        return None

    def append_brick(self, brick):
        """Append a new bar to the rolling window."""
        self.bars.append(brick)

    def evaluate(self, live_session_active, in_position, position=None):
        """
        Called AFTER a new brick has been appended.

        Returns:
          - "exit" ExitSignal if position provided and exit fires
          - "signal" Signal if no position and entry fires
          - None otherwise
        """
        if in_position:
            return self._check_exit(position)
        return self._check_signal(live_session_active)

    def mark_entered(self, direction):
        if direction == 1:
            self.long_armed = False
        else:
            self.short_armed = False