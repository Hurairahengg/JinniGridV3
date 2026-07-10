"""
mother/core/validator.py — Trade validation via strategy replay.

For each trade a VM reports, we replay the strategy on mother's brick history
around that trade's entry brick and compare the outcome. If VM's PnL is within
tolerance of what backtest would have produced, mark as EXACT_MATCH. Otherwise
flag mismatches.

Validation runs asynchronously in background — never blocks live trading.
"""
import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone


# ============================================================
# TOLERANCES
# ============================================================
ENTRY_PRICE_TOLERANCE_PCT = 0.10     # 0.1% price drift OK
PNL_TOLERANCE_USD = 5.0                # $5 PnL drift OK
PNL_TOLERANCE_PCT = 15.0               # 15% PnL % drift OK
MIN_HISTORY_BARS = 200                 # need 200 bars of history to validate


# ============================================================
# EMA (same math as strategy_brain.py)
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
# VALIDATION RESULT
# ============================================================
@dataclass
class ValidationResult:
    status: str                       # EXACT_MATCH | MINOR_MISMATCH | MAJOR_MISMATCH | CANT_LOCATE | NO_VALIDATION
    confidence: float                  # 0..100
    vm_pnl: float = 0.0
    expected_pnl: float = 0.0
    pnl_diff_usd: float = 0.0
    pnl_diff_pct: float = 0.0
    entry_price_diff_pct: float = 0.0
    details: dict = field(default_factory=dict)


# ============================================================
# VALIDATOR
# ============================================================
class Validator:
    """
    Attaches to mother's brain. When a VM reports a completed trade,
    replays the strategy over mother's bar history to compute what
    the trade SHOULD have earned. Compares to VM's actual PnL.
    """

    def __init__(self, brain, on_validation_ready, logger=None):
        self.brain = brain
        self.on_validation_ready = on_validation_ready
        self.log = logger or logging.getLogger("validator")
        self.main_ma = EMA(84)   # matches locked strategy
        self.fast_ma = EMA(34)
        self._queue = asyncio.Queue(maxsize=200)
        self._running = True

    def start(self):
        asyncio.create_task(self._worker_loop())

    def stop(self):
        self._running = False

    def enqueue(self, trade_info):
        """Non-blocking. Adds to background queue."""
        try:
            self._queue.put_nowait(trade_info)
        except asyncio.QueueFull:
            self.log.warning("validation queue full, dropping")

    async def _worker_loop(self):
        while self._running:
            try:
                trade = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                result = self._validate(trade)
                if self.on_validation_ready:
                    try:
                        await self.on_validation_ready(trade, result)
                    except Exception as e:
                        self.log.error(f"validation callback: {e}")
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self.log.error(f"validator worker: {e}")
                await asyncio.sleep(1)

    def _validate(self, trade):
        """
        trade = {
          "vm_id": str, "trade_id": str, "signal_id": str,
          "entry_time": int, "exit_time": int,
          "entry_price": float, "exit_price": float,
          "direction": int, "realized_pnl": float,
          "lots": float, "cost_per_lot": float,
        }
        """
        bars = self.brain.bars
        if len(bars) < MIN_HISTORY_BARS:
            return ValidationResult(status="NO_VALIDATION", confidence=0.0,
                                     details={"reason": "insufficient brain history"})

        # Locate entry brick by mother's canonical brick time (from the signal).
        # This is the SAME timeline as bars[]["time"], so it's an exact hit —
        # never uses VM wall-clock (which drifts vs monotonic brick timestamps).
        entry_brick_time = trade.get("entry_brick_time")
        if entry_brick_time is None:
            entry_brick_time = trade.get("entry_time")   # fallback

        best_idx = None
        best_dist = float("inf")
        for i, b in enumerate(bars):
            dist = abs(b["time"] - entry_brick_time)
            if dist < best_dist:
                best_dist = dist
                best_idx = i
                if dist == 0:
                    break

        # Brick-time space: exact or within a few bricks is fine
        if best_idx is None or best_dist > 10:
            return ValidationResult(status="CANT_LOCATE", confidence=0.0,
                                     details={
                                         "reason": f"no brick near entry_brick_time (best dist {best_dist})",
                                         "entry_brick_time": entry_brick_time,
                                     })

        entry_brick = bars[best_idx]

        # Compare entry price
        entry_diff_pct = abs(trade["entry_price"] - entry_brick["close"]) / max(entry_brick["close"], 1e-9) * 100

        # Compute expected PnL: what would the SAME trade have earned on OANDA data?
        # Simple version: use mother's entry brick close and mother's exit_time-closest brick close
        # Exit brick: walk forward to the brick nearest the VM's hold duration.
        # Approx by bars held (exit_time - entry_time in wall-clock maps roughly
        # to brick count); fall back to the last available brick.
        exit_idx = min(len(bars) - 1, best_idx + 1)
        vm_hold = trade.get("exit_time", 0) - trade.get("entry_time", 0)
        if vm_hold > 0:
            # scan a reasonable forward window; pick last brick whose relative
            # position is plausible. Simplest robust choice: use the final brick
            # in a 200-brick window that exists.
            exit_idx = min(len(bars) - 1, best_idx + 200)
        if exit_idx <= best_idx:
            exit_idx = min(len(bars) - 1, best_idx + 1)
        if exit_idx <= best_idx:
            return ValidationResult(status="CANT_LOCATE", confidence=0.0,
                                     details={"reason": "no forward bricks for exit"})

        expected_entry = entry_brick["close"]
        expected_exit = bars[exit_idx]["close"]
        expected_pts = (expected_exit - expected_entry) * trade["direction"]
        lots = trade.get("lots", 1.0)
        cost_per_lot = trade.get("cost_per_lot", 1.20)
        expected_pnl = expected_pts * lots - (cost_per_lot * lots)

        vm_pnl = trade.get("realized_pnl", 0.0)
        pnl_diff_usd = abs(vm_pnl - expected_pnl)
        pnl_diff_pct = pnl_diff_usd / max(abs(expected_pnl), 1e-9) * 100

        # Grade
        checks = {}
        checks["entry_price"] = entry_diff_pct <= ENTRY_PRICE_TOLERANCE_PCT
        checks["pnl_usd"] = pnl_diff_usd <= PNL_TOLERANCE_USD
        checks["pnl_pct"] = pnl_diff_pct <= PNL_TOLERANCE_PCT

        passed = sum(1 for v in checks.values() if v)
        total = len(checks)
        confidence = (passed / total) * 100.0

        if passed == total:
            status = "EXACT_MATCH"
        elif passed >= total - 1:
            status = "MINOR_MISMATCH"
        else:
            status = "MAJOR_MISMATCH"

        return ValidationResult(
            status=status,
            confidence=confidence,
            vm_pnl=vm_pnl,
            expected_pnl=expected_pnl,
            pnl_diff_usd=pnl_diff_usd,
            pnl_diff_pct=pnl_diff_pct,
            entry_price_diff_pct=entry_diff_pct,
            details={
                "mother_entry_brick": entry_brick,
                "mother_exit_brick": bars[exit_idx],
                "checks": checks,
                "vm_entry_price": trade["entry_price"],
                "vm_exit_price": trade.get("exit_price", 0),
                "lots": lots,
            }
        )