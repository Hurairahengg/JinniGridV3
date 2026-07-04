"""
mother/core/validator.py — Independent trade validator.

Runs a mirror of every VM's Renko + HMA state using mother's own MT5 tick
stream. When a VM reports TRADE_OPEN, we look up that brick in our own
history, recompute the filters, and compare. Produces a grade + confidence
score. All values persisted to fleet.db via the storage layer.

Also validates configs before mother pushes them to VMs.
"""
import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import MetaTrader5 as mt5

from core.bars import RenkoBuilder


# ============================================================
# TOLERANCES (spec-defined)
# ============================================================
ENTRY_PRICE_TOLERANCE_PCT = 0.10          # 0.1%
MA_TOLERANCE_PCT = 0.05                    # 0.05%
SLOPE_TOLERANCE_ABS_PCT = 0.02             # 0.02% absolute
BRICK_TS_TOLERANCE_SEC = 5


# ============================================================
# HMA (identical formula to vm/strategy.py)
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
# SYMBOL MONITOR (one per unique symbol/brick combo)
# ============================================================
class SymbolMonitor:
    """Maintains rolling Renko history + MA state for a single symbol."""

    def __init__(self, symbol, brick_size, main_period, fast_period, rolling_max=1000):
        self.symbol = symbol
        self.brick_size = brick_size
        self.renko = RenkoBuilder(brick_size=brick_size, price_decimals=2, rev_bricks=2.0, clean_mode=True)
        self.main_hma = HMA(main_period)
        self.fast_hma = HMA(fast_period)
        self.bars = []
        self.rolling_max = rolling_max
        self.last_msc = 0
        self.last_ts = 0

    def feed_tick(self, ts, price, volume):
        new_bars = self.renko.feed_tick(ts, price, volume)
        for b in new_bars:
            self.bars.append(b)
            if len(self.bars) > self.rolling_max:
                self.bars.pop(0)

    def find_brick(self, target_ts, target_close, tolerance_sec=BRICK_TS_TOLERANCE_SEC):
        """
        Locate a brick by timestamp + close price. Returns (index, brick) or (None, None).
        Match logic: timestamp within tolerance AND close price matches within 0.1%.
        """
        for i, b in enumerate(self.bars):
            if abs(b["time"] - target_ts) <= tolerance_sec:
                drift_pct = abs(b["close"] - target_close) / max(target_close, 1e-9) * 100
                if drift_pct <= ENTRY_PRICE_TOLERANCE_PCT:
                    return i, b
        return None, None

    def compute_state_at(self, idx, main_slope_lb, fast_slope_lb, conf_streak):
        """
        Reconstruct the state at bar `idx`:
        MA values, slope values, confirmation streak status.
        """
        if idx < 0 or idx >= len(self.bars):
            return None

        closes_upto = [b["close"] for b in self.bars[:idx + 1]]
        n = len(closes_upto)

        main_ma = self.main_hma.value(closes_upto)
        fast_ma = self.fast_hma.value(closes_upto)

        # Slope needs value at idx and at idx-lookback
        def slope_pct(hma_obj, lookback):
            past_slice = closes_upto[:n - lookback] if n > lookback else None
            if past_slice is None:
                return None
            past = hma_obj.value(past_slice)
            cur = hma_obj.value(closes_upto)
            if past is None or cur is None or past == 0:
                return None
            return (cur - past) / past * 100.0

        main_slope = slope_pct(self.main_hma, main_slope_lb)
        fast_slope = slope_pct(self.fast_hma, fast_slope_lb)

        # Confirmation streak: last `conf_streak` bars all closed above (LONG) or below (SHORT) both MAs
        streak_long = True
        streak_short = True
        for k in range(conf_streak):
            if idx - k < 0:
                streak_long = streak_short = False
                break
            b = self.bars[idx - k]
            # Approx using current values — same math as VM at signal moment
            m = self.main_hma.value(closes_upto[:idx - k + 1])
            f = self.fast_hma.value(closes_upto[:idx - k + 1])
            if m is None or f is None:
                streak_long = streak_short = False
                break
            if b["close"] <= m or b["close"] <= f:
                streak_long = False
            if b["close"] >= m or b["close"] >= f:
                streak_short = False

        return {
            "main_ma": main_ma,
            "fast_ma": fast_ma,
            "main_slope": main_slope,
            "fast_slope": fast_slope,
            "streak_long_ok": streak_long,
            "streak_short_ok": streak_short,
            "brick": self.bars[idx],
        }


# ============================================================
# VALIDATION RESULT
# ============================================================
@dataclass
class ValidationResult:
    status: str                    # EXACT_MATCH | MINOR_MISMATCH | MAJOR_MISMATCH | NO_SIGNAL | CANT_LOCATE | NO_VALIDATION
    confidence: float              # 0..100
    entry_price_diff_pct: float = 0.0
    main_ma_diff_pct: float = 0.0
    fast_ma_diff_pct: float = 0.0
    main_slope_diff_abs: float = 0.0
    fast_slope_diff_abs: float = 0.0
    details: dict = field(default_factory=dict)


# ============================================================
# VALIDATOR ENGINE
# ============================================================
class Validator:
    """
    Owns MT5 tick stream and per-symbol monitors. Feeds validation results
    back via a callback for storage + dashboard broadcast.
    """

    def __init__(self, on_validation_ready, log=None):
        self.log = log or logging.getLogger("validator")
        self.on_validation_ready = on_validation_ready

        self.monitors = {}            # (symbol, brick_size) -> SymbolMonitor
        self.symbol_to_key = {}        # symbol -> primary key (last configured)
        self.mt5_ok = False
        self.running = False
        self.min_warmup_bars = 500

    # ---------- MT5 ----------
    def mt5_connect(self):
        if not mt5.initialize(timeout=60000):
            raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
        info = mt5.account_info()
        if info is None:
            raise RuntimeError("MT5 not logged in (validator)")
        self.mt5_ok = True
        self.log.info(f"Validator MT5 attached. Login={info.login}")

    def mt5_shutdown(self):
        try:
            mt5.shutdown()
        except Exception:
            pass
        self.mt5_ok = False

    # ---------- Symbol registration ----------
    def register_symbol(self, symbol, brick_size, main_period, fast_period):
        key = (symbol, brick_size)
        if key in self.monitors:
            return
        if not mt5.symbol_select(symbol, True):
            self.log.warning(f"symbol_select failed: {symbol} — validation limited")
            return
        self.monitors[key] = SymbolMonitor(symbol, brick_size, main_period, fast_period)
        self.symbol_to_key[symbol] = key
        self.log.info(f"Validator watching {symbol} brick={brick_size} main={main_period} fast={fast_period}")

    async def warmup_symbol(self, symbol, brick_size, days=3):
        key = (symbol, brick_size)
        mon = self.monitors.get(key)
        if mon is None:
            return
        now = int(time.time())
        from_ts = now - days * 86400
        ticks = mt5.copy_ticks_range(
            symbol,
            datetime.fromtimestamp(from_ts, tz=timezone.utc),
            datetime.fromtimestamp(now, tz=timezone.utc),
            mt5.COPY_TICKS_ALL,
        )
        if ticks is None or len(ticks) == 0:
            self.log.warning(f"No warmup ticks for {symbol}")
            return
        self.log.info(f"Warming {symbol}: {len(ticks):,} ticks")
        for t in ticks:
            ts_int = int(t["time"])
            bid = float(t["bid"])
            ask = float(t["ask"])
            price = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else (bid or ask or float(t["last"]))
            if price <= 0:
                continue
            vol = float(t["volume"]) if "volume" in t.dtype.names else 0.0
            mon.feed_tick(ts_int, price, vol)
        self.log.info(f"{symbol} warmup: {len(mon.bars)} bricks in rolling window")

    # ---------- Live tick loop ----------
    async def live_loop(self):
        self.running = True
        while self.running:
            try:
                for (symbol, _), mon in list(self.monitors.items()):
                    tick = mt5.symbol_info_tick(symbol)
                    if tick is None:
                        continue
                    ts_int = int(tick.time)
                    if ts_int == mon.last_ts and tick.time_msc == mon.last_msc:
                        continue
                    bid = float(tick.bid)
                    ask = float(tick.ask)
                    price = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else (bid or ask or 0)
                    if price <= 0:
                        continue
                    vol = float(tick.volume)
                    mon.feed_tick(ts_int, price, vol)
                    mon.last_ts = ts_int
                    mon.last_msc = tick.time_msc
                await asyncio.sleep(0.05)
            except Exception as e:
                self.log.error(f"Validator loop error: {e}")
                await asyncio.sleep(2)
        self.mt5_shutdown()

    def stop(self):
        self.running = False

    # ---------- Trade validation ----------
    def validate_trade(self, trade_event):
        """
        Synchronous validation of a TRADE_OPEN event.
        Returns ValidationResult.
        """
        symbol = trade_event["symbol"]
        key = self.symbol_to_key.get(symbol)
        if key is None or key not in self.monitors:
            return ValidationResult(status="NO_VALIDATION", confidence=0.0,
                                    details={"reason": "symbol not monitored"})

        mon = self.monitors[key]
        if len(mon.bars) < self.min_warmup_bars:
            return ValidationResult(status="NO_VALIDATION", confidence=0.0,
                                    details={"reason": "insufficient warmup"})

        entry_brick = trade_event["entry_brick"]
        target_ts = entry_brick["time"]
        target_close = entry_brick["close"]

        idx, brick = mon.find_brick(target_ts, target_close)
        if idx is None:
            return ValidationResult(status="CANT_LOCATE", confidence=0.0,
                                    details={
                                        "reason": "no matching brick in mother history",
                                        "target_ts": target_ts, "target_close": target_close,
                                        "window_first_ts": mon.bars[0]["time"] if mon.bars else 0,
                                        "window_last_ts": mon.bars[-1]["time"] if mon.bars else 0,
                                    })

        # Reconstruct state at that brick
        st = mon.compute_state_at(
            idx,
            main_slope_lb=10,
            fast_slope_lb=20,
            conf_streak=3,
        )
        if st is None or st["main_ma"] is None or st["fast_ma"] is None:
            return ValidationResult(status="CANT_LOCATE", confidence=0.0,
                                    details={"reason": "state reconstruction failed"})

        # Compute diffs
        vm_main = trade_event["main_ma_value"]
        vm_fast = trade_event["fast_ma_value"]
        vm_main_slope = trade_event["main_slope_value"]
        vm_fast_slope = trade_event["fast_slope_value"]
        vm_entry = trade_event["entry_price"]

        entry_diff_pct = abs(vm_entry - brick["close"]) / max(brick["close"], 1e-9) * 100
        main_ma_diff_pct = abs(vm_main - st["main_ma"]) / max(abs(st["main_ma"]), 1e-9) * 100
        fast_ma_diff_pct = abs(vm_fast - st["fast_ma"]) / max(abs(st["fast_ma"]), 1e-9) * 100
        main_slope_diff = abs(vm_main_slope - (st["main_slope"] or 0))
        fast_slope_diff = abs(vm_fast_slope - (st["fast_slope"] or 0))

        # Would the signal have fired?
        direction = trade_event["direction"]
        streak_ok = st["streak_long_ok"] if direction == 1 else st["streak_short_ok"]
        fast_slope_ok = (
            (direction == 1 and (st["fast_slope"] or 0) > 0.15) or
            (direction == -1 and (st["fast_slope"] or 0) < -0.15)
        )
        main_slope_ok = (
            (direction == 1 and (st["main_slope"] or 0) > 0) or
            (direction == -1 and (st["main_slope"] or 0) < 0)
        )
        signal_valid = streak_ok and fast_slope_ok and main_slope_ok

        # Grade
        checks = []
        checks.append(("entry", entry_diff_pct <= ENTRY_PRICE_TOLERANCE_PCT))
        checks.append(("main_ma", main_ma_diff_pct <= MA_TOLERANCE_PCT))
        checks.append(("fast_ma", fast_ma_diff_pct <= MA_TOLERANCE_PCT))
        checks.append(("main_slope", main_slope_diff <= SLOPE_TOLERANCE_ABS_PCT))
        checks.append(("fast_slope", fast_slope_diff <= SLOPE_TOLERANCE_ABS_PCT))
        checks.append(("signal", signal_valid))

        passed = sum(1 for _, ok in checks if ok)
        total = len(checks)
        confidence = (passed / total) * 100.0

        if not signal_valid:
            status = "NO_SIGNAL"
        elif passed == total:
            status = "EXACT_MATCH"
        elif passed >= total - 1:
            status = "MINOR_MISMATCH"
        else:
            status = "MAJOR_MISMATCH"

        return ValidationResult(
            status=status,
            confidence=confidence,
            entry_price_diff_pct=entry_diff_pct,
            main_ma_diff_pct=main_ma_diff_pct,
            fast_ma_diff_pct=fast_ma_diff_pct,
            main_slope_diff_abs=main_slope_diff,
            fast_slope_diff_abs=fast_slope_diff,
            details={
                "mother_view": {
                    "brick": brick, "main_ma": st["main_ma"], "fast_ma": st["fast_ma"],
                    "main_slope": st["main_slope"], "fast_slope": st["fast_slope"],
                    "streak_ok": streak_ok, "signal_valid": signal_valid,
                },
                "vm_view": {
                    "entry_price": vm_entry, "main_ma": vm_main, "fast_ma": vm_fast,
                    "main_slope": vm_main_slope, "fast_slope": vm_fast_slope,
                },
                "checks": {name: ok for name, ok in checks},
            },
        )


# ============================================================
# CONFIG VALIDATOR
# ============================================================
def validate_config(cfg):
    """
    Validates a config dict before mother pushes it to a VM.
    Returns (ok: bool, errors: list[str], warnings: list[str]).
    """
    errors = []
    warnings = []

    # Schema
    required_sections = ["strategy", "risk", "session", "mt5"]
    for s in required_sections:
        if s not in cfg:
            errors.append(f"missing section: {s}")

    if errors:
        return False, errors, warnings

    st = cfg["strategy"]
    rk = cfg["risk"]
    sess = cfg["session"]

    # Strategy sanity
    for k in ["symbol", "brick_size", "main_ma_period", "fast_ma_period",
              "conf_streak", "fast_slope_threshold_pct", "fast_slope_lookback",
              "main_slope_lookback"]:
        if k not in st:
            errors.append(f"strategy.{k} missing")

    if not errors:
        if st["main_ma_period"] <= st["fast_ma_period"]:
            warnings.append("main_ma_period should be greater than fast_ma_period")
        if st["conf_streak"] < 1 or st["conf_streak"] > 10:
            errors.append("conf_streak must be 1..10")
        if st["brick_size"] <= 0:
            errors.append("brick_size must be > 0")
        if st["fast_slope_lookback"] < 5 or st["fast_slope_lookback"] > 100:
            errors.append("fast_slope_lookback should be 5..100")
        if st["main_slope_lookback"] < 5 or st["main_slope_lookback"] > 100:
            errors.append("main_slope_lookback should be 5..100")

    # Risk sanity — spec caps at 2%
    if not (0.01 <= rk.get("risk_pct", 0) <= 2.0):
        errors.append(f"risk_pct must be 0.01..2.0 (spec safety cap), got {rk.get('risk_pct')}")
    if rk.get("max_lots", 0) <= 0:
        errors.append("max_lots must be > 0")
    if rk.get("max_lots", 0) > 1000:
        warnings.append("max_lots > 1000 is aggressive — verify broker allows")

    # Session
    if not (0 <= sess["start_hour"] <= 23) or not (0 <= sess["end_hour"] <= 23):
        errors.append("session hours must be 0..23")
    if sess["start_hour"] >= sess["end_hour"]:
        errors.append("start_hour must be less than end_hour")
    valid_days = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
    for d in sess.get("days", []):
        if d not in valid_days:
            errors.append(f"invalid day: {d}")

    return len(errors) == 0, errors, warnings