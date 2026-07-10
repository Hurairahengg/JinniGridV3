# Repository Snapshot - Part 3 of 3

- Root folder: `/home/hurairahengg/Documents/JinniGridV3`
- You know my wholle Jinjnibacktester simulator thign whre ther is a UI bascially and then i can see  charst and stuff when i need to run simulatiosn liek i send simulatio nto my flask backend server it runs sims and then shows stast and stuff and i can load strategy and shit for now take a look we will be doing bug fixes and some validation and shit. udnerrtsnad each code and its role how it works and keep in ir conetxt i will ask u exactly wha tto do later code later duinerstood
- Total files indexed: `17`
- Files in this chunk: `6`
## Full Project Tree

```text
.gitignore
mother/config.json
mother/configs/vm1.json
mother/configs/vm2.json
mother/core/bars.py
mother/core/error_dedup.py
mother/core/strategy_brain.py
mother/core/validator.py
mother/main.py
mother/web/index.html
mother/web/script.js
mother/web/styles.css
readme.md
requirements.txt
vm/config.json
vm/main.py
vm/mt5_executor.py
```

## Files In This Chunk - Part 3

```text
mother/configs/vm1.json
mother/core/bars.py
mother/core/validator.py
mother/web/index.html
mother/web/styles.css
vm/mt5_executor.py
```

## File Contents


## FILE: `mother/config.json`

```json
{
  "dashboard_port": 8080,
  "fleet_port": 8765,
  "shared_secret": "jinni_grid_secret2347890",

  "mt5_source": {
    "path": null,
    "timeout_ms": 60000,
    "symbol": "US100",
    "brick_size": 8.0,
    "price_decimals": 2,
    "warmup_days": 3
  },

  "strategy": {
    "session_hours_cst": [8, 9, 10, 11, 12, 13, 14, 15, 16],
    "trading_days_utc_weekday": [0, 1, 2, 3, 4]
  },

  "signal": {
    "expiration_ms": 5000,
    "position_poll_interval_ms": 5000,
    "heartbeat_interval_ms": 5000,
    "vm_stale_after_sec": 30,
    "vm_offline_after_sec": 120,
    "startup_recovery_wait_sec": 15,
    "reconciliation_interval_sec": 60
  },

  "telegram": {
    "enabled": true,
    "bot_token": "7320016249:AAH9wV_QttEVNnzlWw5wiqIvjWNgC1TQ4ow",
    "chat_id": "-5448290084",
    "send_startup": true,
    "send_vm_online": true,
    "send_vm_offline": true,
    "send_every_trade": true,
    "send_errors": true,
    "error_cooldown_sec": 300,
    "error_max_burst": 3
  },

  "storage": {
    "db_path": "state/fleet.db",
    "config_history_dir": "state/config_history",
    "brick_buffer_size": 200
  },

  "logging": {
    "log_dir": "logs",
    "retention_days": 30
  }
}

---

## FILE: `mother/configs/vm1.json`

```json
{
  "vm_id": "vm1",
  "display_name": "Node 01",
  "symbol": "US100.cash",
  "cost_per_lot": 1.20,

  "mt5": {
    "path": null,
    "timeout_ms": 60000
  },

  "risk": {
    "risk_mode": "starting_balance",
    "starting_balance": 100000.0,
    "risk_pct": 0.4,
    "max_lots": 600.0,
    "min_lot": 0.01,
    "lot_step": 0.01,
    "max_daily_loss_usd": 5000.0,
    "max_open_positions": 1,
    "auto_halt_on_daily_loss": true
  }
}
```

---

## FILE: `mother/core/bars.py`

```python
"""
mother/core/bars.py — Renko brick engine.

Feed ticks one at a time. Returns list of newly-completed bricks per call.
Bit-for-bit compatible with backtest KokoCandleStreamer.
"""


class RenkoBuilder:
    def __init__(self, brick_size, price_decimals=2, rev_bricks=2.0, clean_mode=True):
        self.rs = float(brick_size)
        self.pd = int(price_decimals)
        self.rev_bricks = float(rev_bricks)
        self.clean_mode = bool(clean_mode)

        self.trend = 0
        self.level = None
        self._has_bar = False
        self._b_high = 0.0
        self._b_low = 0.0
        self._b_vol = 0.0
        self._last_ts = -1

    def feed_tick(self, ts, price, volume=0.0):
        ts = int(ts)
        p = float(price)
        v = float(volume)

        if not self._has_bar:
            self.level = round(round(p / self.rs) * self.rs, self.pd)
            self._b_high = self.level
            self._b_low = self.level
            self._b_vol = v
            self._has_bar = True
            return []

        self._b_vol += v
        if p > self._b_high:
            self._b_high = p
        if p < self._b_low:
            self._b_low = p

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

            else:
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
```

---

## FILE: `mother/core/validator.py`

```python
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
# HMA (same math as strategy_brain.py)
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
        self.main_hma = HMA(21)   # matches locked strategy
        self.fast_hma = HMA(14)
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

        # Locate entry brick in mother's bars by timestamp
        entry_time = trade["entry_time"]
        best_idx = None
        best_dist = float("inf")
        for i, b in enumerate(bars):
            dist = abs(b["time"] - entry_time)
            if dist < best_dist:
                best_dist = dist
                best_idx = i
            if b["time"] > entry_time + 300:  # 5 min after — stop searching
                break

        if best_idx is None or best_dist > 300:
            return ValidationResult(status="CANT_LOCATE", confidence=0.0,
                                     details={
                                         "reason": f"no matching brick within 5 min (best dist {best_dist}s)",
                                         "entry_time": entry_time,
                                     })

        entry_brick = bars[best_idx]

        # Compare entry price
        entry_diff_pct = abs(trade["entry_price"] - entry_brick["close"]) / max(entry_brick["close"], 1e-9) * 100

        # Compute expected PnL: what would the SAME trade have earned on OANDA data?
        # Simple version: use mother's entry brick close and mother's exit_time-closest brick close
        exit_time = trade.get("exit_time", int(time.time()))
        exit_idx = best_idx
        for j in range(best_idx, min(len(bars), best_idx + 200)):
            if bars[j]["time"] >= exit_time:
                exit_idx = j
                break

        if exit_idx <= best_idx:
            return ValidationResult(status="CANT_LOCATE", confidence=0.0,
                                     details={"reason": "exit brick not found"})

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
```

---

## FILE: `mother/web/index.html`

```html
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<meta name="theme-color" content="#08090c">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="mobile-web-app-capable" content="yes">
<meta name="format-detection" content="telephone=no">
<title>JinniGrid</title>
<link rel="stylesheet" href="styles.css">
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<script src="https://cdn.jsdelivr.net/npm/apexcharts@3.45.2/dist/apexcharts.min.js"></script>
</head>
<body>

<div id="app">

  <header id="topbar">
    <button class="icon-btn nav-toggle" id="nav-toggle" title="Toggle sidebar (\)" aria-label="Toggle sidebar">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12h18M3 6h18M3 18h18"/></svg>
    </button>
    <div class="brand" onclick="location.hash='#/overview'">
      <div class="brand-mark"></div>
      <span class="brand-name">JINNIGRID</span>
    </div>
    <div class="search-box" id="search-trigger" role="button" tabindex="0">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
      </svg>
      <span class="search-placeholder">Search anything…</span>
      <span class="search-kbd">⌘K</span>
    </div>
    <div id="topbar-stats">
      <div class="tb-stat">
        <div class="tb-stat-label">Total Balance</div>
        <div class="tb-stat-value" id="stat-balance">—</div>
      </div>
      <div class="tb-stat">
        <div class="tb-stat-label">Total PnL</div>
        <div class="tb-stat-value" id="stat-total-pnl">—</div>
      </div>
      <div class="tb-stat">
        <div class="tb-stat-label">Positions</div>
        <div class="tb-stat-value" id="stat-positions">—</div>
      </div>
      <div class="tb-stat">
        <div class="tb-stat-label">VMs</div>
        <div class="tb-stat-value" id="stat-vms">—</div>
      </div>
      <div class="status-badge" id="live-status"><span>connecting…</span></div>
      <div class="theme-wrap">
        <button class="icon-btn" id="theme-btn" title="Theme (T)" aria-label="Theme">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>
          </svg>
        </button>
        <div class="theme-menu" id="theme-menu">
          <div class="theme-menu-title">Theme</div>
          <div class="theme-option" data-theme="dark">
            <div class="theme-preview" style="background: linear-gradient(135deg, #08090c 50%, #6ea8ff 50%)"></div>
            <span>Dark</span>
          </div>
          <div class="theme-option" data-theme="midnight">
            <div class="theme-preview" style="background: linear-gradient(135deg, #0a0612 50%, #a78bfa 50%)"></div>
            <span>Midnight</span>
          </div>
          <div class="theme-option" data-theme="ocean">
            <div class="theme-preview" style="background: linear-gradient(135deg, #051822 50%, #06b6d4 50%)"></div>
            <span>Ocean</span>
          </div>
          <div class="theme-option" data-theme="forest">
            <div class="theme-preview" style="background: linear-gradient(135deg, #0a1410 50%, #10b981 50%)"></div>
            <span>Forest</span>
          </div>
          <div class="theme-option" data-theme="glass">
            <div class="theme-preview glass-preview"></div>
            <span>Glass</span>
          </div>
          <div class="theme-menu-divider"></div>
          <div class="theme-option" data-theme="light">
            <div class="theme-preview" style="background: linear-gradient(135deg, #ffffff 50%, #3b82f6 50%); border-color: #d1d5de"></div>
            <span>Light</span>
          </div>
          <div class="theme-option" data-theme="paper">
            <div class="theme-preview" style="background: linear-gradient(135deg, #faf7f2 50%, #92664c 50%); border-color: #d1d5de"></div>
            <span>Paper</span>
          </div>
          <div class="theme-option" data-theme="mint">
            <div class="theme-preview" style="background: linear-gradient(135deg, #f0fdf6 50%, #10b981 50%); border-color: #d1d5de"></div>
            <span>Mint</span>
          </div>
          <div class="theme-option" data-theme="sunset">
            <div class="theme-preview" style="background: linear-gradient(135deg, #1a0a1f 50%, #f97316 50%)"></div>
            <span>Sunset</span>
          </div>
        </div>
      </div>
    </div>
  </header>

  <nav id="nav-rail" aria-label="Primary navigation">
    <a class="nav-item" data-route="overview" tabindex="0">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="3" y="3" width="7" height="9"/><rect x="14" y="3" width="7" height="5"/>
        <rect x="14" y="12" width="7" height="9"/><rect x="3" y="16" width="7" height="5"/>
      </svg>
      <span class="nav-label">Dashboard</span>
      <span class="nav-tip">Dashboard</span>
    </a>
    <a class="nav-item" data-route="live" tabindex="0">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M3 3v18h18"/><path d="M7 14l4-4 4 4 5-6"/>
      </svg>
      <span class="nav-label">Live</span>
      <span class="nav-tip">Live Chart</span>
    </a>
    <a class="nav-item" data-route="trades" tabindex="0">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/>
        <line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/>
        <line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>
      </svg>
      <span class="nav-label">Trades</span>
      <span class="nav-tip">Trades</span>
    </a>
    <a class="nav-item" data-route="stats" tabindex="0">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/>
        <line x1="6" y1="20" x2="6" y2="14"/>
      </svg>
      <span class="nav-label">Portfolio</span>
      <span class="nav-tip">Portfolio</span>
    </a>
    <a class="nav-item" data-route="fleet" tabindex="0">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>
        <path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>
      </svg>
      <span class="nav-label">Fleet</span>
      <span class="nav-tip">Fleet</span>
    </a>
    <a class="nav-item" data-route="validation" tabindex="0">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>
      </svg>
      <span class="nav-label">Validation</span>
      <span class="nav-tip">Validation</span>
    </a>
    <a class="nav-item" data-route="logs" tabindex="0">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/>
        <line x1="16" y1="17" x2="8" y2="17"/>
      </svg>
      <span class="nav-label">Logs</span>
      <span class="nav-tip">Logs</span>
    </a>
    <a class="nav-item" data-route="config" tabindex="0">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <line x1="4" y1="21" x2="4" y2="14"/>
        <line x1="4" y1="10" x2="4" y2="3"/>
        <line x1="12" y1="21" x2="12" y2="12"/>
        <line x1="12" y1="8" x2="12" y2="3"/>
        <line x1="20" y1="21" x2="20" y2="16"/>
        <line x1="20" y1="12" x2="20" y2="3"/>
        <line x1="1" y1="14" x2="7" y2="14"/>
        <line x1="9" y1="8" x2="15" y2="8"/>
        <line x1="17" y1="16" x2="23" y2="16"/>
      </svg>
      <span class="nav-label">Settings</span>
      <span class="nav-tip">Settings</span>
    </a>
  </nav>

  <main id="main"></main>

  <aside class="detail-panel" id="detail-panel" aria-hidden="true">
    <div class="detail-header">
      <div class="detail-title" id="detail-title">Details</div>
      <button class="icon-btn" id="detail-close" aria-label="Close">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      </button>
    </div>
    <div class="detail-body" id="detail-body"></div>
  </aside>

  <div class="cmdk" id="cmdk" aria-hidden="true">
    <div class="cmdk-scrim" data-cmdk-close></div>
    <div class="cmdk-box">
      <div class="cmdk-input-wrap">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
        </svg>
        <input class="cmdk-input" id="cmdk-input" placeholder="Type to search commands, VMs, trades…" autocomplete="off">
        <span class="cmdk-hint">Esc</span>
      </div>
      <div class="cmdk-results" id="cmdk-results"></div>
    </div>
  </div>

  <div id="toast-container" aria-live="polite"></div>
</div>

<script src="script.js"></script>
</body>
</html>
```

---

## FILE: `mother/web/styles.css`

```css
/* ============================================================
   TOKENS & THEMES
   ============================================================ */

   /* ============================================================
   CONFIG EDITOR — bulletproof (no media query dependency)
   ============================================================ */
.config-editor {
  display: grid;
  grid-template-columns: 240px 1fr;
  gap: 16px;
  min-height: 500px;
}

.config-tabs {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.config-tab {
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--bg-1);
  border: 1px solid var(--border);
  cursor: pointer;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-dim);
  display: flex;
  align-items: center;
  gap: 8px;
  transition: all 200ms ease;
}

.config-tab:hover {
  border-color: var(--border-strong);
  color: var(--text);
}

.config-tab.active {
  background: var(--accent-dim);
  color: var(--accent);
  border-color: var(--accent);
}

.config-tab-icon {
  width: 16px;
  height: 16px;
  opacity: 0.7;
}

.config-panel {
  background: var(--bg-1);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
}

.config-panel-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 4px;
  color: var(--text);
}

.config-panel-desc {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 20px;
}

.config-field {
  display: grid;
  grid-template-columns: 1fr 260px;
  gap: 16px;
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
  align-items: center;
}

.config-field:last-child {
  border-bottom: none;
}

.config-field-label {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.config-field-name {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
}

.config-field-desc {
  font-size: 11px;
  color: var(--text-muted);
}

.config-field-input {
  width: 100%;
  padding: 8px 12px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: 6px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text);
  transition: all 200ms ease;
}

.config-field-input:hover {
  border-color: var(--border-strong);
}

.config-field-input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-dim);
}

.config-field-input.dirty,
.config-select.dirty {
  border-color: var(--yellow);
  background: var(--yellow-dim);
}

.config-select {
  width: 100%;
  padding: 8px 12px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: 6px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text);
  cursor: pointer;
}

.config-select:focus {
  outline: none;
  border-color: var(--accent);
}

.config-checkbox {
  width: 18px;
  height: 18px;
  accent-color: var(--accent);
  cursor: pointer;
}

.config-diff-panel {
  background: var(--bg-2);
  border: 1px solid var(--yellow-dim);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 16px;
  font-family: var(--font-mono);
  font-size: 11px;
}

.config-diff-title {
  color: var(--yellow);
  font-weight: 600;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.config-diff-row {
  padding: 4px 0;
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 12px;
  align-items: center;
}

.config-diff-key {
  color: var(--text-dim);
}

.config-diff-old {
  color: var(--red);
  text-decoration: line-through;
  opacity: 0.7;
}

.config-diff-new {
  color: var(--green);
}

:root {
  --font-sans: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', 'SF Mono', 'Menlo', 'Fira Code', monospace;

  --space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px;
  --space-5: 20px; --space-6: 24px; --space-8: 32px; --space-10: 40px;
  --space-12: 48px; --space-16: 64px;

  --radius-sm: 4px; --radius: 6px; --radius-lg: 10px; --radius-xl: 14px; --radius-2xl: 20px;

  --ease: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-out: cubic-bezier(0.4, 0, 0.2, 1);
  --spring: cubic-bezier(0.5, 1.5, 0.5, 1);

  --dur-fast: 120ms;
  --dur: 200ms;
  --dur-slow: 320ms;
  --dur-slower: 480ms;

  --nav-w: 60px;
  --nav-w-ex: 220px;
  --topbar-h: 60px;

  --font-display: 2.5rem;
  --font-h1: 1.5rem;
  --font-h2: 1.125rem;
  --font-body: 0.875rem;
  --font-caption: 0.75rem;
  --font-micro: 0.6875rem;
}

/* ---------- DARK (default) ---------- */
[data-theme="dark"] {
  --bg-0: #08090c;
  --bg-1: #0f1116;
  --bg-2: #171922;
  --bg-3: #1f2230;
  --bg-4: #262a3a;
  --border: #2a2e3e;
  --border-strong: #3a3f52;
  --text: #e6e8ee;
  --text-dim: #8b90a3;
  --text-muted: #5a5f72;
  --accent: #6ea8ff;
  --accent-hover: #8bb8ff;
  --accent-dim: rgba(110, 168, 255, 0.15);
  --accent-glow: rgba(110, 168, 255, 0.4);
  --green: #4ade80; --green-dim: rgba(74, 222, 128, 0.15);
  --red: #f87171; --red-dim: rgba(248, 113, 113, 0.15);
  --yellow: #fbbf24; --yellow-dim: rgba(251, 191, 36, 0.15);
  --purple: #c084fc; --cyan: #22d3ee;
  --shadow: 0 2px 8px rgba(0,0,0,0.4);
  --shadow-lg: 0 8px 24px rgba(0,0,0,0.5);
  --shadow-xl: 0 20px 40px rgba(0,0,0,0.6);
  --scrim: rgba(0,0,0,0.6);
}

/* ---------- MIDNIGHT ---------- */
[data-theme="midnight"] {
  --bg-0: #0a0612; --bg-1: #12091d; --bg-2: #1c0f2b; --bg-3: #26163a; --bg-4: #311c49;
  --border: #3a2258; --border-strong: #4e2c73;
  --text: #ede4f7; --text-dim: #a091b8; --text-muted: #6b5d80;
  --accent: #a78bfa; --accent-hover: #c4b5fd;
  --accent-dim: rgba(167, 139, 250, 0.15); --accent-glow: rgba(167, 139, 250, 0.5);
  --green: #22c55e; --green-dim: rgba(34, 197, 94, 0.15);
  --red: #ef4444; --red-dim: rgba(239, 68, 68, 0.15);
  --yellow: #eab308; --yellow-dim: rgba(234, 179, 8, 0.15);
  --purple: #d8b4fe; --cyan: #67e8f9;
  --shadow: 0 2px 8px rgba(0,0,0,0.5);
  --shadow-lg: 0 8px 24px rgba(0,0,0,0.6);
  --shadow-xl: 0 20px 40px rgba(0,0,0,0.7);
  --scrim: rgba(10, 6, 18, 0.75);
}

/* ---------- OCEAN ---------- */
[data-theme="ocean"] {
  --bg-0: #051822; --bg-1: #082633; --bg-2: #0d3646; --bg-3: #144659; --bg-4: #1c5a70;
  --border: #1e4a5e; --border-strong: #2a6580;
  --text: #e0f2fe; --text-dim: #7dd3fc; --text-muted: #6b96a8;
  --accent: #06b6d4; --accent-hover: #22d3ee;
  --accent-dim: rgba(6, 182, 212, 0.15); --accent-glow: rgba(6, 182, 212, 0.5);
  --green: #10b981; --green-dim: rgba(16, 185, 129, 0.15);
  --red: #f87171; --red-dim: rgba(248, 113, 113, 0.15);
  --yellow: #fcd34d; --yellow-dim: rgba(252, 211, 77, 0.15);
  --purple: #a78bfa; --cyan: #67e8f9;
  --shadow: 0 2px 8px rgba(0,0,0,0.4);
  --shadow-lg: 0 8px 24px rgba(0,0,0,0.5);
  --shadow-xl: 0 20px 40px rgba(0,0,0,0.6);
  --scrim: rgba(5, 24, 34, 0.7);
}

/* ---------- FOREST ---------- */
[data-theme="forest"] {
  --bg-0: #0a1410; --bg-1: #0f1e18; --bg-2: #172a20; --bg-3: #1f382b; --bg-4: #294a3a;
  --border: #294538; --border-strong: #3a5f4c;
  --text: #ecfdf5; --text-dim: #86efac; --text-muted: #5f8570;
  --accent: #10b981; --accent-hover: #34d399;
  --accent-dim: rgba(16, 185, 129, 0.15); --accent-glow: rgba(16, 185, 129, 0.5);
  --green: #22c55e; --green-dim: rgba(34, 197, 94, 0.15);
  --red: #f87171; --red-dim: rgba(248, 113, 113, 0.15);
  --yellow: #fcd34d; --yellow-dim: rgba(252, 211, 77, 0.15);
  --purple: #a78bfa; --cyan: #22d3ee;
  --shadow: 0 2px 8px rgba(0,0,0,0.4);
  --shadow-lg: 0 8px 24px rgba(0,0,0,0.5);
  --shadow-xl: 0 20px 40px rgba(0,0,0,0.6);
  --scrim: rgba(10, 20, 16, 0.7);
}

/* ---------- GLASS (frosted, semi-transparent) ---------- */
[data-theme="glass"] {
  --bg-0: #0a0f1e;
  --bg-1: rgba(30, 40, 70, 0.4);
  --bg-2: rgba(50, 60, 90, 0.35);
  --bg-3: rgba(80, 90, 130, 0.3);
  --bg-4: rgba(110, 120, 160, 0.25);
  --border: rgba(255,255,255,0.08);
  --border-strong: rgba(255,255,255,0.16);
  --text: #f0f4ff; --text-dim: #b0bad0; --text-muted: #7a8299;
  --accent: #7dd3fc; --accent-hover: #bae6fd;
  --accent-dim: rgba(125, 211, 252, 0.18); --accent-glow: rgba(125, 211, 252, 0.6);
  --green: #86efac; --green-dim: rgba(134, 239, 172, 0.2);
  --red: #fda4af; --red-dim: rgba(253, 164, 175, 0.2);
  --yellow: #fde68a; --yellow-dim: rgba(253, 230, 138, 0.2);
  --purple: #d8b4fe; --cyan: #67e8f9;
  --shadow: 0 4px 16px rgba(0,0,0,0.3);
  --shadow-lg: 0 12px 32px rgba(0,0,0,0.4);
  --shadow-xl: 0 24px 48px rgba(0,0,0,0.5);
  --scrim: rgba(10, 15, 30, 0.5);
}
[data-theme="glass"] body {
  background:
    radial-gradient(ellipse at top left, rgba(125, 211, 252, 0.15), transparent 50%),
    radial-gradient(ellipse at bottom right, rgba(167, 139, 250, 0.15), transparent 50%),
    linear-gradient(135deg, #0a0f1e, #1a1f3a);
  background-attachment: fixed;
}
[data-theme="glass"] .card,
[data-theme="glass"] #topbar,
[data-theme="glass"] #nav-rail,
[data-theme="glass"] .detail-panel,
[data-theme="glass"] .cmdk-box,
[data-theme="glass"] .theme-menu,
[data-theme="glass"] .search-box,
[data-theme="glass"] .kpi-card {
  backdrop-filter: blur(30px) saturate(1.5);
  -webkit-backdrop-filter: blur(30px) saturate(1.5);
  background: rgba(30, 40, 70, 0.4);
  border: 1px solid rgba(255,255,255,0.1);
}

/* ---------- LIGHT ---------- */
[data-theme="light"] {
  --bg-0: #ffffff; --bg-1: #f8f9fb; --bg-2: #eff1f5; --bg-3: #e4e7ee; --bg-4: #d8dde6;
  --border: #d1d5de; --border-strong: #b0b5c2;
  --text: #0f1116; --text-dim: #4a5060; --text-muted: #7a8090;
  --accent: #3b82f6; --accent-hover: #2563eb;
  --accent-dim: rgba(59, 130, 246, 0.12); --accent-glow: rgba(59, 130, 246, 0.3);
  --green: #16a34a; --green-dim: rgba(22, 163, 74, 0.12);
  --red: #dc2626; --red-dim: rgba(220, 38, 38, 0.12);
  --yellow: #ca8a04; --yellow-dim: rgba(202, 138, 4, 0.12);
  --purple: #9333ea; --cyan: #0891b2;
  --shadow: 0 2px 8px rgba(0,0,0,0.06);
  --shadow-lg: 0 8px 24px rgba(0,0,0,0.1);
  --shadow-xl: 0 20px 40px rgba(0,0,0,0.15);
  --scrim: rgba(0,0,0,0.4);
}

/* ---------- PAPER (warm light) ---------- */
[data-theme="paper"] {
  --bg-0: #faf7f2; --bg-1: #f4efe6; --bg-2: #ede5d5; --bg-3: #e0d4bd; --bg-4: #d1c1a4;
  --border: #d5c8b0; --border-strong: #a08670;
  --text: #2d2418; --text-dim: #6b5a45; --text-muted: #9c8770;
  --accent: #92664c; --accent-hover: #7a5539;
  --accent-dim: rgba(146, 102, 76, 0.15); --accent-glow: rgba(146, 102, 76, 0.3);
  --green: #4d7c0f; --green-dim: rgba(77, 124, 15, 0.15);
  --red: #b91c1c; --red-dim: rgba(185, 28, 28, 0.15);
  --yellow: #a16207; --yellow-dim: rgba(161, 98, 7, 0.15);
  --purple: #7c3aed; --cyan: #0e7490;
  --shadow: 0 2px 8px rgba(60,40,20,0.08);
  --shadow-lg: 0 8px 24px rgba(60,40,20,0.12);
  --shadow-xl: 0 20px 40px rgba(60,40,20,0.18);
  --scrim: rgba(0,0,0,0.4);
}

/* ---------- MINT (fresh light) ---------- */
[data-theme="mint"] {
  --bg-0: #f0fdf6; --bg-1: #e4f9ec; --bg-2: #d5f0dd; --bg-3: #b8e5c4; --bg-4: #97d6a7;
  --border: #c9e6d0; --border-strong: #86c19a;
  --text: #0a2f1a; --text-dim: #325742; --text-muted: #698775;
  --accent: #10b981; --accent-hover: #059669;
  --accent-dim: rgba(16, 185, 129, 0.15); --accent-glow: rgba(16, 185, 129, 0.4);
  --green: #16a34a; --green-dim: rgba(22, 163, 74, 0.15);
  --red: #dc2626; --red-dim: rgba(220, 38, 38, 0.15);
  --yellow: #ca8a04; --yellow-dim: rgba(202, 138, 4, 0.15);
  --purple: #7c3aed; --cyan: #0891b2;
  --shadow: 0 2px 8px rgba(30,80,50,0.08);
  --shadow-lg: 0 8px 24px rgba(30,80,50,0.12);
  --shadow-xl: 0 20px 40px rgba(30,80,50,0.18);
  --scrim: rgba(0,0,0,0.35);
}
/* ---------- SUNSET (warm) ---------- */
[data-theme="sunset"] {
  --bg-0: #1a0a1f; --bg-1: #2a1128; --bg-2: #3a1a34; --bg-3: #4c2542; --bg-4: #602f4f;
  --border: #4a2540; --border-strong: #6b3856;
  --text: #ffedd5; --text-dim: #fdba74; --text-muted: #a06d5e;
  --accent: #f97316; --accent-hover: #fb923c;
  --accent-dim: rgba(249, 115, 22, 0.15); --accent-glow: rgba(249, 115, 22, 0.5);
  --green: #22c55e; --green-dim: rgba(34, 197, 94, 0.15);
  --red: #ef4444; --red-dim: rgba(239, 68, 68, 0.15);
  --yellow: #eab308; --yellow-dim: rgba(234, 179, 8, 0.15);
  --purple: #f472b6; --cyan: #ec4899;
  --shadow: 0 2px 8px rgba(0,0,0,0.5);
  --shadow-lg: 0 8px 24px rgba(0,0,0,0.6);
  --shadow-xl: 0 20px 40px rgba(0,0,0,0.7);
  --scrim: rgba(26, 10, 31, 0.7);
}

/* ============================================================
   RESET
   ============================================================ */
* { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
html, body {
  height: 100%;
  overflow: hidden;
  background: var(--bg-0);
  color: var(--text);
  font-family: var(--font-sans);
  font-size: var(--font-body);
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  transition: background var(--dur-slow) var(--ease), color var(--dur-slow) var(--ease);
}
button, input, select, textarea { font: inherit; color: inherit; }
button { cursor: pointer; background: transparent; border: none; }
a { color: inherit; text-decoration: none; -webkit-user-select: none; user-select: none; }
::selection { background: var(--accent-dim); }
img, svg { display: block; max-width: 100%; }

/* Scrollbars */
* { scrollbar-width: thin; scrollbar-color: var(--border-strong) transparent; }
*::-webkit-scrollbar { width: 8px; height: 8px; }
*::-webkit-scrollbar-track { background: transparent; }
*::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 4px; }
*::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

/* ============================================================
   APP SHELL
   ============================================================ */
#app {
  display: grid;
  grid-template-rows: var(--topbar-h) 1fr;
  grid-template-columns: var(--nav-w) 1fr;
  height: 100vh;
  transition: grid-template-columns var(--dur-slow) var(--ease);
}
#app.nav-expanded { grid-template-columns: var(--nav-w-ex) 1fr; }

/* ============================================================
   TOP BAR
   ============================================================ */
#topbar {
  grid-column: 1 / -1;
  background: var(--bg-1);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  padding: 0 var(--space-4);
  gap: var(--space-3);
  z-index: 20;
  position: relative;
}
.brand {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 1px;
  color: var(--accent);
  padding: 0 var(--space-2);
  cursor: pointer;
  transition: color var(--dur) var(--ease), transform var(--dur) var(--ease);
}
.brand:hover { color: var(--accent-hover); transform: scale(1.02); }
.brand-mark {
  width: 6px;
  height: 22px;
  border-radius: 2px;
  background: linear-gradient(180deg, var(--accent), var(--purple));
  box-shadow: 0 0 12px var(--accent-glow);
  animation: brand-glow 2.5s ease-in-out infinite;
}
@keyframes brand-glow {
  0%, 100% { box-shadow: 0 0 8px var(--accent-glow); }
  50% { box-shadow: 0 0 20px var(--accent-glow); }
}
.search-box {
  flex: 1;
  max-width: 420px;
  height: 36px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  display: flex;
  align-items: center;
  padding: 0 var(--space-3);
  gap: var(--space-2);
  cursor: text;
  color: var(--text-muted);
  transition: all var(--dur) var(--ease);
}
.search-box:hover, .search-box:focus-visible {
  border-color: var(--accent);
  color: var(--text-dim);
  box-shadow: 0 0 0 3px var(--accent-dim);
  outline: none;
}
.search-placeholder {
  flex: 1;
  font-size: 13px;
}
.search-kbd {
  padding: 2px 6px;
  background: var(--bg-3);
  border: 1px solid var(--border);
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
}
#topbar-stats {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--space-5);
}
.tb-stat {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
}
.tb-stat-label {
  font-size: 9px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 1.5px;
  font-weight: 600;
}
.tb-stat-value {
  font-family: var(--font-mono);
  font-size: 14px;
  font-weight: 600;
  transition: color var(--dur) var(--ease);
}
.tb-stat-value.pos { color: var(--green); }
.tb-stat-value.neg { color: var(--red); }
.tb-stat-value.pulse { animation: value-pulse 500ms var(--ease); }
@keyframes value-pulse {
  0% { transform: scale(1); }
  50% { transform: scale(1.08); text-shadow: 0 0 20px var(--accent-glow); }
  100% { transform: scale(1); }
}

.status-badge {
  display: flex; align-items: center; gap: 6px;
  padding: 5px 12px;
  border-radius: 14px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--text-dim);
  transition: all var(--dur) var(--ease);
}
.status-badge::before {
  content: "";
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--text-muted);
}
.status-badge.connected {
  color: var(--green);
  border-color: var(--green-dim);
  background: var(--green-dim);
}
.status-badge.connected::before {
  background: var(--green);
  box-shadow: 0 0 8px var(--green);
  animation: dot-pulse 1.5s ease-in-out infinite;
}
.status-badge.disconnected {
  color: var(--red);
  border-color: var(--red-dim);
  background: var(--red-dim);
}
.status-badge.disconnected::before { background: var(--red); }
@keyframes dot-pulse {
  0%, 100% { opacity: 1; box-shadow: 0 0 6px currentColor; }
  50% { opacity: 0.5; box-shadow: 0 0 12px currentColor; }
}

.icon-btn {
  width: 36px; height: 36px;
  display: flex; align-items: center; justify-content: center;
  border-radius: var(--radius-lg);
  color: var(--text-dim);
  transition: all var(--dur) var(--ease);
  position: relative;
}
.icon-btn:hover, .icon-btn:focus-visible {
  background: var(--bg-2);
  color: var(--accent);
  transform: translateY(-1px);
  outline: none;
}
.icon-btn:active { transform: scale(0.9); }
.icon-btn svg { width: 18px; height: 18px; }

/* Theme menu */
.theme-wrap { position: relative; }
.theme-menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  background: var(--bg-1);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-xl);
  padding: var(--space-2);
  box-shadow: var(--shadow-lg);
  min-width: 200px;
  z-index: 60;
  opacity: 0;
  visibility: hidden;
  transform: translateY(-8px) scale(0.96);
  transition: opacity var(--dur) var(--ease), transform var(--dur) var(--ease), visibility 0s var(--dur);
}
.theme-menu.open {
  opacity: 1;
  visibility: visible;
  transform: translateY(0) scale(1);
  transition: opacity var(--dur) var(--ease), transform var(--dur) var(--ease), visibility 0s;
}
.theme-menu-title {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: var(--text-muted);
  padding: var(--space-2) var(--space-3) var(--space-1);
  font-weight: 600;
}
.theme-menu-divider {
  height: 1px;
  background: var(--border);
  margin: var(--space-1) var(--space-2);
}
.theme-option {
  display: flex; align-items: center; gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease);
  font-size: 13px;
}
.theme-option:hover { background: var(--bg-2); }
.theme-option.active {
  background: var(--accent-dim);
  color: var(--accent);
  font-weight: 600;
}
.theme-preview {
  width: 22px; height: 22px;
  border-radius: 50%;
  border: 2px solid var(--border);
  flex-shrink: 0;
  transition: transform var(--dur) var(--ease);
}
.theme-option:hover .theme-preview {
  transform: rotate(180deg);
}
.glass-preview {
  background: linear-gradient(135deg,
    rgba(125, 211, 252, 0.6) 0%,
    rgba(167, 139, 250, 0.6) 100%);
  backdrop-filter: blur(4px);
  border-color: rgba(255,255,255,0.3);
}

/* ============================================================
   NAV RAIL
   ============================================================ */
#nav-rail {
  order: 3 !important;
  position: sticky !important;
  bottom: 0 !important;
  left: 0 !important;
  right: 0 !important;
  width: 100% !important;
  height: calc(60px + env(safe-area-inset-bottom, 0px)) !important;
  padding: 4px 0 calc(4px + env(safe-area-inset-bottom, 0px)) 0 !important;
  display: flex !important;
  flex-direction: row !important;
  border-right: none !important;
  border-top: 1px solid var(--border) !important;
  gap: 0 !important;
  justify-content: space-around !important;
  align-items: flex-start !important;
  overflow-x: auto !important;
  overflow-y: hidden !important;
  background: var(--bg-1) !important;
  z-index: 30 !important;
  -webkit-overflow-scrolling: touch !important;
  flex-shrink: 0 !important;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 10px var(--space-3);
  border-radius: var(--radius-lg);
  color: var(--text-dim);
  transition: all var(--dur) var(--ease);
  cursor: pointer;
  position: relative;
  white-space: nowrap;
  overflow: hidden;
}
.nav-item:hover {
  background: var(--bg-2);
  color: var(--text);
  transform: translateX(2px);
}
.nav-item.active {
  background: var(--accent-dim);
  color: var(--accent);
}
.nav-item.active::before {
  content: "";
  position: absolute;
  left: -1px;
  top: 8px; bottom: 8px;
  width: 3px;
  background: var(--accent);
  border-radius: 0 2px 2px 0;
  box-shadow: 0 0 8px var(--accent-glow);
}
.nav-item svg { width: 20px; height: 20px; flex-shrink: 0; transition: transform var(--dur) var(--ease); }
.nav-item:hover svg { transform: scale(1.1); }
.nav-label {
  font-size: 13px; font-weight: 500;
  opacity: 0;
  transform: translateX(-4px);
  transition: all var(--dur) var(--ease);
}
#app.nav-expanded .nav-label {
  opacity: 1;
  transform: translateX(0);
}
.nav-tip {
  position: absolute;
  left: calc(100% + 12px);
  top: 50%;
  transform: translateY(-50%) scale(0.9);
  background: var(--bg-3);
  color: var(--text);
  padding: 5px 10px;
  border-radius: var(--radius);
  font-size: 12px;
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transition: opacity var(--dur) var(--ease), transform var(--dur) var(--ease);
  box-shadow: var(--shadow);
  border: 1px solid var(--border);
  z-index: 100;
}
.nav-item:hover .nav-tip {
  opacity: 1;
  transform: translateY(-50%) scale(1);
}
#app.nav-expanded .nav-tip { display: none; }

/* ============================================================
   MAIN
   ============================================================ */
#main {
  background: var(--bg-0);
  overflow-y: auto;
  overflow-x: hidden;
  position: relative;
}
.page {
  padding: var(--space-6);
  max-width: 1600px;
  margin: 0 auto;
  animation: page-enter var(--dur-slower) var(--ease);
}
@keyframes page-enter {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.page-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: var(--space-6);
  gap: var(--space-4);
  flex-wrap: wrap;
}
.page-title {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.3px;
}
.page-subtitle {
  color: var(--text-dim);
  font-size: 13px;
  margin-top: 2px;
}

/* ============================================================
   KPI CARDS
   ============================================================ */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-4);
  margin-bottom: var(--space-6);
}
.kpi-card {
  background: var(--bg-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  padding: var(--space-5);
  transition: all var(--dur) var(--ease);
  position: relative;
  overflow: hidden;
}
.kpi-card::before {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, transparent 40%, var(--accent-dim) 100%);
  opacity: 0;
  transition: opacity var(--dur) var(--ease);
  pointer-events: none;
}
.kpi-card:hover {
  border-color: var(--border-strong);
  transform: translateY(-3px);
  box-shadow: var(--shadow-lg);
}
.kpi-card:hover::before { opacity: 1; }
.kpi-label {
  font-size: 10px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 1.5px;
  font-weight: 600;
  margin-bottom: var(--space-2);
}
.kpi-value {
  font-family: var(--font-mono);
  font-size: 30px;
  font-weight: 700;
  letter-spacing: -0.5px;
  line-height: 1.1;
  margin-bottom: var(--space-2);
  transition: color var(--dur) var(--ease);
  position: relative;
  z-index: 1;
}
.kpi-value.pos { color: var(--green); }
.kpi-value.neg { color: var(--red); }
.kpi-sub {
  display: flex; align-items: center;
  gap: var(--space-2);
  font-size: 12px;
  color: var(--text-dim);
  position: relative;
  z-index: 1;
}
.kpi-sub .change { font-family: var(--font-mono); font-weight: 500; }
.kpi-sub .change.pos { color: var(--green); }
.kpi-sub .change.neg { color: var(--red); }
.kpi-sparkline {
  position: absolute;
  right: var(--space-3); top: var(--space-3);
  width: 80px; height: 30px;
  opacity: 0.6;
  transition: opacity var(--dur) var(--ease);
}
.kpi-card:hover .kpi-sparkline { opacity: 1; }

/* ============================================================
   CARDS & GRIDS
   ============================================================ */
.grid-2 {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}
.grid-3 {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}
.card {
  background: var(--bg-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  overflow: hidden;
  transition: all var(--dur) var(--ease);
}
.card:hover { border-color: var(--border-strong); }
.card-header {
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}
.card-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  letter-spacing: 0.2px;
}
.card-subtitle {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}
.card-body { padding: var(--space-4); }
.card-body.tight { padding: 0; }

.chart-container {
  height: 320px;
  width: 100%;
  position: relative;
}
.chart-container.tall { height: 480px; }
.chart-container.short { height: 220px; }
.chart-container canvas {
  display: block;
  width: 100% !important;
  height: 100% !important;
}
.chart-container.tall { height: 480px; }
.chart-container.short { height: 220px; }

/* ============================================================
   LIST / TABLE ROWS
   ============================================================ */
.list-compact { display: flex; flex-direction: column; }
.list-row {
  display: flex; align-items: center;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border);
  gap: var(--space-3);
  transition: background var(--dur-fast) var(--ease);
  cursor: pointer;
}
.list-row:hover {
  background: var(--bg-2);
  transform: translateX(2px);
}
.list-row:last-child { border-bottom: none; }

.node-row .node-name {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  min-width: 80px;
}
.node-status-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--text-muted);
  flex-shrink: 0;
}
.node-status-dot.trading,
.node-status-dot.online,
.node-status-dot.LIVE {
  background: var(--green);
  box-shadow: 0 0 6px var(--green);
  animation: dot-pulse 2s ease-in-out infinite;
}
.node-status-dot.warming_up,
.node-status-dot.warming,
.node-status-dot.IDLE {
  background: var(--yellow);
}
.node-status-dot.stale,
.node-status-dot.offline,
.node-status-dot.STALE {
  background: var(--red);
}
.node-status-dot.awaiting_config { background: var(--purple); }

.node-row .node-balance {
  flex: 1;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-dim);
}
.node-row .node-pnl {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  text-align: right;
}

.pos { color: var(--green); }
.neg { color: var(--red); }

.trade-row {
  display: grid;
  grid-template-columns: 50px 32px 30px 1fr auto 100px 100px;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border);
  align-items: center;
  font-family: var(--font-mono);
  font-size: 12px;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease);
}
.trade-row:hover {
  background: var(--bg-2);
  transform: translateX(2px);
}
.trade-row.selected {
  background: var(--accent-dim);
  border-left: 3px solid var(--accent);
  padding-left: calc(var(--space-4) - 3px);
}
.trade-id { color: var(--text-muted); font-size: 11px; }
.badge {
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.5px;
  text-align: center;
  display: inline-block;
}
.badge.WIN, .badge.win { background: var(--green-dim); color: var(--green); }
.badge.LOSS, .badge.loss { background: var(--red-dim); color: var(--red); }
.badge.EXACT_MATCH { background: var(--green-dim); color: var(--green); }
.badge.MINOR_MISMATCH { background: var(--yellow-dim); color: var(--yellow); }
.badge.MAJOR_MISMATCH, .badge.NO_SIGNAL { background: var(--red-dim); color: var(--red); }
.badge.CANT_LOCATE, .badge.NO_VALIDATION { background: var(--bg-3); color: var(--text-muted); }

.dir-arrow {
  font-weight: 700;
  text-align: center;
  font-size: 14px;
}
.dir-arrow.LONG { color: var(--green); }
.dir-arrow.SHORT { color: var(--red); }
.trade-time { color: var(--text-dim); font-size: 10px; }
.trade-price { font-size: 11px; color: var(--text-dim); text-align: right; }
.trade-pnl {
  text-align: right;
  font-weight: 700;
  font-size: 12px;
}
.trade-pnl.pos { color: var(--green); }
.trade-pnl.neg { color: var(--red); }

/* Activity items */
.activity-item {
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border);
  display: flex; gap: var(--space-3);
  align-items: flex-start;
  transition: background var(--dur-fast) var(--ease);
}
.activity-item:hover { background: var(--bg-2); }
.activity-icon {
  width: 30px; height: 30px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  font-size: 14px;
  transition: transform var(--dur) var(--ease);
}
.activity-item:hover .activity-icon { transform: scale(1.1); }
.activity-icon.trade { background: var(--accent-dim); color: var(--accent); }
.activity-icon.session { background: var(--yellow-dim); color: var(--yellow); }
.activity-icon.warn { background: var(--red-dim); color: var(--red); }
.activity-icon.info { background: var(--bg-3); color: var(--text-dim); }
.activity-content { flex: 1; min-width: 0; }
.activity-message {
  font-size: 12px;
  color: var(--text);
  line-height: 1.4;
}
.activity-meta {
  font-size: 10px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  margin-top: 2px;
}

/* ============================================================
   CHIP FILTERS
   ============================================================ */
.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
}
.chip {
  padding: 6px 14px;
  border-radius: 16px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-dim);
  cursor: pointer;
  transition: all var(--dur) var(--ease);
  user-select: none;
}
.chip:hover {
  color: var(--text);
  border-color: var(--border-strong);
  transform: translateY(-1px);
}
.chip.active {
  background: var(--accent);
  color: var(--bg-0);
  border-color: var(--accent);
  font-weight: 600;
  box-shadow: 0 4px 12px var(--accent-glow);
}

/* ============================================================
   DETAIL PANEL
   ============================================================ */
.detail-panel {
  position: fixed;
  top: var(--topbar-h);
  right: 0;
  bottom: 0;
  width: 420px;
  background: var(--bg-1);
  border-left: 1px solid var(--border);
  overflow-y: auto;
  transform: translateX(105%);
  transition: transform var(--dur-slow) var(--ease);
  z-index: 40;
  box-shadow: var(--shadow-xl);
}
.detail-panel.open {
  transform: translateX(0);
}
.detail-header {
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  position: sticky;
  top: 0;
  background: var(--bg-1);
  z-index: 1;
  backdrop-filter: blur(8px);
}
.detail-title {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 700;
  color: var(--accent);
  letter-spacing: 0.5px;
}
.detail-body { padding: var(--space-5); }
.detail-section { margin-bottom: var(--space-5); }
.detail-section-title {
  font-size: 10px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 1.5px;
  font-weight: 600;
  margin-bottom: var(--space-3);
}
.detail-row {
  display: flex;
  justify-content: space-between;
  padding: var(--space-2) 0;
  font-family: var(--font-mono);
  font-size: 12px;
  gap: var(--space-3);
  animation: detail-row-in 300ms var(--ease) both;
}
@keyframes detail-row-in {
  from { opacity: 0; transform: translateX(8px); }
  to { opacity: 1; transform: translateX(0); }
}
.detail-row .k { color: var(--text-muted); }
.detail-row .v { color: var(--text); font-weight: 500; text-align: right; word-break: break-all; }
.detail-row .v.pos { color: var(--green); }
.detail-row .v.neg { color: var(--red); }

/* ============================================================
   COMMAND PALETTE
   ============================================================ */
.cmdk {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 120px;
  opacity: 0;
  visibility: hidden;
  transition: opacity var(--dur) var(--ease), visibility 0s var(--dur);
}
.cmdk.open {
  opacity: 1;
  visibility: visible;
  transition: opacity var(--dur) var(--ease), visibility 0s;
}
.cmdk-scrim {
  position: absolute;
  inset: 0;
  background: var(--scrim);
  backdrop-filter: blur(6px);
}
.cmdk-box {
  position: relative;
  width: 90%;
  max-width: 640px;
  background: var(--bg-1);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-2xl);
  overflow: hidden;
  box-shadow: var(--shadow-xl);
  transform: scale(0.95) translateY(-8px);
  transition: transform var(--dur-slow) var(--spring);
}
.cmdk.open .cmdk-box { transform: scale(1) translateY(0); }
.cmdk-input-wrap {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--border);
}
.cmdk-input-wrap svg { width: 18px; height: 18px; color: var(--text-muted); flex-shrink: 0; }
.cmdk-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  font-size: 15px;
  color: var(--text);
  font-family: var(--font-sans);
}
.cmdk-input::placeholder { color: var(--text-muted); }
.cmdk-hint {
  padding: 2px 8px;
  background: var(--bg-3);
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
}
.cmdk-results {
  max-height: 420px;
  overflow-y: auto;
  padding: var(--space-2);
}
.cmdk-item {
  padding: var(--space-3) var(--space-4);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  cursor: pointer;
  border-radius: var(--radius);
  transition: background var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease);
}
.cmdk-item:hover, .cmdk-item.focused {
  background: var(--accent-dim);
  transform: translateX(4px);
}
.cmdk-item svg { width: 16px; height: 16px; color: var(--text-dim); flex-shrink: 0; }
.cmdk-item-label { flex: 1; font-size: 13px; }
.cmdk-item-hint {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
}
.cmdk-empty {
  padding: var(--space-8);
  text-align: center;
  color: var(--text-muted);
  font-size: 13px;
}

/* ============================================================
   TOASTS
   ============================================================ */
#toast-container {
  position: fixed;
  bottom: var(--space-6);
  right: var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  z-index: 80;
  pointer-events: none;
}
.toast {
  background: var(--bg-2);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-lg);
  padding: var(--space-3) var(--space-4);
  font-size: 13px;
  min-width: 260px;
  max-width: 380px;
  box-shadow: var(--shadow-lg);
  animation: toast-slide-in 400ms var(--spring);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  pointer-events: auto;
  position: relative;
  overflow: hidden;
}
.toast::before {
  content: "";
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 3px;
  background: var(--accent);
}
.toast.success { border-color: var(--green-dim); }
.toast.success::before { background: var(--green); }
.toast.error { border-color: var(--red-dim); }
.toast.error::before { background: var(--red); }
.toast.warning { border-color: var(--yellow-dim); }
.toast.warning::before { background: var(--yellow); }
.toast.info::before { background: var(--accent); }
.toast.leaving {
  animation: toast-slide-out 300ms var(--ease) forwards;
}
@keyframes toast-slide-in {
  from { transform: translateX(120%) scale(0.9); opacity: 0; }
  to { transform: translateX(0) scale(1); opacity: 1; }
}
@keyframes toast-slide-out {
  to { transform: translateX(120%) scale(0.9); opacity: 0; }
}

/* ============================================================
   FLEET NODE CARDS
   ============================================================ */
.node-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--space-4);
}
.node-card {
  background: var(--bg-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  padding: var(--space-5);
  cursor: pointer;
  transition: all var(--dur-slow) var(--ease);
  position: relative;
  overflow: hidden;
}
.node-card::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: linear-gradient(135deg, var(--accent-glow), transparent 60%);
  opacity: 0;
  transition: opacity var(--dur) var(--ease);
  pointer-events: none;
}
.node-card:hover {
  border-color: var(--accent);
  transform: translateY(-4px) scale(1.01);
  box-shadow: var(--shadow-lg);
}
.node-card:hover::after { opacity: 0.15; }
.node-card-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: var(--space-3);
  position: relative;
  z-index: 1;
}
.node-card-name {
  font-family: var(--font-mono);
  font-size: 14px;
  font-weight: 700;
  display: flex; align-items: center;
  gap: var(--space-2);
}
.node-card-balance {
  font-family: var(--font-mono);
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.5px;
  margin: var(--space-2) 0;
  position: relative;
  z-index: 1;
}
.node-card-chart {
  height: 70px;
  width: 100%;
  display: block;
  background: var(--bg-2);
  border-radius: var(--radius);
  margin: var(--space-3) 0;
  position: relative;
  z-index: 1;
}
.node-card-metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-2);
  font-family: var(--font-mono);
  font-size: 11px;
  position: relative;
  z-index: 1;
}
.node-card-metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.node-card-metric .lbl {
  color: var(--text-muted);
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 1px;
  font-weight: 600;
}
.node-card-metric .val {
  color: var(--text);
  font-weight: 600;
}
.node-card-metric .val.pos { color: var(--green); }
.node-card-metric .val.neg { color: var(--red); }
.node-card-actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--border);
  position: relative;
  z-index: 1;
}
.node-btn {
  flex: 1;
  padding: 6px 10px;
  border-radius: var(--radius);
  background: var(--bg-2);
  border: 1px solid var(--border);
  color: var(--text-dim);
  font-size: 11px;
  font-family: var(--font-mono);
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease);
}
.node-btn:hover {
  background: var(--bg-3);
  color: var(--text);
  border-color: var(--border-strong);
}
.node-btn.danger:hover {
  background: var(--red-dim);
  color: var(--red);
  border-color: var(--red);
}

/* ============================================================
   LIVE VIEW
   ============================================================ */
.live-container {
  height: calc(100vh - var(--topbar-h));
  position: relative;
  display: flex;
  flex-direction: column;
}
.live-toolbar {
  padding: var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--border);
  background: var(--bg-1);
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex-shrink: 0;
  flex-wrap: wrap;
}
.live-chart-wrap {
  flex: 1;
  position: relative;
  min-height: 0;
}
.ma-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  padding: 5px 10px;
  border-radius: var(--radius);
  user-select: none;
  transition: background var(--dur-fast) var(--ease);
}
.ma-toggle:hover { background: var(--bg-2); }
.ma-toggle input { accent-color: var(--accent); cursor: pointer; }
.ma-swatch {
  display: inline-block;
  width: 14px;
  height: 3px;
  border-radius: 2px;
}
.ma-swatch.main { background: var(--purple); }
.ma-swatch.fast { background: var(--cyan); }
.ma-toggle-label { font-size: 11px; font-family: var(--font-mono); }
.session-badge {
  padding: 5px 14px;
  border-radius: 16px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-dim);
}
.session-badge.active {
  color: var(--green);
  border-color: var(--green-dim);
  background: var(--green-dim);
}

/* ============================================================
   LOGS PAGE — bulletproof
   ============================================================ */
.log-detail-row {
  padding: 8px 16px;
  border-bottom: 1px solid var(--border);
  display: grid;
  grid-template-columns: 140px 90px 70px 80px 1fr;
  gap: 12px;
  font-family: var(--font-mono);
  font-size: 11px;
  align-items: start;
  transition: background 120ms ease;
  cursor: pointer;
  background: var(--bg-1);
}

.log-detail-row:hover {
  background: var(--bg-2);
}

.log-detail-row.expanded {
  background: var(--bg-2);
}

.log-detail-row.expanded .log-json {
  display: block !important;
}

.log-ts {
  color: var(--text-muted);
  font-size: 10px;
}

.log-type {
  background: var(--bg-3);
  color: var(--accent);
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.5px;
  text-align: center;
}

.log-vm-tag {
  color: var(--purple);
  font-size: 10px;
  padding: 2px 6px;
  background: var(--bg-3);
  border-radius: 3px;
  text-align: center;
}

.log-severity {
  font-weight: 700;
  font-size: 10px;
}

.log-severity.INFO { color: var(--text-dim); }
.log-severity.WARNING { color: var(--yellow); }
.log-severity.ERROR,
.log-severity.CRITICAL { color: var(--red); }

.log-msg {
  color: var(--text);
  word-break: break-word;
  line-height: 1.5;
}

.log-json {
  display: none;
  grid-column: 1 / -1;
  margin-top: 8px;
  padding: 10px;
  background: var(--bg-3);
  border-radius: 6px;
  color: var(--text-dim);
  font-size: 10px;
  white-space: pre-wrap;
  word-break: break-word;
}
/* ============================================================
   CONFIG JSON
   ============================================================ */
.config-json {
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: var(--space-4);
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text);
  overflow-x: auto;
  white-space: pre;
  line-height: 1.6;
}
.json-key { color: var(--accent); }
.json-string { color: var(--green); }
.json-number { color: var(--yellow); }
.json-bool { color: var(--purple); }

/* ============================================================
   EMPTY STATES
   ============================================================ */
.empty-state {
  padding: var(--space-12) var(--space-6);
  text-align: center;
  color: var(--text-muted);
}
.empty-icon {
  font-size: 40px;
  margin-bottom: var(--space-3);
  opacity: 0.4;
  animation: float 3s ease-in-out infinite;
}
@keyframes float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-6px); }
}
.empty-title {
  font-size: 15px;
  color: var(--text-dim);
  margin-bottom: var(--space-2);
}
.empty-msg {
  font-size: 12px;
  font-family: var(--font-mono);
}

/* ============================================================
   BUTTONS
   ============================================================ */
.btn {
  padding: 8px 16px;
  border-radius: var(--radius-lg);
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--dur) var(--ease);
  border: 1px solid var(--border);
  background: var(--bg-2);
  color: var(--text);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.btn:hover {
  transform: translateY(-1px);
  box-shadow: var(--shadow);
  border-color: var(--border-strong);
}
.btn:active { transform: translateY(0); }
.btn.primary {
  background: var(--accent);
  color: var(--bg-0);
  border-color: var(--accent);
  font-weight: 600;
}
.btn.primary:hover {
  background: var(--accent-hover);
  box-shadow: 0 4px 12px var(--accent-glow);
}
.btn.danger {
  background: var(--red);
  color: white;
  border-color: var(--red);
}

/* ============================================================
   STATUS PILLS
   ============================================================ */
.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  border-radius: 10px;
  font-size: 10px;
  font-family: var(--font-mono);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.status-pill.online, .status-pill.trading { background: var(--green-dim); color: var(--green); }
.status-pill.warming_up { background: var(--yellow-dim); color: var(--yellow); }
.status-pill.awaiting_config { background: var(--accent-dim); color: var(--accent); }
.status-pill.stale, .status-pill.offline { background: var(--red-dim); color: var(--red); }

/* ============================================================
   DESKTOP GUARD — ensure grid layout wins above 768px
   ============================================================ */
@media (min-width: 769px) {
  #app {
    display: grid !important;
    grid-template-rows: var(--topbar-h) 1fr !important;
    grid-template-columns: var(--nav-w) 1fr !important;
    flex-direction: unset !important;
  }
  #app.nav-expanded {
    grid-template-columns: var(--nav-w-ex) 1fr !important;
  }

  #topbar {
    grid-column: 1 / -1 !important;
    display: flex !important;
    position: relative !important;
    height: var(--topbar-h) !important;
    min-height: var(--topbar-h) !important;
  }

  #nav-rail {
    grid-row: 2 !important;
    grid-column: 1 !important;
    position: relative !important;
    display: flex !important;
    flex-direction: column !important;
    width: auto !important;
    height: auto !important;
    padding: var(--space-3) var(--space-1) !important;
    border-right: 1px solid var(--border) !important;
    border-top: none !important;
    order: unset !important;
    justify-content: flex-start !important;
    align-items: stretch !important;
  }

  .nav-item {
    flex-direction: row !important;
    justify-content: flex-start !important;
    padding: 10px var(--space-3) !important;
    max-width: none !important;
    min-width: 0 !important;
  }

  #main {
    grid-row: 2 !important;
    grid-column: 2 !important;
    order: unset !important;
  }

  .search-box {
    display: flex !important;
  }
  .nav-toggle {
    display: flex !important;
  }
}

/* ============================================================
   RESPONSIVE — TABLET
   ============================================================ */
@media (max-width: 1200px) {
  .kpi-grid { grid-template-columns: repeat(2, 1fr); }
  .grid-3 { grid-template-columns: repeat(2, 1fr); }
  #topbar-stats { gap: var(--space-3); }
  .tb-stat-value { font-size: 12px; }
}

@media (max-width: 900px) {
  .grid-2 { grid-template-columns: 1fr; }
  .grid-3 { grid-template-columns: 1fr; }
  .detail-panel { width: 340px; }
  .search-box { max-width: 240px; }
}
/* ============================================================
   RESPONSIVE — TABLET (901-1200px)
   ============================================================ */
@media (max-width: 1200px) {
  .kpi-grid { grid-template-columns: repeat(2, 1fr); }
  .grid-3 { grid-template-columns: repeat(2, 1fr); }
  #topbar-stats { gap: var(--space-3); }
  .tb-stat-value { font-size: 12px; }
}

@media (max-width: 900px) {
  .grid-2 { grid-template-columns: 1fr; }
  .grid-3 { grid-template-columns: 1fr; }
  .detail-panel { width: 340px; }
  .search-box { max-width: 240px; }
}

/* ============================================================
   RESPONSIVE — MOBILE (≤768px only)
   ============================================================ */
@media (max-width: 768px) {
  html, body {
    overflow-y: auto;
    overflow-x: hidden;
  }

  #app {
    display: flex !important;
    flex-direction: column !important;
    height: 100vh;
    height: 100dvh;
  }
  #app.nav-expanded {
    grid-template-columns: none !important;
  }

  #topbar {
    position: sticky;
    top: 0;
    z-index: 30;
    padding: 0 12px;
    gap: 8px;
    min-height: 52px;
    height: 52px;
    flex-shrink: 0;
    background: var(--bg-1);
    border-bottom: 1px solid var(--border);
    display: flex;
  }

  .nav-toggle {
    display: none !important;
  }

  .brand {
    flex-shrink: 0;
    padding: 0;
    font-size: 12px;
  }
  .brand-name {
    display: inline !important;
    font-size: 11px;
    letter-spacing: 0.5px;
  }
  .brand-mark {
    width: 4px;
    height: 18px;
  }

  .search-box {
    display: none !important;
  }

  #topbar-stats {
    gap: 6px;
    margin-left: auto;
    flex-wrap: nowrap;
    overflow: hidden;
  }
  .tb-stat {
    flex-shrink: 0;
  }
  .tb-stat:nth-child(n+3) {
    display: none;
  }
  .tb-stat-value {
    font-size: 11px;
  }
  .tb-stat-label {
    font-size: 8px;
    letter-spacing: 0.5px;
  }

  .status-badge {
    padding: 4px 6px;
    font-size: 10px;
  }
  .status-badge span {
    display: none;
  }

  .icon-btn {
    width: 32px;
    height: 32px;
  }
  .icon-btn svg {
    width: 16px;
    height: 16px;
  }

  #nav-rail {
    order: 3;
    position: sticky;
    bottom: 0;
    left: 0;
    right: 0;
    width: 100% !important;
    height: calc(60px + env(safe-area-inset-bottom, 0px));
    padding: 4px 0 calc(4px + env(safe-area-inset-bottom, 0px)) 0;
    flex-direction: row !important;
    border-right: none;
    border-top: 1px solid var(--border);
    gap: 0;
    justify-content: space-around;
    align-items: flex-start;
    overflow-x: auto;
    overflow-y: hidden;
    background: var(--bg-1);
    z-index: 30;
    -webkit-overflow-scrolling: touch;
    flex-shrink: 0;
  }

  #nav-rail .nav-item {
    flex-direction: column !important;
    gap: 2px !important;
    padding: 4px 8px !important;
    flex: 1 1 auto !important;
    justify-content: center !important;
    align-items: center !important;
    text-align: center !important;
    min-width: 50px !important;
    max-width: 80px !important;
    width: auto !important;
    height: auto !important;
    border-radius: 6px !important;
    white-space: nowrap !important;
  }
  #nav-rail .nav-item svg {
    width: 20px !important;
    height: 20px !important;
    flex-shrink: 0 !important;
  }
  #nav-rail .nav-item.active::before {
    top: -4px !important;
    bottom: auto !important;
    left: 25% !important;
    right: 25% !important;
    width: auto !important;
    height: 3px !important;
    border-radius: 0 0 2px 2px !important;
  }
  #nav-rail .nav-label {
    opacity: 1 !important;
    transform: none !important;
    display: inline !important;
    font-size: 9px !important;
    letter-spacing: 0.3px !important;
    font-weight: 500 !important;
  }
  #nav-rail .nav-tip {
    display: none !important;
  }
  #main {
    order: 2;
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    -webkit-overflow-scrolling: touch;
    background: var(--bg-0);
  }

  .page {
    padding: 12px;
    max-width: 100%;
  }
  .page-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
    margin-bottom: 16px;
  }
  .page-title { font-size: 18px; }
  .page-subtitle { font-size: 11px; }

  .kpi-grid {
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    margin-bottom: 16px;
  }
  .kpi-card {
    padding: 12px;
    border-radius: 10px;
  }
  .kpi-label { font-size: 9px; }
  .kpi-value {
    font-size: 20px;
    margin-bottom: 4px;
  }
  .kpi-sub { font-size: 10px; }
  .kpi-sparkline { display: none; }

  .card {
    border-radius: 10px;
    margin-bottom: 12px;
  }
  .card-header {
    padding: 12px;
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  .card-title { font-size: 12px; }
  .card-subtitle { font-size: 10px; }
  .card-body { padding: 12px; }

  .chip-row {
    flex-wrap: nowrap;
    overflow-x: auto;
    overflow-y: hidden;
    padding-bottom: 4px;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
  }
  .chip-row::-webkit-scrollbar {
    display: none;
  }
  .chip {
    flex-shrink: 0;
    padding: 4px 10px;
    font-size: 10px;
  }

  .trade-row {
    grid-template-columns: 40px 24px 22px 1fr 80px;
    gap: 6px;
    padding: 10px 12px;
    font-size: 10px;
  }
  .trade-row .trade-price {
    display: none;
  }
  .trade-id { font-size: 9px; }
  .trade-time { font-size: 9px; }
  .trade-pnl { font-size: 11px; }

  .log-row,
  .log-detail-row {
    grid-template-columns: 90px 60px 1fr;
    gap: 6px;
    padding: 8px 12px;
    font-size: 10px;
  }
  .log-detail-row .log-vm-tag,
  .log-detail-row .log-severity {
    display: none;
  }
  .log-ts { font-size: 9px; }

  .node-grid {
    grid-template-columns: 1fr;
    gap: 10px;
  }
  .node-card { padding: 14px; }
  .node-card-balance { font-size: 22px; }

  .detail-panel {
    width: 100%;
    top: 0;
    z-index: 100;
    height: 100vh;
    height: 100dvh;
  }
  .detail-header { padding: 12px; }
  .detail-body { padding: 12px; }
  .detail-title { font-size: 12px; }

  .cmdk { padding-top: 40px; }
  .cmdk-box {
    width: 95%;
    max-width: none;
  }
  .cmdk-input-wrap { padding: 12px; }
  .cmdk-input { font-size: 14px; }

  #toast-container {
    bottom: calc(76px + env(safe-area-inset-bottom, 0px));
    right: 12px;
    left: 12px;
  }
  .toast {
    min-width: 0;
    max-width: none;
    padding: 10px 14px;
    font-size: 12px;
  }

  .live-container {
    height: calc(100vh - 52px - 60px - env(safe-area-inset-bottom, 0px));
    height: calc(100dvh - 52px - 60px - env(safe-area-inset-bottom, 0px));
  }
  .live-toolbar {
    padding: 8px 12px;
    gap: 8px;
    flex-wrap: wrap;
  }
  .live-toolbar .card-title { font-size: 12px; }
  .ma-toggle {
    padding: 4px 8px;
    font-size: 10px;
  }
  .session-badge {
    padding: 4px 8px;
    font-size: 10px;
  }

  .theme-menu {
    position: fixed;
    top: 52px;
    left: 12px;
    right: 12px;
    min-width: auto;
    max-width: none;
  }

  .config-editor {
    grid-template-columns: 1fr;
    gap: 12px;
  }
  .config-tabs {
    flex-direction: row;
    overflow-x: auto;
    gap: 6px;
    padding-bottom: 4px;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
  }
  .config-tabs::-webkit-scrollbar {
    display: none;
  }
  .config-tab {
    flex-shrink: 0;
    padding: 8px 12px;
    font-size: 11px;
  }
  .config-panel { padding: 12px; }
  .config-field {
    grid-template-columns: 1fr;
    gap: 6px;
    padding: 10px 0;
  }
  .config-field-input,
  .config-select {
    font-size: 12px;
    padding: 8px 10px;
  }

  .unlock-modal-box {
    min-width: 0;
    width: 90%;
    max-width: 340px;
    padding: 24px;
  }
}

/* Very small phones */
@media (max-width: 380px) {
  .kpi-grid { grid-template-columns: 1fr; }
  .brand-name { display: none !important; }
  #topbar-stats .tb-stat:nth-child(n+2) { display: none; }
  .nav-item {
    min-width: 42px;
    padding: 4px 4px;
  }
  .nav-label { font-size: 8px; }
  .page-title { font-size: 16px; }
}

/* ============================================================
   PRINT
   ============================================================ */
@media print {
  #nav-rail,
  #topbar,
  .detail-panel,
  .cmdk,
  #toast-container {
    display: none !important;
  }
  #main { overflow: visible; }
  .card { break-inside: avoid; }
}

.page-header .btn,
.page-header .btn.primary {
  display: inline-flex !important;
  visibility: visible !important;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 8px;
  cursor: pointer;
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 500;
  transition: all 200ms ease;
  border: 1px solid var(--border);
  background: var(--bg-2);
  color: var(--text);
}

.page-header .btn.primary {
  background: var(--accent);
  color: var(--bg-0);
  border-color: var(--accent);
  font-weight: 600;
}

.page-header .btn:hover {
  transform: translateY(-1px);
  box-shadow: var(--shadow);
}

.page-header .btn.primary:hover {
  background: var(--accent-hover);
  box-shadow: 0 4px 12px var(--accent-glow);
}

.page-header .btn:disabled,
.page-header .btn.primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  pointer-events: none;
}

/* ============================================================
   UNLOCK MODAL
   ============================================================ */
.unlock-modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 200;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 200ms ease;
}

.unlock-modal-overlay.open {
  opacity: 1;
}

.unlock-modal-box {
  background: var(--bg-1);
  border: 1px solid var(--border-strong);
  border-radius: 16px;
  padding: 28px;
  min-width: 340px;
  max-width: 400px;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.6);
  transform: scale(0.95);
  transition: transform 320ms cubic-bezier(0.5, 1.5, 0.5, 1);
}

.unlock-modal-overlay.open .unlock-modal-box {
  transform: scale(1);
}

.unlock-modal-title {
  font-size: 17px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 6px;
  text-align: center;
}

.unlock-modal-subtitle {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 24px;
  text-align: center;
}

.unlock-modal-input {
  width: 100%;
  padding: 12px 14px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: 10px;
  font-family: var(--font-mono);
  font-size: 14px;
  color: var(--text);
  margin-bottom: 20px;
  outline: none;
  transition: all 200ms ease;
  letter-spacing: 4px;
}

.unlock-modal-input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-dim);
  background: var(--bg-3);
}

.unlock-modal-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}

.unlock-modal-actions .btn {
  padding: 8px 20px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid var(--border);
  background: var(--bg-2);
  color: var(--text);
  font-family: var(--font-sans);
  transition: all 200ms ease;
}

.unlock-modal-actions .btn:hover {
  background: var(--bg-3);
  transform: translateY(-1px);
}

.unlock-modal-actions .btn.primary {
  background: var(--accent);
  color: var(--bg-0);
  border-color: var(--accent);
  font-weight: 600;
}

.unlock-modal-actions .btn.primary:hover {
  background: var(--accent-hover);
}

/* ============================================================
   UNLOCK MODAL
   ============================================================ */
.unlock-modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 200;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 200ms ease;
}

.unlock-modal-overlay.open { opacity: 1; }

.unlock-modal-box {
  background: var(--bg-1);
  border: 1px solid var(--border-strong);
  border-radius: 16px;
  padding: 28px;
  min-width: 340px;
  max-width: 400px;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.6);
  transform: scale(0.95);
  transition: transform 320ms cubic-bezier(0.5, 1.5, 0.5, 1);
}

.unlock-modal-overlay.open .unlock-modal-box { transform: scale(1); }

.unlock-modal-title {
  font-size: 17px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 6px;
  text-align: center;
}

.unlock-modal-subtitle {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 24px;
  text-align: center;
}

.unlock-modal-input {
  width: 100%;
  padding: 12px 14px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: 10px;
  font-family: var(--font-mono);
  font-size: 14px;
  color: var(--text);
  margin-bottom: 20px;
  outline: none;
  transition: all 200ms ease;
  letter-spacing: 4px;
}

.unlock-modal-input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-dim);
  background: var(--bg-3);
}

.unlock-modal-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}

.unlock-modal-actions .btn {
  padding: 8px 20px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid var(--border);
  background: var(--bg-2);
  color: var(--text);
  font-family: var(--font-sans);
  transition: all 200ms ease;
}

.unlock-modal-actions .btn:hover {
  background: var(--bg-3);
  transform: translateY(-1px);
}

.unlock-modal-actions .btn.primary {
  background: var(--accent);
  color: var(--bg-0);
  border-color: var(--accent);
  font-weight: 600;
}

.unlock-modal-actions .btn.primary:hover {
  background: var(--accent-hover);
}

.db-trade-row:hover {
  background: var(--bg-3) !important;
}

.btn.danger {
  background: var(--red-dim);
  color: var(--red);
  border-color: var(--red-dim);
}

.btn.danger:hover {
  background: var(--red);
  color: var(--bg-0);
}

/* ============================================================
   TRADING CALENDAR
   ============================================================ */
.cal-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 4px;
}

.cal-header-cell {
  padding: 8px;
  text-align: center;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 1.5px;
  font-weight: 600;
}

.cal-cell {
  aspect-ratio: 1 / 0.85;
  padding: 6px 8px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--bg-2);
  display: flex;
  flex-direction: column;
  cursor: pointer;
  transition: all 150ms ease;
  min-height: 60px;
}

.cal-cell:not(.cal-empty):hover {
  border-color: var(--accent);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.cal-cell.cal-empty {
  cursor: default;
  background: transparent;
  border: 1px dashed var(--border);
  opacity: 0.3;
}

.cal-cell.cal-today {
  border-color: var(--accent);
  border-width: 2px;
  box-shadow: 0 0 0 2px var(--accent-dim);
}

.cal-cell.cal-has-trades {
  cursor: pointer;
}

.cal-date {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text);
  font-weight: 700;
}

.cal-pnl {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 700;
  margin-top: 4px;
}

.cal-count {
  font-family: var(--font-mono);
  font-size: 9px;
  color: var(--text-muted);
  margin-top: 2px;
  text-transform: uppercase;
}

.cal-empty-cell {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
  opacity: 0.4;
  margin-top: auto;
  margin-bottom: auto;
  text-align: center;
}

.cal-stat-box {
  background: var(--bg-1);
  padding: 10px 12px;
  border-radius: 6px;
  border: 1px solid var(--border);
  text-align: center;
}

.cal-stat-label {
  font-size: 9px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 1px;
  font-weight: 600;
  margin-bottom: 4px;
}

.cal-stat-value {
  font-family: var(--font-mono);
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
}

.cal-stat-value.pos { color: var(--green); }
.cal-stat-value.neg { color: var(--red); }

/* Calendar mobile */
  .cal-cell {
    min-height: 44px;
    padding: 3px 4px;
  }
  .cal-date { font-size: 10px; }
  .cal-pnl { font-size: 9px; margin-top: 2px; }
  .cal-count { font-size: 8px; }
  .cal-header-cell {
    padding: 4px 0;
    font-size: 9px;
    letter-spacing: 0.5px;
  }
  .cal-stat-box { padding: 8px 6px; }
  .cal-stat-label { font-size: 8px; }
  .cal-stat-value { font-size: 12px; }

  #cal-month-label { min-width: 100px !important; font-size: 11px !important; }
  #cal-today { font-size: 10px !important; padding: 4px 8px !important; }

  /* Card header stacks vertically on mobile */
  .card-header {
    align-items: stretch !important;
  }
```

---

## FILE: `vm/mt5_executor.py`

```python
"""
vm/mt5_executor.py — Clean MT5 order wrappers.

Rules:
  - Every function returns (ok: bool, result_dict: dict)
  - Never raises unless MT5 itself is dead
  - Never retries infinitely — max 1 retry then report error
  - Result dict includes actual fill data + slippage
"""
import logging
import time

import MetaTrader5 as mt5


log = logging.getLogger("mt5_exec")


MAGIC_NUMBER = 900001
DEVIATION = 20


def _last_error():
    try:
        return mt5.last_error()
    except Exception:
        return (0, "unknown")


def get_symbol_info(symbol):
    return mt5.symbol_info(symbol)


def get_tick(symbol):
    return mt5.symbol_info_tick(symbol)


def open_position(symbol, direction, lots, sl_distance_pts, signal_id="", magic=MAGIC_NUMBER):
    """
    Open market position at broker's current bid/ask.
    Comment field is tagged with signal_id for recovery linkage.
    """
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return False, {"error_code": -1, "error_message": f"No tick for {symbol}"}

    if direction == 1:
        entry_price = float(tick.ask)
        sl_price = round(entry_price - sl_distance_pts, 5)
        order_type = mt5.ORDER_TYPE_BUY
    else:
        entry_price = float(tick.bid)
        sl_price = round(entry_price + sl_distance_pts, 5)
        order_type = mt5.ORDER_TYPE_SELL

    info = mt5.symbol_info(symbol)
    if info is not None and info.trade_stops_level > 0:
        min_stop_pts = info.trade_stops_level * info.point
        if sl_distance_pts < min_stop_pts:
            return False, {
                "error_code": -2,
                "error_message": f"SL distance {sl_distance_pts} < broker min {min_stop_pts}",
                "sl_distance": sl_distance_pts,
                "broker_min": min_stop_pts,
            }

    # Tag comment with signal_id for recovery linkage
    # MT5 comments are max ~31 chars
    if signal_id:
        comment = f"jg:{signal_id[:24]}"
    else:
        comment = "JinniGrid V4"

    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(lots),
        "type": order_type,
        "price": entry_price,
        "sl": sl_price,
        "tp": 0.0,
        "deviation": DEVIATION,
        "magic": magic,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(req)
    if result is None:
        err = _last_error()
        return False, {"error_code": err[0], "error_message": err[1], "retcode": None}

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return False, {
            "error_code": result.retcode,
            "error_message": f"retcode {result.retcode}",
            "retcode": result.retcode,
        }

    actual_fill = float(result.price)
    slippage = abs(actual_fill - entry_price)

    return True, {
        "ticket": int(result.order),
        "fill_price": actual_fill,
        "sl_price": sl_price,
        "actual_lots": float(result.volume),
        "slippage_pts": slippage,
    }



def modify_sl(symbol, ticket, new_sl_price):
    """
    Modify SL of an open position.
    Only sends if new_sl_price is strictly more favorable than current SL.
    Returns (True, {"new_sl": float}) or (False, {"error": ...})
    """
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        return False, {"error_message": f"Position {ticket} not found"}

    pos = positions[0]
    current_sl = pos.sl
    direction = 1 if pos.type == mt5.POSITION_TYPE_BUY else -1

    # Only move SL in favorable direction
    if direction == 1 and new_sl_price <= current_sl:
        return True, {"new_sl": current_sl, "unchanged": True}
    if direction == -1 and new_sl_price >= current_sl:
        return True, {"new_sl": current_sl, "unchanged": True}

    # Verify broker min stop
    info = mt5.symbol_info(symbol)
    if info is not None and info.trade_stops_level > 0:
        tick = mt5.symbol_info_tick(symbol)
        if tick is not None:
            cur_price = tick.bid if direction == 1 else tick.ask
            min_stop = info.trade_stops_level * info.point
            dist = abs(cur_price - new_sl_price)
            if dist < min_stop:
                return False, {
                    "error_message": f"New SL too close to price: {dist} < {min_stop}",
                }

    req = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": symbol,
        "position": int(ticket),
        "sl": float(new_sl_price),
        "tp": 0.0,
    }
    result = mt5.order_send(req)
    if result is None:
        err = _last_error()
        return False, {"error_code": err[0], "error_message": err[1]}

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return False, {
            "error_code": result.retcode,
            "error_message": f"retcode {result.retcode}",
        }

    return True, {"new_sl": new_sl_price}


def close_position(symbol, ticket):
    """
    Close position at market.
    Returns (True, {"exit_price": float, "realized_pnl": float}) or error.
    """
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        return False, {"error_message": f"Position {ticket} not found (already closed?)"}

    pos = positions[0]
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return False, {"error_message": "No tick"}

    direction = 1 if pos.type == mt5.POSITION_TYPE_BUY else -1
    exit_price = float(tick.bid) if direction == 1 else float(tick.ask)
    close_type = mt5.ORDER_TYPE_SELL if direction == 1 else mt5.ORDER_TYPE_BUY

    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(pos.volume),
        "type": close_type,
        "position": int(ticket),
        "price": exit_price,
        "deviation": DEVIATION,
        "magic": MAGIC_NUMBER,
        "comment": "JinniGrid V3 close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(req)
    if result is None:
        err = _last_error()
        return False, {"error_code": err[0], "error_message": err[1]}

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return False, {
            "error_code": result.retcode,
            "error_message": f"retcode {result.retcode}",
        }

    return True, {
        "exit_price": float(result.price),
        "realized_pnl": float(pos.profit),
    }


def get_open_positions(magic=MAGIC_NUMBER, symbol=None):
    """
    Query open positions from MT5.
    Extracts signal_id from comment field if tagged with "jg:" prefix.
    """
    if symbol:
        positions = mt5.positions_get(symbol=symbol)
    else:
        positions = mt5.positions_get()

    if positions is None:
        return []

    result = []
    for p in positions:
        if p.magic != magic:
            continue
        # Extract signal_id from comment if present
        signal_id = None
        if p.comment and p.comment.startswith("jg:"):
            signal_id = p.comment[3:]
        result.append({
            "ticket": int(p.ticket),
            "symbol": p.symbol,
            "direction": 1 if p.type == mt5.POSITION_TYPE_BUY else -1,
            "volume": float(p.volume),
            "open_price": float(p.price_open),
            "current_sl": float(p.sl),
            "current_price": float(p.price_current),
            "unrealized_pnl": float(p.profit),
            "open_time": int(p.time),
            "comment": p.comment,
            "signal_id": signal_id,
        })
    return result

def get_recent_deals(from_ts, magic=MAGIC_NUMBER):
    """
    Query closed deals since from_ts. Returns list of dict.
    Used to detect positions that closed locally (SL hit) without our command.
    """
    now = int(time.time())
    from time import gmtime
    from datetime import datetime, timezone
    deals = mt5.history_deals_get(
        datetime.fromtimestamp(from_ts, tz=timezone.utc),
        datetime.fromtimestamp(now, tz=timezone.utc),
    )
    if deals is None:
        return []
    result = []
    for d in deals:
        if d.magic != magic:
            continue
        result.append({
            "ticket": int(d.ticket),
            "position_id": int(d.position_id),
            "symbol": d.symbol,
            "type": int(d.type),
            "volume": float(d.volume),
            "price": float(d.price),
            "profit": float(d.profit),
            "time": int(d.time),
            "comment": d.comment,
        })
    return result
```
