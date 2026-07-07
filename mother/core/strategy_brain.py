"""
mother/core/strategy_brain.py — The ONE strategy brain.

BUG-FIXED HMA-21 F14 BE+TR winning config.

Execution order per brick during open trade:
  A. Preserve sl_active (from previous brick — what broker sees)
  B. Check SL hit → EMIT CloseSignal + return
  C. Check dyn_fast_ma exit → EMIT CloseSignal + return
  D. Check timeout → EMIT CloseSignal + return
  E. Update SL for NEXT brick:
     - BE trigger check (returns early if fires)
     - Then trail_ma update (only if BE already triggered)

BE and Trail NEVER fire on same brick.

Emits:
  - SignalOpen(direction, sl_distance_pts)
  - SignalModifySL(new_sl_distance_pts_from_entry)
  - SignalClose(reason)
"""
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


# ============================================================
# LOCKED STRATEGY CONSTANTS
# ============================================================
MA_TYPE           = "HMA"
MAIN_MA_PERIOD    = 21
FAST_MA_PERIOD    = 14
CONF_STREAK       = 4
FAST_SLOPE_LB     = 5
FAST_SLOPE_THR    = 0.15
MAIN_SLOPE_LB     = 10
MAIN_SLOPE_THR    = 0.15
BE_BRICKS         = 1
BE_BUFFER_PTS     = 2
TR_MA_BUFFER_PTS  = 0
MAX_FWD_BRICKS    = 200


# ============================================================
# SIGNAL DATA CLASSES
# ============================================================
@dataclass
class SignalOpen:
    signal_id: str
    direction: int              # 1 = LONG, -1 = SHORT
    entry_brick_time: int       # brick close ts
    entry_price: float          # mother's reference (VM uses own broker bid/ask)
    sl_distance_pts: float      # positive number
    main_ma_value: float
    fast_ma_value: float
    main_slope_value: float
    fast_slope_value: float


@dataclass
class SignalModifySL:
    signal_id: str
    new_sl_distance_pts_from_entry: float   # signed toward entry side
    reason: str                              # "breakeven" | "trail"


@dataclass
class SignalClose:
    signal_id: str
    reason: str                              # "sl_hit" | "dyn_ma_exit" | "timeout"


# ============================================================
# HMA COMPUTER
# ============================================================
class HMA:
    def __init__(self, period):
        self.p = int(period)
        self.half = max(1, self.p // 2)
        self.sqrt_p = max(1, int(round(math.sqrt(self.p))))

    def _wma(self, arr, p):
        n = len(arr)
        if n < p:
            return None
        ws = p * (p + 1) / 2.0
        s = 0.0
        for k in range(p):
            s += arr[n - p + k] * (k + 1)
        return s / ws

    def value(self, closes):
        p = self.p
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


# ============================================================
# STRATEGY BRAIN (owns state, produces signals)
# ============================================================
class StrategyBrain:
    """
    Feeds on Renko bricks. Emits signals via callbacks.

    on_signal_open(SignalOpen)
    on_signal_modify_sl(SignalModifySL)
    on_signal_close(SignalClose)
    """

    def __init__(self, session_hours_cst, trading_days_utc_weekday, on_signal_open,
                 on_signal_modify_sl, on_signal_close, logger=None):
        self.session_hours = set(session_hours_cst)
        self.trading_days = set(trading_days_utc_weekday)
        self.on_signal_open = on_signal_open
        self.on_signal_modify_sl = on_signal_modify_sl
        self.on_signal_close = on_signal_close
        self.log = logger

        self.main_hma = HMA(MAIN_MA_PERIOD)
        self.fast_hma = HMA(FAST_MA_PERIOD)

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
        self.be_triggered = False
        self.fav_bricks_count = 0
        self.current_signal_id = None

        # Rearm state
        self.long_armed = True
        self.short_armed = True

    def prepend_history(self, bars, abs_start_index=0):
        """Bulk load warmup bricks before going live."""
        self.bars = list(bars)
        self.abs_start_index = int(abs_start_index)

    def append_brick(self, brick):
        """Non-destructive append (does NOT trigger eval)."""
        self.bars.append(brick)
        # Trim to reasonable size
        if len(self.bars) > 500:
            drop = len(self.bars) - 500
            self.bars = self.bars[drop:]
            self.abs_start_index += drop

    # ============================================================
    # SESSION GATE — simple UTC-6 offset (matches backtest)
    # ============================================================
    def _in_session(self, unix_ts):
        dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
        cst_hour = (dt.hour - 6) % 24
        # Weekday adjustment for UTC-6 crossing midnight
        # Simple check: if UTC hour < 6, we're in previous day CST
        # For NY session (8-16 CST) this doesn't matter — always same UTC day
        weekday = dt.weekday()
        return (cst_hour in self.session_hours) and (weekday in self.trading_days)

    # ============================================================
    # MAIN EVAL — called after brick append
    # ============================================================
    def on_new_brick(self, brick):
        """
        Called by mother after each new brick forms from OANDA ticks.
        Runs the FIXED execution order.
        """
        self.append_brick(brick)

        if self.in_position:
            self._eval_in_trade(brick)
        else:
            self._eval_for_entry(brick)

    # ============================================================
    # IN-TRADE EVALUATION (STEPS A-E)
    # ============================================================
    def _eval_in_trade(self, brick):
        entry_price = self.entry_price

        # ==========================================================
        # STEP B: SL hit check (using CURRENT SL from prev brick)
        # ==========================================================
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

        # ==========================================================
        # STEP C: Dyn fast MA exit
        # ==========================================================
        if not exited:
            closes = [b["close"] for b in self.bars]
            fast_ma = self.fast_hma.value(closes)
            if fast_ma is not None:
                if self.trade_direction == 1 and brick["close"] < fast_ma:
                    exited = True
                    exit_reason = "dyn_ma_exit"
                elif self.trade_direction == -1 and brick["close"] > fast_ma:
                    exited = True
                    exit_reason = "dyn_ma_exit"

        # ==========================================================
        # STEP D: Timeout
        # ==========================================================
        if not exited:
            current_abs = self.abs_start_index + len(self.bars) - 1
            if current_abs - self.entry_brick_index_abs >= MAX_FWD_BRICKS:
                exited = True
                exit_reason = "timeout"

        if exited:
            self._emit_close(exit_reason)
            return

        # ==========================================================
        # STEP E: Update SL for NEXT brick
        # BE OR Trail — never both on same brick
        # ==========================================================
        if self.trade_direction == 1:
            is_favorable = brick["close"] > brick["open"]
        else:
            is_favorable = brick["close"] < brick["open"]

        # Priority 1: BE trigger
        if not self.be_triggered:
            if is_favorable:
                self.fav_bricks_count += 1
            else:
                self.fav_bricks_count = 0

            if self.fav_bricks_count >= BE_BRICKS:
                if self.trade_direction == 1:
                    new_be = entry_price + BE_BUFFER_PTS
                    if new_be > self.current_sl_price:
                        self.current_sl_price = new_be
                        self._emit_modify_sl("breakeven")
                else:
                    new_be = entry_price - BE_BUFFER_PTS
                    if new_be < self.current_sl_price:
                        self.current_sl_price = new_be
                        self._emit_modify_sl("breakeven")
                self.be_triggered = True
                return  # skip trail this brick

        # Priority 2: Trail (only if BE already triggered)
        if self.be_triggered:
            closes = [b["close"] for b in self.bars]
            fast_ma = self.fast_hma.value(closes)
            if fast_ma is not None:
                if self.trade_direction == 1:
                    new_sl = fast_ma - TR_MA_BUFFER_PTS
                    if new_sl > self.current_sl_price:
                        self.current_sl_price = new_sl
                        self._emit_modify_sl("trail")
                else:
                    new_sl = fast_ma + TR_MA_BUFFER_PTS
                    if new_sl < self.current_sl_price:
                        self.current_sl_price = new_sl
                        self._emit_modify_sl("trail")

    # ============================================================
    # ENTRY EVALUATION
    # ============================================================
    def _eval_for_entry(self, brick):
        n = len(self.bars)
        need = max(MAIN_MA_PERIOD + MAIN_SLOPE_LB + CONF_STREAK,
                   FAST_MA_PERIOD + FAST_SLOPE_LB + CONF_STREAK) + 5
        if n < need:
            return

        closes = [b["close"] for b in self.bars]
        m_v = self.main_hma.value(closes)
        f_v = self.fast_hma.value(closes)
        if m_v is None or f_v is None:
            return

        cur_close = closes[-1]

        # Re-arm gate: main_ma_reset — arm when close moves through main MA
        if not self.long_armed and cur_close < m_v:
            self.long_armed = True
        if not self.short_armed and cur_close > m_v:
            self.short_armed = True

        # Session gate
        if not self._in_session(brick["time"]):
            return

        # Confirmation streak (needs main_hma and fast_hma values for last N closes)
        long_ok = False
        short_ok = False

        if self.long_armed:
            ok = True
            for k in range(CONF_STREAK):
                if len(closes) - k < 1:
                    ok = False
                    break
                sub = closes[:len(closes) - k]
                mv = self.main_hma.value(sub)
                fv = self.fast_hma.value(sub)
                cv = closes[-(k + 1)]
                if mv is None or fv is None or cv <= mv or cv <= fv:
                    ok = False
                    break
            if ok:
                long_ok = True

        if self.short_armed and not long_ok:
            ok = True
            for k in range(CONF_STREAK):
                if len(closes) - k < 1:
                    ok = False
                    break
                sub = closes[:len(closes) - k]
                mv = self.main_hma.value(sub)
                fv = self.fast_hma.value(sub)
                cv = closes[-(k + 1)]
                if mv is None or fv is None or cv >= mv or cv >= fv:
                    ok = False
                    break
            if ok:
                short_ok = True

        direction = 1 if long_ok else (-1 if short_ok else 0)
        if direction == 0:
            return

        # Fast slope
        if len(closes) <= FAST_SLOPE_LB:
            return
        past_fast = self.fast_hma.value(closes[:-FAST_SLOPE_LB])
        if past_fast is None or past_fast == 0:
            return
        fast_slope = (f_v - past_fast) / past_fast * 100.0
        if direction == 1 and fast_slope <= FAST_SLOPE_THR:
            return
        if direction == -1 and fast_slope >= -FAST_SLOPE_THR:
            return

        # Main slope (threshold_med 0.15%)
        if len(closes) <= MAIN_SLOPE_LB:
            return
        past_main = self.main_hma.value(closes[:-MAIN_SLOPE_LB])
        if past_main is None or past_main == 0:
            return
        main_slope = (m_v - past_main) / past_main * 100.0
        if direction == 1 and main_slope <= MAIN_SLOPE_THR:
            return
        if direction == -1 and main_slope >= -MAIN_SLOPE_THR:
            return

        # All filters passed — build signal
        entry_price = brick["close"]
        # SL = trade_bar_extreme (brick low for LONG, brick high for SHORT)
        sl_price = brick["low"] if direction == 1 else brick["high"]
        sl_distance = abs(entry_price - sl_price)
        if sl_distance <= 0:
            # Invalid SL — disarm
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

        # Disarm same direction
        if direction == 1:
            self.long_armed = False
        else:
            self.short_armed = False

        # Emit open signal
        signal_id = f"sig_{int(brick['time'])}_{direction}"
        self.current_signal_id = signal_id
        sig = SignalOpen(
            signal_id=signal_id,
            direction=direction,
            entry_brick_time=brick["time"],
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

        # Reset state
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

    def get_state(self):
        """For dashboard/diagnostics."""
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