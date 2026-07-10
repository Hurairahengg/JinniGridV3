"""
mother/core/strategy_brain.py — The ONE strategy brain.

NEW WINNER: EMA-84/34 two-MA smooth-grinder, HOUR-10 entries only.

Config (locked):
  - EMA main=84, fast=34
  - Confirmation streak: 2 (each candle bull for long / bear for short,
    AND closes beyond BOTH main & fast EMA)
  - Slopes: main any_positive lb10, fast any_positive lb5
  - SL: trade_candle_extreme (entry brick low/high)
  - Exit: dyn_main_ma (close crosses back through main EMA)
  - Trailing: candle_extreme (each favorable brick -> SL to that brick's
    low(long)/high(short), favorable direction only, capped below/above close)
  - NO breakeven
  - Retrig: main_ma_reset

Execution order per brick during open trade:
  A. (SL already active from previous brick — what broker sees)
  B. Check SL hit → EMIT CloseSignal + return
  C. Check dyn_main_ma exit → EMIT CloseSignal + return
  D. Check timeout → EMIT CloseSignal + return
  E. Update SL for NEXT brick via candle_extreme trail (favorable only)

Emits:
  - SignalOpen(direction, sl_distance_pts, entry_brick_time, ...)
  - SignalModifySL(new_sl_distance_pts_from_entry)
  - SignalClose(reason)
"""
from dataclasses import dataclass
from datetime import datetime, timezone


# ============================================================
# LOCKED STRATEGY CONSTANTS
# ============================================================
MA_TYPE           = "EMA"
MAIN_MA_PERIOD    = 84
FAST_MA_PERIOD    = 34
CONF_STREAK       = 2
FAST_SLOPE_LB     = 5      # any_positive
MAIN_SLOPE_LB     = 10     # any_positive
MAX_FWD_BRICKS    = 200


# ============================================================
# SIGNAL DATA CLASSES
# ============================================================
@dataclass
class SignalOpen:
    signal_id: str
    direction: int              # 1 = LONG, -1 = SHORT
    entry_brick_time: int       # mother's brick close ts (canonical timeline)
    entry_price: float          # mother reference (VM uses own broker bid/ask)
    sl_distance_pts: float      # positive number
    main_ma_value: float
    fast_ma_value: float
    main_slope_value: float
    fast_slope_value: float


@dataclass
class SignalModifySL:
    signal_id: str
    new_sl_distance_pts_from_entry: float   # signed offset from entry
    reason: str                              # "trail"


@dataclass
class SignalClose:
    signal_id: str
    reason: str                              # "sl_hit" | "dyn_ma_exit" | "timeout"


# ============================================================
# EMA COMPUTER (matches backtest ema_njit exactly)
# ============================================================
class EMA:
    def __init__(self, period):
        self.p = int(period)

    def value(self, closes):
        n = len(closes)
        if n < self.p:
            return None
        a = 2.0 / (self.p + 1)
        s = 0.0
        for i in range(self.p):
            s += closes[i]
        ema = s / self.p
        for i in range(self.p, n):
            ema = a * closes[i] + (1 - a) * ema
        return ema


# ============================================================
# STRATEGY BRAIN
# ============================================================
class StrategyBrain:
    def __init__(self, session_hours_cst, trading_days_utc_weekday, on_signal_open,
                 on_signal_modify_sl, on_signal_close, logger=None):
        self.session_hours = set(session_hours_cst)
        self.trading_days = set(trading_days_utc_weekday)
        self.on_signal_open = on_signal_open
        self.on_signal_modify_sl = on_signal_modify_sl
        self.on_signal_close = on_signal_close
        self.log = logger

        # NOTE: attribute names kept as main_ma / fast_ma (EMA computers)
        self.main_ma = EMA(MAIN_MA_PERIOD)
        self.fast_ma = EMA(FAST_MA_PERIOD)

        # Rolling brick history
        self.bars = []
        self.abs_start_index = 0

        # Position state
        self.in_position = False
        self.trade_direction = 0
        self.entry_price = 0.0
        self.entry_brick_index_abs = -1
        self.entry_ts = 0
        self.current_sl_price = 0.0
        self.initial_sl_price = 0.0
        self.be_triggered = False       # kept for recovery/main.py compatibility (always False)
        self.fav_bricks_count = 0       # kept for compatibility
        self.current_signal_id = None

        # Rearm state (main_ma_reset)
        self.long_armed = True
        self.short_armed = True

    def prepend_history(self, bars, abs_start_index=0):
        self.bars = list(bars)
        self.abs_start_index = int(abs_start_index)

    def append_brick(self, brick):
        self.bars.append(brick)
        if len(self.bars) > 600:
            drop = len(self.bars) - 600
            self.bars = self.bars[drop:]
            self.abs_start_index += drop

    # ============================================================
    # SESSION GATE — simple UTC-6 offset (matches backtest)
    # Entries only during configured CST hours (hour 10) on trading days.
    # ============================================================
    def _in_session(self, unix_ts):
        dt = datetime.fromtimestamp(int(unix_ts), tz=timezone.utc)
        cst_hour = (dt.hour - 6) % 24
        weekday = dt.weekday()
        in_hours = cst_hour in self.session_hours
        in_days = weekday in self.trading_days
        if self.log:
            self.log.debug(
                f"SESSION ts={unix_ts} utc_hr={dt.hour} cst_hr={cst_hour} "
                f"wd={weekday} in_hrs={in_hours} in_days={in_days}"
            )
        return in_hours and in_days

    # ============================================================
    # MAIN EVAL
    # ============================================================
    def on_new_brick(self, brick):
        self.append_brick(brick)

        # Session gate at top. Out-of-session: manage open positions only,
        # NEVER open new ones. (Open trades run to normal exit — no forced close.)
        if not self._in_session(brick["time"]):
            if self.in_position:
                self._eval_in_trade(brick)
            return

        if self.in_position:
            self._eval_in_trade(brick)
        else:
            self._eval_for_entry(brick)

    # ============================================================
    # IN-TRADE EVALUATION
    # ============================================================
    def _eval_in_trade(self, brick):
        # STEP B: SL hit (using CURRENT SL from previous brick)
        exited = False
        exit_reason = ""
        if self.trade_direction == 1:
            if brick["low"] <= self.current_sl_price:
                exited = True
                exit_reason = "sl_hit"
        else:
            if brick["high"] >= self.current_sl_price:
                exited = True
                exit_reason = "sl_hit"

        # STEP C: Dyn MAIN MA exit
        if not exited:
            closes = [b["close"] for b in self.bars]
            main_v = self.main_ma.value(closes)
            if main_v is not None:
                if self.trade_direction == 1 and brick["close"] < main_v:
                    exited = True
                    exit_reason = "dyn_ma_exit"
                elif self.trade_direction == -1 and brick["close"] > main_v:
                    exited = True
                    exit_reason = "dyn_ma_exit"

        # STEP D: Timeout
        if not exited:
            current_abs = self.abs_start_index + len(self.bars) - 1
            if current_abs - self.entry_brick_index_abs >= MAX_FWD_BRICKS:
                exited = True
                exit_reason = "timeout"

        if exited:
            self._emit_close(exit_reason)
            return

        # STEP E: candle_extreme trail (NO breakeven) — favorable candle only
        if self.trade_direction == 1:
            is_favorable = brick["close"] > brick["open"]
        else:
            is_favorable = brick["close"] < brick["open"]

        if is_favorable:
            cur_close = brick["close"]
            if self.trade_direction == 1:
                cand = brick["low"]
                if cand > self.current_sl_price and cand < cur_close:
                    self.current_sl_price = cand
                    self._emit_modify_sl("trail")
            else:
                cand = brick["high"]
                if cand < self.current_sl_price and cand > cur_close:
                    self.current_sl_price = cand
                    self._emit_modify_sl("trail")

    # ============================================================
    # ENTRY EVALUATION
    # ============================================================
    def _eval_for_entry(self, brick):
        if not self._in_session(brick["time"]):
            return

        n = len(self.bars)
        need = max(MAIN_MA_PERIOD + MAIN_SLOPE_LB, FAST_MA_PERIOD + FAST_SLOPE_LB) + CONF_STREAK + 5
        if n < need:
            return

        closes = [b["close"] for b in self.bars]
        m_v = self.main_ma.value(closes)
        f_v = self.fast_ma.value(closes)
        if m_v is None or f_v is None:
            return

        cur_close = closes[-1]

        # Re-arm gate: main_ma_reset
        if not self.long_armed and cur_close < m_v:
            self.long_armed = True
        if not self.short_armed and cur_close > m_v:
            self.short_armed = True

        # Confirmation streak + candle-direction match + two-MA passing
        long_ok = False
        short_ok = False

        if self.long_armed:
            ok = True
            for k in range(CONF_STREAK):
                idx = n - 1 - k
                if idx < 0:
                    ok = False
                    break
                b = self.bars[idx]
                if b["close"] <= b["open"]:            # must be BULL candle
                    ok = False
                    break
                sub = closes[:idx + 1]
                mv = self.main_ma.value(sub)
                fv = self.fast_ma.value(sub)
                if mv is None or fv is None:
                    ok = False
                    break
                if b["close"] <= mv or b["close"] <= fv:
                    ok = False
                    break
            if ok:
                long_ok = True

        if self.short_armed and not long_ok:
            ok = True
            for k in range(CONF_STREAK):
                idx = n - 1 - k
                if idx < 0:
                    ok = False
                    break
                b = self.bars[idx]
                if b["close"] >= b["open"]:            # must be BEAR candle
                    ok = False
                    break
                sub = closes[:idx + 1]
                mv = self.main_ma.value(sub)
                fv = self.fast_ma.value(sub)
                if mv is None or fv is None:
                    ok = False
                    break
                if b["close"] >= mv or b["close"] >= fv:
                    ok = False
                    break
            if ok:
                short_ok = True

        direction = 1 if long_ok else (-1 if short_ok else 0)
        if direction == 0:
            return

        # Main slope any_positive
        if len(closes) <= MAIN_SLOPE_LB:
            return
        past_main = self.main_ma.value(closes[:-MAIN_SLOPE_LB])
        if past_main is None or past_main == 0:
            return
        main_slope = (m_v - past_main) / past_main * 100.0
        if direction == 1 and main_slope <= 0.0:
            return
        if direction == -1 and main_slope >= 0.0:
            return

        # Fast slope any_positive
        if len(closes) <= FAST_SLOPE_LB:
            return
        past_fast = self.fast_ma.value(closes[:-FAST_SLOPE_LB])
        if past_fast is None or past_fast == 0:
            return
        fast_slope = (f_v - past_fast) / past_fast * 100.0
        if direction == 1 and fast_slope <= 0.0:
            return
        if direction == -1 and fast_slope >= 0.0:
            return

        # Build signal — SL = trade_candle_extreme (entry brick low/high)
        entry_price = brick["close"]
        sl_price = brick["low"] if direction == 1 else brick["high"]
        sl_distance = abs(entry_price - sl_price)
        if sl_distance <= 0:
            if direction == 1:
                self.long_armed = False
            else:
                self.short_armed = False
            return

        # Store position state
        self.in_position = True
        self.trade_direction = direction
        self.entry_price = entry_price
        self.entry_brick_index_abs = self.abs_start_index + n - 1
        self.entry_ts = brick["time"]
        self.current_sl_price = sl_price
        self.initial_sl_price = sl_price
        self.be_triggered = False
        self.fav_bricks_count = 0

        if direction == 1:
            self.long_armed = False
        else:
            self.short_armed = False

        signal_id = f"sig_{int(brick['time'])}_{direction}"
        self.current_signal_id = signal_id
        sig = SignalOpen(
            signal_id=signal_id,
            direction=direction,
            entry_brick_time=int(brick["time"]),
            entry_price=entry_price,
            sl_distance_pts=sl_distance,
            main_ma_value=m_v,
            fast_ma_value=f_v,
            main_slope_value=main_slope,
            fast_slope_value=fast_slope,
        )
        try:
            self.on_signal_open(sig)
        except Exception as e:
            if self.log:
                self.log.error(f"on_signal_open callback error: {e}")

    def _emit_modify_sl(self, reason):
        if self.trade_direction == 1:
            offset = self.current_sl_price - self.entry_price
        else:
            offset = self.entry_price - self.current_sl_price
        sig = SignalModifySL(
            signal_id=self.current_signal_id or "",
            new_sl_distance_pts_from_entry=offset,
            reason=reason,
        )
        try:
            self.on_signal_modify_sl(sig)
        except Exception as e:
            if self.log:
                self.log.error(f"on_signal_modify_sl callback error: {e}")

    def _emit_close(self, reason):
        sig = SignalClose(signal_id=self.current_signal_id or "", reason=reason)
        try:
            self.on_signal_close(sig)
        except Exception as e:
            if self.log:
                self.log.error(f"on_signal_close callback error: {e}")

        self.in_position = False
        self.trade_direction = 0
        self.entry_price = 0.0
        self.entry_brick_index_abs = -1
        self.entry_ts = 0
        self.current_sl_price = 0.0
        self.initial_sl_price = 0.0
        self.be_triggered = False
        self.fav_bricks_count = 0
        self.current_signal_id = None

    def rebuild_state_from_position(self, direction, entry_price, entry_ts,
                                    current_sl_price, signal_id, be_triggered=False):
        self.in_position = True
        self.trade_direction = direction
        self.entry_price = entry_price
        self.entry_ts = entry_ts
        self.current_sl_price = current_sl_price
        self.initial_sl_price = current_sl_price
        self.be_triggered = be_triggered
        self.fav_bricks_count = 0
        self.current_signal_id = signal_id
        if direction == 1:
            self.long_armed = False
        else:
            self.short_armed = False
        self.entry_brick_index_abs = self.abs_start_index + len(self.bars) - 1
        if self.log:
            self.log.info(f"Brain rebuilt from position: dir={direction} entry={entry_price:.2f} "
                          f"SL={current_sl_price:.2f} signal_id={signal_id}")

    def reset_state(self):
        self.in_position = False
        self.trade_direction = 0
        self.entry_price = 0.0
        self.entry_brick_index_abs = -1
        self.entry_ts = 0
        self.current_sl_price = 0.0
        self.initial_sl_price = 0.0
        self.be_triggered = False
        self.fav_bricks_count = 0
        self.current_signal_id = None
        self.long_armed = True
        self.short_armed = True

    def get_state(self):
        return {
            "in_position": self.in_position,
            "direction": self.trade_direction,
            "entry_price": self.entry_price,
            "current_sl": self.current_sl_price,
            "be_triggered": self.be_triggered,
            "long_armed": self.long_armed,
            "short_armed": self.short_armed,
            "bars_count": len(self.bars),
            "signal_id": self.current_signal_id,
        }