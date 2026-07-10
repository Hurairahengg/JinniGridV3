# Repository Snapshot - Part 1 of 3

- Root folder: `/home/hurairahengg/Documents/JinniGridV3`
- okay so i will give u ALL the codes in chunk with my full jinnig rid code base u already coded this way back in the convo so first wait for all the chunks so u get the full codebase then u will after i tell u what to do fix some erros, update the strategy with our ne strategy and yeah heres chunk 1 
- Total files indexed: `17`
- Files in this chunk: `8`
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

## Files In This Chunk - Part 1

```text
.gitignore
mother/configs/vm2.json
mother/core/error_dedup.py
mother/main.py
readme.md
requirements.txt
vm/config.json
vm/main.py
```

## File Contents


---

## FILE: `.gitignore`

```text
# Python
__pycache__/
*.pyc
*.pyo
*.pyd
.venv/
venv/
env/

#state
mother/state/*.db
mother/state/*.db-journal
mother/state/config_history/
vm/state.db
vm/state.db-journal

*.log
mother/logs/
vm/logs/

```

---

## FILE: `mother/configs/vm2.json`

```json
{
  "vm_id": "vm2",
  "display_name": "Node 02",
  "symbol": "USTEC",
  "cost_per_lot": 1.20,

  "mt5": {
    "path": null,
    "timeout_ms": 60000
  },

  "risk": {
    "risk_mode": "current_balance",
    "starting_balance": 3300.0,
    "risk_pct": 4.0,
    "max_lots": 600.0,
    "min_lot": 0.01,
    "lot_step": 0.01,
    "max_daily_loss_usd": 3300.0,
    "max_open_positions": 1,
    "auto_halt_on_daily_loss": true
  }
}
```

---

## FILE: `mother/core/error_dedup.py`

```python
"""
mother/core/error_dedup.py — Kill error spam once and for all.

Circuit breaker + rate limiter + dedup for Telegram/dashboard error paths.
Never blocks. Never spams. If broken, it fails silently rather than DoS'ing you.
"""
import asyncio
import hashlib
import logging
import time
from collections import defaultdict


class ErrorDedup:
    """
    Tracks error events with (source, error_key) buckets.

    Rules:
      - First error: fire immediately
      - 2nd-Nth error within cooldown: suppress
      - After cooldown expires: send ONE summary "muted N errors, resetting"
      - If burst > max_burst within cooldown, circuit-break that path for cooldown

    Non-blocking: uses asyncio queue for outbound. Overflow → drop silently.
    """

    def __init__(self, cooldown_sec=300, max_burst=3, max_queue=500, logger=None):
        self.cooldown = cooldown_sec
        self.max_burst = max_burst
        self.log = logger or logging.getLogger("dedup")
        self._buckets = {}  # (source, key) -> {"first": ts, "last": ts, "count": n, "broken": bool}
        self._outbound = asyncio.Queue(maxsize=max_queue)
        self._sender = None
        self._running = True
        self._send_fn = None

    def bind_sender(self, send_fn):
        """Register the actual send function (e.g. telegram send)."""
        self._send_fn = send_fn

    def start(self):
        """Start the background sender task."""
        if self._sender is None:
            self._sender = asyncio.create_task(self._sender_loop())

    def stop(self):
        self._running = False

    def _hash_key(self, msg):
        return hashlib.md5((msg or "")[:200].encode()).hexdigest()[:12]

    def _dedupe_key(self, source, category, msg):
        return (source or "?", category, self._hash_key(msg))

    def emit(self, source, category, message, level="ERROR"):
        """
        Non-blocking. Returns immediately.
        Enqueues send job if not deduped/broken.
        """
        try:
            key = self._dedupe_key(source, category, message)
            now = time.time()
            bucket = self._buckets.get(key)

            if bucket is None:
                self._buckets[key] = {"first": now, "last": now, "count": 1, "broken": False}
                self._enqueue({
                    "source": source,
                    "category": category,
                    "message": message,
                    "level": level,
                    "count": 1,
                })
                return

            elapsed = now - bucket["first"]
            bucket["count"] += 1
            bucket["last"] = now

            if elapsed < self.cooldown:
                if bucket["count"] > self.max_burst and not bucket["broken"]:
                    bucket["broken"] = True
                    self._enqueue({
                        "source": source,
                        "category": "circuit_breaker",
                        "message": f"🔒 CIRCUIT BREAKER: {source} {category} — muting for {self.cooldown}s ({bucket['count']} bursts)",
                        "level": "WARNING",
                        "count": bucket["count"],
                    })
                return

            # Cooldown expired
            count = bucket["count"]
            self._buckets[key] = {"first": now, "last": now, "count": 1, "broken": False}
            if count > self.max_burst:
                self._enqueue({
                    "source": source,
                    "category": category,
                    "message": f"{message}\n<i>({count}× in last {int(elapsed)}s, muting cleared)</i>",
                    "level": level,
                    "count": count,
                })
            else:
                self._enqueue({
                    "source": source,
                    "category": category,
                    "message": message,
                    "level": level,
                    "count": count,
                })

        except Exception as e:
            self.log.warning(f"emit failed silently: {e}")

    def _enqueue(self, payload):
        try:
            self._outbound.put_nowait(payload)
        except asyncio.QueueFull:
            self.log.debug("dedup queue full, dropping message")

    async def _sender_loop(self):
        while self._running:
            try:
                payload = await asyncio.wait_for(self._outbound.get(), timeout=1.0)
                if self._send_fn is None:
                    continue
                try:
                    await self._send_fn(payload)
                except Exception as e:
                    self.log.debug(f"send_fn failed: {e}")
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self.log.error(f"sender_loop error: {e}")
                await asyncio.sleep(1)

    def cleanup_old(self):
        """Prune expired buckets to prevent memory growth."""
        now = time.time()
        expired = [k for k, v in self._buckets.items() if now - v["last"] > self.cooldown * 3]
        for k in expired:
            del self._buckets[k]

    def stats(self):
        return {
            "active_buckets": len(self._buckets),
            "queue_size": self._outbound.qsize(),
            "broken_count": sum(1 for v in self._buckets.values() if v["broken"]),
        }
```

---

## FILE: `mother/main.py`

```python
"""
mother/main.py — Mother orchestrator (V4).

Architecture:
  - Connects to own MT5 (OANDA) for canonical tick feed
  - Runs strategy_brain — the ONE strategy
  - Broadcasts signals to all VMs via WebSocket
  - Tracks positions per VM via 5s state polling from VMs
  - Rolling 200-brick memory buffer for instant chart render
  - Background validator that replays trades on brain's brick history
  - Bulletproof error dedup — no more spam
  - Simple UTC session gate (matches backtest)
"""
import asyncio
import hashlib
import json
import logging
import os
import signal as sig_module
import sqlite3
import sys
import time
import traceback
import uuid
import weakref
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import requests
import MetaTrader5 as mt5
from aiohttp import web

from core.bars import RenkoBuilder
from core.strategy_brain import StrategyBrain, SignalOpen, SignalModifySL, SignalClose
from core.error_dedup import ErrorDedup
from core.validator import Validator


# ============================================================
# CONFIG
# ============================================================
MOTHER_CONFIG_PATH = Path("config.json")


def load_mother_config():
    if not MOTHER_CONFIG_PATH.exists():
        raise RuntimeError(f"Missing {MOTHER_CONFIG_PATH}")
    with open(MOTHER_CONFIG_PATH) as f:
        return json.load(f)


MOTHER_CFG = load_mother_config()
DASHBOARD_PORT = MOTHER_CFG["dashboard_port"]
FLEET_PORT = MOTHER_CFG["fleet_port"]
SHARED_SECRET = MOTHER_CFG["shared_secret"]
CONFIG_DIR = Path("configs")
CONFIG_HISTORY_DIR = Path(MOTHER_CFG["storage"]["config_history_dir"])
DB_PATH = Path(MOTHER_CFG["storage"]["db_path"])
LOG_DIR = Path(MOTHER_CFG["logging"]["log_dir"])
BRICK_BUFFER_SIZE = MOTHER_CFG["storage"].get("brick_buffer_size", 200)

STRATEGY_CFG = MOTHER_CFG["strategy"]
SIGNAL_CFG = MOTHER_CFG["signal"]
MT5_SRC_CFG = MOTHER_CFG["mt5_source"]

VM_STALE_SEC = SIGNAL_CFG["vm_stale_after_sec"]
VM_OFFLINE_SEC = SIGNAL_CFG["vm_offline_after_sec"]
POLL_INTERVAL_MS = 50


# ============================================================
# LOGGING
# ============================================================
def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    day = datetime.utcnow().strftime("%Y%m%d")
    fp = LOG_DIR / f"mother_{day}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        handlers=[
            logging.FileHandler(fp, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


# ============================================================
# TELEGRAM (via ErrorDedup)
# ============================================================
class Telegram:
    def __init__(self, cfg):
        self.enabled = cfg.get("enabled", False)
        self.token = cfg.get("bot_token", "")
        self.chat_id = cfg.get("chat_id", "")
        self.opts = cfg
        self._url = f"https://api.telegram.org/bot{self.token}/sendMessage" if self.token else None
        self.log = logging.getLogger("telegram")

    async def send_raw(self, text):
        if not self.enabled or not self._url:
            return
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: requests.post(
                    self._url,
                    data={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                    timeout=8,
                ),
            )
        except Exception as e:
            self.log.debug(f"tg send failed: {e}")

    async def dedup_dispatch(self, payload):
        level = payload.get("level", "INFO")
        source = payload.get("source", "?")
        msg = payload.get("message", "")
        emoji = "❌" if level == "ERROR" else "⚠️" if level == "WARNING" else "ℹ️"
        text = f"{emoji} <b>[{source}]</b> {msg[:800]}"
        await self.send_raw(text)

    async def startup(self):
        if self.opts.get("send_startup"):
            await self.send_raw("🚀 <b>JinniGrid Mother V4 started</b>")

    async def vm_online(self, vm_id):
        if self.opts.get("send_vm_online"):
            await self.send_raw(f"🟢 <b>[{vm_id}]</b> VM online")

    async def vm_offline(self, vm_id):
        if self.opts.get("send_vm_offline"):
            await self.send_raw(f"🔴 <b>[{vm_id}]</b> VM offline")

    async def trade_open(self, vm_id, data):
        if not self.opts.get("send_every_trade"):
            return
        d = "LONG" if data["direction"] == 1 else "SHORT"
        arrow = "📈" if data["direction"] == 1 else "📉"
        await self.send_raw(
            f"{arrow} <b>[{vm_id}] {d} filled</b>\n"
            f"Fill: <code>{data.get('fill_price', 0):.2f}</code>\n"
            f"SL: <code>{data.get('sl_price', 0):.2f}</code>\n"
            f"Lots: <code>{data.get('lots', 0):.2f}</code>\n"
            f"Ticket: <code>{data.get('mt5_ticket', '?')}</code>"
        )

    async def trade_close(self, vm_id, data):
        if not self.opts.get("send_every_trade"):
            return
        pnl = data.get("realized_pnl", 0)
        emoji = "✅" if pnl > 0 else "🚨"
        sign = "+" if pnl >= 0 else ""
        result = "WIN" if pnl > 0 else "LOSS"
        await self.send_raw(
            f"{emoji} <b>[{vm_id}] Closed {result}</b>\n"
            f"Exit: <code>{data.get('exit_price', 0):.2f}</code>\n"
            f"PnL: <code>{sign}${pnl:.2f}</code>\n"
            f"Reason: <code>{data.get('exit_reason', '?')}</code>"
        )


# ============================================================
# FLEET DATABASE
# ============================================================
class FleetDB:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS vms (
        id TEXT PRIMARY KEY,
        name TEXT,
        status TEXT,
        last_seen INTEGER,
        symbol TEXT,
        balance REAL DEFAULT 0,
        equity REAL DEFAULT 0,
        peak_balance REAL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS trades (
        id TEXT PRIMARY KEY,
        vm_id TEXT,
        signal_id TEXT,
        symbol TEXT,
        direction INTEGER,
        entry_time INTEGER,
        entry_price REAL,
        exit_time INTEGER,
        exit_price REAL,
        sl_price REAL,
        lots REAL,
        realized_pnl REAL,
        exit_reason TEXT,
        mt5_ticket INTEGER,
        validation_status TEXT,
        validation_confidence REAL,
        mismatch_details TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_trades_vm ON trades(vm_id);
    CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(entry_time);

    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vm_id TEXT,
        event_type TEXT,
        timestamp INTEGER,
        severity TEXT,
        data TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp);

    CREATE TABLE IF NOT EXISTS equity_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vm_id TEXT,
        timestamp INTEGER,
        balance REAL,
        equity REAL
    );
    CREATE INDEX IF NOT EXISTS idx_eq_vm_ts ON equity_snapshots(vm_id, timestamp);

    CREATE TABLE IF NOT EXISTS config_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vm_id TEXT,
        config_snapshot TEXT,
        changed_by TEXT,
        change_reason TEXT,
        timestamp INTEGER
    );
    """

    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.executescript(self.SCHEMA)
        self.conn.commit()

        # Auto-migrate for older DBs
        for col in [
            "validation_status TEXT",
            "validation_confidence REAL",
            "mismatch_details TEXT",
            "recovery_status TEXT",
            "recovered_at INTEGER",
        ]:
            try:
                self.conn.execute(f"ALTER TABLE trades ADD COLUMN {col}")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass

    def upsert_vm(self, vm_id, updates):
        existing = self.conn.execute("SELECT id FROM vms WHERE id=?", (vm_id,)).fetchone()
        if existing:
            sets = ",".join(f"{k}=?" for k in updates.keys())
            self.conn.execute(f"UPDATE vms SET {sets} WHERE id=?",
                              list(updates.values()) + [vm_id])
        else:
            cols = ["id"] + list(updates.keys())
            vals = [vm_id] + list(updates.values())
            ph = ",".join("?" for _ in cols)
            self.conn.execute(f"INSERT INTO vms ({','.join(cols)}) VALUES ({ph})", vals)
        self.conn.commit()

    def insert_event(self, vm_id, event_type, severity, data_dict):
        self.conn.execute(
            "INSERT INTO events (vm_id, event_type, timestamp, severity, data) VALUES (?, ?, ?, ?, ?)",
            (vm_id, event_type, int(time.time()), severity, json.dumps(data_dict))
        )
        self.conn.commit()

    def upsert_trade_open(self, vm_id, trade):
        self.conn.execute("""
            INSERT OR REPLACE INTO trades
            (id, vm_id, signal_id, symbol, direction, entry_time, entry_price, sl_price, lots, mt5_ticket)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (trade["trade_id"], vm_id, trade.get("signal_id"), trade["symbol"],
              trade["direction"], trade["entry_time"], trade["entry_price"],
              trade["sl_price"], trade["lots"], trade.get("mt5_ticket")))
        self.conn.commit()

    def update_trade_close(self, trade_id, close_data):
        self.conn.execute("""
            UPDATE trades SET exit_time=?, exit_price=?, exit_reason=?, realized_pnl=?
            WHERE id=?
        """, (close_data["exit_time"], close_data["exit_price"],
              close_data["exit_reason"], close_data["realized_pnl"], trade_id))
        self.conn.commit()

    def attach_validation(self, trade_id, status, confidence, details_dict):
        self.conn.execute("""
            UPDATE trades SET validation_status=?, validation_confidence=?, mismatch_details=?
            WHERE id=?
        """, (status, confidence, json.dumps(details_dict), trade_id))
        self.conn.commit()
    def mark_recovered(self, trade_id, status):
        """Mark a trade as recovered/reconciled."""
        self.conn.execute(
            "UPDATE trades SET recovery_status=?, recovered_at=? WHERE id=?",
            (status, int(time.time()), trade_id)
        )
        self.conn.commit()

    def insert_recovered_trade(self, vm_id, position):
        """Create a DB record for a recovered open position."""
        trade_id = f"recovered_{position['ticket']}"
        signal_id = position.get("signal_id") or f"recovered_{position['ticket']}"
        try:
            self.conn.execute("""
                INSERT OR IGNORE INTO trades
                (id, vm_id, signal_id, symbol, direction, entry_time, entry_price, sl_price, lots, mt5_ticket, recovery_status, recovered_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (trade_id, vm_id, signal_id, position["symbol"],
                  position["direction"], position["open_time"],
                  position["open_price"], position["current_sl"],
                  position["volume"], position["ticket"],
                  "RECOVERED", int(time.time())))
            self.conn.commit()
            return trade_id
        except Exception as e:
            return None

    def get_open_trades(self):
        """Get all trades that haven't been closed yet."""
        rows = self.conn.execute(
            "SELECT id, vm_id, signal_id, symbol, direction, entry_time, entry_price, sl_price, lots, mt5_ticket "
            "FROM trades WHERE exit_time IS NULL"
        ).fetchall()
        keys = ["trade_id", "vm_id", "signal_id", "symbol", "direction", "entry_time",
                "entry_price", "sl_price", "lots", "mt5_ticket"]
        return [dict(zip(keys, r)) for r in rows]

    def find_deal_for_ticket(self, mt5_ticket, deals):
        """Search a list of deals for close events matching a position ticket."""
        for d in deals:
            if d.get("position_id") == mt5_ticket:
                return d
        return None

    def snapshot_equity(self, vm_id, balance, equity):
        self.conn.execute(
            "INSERT INTO equity_snapshots (vm_id, timestamp, balance, equity) VALUES (?, ?, ?, ?)",
            (vm_id, int(time.time()), balance, equity)
        )
        self.conn.commit()

    def save_config_history(self, vm_id, config, changed_by, reason):
        self.conn.execute("""
            INSERT INTO config_history (vm_id, config_snapshot, changed_by, change_reason, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (vm_id, json.dumps(config), changed_by, reason, int(time.time())))
        self.conn.commit()

    def get_trades_last(self, limit=1000):
        rows = self.conn.execute(
            "SELECT id, vm_id, signal_id, symbol, direction, entry_time, entry_price, exit_time, exit_price, "
            "sl_price, lots, realized_pnl, exit_reason, mt5_ticket, "
            "validation_status, validation_confidence, mismatch_details "
            "FROM trades ORDER BY entry_time DESC LIMIT ?", (limit,)
        ).fetchall()
        keys = ["trade_id", "vm_id", "signal_id", "symbol", "direction", "entry_ts", "entry_price",
                "exit_ts", "exit_price", "sl_price", "lots", "realized_pnl", "exit_reason", "mt5_ticket",
                "validation_status", "validation_confidence", "mismatch_details"]
        return [dict(zip(keys, r)) for r in rows]

    def get_events_last(self, vm_id=None, limit=500):
        if vm_id:
            rows = self.conn.execute(
                "SELECT vm_id, event_type, timestamp, severity, data FROM events "
                "WHERE vm_id=? ORDER BY id DESC LIMIT ?", (vm_id, limit)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT vm_id, event_type, timestamp, severity, data FROM events ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [{"vm_id": r[0], "type": r[1], "ts": r[2], "severity": r[3],
                 "message": r[1], "data": json.loads(r[4]) if r[4] else {}} for r in rows]

    def get_equity_history(self, vm_id=None, limit=1000):
        if vm_id:
            rows = self.conn.execute(
                "SELECT timestamp, balance, equity FROM equity_snapshots "
                "WHERE vm_id=? ORDER BY id DESC LIMIT ?", (vm_id, limit)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT timestamp, balance, equity FROM equity_snapshots ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [{"ts": r[0], "balance": r[1], "equity": r[2]} for r in reversed(rows)]


# ============================================================
# CONFIG MANAGER
# ============================================================
class ConfigManager:
    def __init__(self, db):
        self.db = db
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        self.log = logging.getLogger("config")

    def path_for(self, vm_id):
        return CONFIG_DIR / f"{vm_id}.json"

    def load(self, vm_id):
        p = self.path_for(vm_id)
        if not p.exists():
            return None
        try:
            with open(p) as f:
                return json.load(f)
        except Exception as e:
            self.log.error(f"Failed to load {p}: {e}")
            return None

    def save(self, vm_id, config, changed_by="user", reason=""):
        try:
            self._validate(config)
        except Exception as e:
            return False, [str(e)], []
        p = self.path_for(vm_id)
        with open(p, "w") as f:
            json.dump(config, f, indent=2)
        snap_name = f"{vm_id}_{int(time.time())}.json"
        with open(CONFIG_HISTORY_DIR / snap_name, "w") as f:
            json.dump(config, f, indent=2)
        self.db.save_config_history(vm_id, config, changed_by, reason)
        return True, [], []

    def _validate(self, cfg):
        for k in ["vm_id", "symbol", "cost_per_lot", "mt5", "risk"]:
            if k not in cfg:
                raise ValueError(f"missing: {k}")
        r = cfg["risk"]
        if not (0.0 < r.get("risk_pct", 0) <= 5.0):
            raise ValueError(f"risk_pct out of (0, 5]: {r.get('risk_pct')}")
        if r.get("max_lots", 0) <= 0:
            raise ValueError("max_lots must be > 0")

    def list_all(self):
        result = {}
        for p in CONFIG_DIR.glob("*.json"):
            if p.name.startswith("example_"):
                continue
            try:
                with open(p) as f:
                    result[p.stem] = json.load(f)
            except Exception:
                pass
        return result


# ============================================================
# FLEET STATE
# ============================================================
class FleetState:
    def __init__(self):
        self.vms = {}
        self.recent_bricks = deque(maxlen=BRICK_BUFFER_SIZE)
        self.recent_ma_data = deque(maxlen=BRICK_BUFFER_SIZE)
        self.brain_state = {}

    def upsert_vm(self, vm_id, **patch):
        if vm_id not in self.vms:
            self.vms[vm_id] = {
                "vm_id": vm_id,
                "status": "not_connected",
                "last_seen": 0,
                "balance": 0,
                "equity": 0,
                "peak_balance": 0,
                "position_count": 0,
                "open_positions": {},
                "config": None,
            }
        self.vms[vm_id].update(patch)

    def push_brick(self, brick, main_ma=None, fast_ma=None):
        self.recent_bricks.append(brick)
        self.recent_ma_data.append({"main_ma": main_ma, "fast_ma": fast_ma})


# ============================================================
# MOTHER ENGINE
# ============================================================
class Mother:
    def __init__(self):
        self.log = logging.getLogger("mother")
        self.db = FleetDB(DB_PATH)
        self.cfg_mgr = ConfigManager(self.db)
        self.state = FleetState()
        self.vm_connections = {}
        self.dashboard_clients = weakref.WeakSet()
        self.tg = Telegram(MOTHER_CFG["telegram"])
        self.dedup = ErrorDedup(
            cooldown_sec=MOTHER_CFG["telegram"].get("error_cooldown_sec", 300),
            max_burst=MOTHER_CFG["telegram"].get("error_max_burst", 3),
            logger=self.log,
        )
        self.dedup.bind_sender(self.tg.dedup_dispatch)
        # Recovery state
        self._recovery_active = False
        self._pending_vm_reports = {}   # vm_id → asyncio.Event, set when VM sends ACTUAL_STATE_REPORT
        self._vm_reports = {}            # vm_id → last actual state report
        self.brain = None
        self.renko = None
        self.symbol = MT5_SRC_CFG["symbol"]
        self.brick_size = MT5_SRC_CFG["brick_size"]

        self.validator = None

        self.mt5_ok = False
        self.mt5_ready_event = asyncio.Event()

        self.running = True
        self._startup_ts = int(time.time())

    # ==============================================================
    # STARTUP
    # ==============================================================
    async def start(self):
        self.log.info("=" * 60)
        self.log.info("Mother V4 startup")
        self.log.info(f"Symbol: {self.symbol} brick={self.brick_size}")
        self.log.info(f"Session hours (CST): {STRATEGY_CFG['session_hours_cst']}")
        self.log.info(f"Trading days (UTC weekday): {STRATEGY_CFG['trading_days_utc_weekday']}")
        self.log.info("=" * 60)

        self.dedup.start()
        await self.tg.startup()

        configs = self.cfg_mgr.list_all()
        for vm_id, cfg in configs.items():
            self.state.upsert_vm(
                vm_id,
                status="not_connected",
                config=cfg,
                symbol=cfg.get("symbol", ""),
            )
        self.log.info(f"Pre-populated {len(configs)} VMs from configs")

        self.renko = RenkoBuilder(
            brick_size=self.brick_size,
            price_decimals=MT5_SRC_CFG.get("price_decimals", 2),
            rev_bricks=2.0,
            clean_mode=True,
        )
        self.brain = StrategyBrain(
            session_hours_cst=STRATEGY_CFG["session_hours_cst"],
            trading_days_utc_weekday=STRATEGY_CFG["trading_days_utc_weekday"],
            on_signal_open=self._on_signal_open,
            on_signal_modify_sl=self._on_signal_modify_sl,
            on_signal_close=self._on_signal_close,
            logger=self.log,
        )

        # Validator uses brain's bars for replay
        self.validator = Validator(
            brain=self.brain,
            on_validation_ready=self._on_validation_ready,
            logger=self.log,
        )
        self.validator.start()
        # RECOVER from restart: check DB for still-open trades and mark them as stale
        # Any trade with entry_time > 30 min ago and no exit_time is likely orphaned
        try:
            cutoff = int(time.time()) - 1800  # 30 min ago
            stale_trades = self.db.conn.execute(
                "SELECT id, vm_id, entry_time FROM trades "
                "WHERE exit_time IS NULL AND entry_time < ?",
                (cutoff,)
            ).fetchall()
            for row in stale_trades:
                self.log.warning(f"Orphaned trade detected from previous session: "
                                 f"{row[0][:12]} on {row[1]} (opened {(int(time.time())-row[2])/60:.0f} min ago)")
                # Mark it as force-closed to prevent ghost updates
                self.db.conn.execute(
                    "UPDATE trades SET exit_time=?, exit_reason=?, realized_pnl=0 WHERE id=?",
                    (int(time.time()), "orphaned_on_restart", row[0])
                )
            self.db.conn.commit()
            if stale_trades:
                self.log.info(f"Cleaned up {len(stale_trades)} orphaned trades from previous session")
        except Exception as e:
            self.log.error(f"Startup reconciliation failed: {e}")

    # ==============================================================
    # MT5 TICK SOURCE
    # ==============================================================
    def mt5_connect(self):
        path = MT5_SRC_CFG.get("path")
        timeout = MT5_SRC_CFG.get("timeout_ms", 60000)
        if path:
            ok = mt5.initialize(path=path, timeout=timeout)
        else:
            ok = mt5.initialize(timeout=timeout)
        if not ok:
            raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
        if not mt5.symbol_select(self.symbol, True):
            raise RuntimeError(f"symbol_select failed: {self.symbol}")
        info = mt5.account_info()
        if info is None:
            raise RuntimeError("MT5 not logged in (mother)")
        self.mt5_ok = True
        self.log.info(f"Mother MT5 connected. Login={info.login} broker={info.company}")

    async def warmup(self):
        days = MT5_SRC_CFG.get("warmup_days", 3)
        now = int(datetime.now(timezone.utc).timestamp())
        from_ts = now - days * 86400
        self.log.info(f"Warmup: pulling {days} days of ticks for {self.symbol}...")
        ticks = mt5.copy_ticks_range(
            self.symbol,
            datetime.fromtimestamp(from_ts, tz=timezone.utc),
            datetime.fromtimestamp(now, tz=timezone.utc),
            mt5.COPY_TICKS_ALL,
        )
        if ticks is None or len(ticks) == 0:
            self.log.warning("No warmup ticks!")
            self.mt5_ready_event.set()
            return

        self.log.info(f"Feeding {len(ticks):,} warmup ticks...")

        # Detect broker time offset
        last_tick_time = int(ticks[-1]["time"]) if len(ticks) > 0 else now
        broker_offset_sec = last_tick_time - now
        if abs(broker_offset_sec) < 300:
            broker_offset_sec = 0
        self.log.info(f"Warmup broker time offset: {broker_offset_sec}s ({broker_offset_sec/3600:.1f}h)")

        bars = []
        for t in ticks:
            ts_int = int(t["time"]) - broker_offset_sec  # normalize to real UTC
            bid = float(t["bid"])
            ask = float(t["ask"])
            price = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else (bid or ask or float(t.get("last", 0)))
            if price <= 0:
                continue
            vol = float(t["volume"]) if "volume" in t.dtype.names else 0.0
            new_bricks = self.renko.feed_tick(ts_int, price, vol)
            for b in new_bricks:
                bars.append(b)

        self.brain.prepend_history(bars, abs_start_index=0)
        for b in bars[-BRICK_BUFFER_SIZE:]:
            self.state.push_brick(b)
        self.log.info(f"Warmup done. {len(bars)} bars loaded, brain armed.")

        # Reset renko so live UTC timestamps aren't force-incremented from warmup
        self.renko._last_ts = 0

        self.mt5_ready_event.set()

    async def tick_loop(self):
        await self.mt5_ready_event.wait()
        self.log.info("Entering live tick loop")
        last_msc = 0

        while self.running:
            try:
                tick = mt5.symbol_info_tick(self.symbol)
                if tick is None:
                    await asyncio.sleep(POLL_INTERVAL_MS / 1000)
                    continue

                # Use real UTC time — NEVER trust broker time for session decisions
                ts_int = int(datetime.now(timezone.utc).timestamp())
                bid = float(tick.bid)
                ask = float(tick.ask)
                if bid > 0 and ask > 0:
                    price = (bid + ask) / 2.0
                elif bid > 0 or ask > 0:
                    price = bid or ask
                else:
                    await asyncio.sleep(POLL_INTERVAL_MS / 1000)
                    continue

                if tick.time_msc != last_msc:
                    new_bricks = self.renko.feed_tick(ts_int, price, float(tick.volume))
                    last_msc = tick.time_msc
                    for brick in new_bricks:
                        closes = [b["close"] for b in self.brain.bars] + [brick["close"]]
                        main_ma = self.brain.main_hma.value(closes)
                        fast_ma = self.brain.fast_hma.value(closes)
                        self.state.push_brick(brick, main_ma, fast_ma)

                        self.brain.on_new_brick(brick)

                        await self._broadcast_dashboard({
                            "type": "bar_new",
                            "brick": brick,
                            "main_ma": main_ma,
                            "fast_ma": fast_ma,
                        })

                await asyncio.sleep(POLL_INTERVAL_MS / 1000)

            except Exception as e:
                self.log.error(f"Tick loop error: {e}\n{traceback.format_exc()}")
                self.dedup.emit("mother", "tick_loop", str(e), "ERROR")
                await asyncio.sleep(2)

    # ==============================================================
    # SIGNAL CALLBACKS
    # ==============================================================
    def _on_signal_open(self, sig: SignalOpen):
        asyncio.create_task(self._async_broadcast_open(sig))

    def _on_signal_modify_sl(self, sig: SignalModifySL):
        asyncio.create_task(self._async_broadcast_modify_sl(sig))

    def _on_signal_close(self, sig: SignalClose):
        asyncio.create_task(self._async_broadcast_close(sig))

    async def _async_broadcast_open(self, sig: SignalOpen):
        expires_at = int(time.time() * 1000) + SIGNAL_CFG["expiration_ms"]
        payload = {
            "type": "SIGNAL_OPEN",
            "signal_id": sig.signal_id,
            "direction": sig.direction,
            "sl_distance_pts": sig.sl_distance_pts,
            "expires_at_ms": expires_at,
            "mother_entry_price": sig.entry_price,
            "mother_symbol": self.symbol,
            "mother_ma_ctx": {
                "main_ma": sig.main_ma_value,
                "fast_ma": sig.fast_ma_value,
                "main_slope": sig.main_slope_value,
                "fast_slope": sig.fast_slope_value,
            },
        }
        n = await self._broadcast_to_vms(payload)
        self.log.info(f"SIGNAL_OPEN {sig.signal_id} direction={sig.direction} broadcast to {n} VM(s)")
        await self._broadcast_dashboard({"type": "signal_open", "signal": payload})

    async def _async_broadcast_modify_sl(self, sig: SignalModifySL):
        payload = {
            "type": "SIGNAL_MODIFY_SL",
            "signal_id": sig.signal_id,
            "new_sl_distance_pts_from_entry": sig.new_sl_distance_pts_from_entry,
            "reason": sig.reason,
        }
        await self._broadcast_to_vms(payload)
        self.log.info(f"SIGNAL_MODIFY_SL {sig.signal_id} reason={sig.reason} offset={sig.new_sl_distance_pts_from_entry}")

    async def _async_broadcast_close(self, sig: SignalClose):
        payload = {
            "type": "SIGNAL_CLOSE",
            "signal_id": sig.signal_id,
            "reason": sig.reason,
        }
        await self._broadcast_to_vms(payload)
        self.log.info(f"SIGNAL_CLOSE {sig.signal_id} reason={sig.reason}")

    async def _broadcast_to_vms(self, payload):
        n = 0
        now = time.time()
        payload["timestamp_ms"] = int(now * 1000)
        payload["message_id"] = str(uuid.uuid4())
        text = json.dumps(payload)
        for vm_id, ws in list(self.vm_connections.items()):
            vm = self.state.vms.get(vm_id, {})
            last_seen = vm.get("last_seen", 0)
            if now - last_seen > VM_STALE_SEC:
                continue
            try:
                await ws.send_str(text)
                n += 1
            except Exception as e:
                self.dedup.emit(vm_id, "broadcast_fail", str(e), "WARNING")
        return n

    # ==============================================================
    # VALIDATION CALLBACK
    # ==============================================================
    async def _on_validation_ready(self, trade, result):
        try:
            trade_id = trade["trade_id"]
            vm_id = trade["vm_id"]
            self.db.attach_validation(trade_id, result.status, result.confidence, result.details)
            self.log.info(f"[{vm_id}] Validation: {result.status} conf={result.confidence:.1f}% "
                          f"vm_pnl=${result.vm_pnl:.2f} expected=${result.expected_pnl:.2f}")
            await self._broadcast_dashboard({
                "type": "validation_result",
                "vm_id": vm_id,
                "trade_id": trade_id,
                "result": {
                    "status": result.status,
                    "confidence": result.confidence,
                    "vm_pnl": result.vm_pnl,
                    "expected_pnl": result.expected_pnl,
                    "pnl_diff_usd": result.pnl_diff_usd,
                    "pnl_diff_pct": result.pnl_diff_pct,
                    "entry_price_diff_pct": result.entry_price_diff_pct,
                    "details": result.details,
                }
            })
            if result.status == "MAJOR_MISMATCH":
                await self.tg.send_raw(
                    f"⚠️ <b>[{vm_id}] MAJOR MISMATCH</b>\n"
                    f"Trade #{trade_id[:12]}\n"
                    f"VM PnL: ${result.vm_pnl:.2f}\n"
                    f"Expected: ${result.expected_pnl:.2f}\n"
                    f"Diff: ${result.pnl_diff_usd:.2f} ({result.pnl_diff_pct:.1f}%)"
                )
        except Exception as e:
            self.log.error(f"validation ready handler: {e}")
    # ==============================================================
    # RECOVERY & RECONCILIATION
    # ==============================================================
    async def request_all_vm_states(self, timeout_sec=15):
        """
        Broadcast REPORT_ACTUAL_STATE to all connected VMs.
        Wait up to timeout_sec for their responses.
        Returns dict of {vm_id: state_report or None}
        """
        connected_vms = list(self.vm_connections.keys())
        if not connected_vms:
            self.log.info("No VMs connected, skipping actual state request")
            return {}

        # Reset pending events
        self._pending_vm_reports = {vm: asyncio.Event() for vm in connected_vms}
        self._vm_reports = {}

        # Broadcast request
        payload = {
            "type": "REPORT_ACTUAL_STATE",
            "timestamp_ms": int(time.time() * 1000),
            "message_id": str(uuid.uuid4()),
            "data": {},
        }
        text = json.dumps(payload)
        for vm_id, ws in self.vm_connections.items():
            try:
                await ws.send_str(text)
            except Exception as e:
                self.log.warning(f"Couldn't request state from {vm_id}: {e}")

        # Wait for all responses (or timeout)
        try:
            await asyncio.wait_for(
                asyncio.gather(*[e.wait() for e in self._pending_vm_reports.values()]),
                timeout=timeout_sec
            )
            self.log.info(f"All VMs reported actual state ({len(connected_vms)} VMs)")
        except asyncio.TimeoutError:
            missing = [vm for vm, ev in self._pending_vm_reports.items() if not ev.is_set()]
            self.log.warning(f"Timeout waiting for state from {len(missing)} VMs: {missing}")

        result = dict(self._vm_reports)
        self._pending_vm_reports = {}
        return result

    async def reconcile_from_reports(self, vm_reports):
        """
        Given actual state reports from VMs, reconcile mother's DB.
        Returns list of recovered positions (for brain state rebuild).
        """
        recovered_positions = []

        # 1. For each VM's open positions, ensure they're in DB
        for vm_id, report in vm_reports.items():
            if report is None:
                continue
            for pos in report.get("open_positions", []):
                # Check if this position is already tracked in DB
                existing = self.db.conn.execute(
                    "SELECT id FROM trades WHERE mt5_ticket=? AND vm_id=?",
                    (pos["ticket"], vm_id)
                ).fetchone()

                if existing is None:
                    # Not in DB — create recovered trade record
                    trade_id = self.db.insert_recovered_trade(vm_id, pos)
                    if trade_id:
                        recovered_positions.append({
                            "vm_id": vm_id,
                            "trade_id": trade_id,
                            "position": pos,
                        })
                        self.log.warning(f"[{vm_id}] Recovered orphaned position: "
                                         f"ticket={pos['ticket']} dir={pos['direction']} "
                                         f"open_price={pos['open_price']:.2f}")
                else:
                    # In DB — just verify status
                    trade_id = existing[0]
                    self.db.conn.execute(
                        "UPDATE trades SET sl_price=? WHERE id=?",
                        (pos["current_sl"], trade_id)
                    )
                    self.db.conn.commit()

                # Update in-memory state
                vm_state = self.state.vms.get(vm_id, {})
                positions = vm_state.get("open_positions", {})
                trade_id_final = existing[0] if existing else f"recovered_{pos['ticket']}"
                positions[trade_id_final] = pos
                self.state.upsert_vm(vm_id, open_positions=positions)

        # 2. For each DB trade marked open, check if VM still has it
        db_open_trades = self.db.get_open_trades()
        for db_trade in db_open_trades:
            vm_id = db_trade["vm_id"]
            ticket = db_trade["mt5_ticket"]
            if vm_id not in vm_reports or vm_reports[vm_id] is None:
                continue  # VM offline, can't reconcile

            vm_positions = vm_reports[vm_id].get("open_positions", [])
            still_open = any(p["ticket"] == ticket for p in vm_positions)

            if not still_open:
                # Trade was closed while mother was down — find exit in deals
                deals = vm_reports[vm_id].get("recent_deals", [])
                exit_deal = self.db.find_deal_for_ticket(ticket, deals)
                if exit_deal:
                    self.db.update_trade_close(db_trade["trade_id"], {
                        "exit_time": exit_deal["time"],
                        "exit_price": exit_deal["price"],
                        "exit_reason": "broker_closed_offline",
                        "realized_pnl": exit_deal["profit"],
                    })
                    self.db.mark_recovered(db_trade["trade_id"], "RECONCILED_CLOSED")
                    self.log.info(f"[{vm_id}] Reconciled offline close: "
                                  f"trade={db_trade['trade_id'][:12]} "
                                  f"exit_price={exit_deal['price']:.2f} pnl={exit_deal['profit']:.2f}")
                else:
                    # Can't find exit deal — mark as unknown_close
                    self.db.update_trade_close(db_trade["trade_id"], {
                        "exit_time": int(time.time()),
                        "exit_price": 0,
                        "exit_reason": "unknown_offline_close",
                        "realized_pnl": 0,
                    })
                    self.db.mark_recovered(db_trade["trade_id"], "RECONCILED_UNKNOWN")
                    self.log.warning(f"[{vm_id}] Trade {db_trade['trade_id'][:12]} closed but no deal found")

        return recovered_positions

    async def do_startup_recovery(self):
        """
        Full startup recovery sequence.
        Waits for VMs to connect, asks for actual state, reconciles DB, rebuilds brain state.
        """
        self._recovery_active = True
        wait_sec = SIGNAL_CFG.get("startup_recovery_wait_sec", 15)
        self.log.info(f"Startup recovery: waiting {wait_sec}s for VMs to reconnect...")
        await asyncio.sleep(wait_sec)

        vm_reports = await self.request_all_vm_states(timeout_sec=10)
        if not vm_reports:
            self.log.info("No VM reports received — starting with fresh brain state")
            self._recovery_active = False
            return

        recovered = await self.reconcile_from_reports(vm_reports)

        if recovered:
            # Rebuild brain from the FIRST recovered position (strategy is one-at-a-time)
            first = recovered[0]
            pos = first["position"]
            self.brain.rebuild_state_from_position(
                direction=pos["direction"],
                entry_price=pos["open_price"],
                entry_ts=pos["open_time"],
                current_sl_price=pos["current_sl"],
                signal_id=first["trade_id"],
                be_triggered=False,  # Conservative — assume not yet triggered
            )
            self.log.info(f"Brain rebuilt from {len(recovered)} recovered position(s). "
                          f"Managing signal {first['trade_id']}")
            await self.tg.send_raw(
                f"🔄 <b>Recovery complete</b>\n"
                f"Rebuilt {len(recovered)} position(s) from broker state.\n"
                f"Brain resumed managing signal {first['trade_id'][:16]}"
            )
        else:
            self.log.info("Recovery complete — no open positions, starting fresh")

        self._recovery_active = False

    async def periodic_reconciliation(self):
        """
        Every N seconds, ask VMs for actual state and reconcile.
        Catches drift from manual broker interactions, network issues, etc.
        """
        interval = SIGNAL_CFG.get("reconciliation_interval_sec", 60)
        while self.running:
            await asyncio.sleep(interval)
            try:
                if self._recovery_active:
                    continue  # Don't step on startup recovery

                vm_reports = await self.request_all_vm_states(timeout_sec=8)
                if vm_reports:
                    recovered = await self.reconcile_from_reports(vm_reports)
                    if recovered:
                        self.log.info(f"Periodic reconciliation recovered {len(recovered)} positions")
                        # If brain thinks not in position but we found one, rebuild
                        if not self.brain.in_position and recovered:
                            first = recovered[0]
                            pos = first["position"]
                            self.brain.rebuild_state_from_position(
                                direction=pos["direction"],
                                entry_price=pos["open_price"],
                                entry_ts=pos["open_time"],
                                current_sl_price=pos["current_sl"],
                                signal_id=first["trade_id"],
                            )
                            self.log.info(f"Brain rebuilt during periodic reconciliation")
            except Exception as e:
                self.log.error(f"periodic_reconciliation: {e}")
    # ==============================================================
    # VM WEBSOCKET
    # ==============================================================
    async def handle_vm_ws(self, request):
        ws = web.WebSocketResponse(heartbeat=30, autoping=True)
        await ws.prepare(request)
        vm_id = None

        try:
            handshake = await asyncio.wait_for(ws.receive_json(), timeout=15)
            if handshake.get("type") != "HANDSHAKE":
                await ws.send_json({"type": "HANDSHAKE_REJECT", "reason": "expected HANDSHAKE"})
                return ws
            if handshake.get("shared_secret") != SHARED_SECRET:
                await ws.send_json({"type": "HANDSHAKE_REJECT", "reason": "invalid secret"})
                return ws

            vm_id = handshake["vm_id"]
            self.vm_connections[vm_id] = ws
            await ws.send_json({"type": "HANDSHAKE_OK", "server_ts_ms": int(time.time() * 1000)})
            self.log.info(f"VM {vm_id} connected")
            self.state.upsert_vm(vm_id, status="online", last_seen=int(time.time()))
            await self.tg.vm_online(vm_id)

            cfg = self.cfg_mgr.load(vm_id)
            if cfg is not None:
                await ws.send_json({
                    "type": "PUSH_CONFIG",
                    "timestamp_ms": int(time.time() * 1000),
                    "message_id": str(uuid.uuid4()),
                    "data": {"full_config": cfg},
                })
                self.log.info(f"Pushed config to {vm_id}")

            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self._handle_vm_message(vm_id, data)
                    except Exception as e:
                        self.log.error(f"VM msg error: {e}")

        except asyncio.TimeoutError:
            self.log.warning("Handshake timeout")
        except Exception as e:
            self.log.error(f"VM WS error: {e}")
        finally:
            if vm_id and vm_id in self.vm_connections:
                del self.vm_connections[vm_id]
                self.state.upsert_vm(vm_id, status="offline")
                await self._broadcast_dashboard({
                    "type": "vm_status_change", "vm_id": vm_id, "status": "offline"
                })
                await self.tg.vm_offline(vm_id)
                self.log.info(f"VM {vm_id} disconnected")
        return ws

    async def _handle_vm_message(self, vm_id, msg):
        mt = msg.get("type")
        data = msg.get("data", {})

        if mt == "HEARTBEAT":
            self.state.upsert_vm(
                vm_id,
                last_seen=int(time.time()),
                status="online",
                balance=data.get("balance", 0),
                equity=data.get("equity", 0),
                position_count=data.get("position_count", 0),
                mt5_ok=data.get("mt5_ok", False),
            )
            if data.get("balance") is not None:
                self.db.snapshot_equity(vm_id, data.get("balance", 0), data.get("equity", 0))

        elif mt == "SIGNAL_ACK":
            status = data.get("status")
            self.log.info(f"[{vm_id}] SIGNAL_ACK {data.get('signal_id')} status={status}")
            if status == "filled":
                trade = {
                    "trade_id": data.get("position_id", str(uuid.uuid4())),
                    "signal_id": data.get("signal_id"),
                    "symbol": data.get("symbol", self.symbol),
                    "direction": data.get("direction", 0),
                    "entry_time": data.get("fill_time", int(time.time())),
                    "entry_price": data.get("fill_price", 0),
                    "sl_price": data.get("sl_price", 0),
                    "lots": data.get("lots", 0),
                    "mt5_ticket": data.get("mt5_ticket"),
                }
                self.db.upsert_trade_open(vm_id, trade)
                await self.tg.trade_open(vm_id, {
                    "direction": data.get("direction", 0),
                    "fill_price": data.get("fill_price", 0),
                    "sl_price": data.get("sl_price", 0),
                    "lots": data.get("lots", 0),
                    "mt5_ticket": data.get("mt5_ticket"),
                })

            self.db.insert_event(vm_id, "SIGNAL_ACK", "INFO", data)
            await self._broadcast_dashboard({
                "type": "vm_event", "vm_id": vm_id, "event_type": "SIGNAL_ACK", "data": data,
            })

        elif mt == "POSITION_UPDATE":
            pos_id = data.get("position_id")
            vm = self.state.vms.get(vm_id, {})
            positions = vm.get("open_positions", {})
            positions[pos_id] = data
            self.state.upsert_vm(vm_id, open_positions=positions)

        elif mt == "POSITION_CLOSED":
            pos_id = data.get("position_id")
            signal_id = data.get("signal_id")
            vm = self.state.vms.get(vm_id, {})
            positions = vm.get("open_positions", {})
            if pos_id in positions:
                del positions[pos_id]
            self.state.upsert_vm(vm_id, open_positions=positions)

            # Check if we actually know about this trade in DB
            existing = self.db.conn.execute(
                "SELECT id, exit_time FROM trades WHERE id=?", (pos_id,)
            ).fetchone()

            if existing is None:
                # Unknown trade — VM had it open from before restart, we never tracked it
                self.log.warning(f"[{vm_id}] POSITION_CLOSED for unknown trade {pos_id} "
                                f"(from previous session?). Recording but skipping alerts.")
                # Insert minimal record so DB is consistent
                try:
                    self.db.conn.execute("""
                        INSERT INTO trades (id, vm_id, signal_id, direction, entry_time,
                                            entry_price, exit_time, exit_price, exit_reason, realized_pnl)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (pos_id, vm_id, signal_id, 0, 0, 0,
                        data.get("exit_time", int(time.time())),
                        data.get("exit_price", 0), "orphaned_" + data.get("exit_reason", "?"),
                        data.get("realized_pnl", 0)))
                    self.db.conn.commit()
                except Exception as e:
                    self.log.error(f"insert orphaned trade: {e}")
            elif existing[1] is not None:
                # Already closed — VM re-sent (probably reconnect race)
                self.log.info(f"[{vm_id}] duplicate close for {pos_id}, ignoring")
                return
            else:
                # Normal path — real trade close
                self.db.update_trade_close(pos_id, {
                    "exit_time": data.get("exit_time", int(time.time())),
                    "exit_price": data.get("exit_price", 0),
                    "exit_reason": data.get("exit_reason", "?"),
                    "realized_pnl": data.get("realized_pnl", 0),
                })
                await self.tg.trade_close(vm_id, data)
            self.db.insert_event(vm_id, "POSITION_CLOSED", "INFO", data)
            await self._broadcast_dashboard({
                "type": "vm_event", "vm_id": vm_id, "event_type": "POSITION_CLOSED", "data": data,
            })

            # ENQUEUE VALIDATION
            if self.validator is not None:
                row = self.db.conn.execute(
                    "SELECT id, vm_id, signal_id, direction, entry_time, entry_price, "
                    "exit_time, exit_price, lots, realized_pnl FROM trades WHERE id=?",
                    (pos_id,)
                ).fetchone()
                if row:
                    vm_cfg = self.state.vms.get(vm_id, {}).get("config", {})
                    cost_per_lot = vm_cfg.get("cost_per_lot", 1.20)
                    self.validator.enqueue({
                        "vm_id": row[1],
                        "trade_id": row[0],
                        "signal_id": row[2],
                        "direction": row[3],
                        "entry_time": row[4],
                        "entry_price": row[5],
                        "exit_time": row[6],
                        "exit_price": row[7],
                        "lots": row[8],
                        "realized_pnl": row[9],
                        "cost_per_lot": cost_per_lot,
                    })

            # Reconcile brain if all VMs closed this signal
            if signal_id and signal_id == self.brain.current_signal_id:
                any_still_open = False
                for other_vm in self.state.vms.values():
                    for p in (other_vm.get("open_positions") or {}).values():
                        if p.get("signal_id") == signal_id:
                            any_still_open = True
                            break
                    if any_still_open:
                        break
                if not any_still_open:
                    self.log.info(f"All VMs closed signal {signal_id} — resetting brain")
                    self.brain.in_position = False
                    self.brain.trade_direction = 0
                    self.brain.entry_price = 0.0
                    self.brain.entry_brick_index_abs = -1
                    self.brain.current_sl_price = 0.0
                    self.brain.be_triggered = False
                    self.brain.fav_bricks_count = 0
                    self.brain.current_signal_id = None

        elif mt == "SL_STATE":
            pos_id = data.get("position_id")
            actual_sl = data.get("actual_sl")
            reason = data.get("reason", "?")
            self.log.info(f"[{vm_id}] SL_STATE: pos={pos_id} actual={actual_sl} ({reason})")
            vm = self.state.vms.get(vm_id, {})
            positions = vm.get("open_positions", {})
            if pos_id in positions:
                positions[pos_id]["actual_sl_reported"] = actual_sl
                positions[pos_id]["sl_divergence_reason"] = reason
                self.state.upsert_vm(vm_id, open_positions=positions)
            self.db.insert_event(vm_id, "SL_STATE", "WARNING", data)

        elif mt == "VM_ERROR":
            code = data.get("error_code", "?")
            emsg = data.get("error_message", "")[:400]
            self.dedup.emit(vm_id, str(code), emsg, "ERROR")
            self.db.insert_event(vm_id, "VM_ERROR", "ERROR", data)

        elif mt == "VM_ONLINE":
            self.state.upsert_vm(vm_id, status="online", last_seen=int(time.time()))
            
        elif mt == "ACTUAL_STATE_REPORT":
            self.log.info(f"[{vm_id}] ACTUAL_STATE_REPORT: {len(data.get('open_positions', []))} open positions")
            self._vm_reports[vm_id] = data
            if vm_id in self._pending_vm_reports:
                self._pending_vm_reports[vm_id].set()

    # ==============================================================
    # DASHBOARD
    # ==============================================================
    async def _broadcast_dashboard(self, msg):
        if not self.dashboard_clients:
            return
        payload = json.dumps(msg)
        dead = []
        for client in list(self.dashboard_clients):
            try:
                await client.send_str(payload)
            except Exception:
                dead.append(client)
        for d in dead:
            try:
                self.dashboard_clients.discard(d)
            except Exception:
                pass

    async def handle_index(self, request):
        p = Path("web/index.html")
        if not p.exists():
            return web.Response(text="index.html missing", status=404)
        return web.FileResponse(p)

    async def handle_asset(self, request):
        name = request.match_info["name"]
        p = Path("web") / name
        if not p.exists() or ".." in name:
            return web.Response(status=404)
        return web.FileResponse(p)

    async def handle_health(self, request):
        return web.json_response({
            "status": "ok",
            "uptime_sec": int(time.time()) - self._startup_ts,
            "vms_connected": len(self.vm_connections),
            "mt5_ok": self.mt5_ok,
            "dedup_stats": self.dedup.stats(),
        })

    async def handle_dashboard_ws(self, request):
        ws = web.WebSocketResponse(heartbeat=30, autoping=True)
        await ws.prepare(request)
        self.dashboard_clients.add(ws)
        self.log.info(f"Dashboard client connected (total={len(list(self.dashboard_clients))})")
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self._handle_dashboard_msg(ws, data)
                    except Exception as e:
                        self.log.error(f"dashboard msg: {e}")
        finally:
            try:
                self.dashboard_clients.discard(ws)
            except Exception:
                pass
        return ws

    async def _handle_dashboard_msg(self, ws, msg):
        t = msg.get("type")

        if t == "hello":
            await self._send_initial_state(ws)

        elif t == "command":
            action = msg.get("action")
            vm_id = msg.get("vm_id")
            self.log.info(f"Dashboard cmd: {action} on {vm_id}")

            if action == "halt":
                await self._send_cmd_to_vm(vm_id, "HALT_TRADING", {})
            elif action == "resume":
                await self._send_cmd_to_vm(vm_id, "RESUME_TRADING", {})
            elif action == "close_all":
                await self._send_cmd_to_vm(vm_id, "CLOSE_ALL_POSITIONS", {})
            elif action == "shutdown":
                await self._send_cmd_to_vm(vm_id, "SHUTDOWN", {})
            elif action == "delete_trade":
                trade_id = msg.get("trade_id")
                if trade_id:
                    self.db.conn.execute("DELETE FROM trades WHERE id=?", (trade_id,))
                    self.db.conn.commit()
                    self.log.info(f"Deleted trade {trade_id} from DB")
                    await self._broadcast_dashboard({
                        "type": "toast", "level": "success",
                        "message": f"Deleted trade {trade_id[:12]}"
                    })
                    # Force refresh initial state so DB change reflects on dashboard
                    for client in list(self.dashboard_clients):
                        try:
                            await self._send_initial_state(client)
                        except Exception:
                            pass
            elif action == "delete_trades_bulk":
                trade_ids = msg.get("trade_ids", [])
                if trade_ids:
                    marks = ",".join("?" for _ in trade_ids)
                    self.db.conn.execute(f"DELETE FROM trades WHERE id IN ({marks})", trade_ids)
                    self.db.conn.commit()
                    self.log.info(f"Bulk deleted {len(trade_ids)} trades")
                    await self._broadcast_dashboard({
                        "type": "toast", "level": "success",
                        "message": f"Deleted {len(trade_ids)} trades"
                    })
                    for client in list(self.dashboard_clients):
                        try:
                            await self._send_initial_state(client)
                        except Exception:
                            pass
            elif action == "push_config":
                cfg = msg.get("config")
                reason = msg.get("reason", "dashboard edit")
                ok, errors, _ = self.cfg_mgr.save(vm_id, cfg, changed_by="dashboard", reason=reason)
                if not ok:
                    await ws.send_json({
                        "type": "config_result", "vm_id": vm_id,
                        "ok": False, "errors": errors,
                    })
                    return
                sent = await self._send_cmd_to_vm(vm_id, "PUSH_CONFIG", {"full_config": cfg})
                await ws.send_json({
                    "type": "config_result", "vm_id": vm_id,
                    "ok": sent, "errors": [] if sent else ["send failed"],
                })

    async def _send_cmd_to_vm(self, vm_id, cmd_type, data):
        ws = self.vm_connections.get(vm_id)
        if ws is None:
            return False
        try:
            await ws.send_json({
                "type": cmd_type,
                "timestamp_ms": int(time.time() * 1000),
                "message_id": str(uuid.uuid4()),
                "data": data,
            })
            return True
        except Exception as e:
            self.dedup.emit(vm_id, "cmd_send_fail", str(e), "WARNING")
            return False

    async def _send_initial_state(self, ws):
        all_configs = self.cfg_mgr.list_all()
        merged = {}
        for vm_id, cfg in all_configs.items():
            state_data = self.state.vms.get(vm_id, {"vm_id": vm_id, "status": "not_connected"})
            merged[vm_id] = dict(state_data)
            merged[vm_id]["config"] = cfg

        for vm_id, state_data in self.state.vms.items():
            if vm_id not in merged:
                merged[vm_id] = dict(state_data)
                merged[vm_id]["config"] = {}

        # Only send limited event count for perf
        for vm_id, vm in merged.items():
            trades = self.db.get_trades_last(500)
            vm["trades"] = [t for t in trades if t.get("vm_id") == vm_id]
            vm["events"] = self.db.get_events_last(vm_id, 200)  # reduced from 500 to fix slow logs
            vm["equity_history"] = self.db.get_equity_history(vm_id, 500)

        payload = {
            "type": "initial_state",
            "vms": merged,
            "recent_bricks": list(self.state.recent_bricks),
            "recent_ma_data": list(self.state.recent_ma_data),
            "symbol": self.symbol,
            "brain_state": self.brain.get_state() if self.brain else {},
            "server_time_ms": int(time.time() * 1000),
        }
        await ws.send_str(json.dumps(payload))
        self.log.info(f"Sent initial state with {len(merged)} VMs, {len(self.state.recent_bricks)} bricks")

    # ==============================================================
    # PERIODIC
    # ==============================================================
    async def stale_monitor(self):
        while self.running:
            try:
                now = int(time.time())
                for vm_id, vm in list(self.state.vms.items()):
                    last_seen = vm.get("last_seen", 0)
                    status = vm.get("status", "not_connected")
                    if last_seen == 0:
                        continue
                    age = now - last_seen
                    new_status = None
                    if age > VM_OFFLINE_SEC and status != "offline":
                        new_status = "offline"
                    elif age > VM_STALE_SEC and status == "online":
                        new_status = "stale"
                    if new_status and new_status != status:
                        self.state.upsert_vm(vm_id, status=new_status)
                        await self._broadcast_dashboard({
                            "type": "vm_status_change", "vm_id": vm_id, "status": new_status,
                        })
            except Exception as e:
                self.log.error(f"stale_monitor: {e}")
            await asyncio.sleep(15)

    async def dedup_cleanup_loop(self):
        while self.running:
            try:
                self.dedup.cleanup_old()
            except Exception as e:
                self.log.error(f"dedup cleanup: {e}")
            await asyncio.sleep(300)

    # ==============================================================
    # RUN
    # ==============================================================
    async def run(self):
        app = web.Application()
        app.router.add_get("/", self.handle_index)
        app.router.add_get("/health", self.handle_health)
        app.router.add_get("/ws", self.handle_dashboard_ws)
        app.router.add_get("/{name}", self.handle_asset)
        runner = web.AppRunner(app)
        await runner.setup()
        dashboard_site = web.TCPSite(runner, "0.0.0.0", DASHBOARD_PORT)
        await dashboard_site.start()
        self.log.info(f"Dashboard on :{DASHBOARD_PORT}")

        fleet_app = web.Application()
        fleet_app.router.add_get("/fleet", self.handle_vm_ws)
        fleet_runner = web.AppRunner(fleet_app)
        await fleet_runner.setup()
        fleet_site = web.TCPSite(fleet_runner, "0.0.0.0", FLEET_PORT)
        await fleet_site.start()
        self.log.info(f"Fleet WS on :{FLEET_PORT}")

        await self.start()

        try:
            self.mt5_connect()
        except Exception as e:
            self.log.critical(f"Mother MT5 failed: {e}")
            self.dedup.emit("mother", "mt5_init_fail", str(e), "ERROR")
            self.running = False
            return

        await self.warmup()

        # Perform startup recovery BEFORE entering tick loop
        # This waits for VMs and rebuilds brain state from any recovered positions
        await self.do_startup_recovery()

        tasks = [
            asyncio.create_task(self.tick_loop()),
            asyncio.create_task(self.stale_monitor()),
            asyncio.create_task(self.dedup_cleanup_loop()),
            asyncio.create_task(self.periodic_reconciliation()),
        ]

        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            self.log.info("Mother shutting down")
            self.dedup.stop()
            if self.validator:
                self.validator.stop()
            try:
                mt5.shutdown()
            except Exception:
                pass


# ============================================================
# ENTRY
# ============================================================
async def main_async():
    setup_logging()
    log = logging.getLogger("main")
    log.info("=" * 60)
    log.info("JinniGrid Mother V4")
    log.info("=" * 60)

    mother = Mother()

    def _shutdown(*_):
        mother.running = False

    for s in (sig_module.SIGTERM, sig_module.SIGINT):
        try:
            asyncio.get_event_loop().add_signal_handler(s, _shutdown)
        except NotImplementedError:
            pass

    try:
        await mother.run()
    except Exception as e:
        log.critical(f"Fatal: {e}\n{traceback.format_exc()}")


if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass
```

---

## FILE: `readme.md`

````markdown
# JinniGrid V3

Distributed MT5 trading fleet with a **mother-as-brain** architecture.

The mother process owns the strategy, validates signals, and coordinates execution across VM workers. Each VM receives orders and executes trades without running its own independent strategy.

## Architecture

- **Mother** connects to its own MT5 instance (OANDA) for canonical tick data.
- **Mother** runs the single strategy and generates trade signals.
- **Mother** broadcasts signals to all VMs over WebSocket.
- **VMs** act as execution arms: receive signals, execute trades, and report position state.
- **VMs** poll their own MT5 periodically and report status back to mother.
- This design avoids per-VM strategy divergence from broker tick differences.

## Requirements

- Python dependencies: `pip install -r requirements.txt`
- MetaTrader 5 installed on both mother and VM machines
- Mother must have an OANDA MT5 account logged in for clean tick data

## Mother setup

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Start the mother service:

```bash
cd mother
python main.py
```

3. Open the dashboard in a browser:

```text
http://<mother-ip>:8080
```

## VM setup

Each VM must have MetaTrader 5 running with its broker account.

Create `vm/.env` with the following values:

```text
MOTHER_HOST=192.168.2.105
MOTHER_PORT=8765
VM_ID=vm1
SHARED_SECRET=jinni_grid_secret2347890
```

Then start the VM process:

```bash
cd vm
python main.py
```

## Ports

- `8080` — mother dashboard HTTP
- `8765` — fleet WebSocket server

## Configuration notes

- `mother/config.json` contains mother settings, ports, and the shared secret.
- `mother/configs/<vm_id>.json` contains per-VM settings.
- `VM_ID` in `vm/.env` must match the VM config filename under `mother/configs/`.
- `SHARED_SECRET` in `vm/.env` must match `shared_secret` in `mother/config.json`.
- Mother stores fleet state in `mother/state/fleet.db`.
- Strategy logic is locked in `mother/core/strategy_brain.py`.

## Recommended workflow

1. Start the mother process first.
2. Verify the dashboard is available.
3. Start each VM after the mother is running.
4. Monitor VM connectivity and trade execution from the dashboard.

## Important

- Keep `mother/config.json` and `vm/.env` secure.
- Do not commit sensitive credentials to a public repository.
````

---

## FILE: `requirements.txt`

```text
MetaTrader5>=5.0.4200
aiohttp>=3.9.0
websockets>=12.0
cryptography>=41.0.0
tzdata>=2024.1
```

---

## FILE: `vm/config.json`

```json
{}
```

---

## FILE: `vm/main.py`

```python
"""
vm/main.py — VM: dumb execution arm (V3).

Responsibilities:
  - Connect to mother via WebSocket
  - Receive signals: SIGNAL_OPEN, SIGNAL_MODIFY_SL, SIGNAL_CLOSE
  - Execute via mt5_executor
  - Poll own MT5 every 5s and report state to mother
  - Report errors ONCE (mother handles dedup), not spam
  - Never runs strategy — mother is the brain
"""
import asyncio
import json
import logging
import math
import os
import signal as sig_module
import sqlite3
import sys
import time
import traceback
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5
import aiohttp

import mt5_executor as executor


# ============================================================
# CONSTANTS
# ============================================================
HEARTBEAT_INTERVAL_SEC = 5
POSITION_POLL_INTERVAL_SEC = 5
WS_RETRY_BASE_SEC = 2
WS_RETRY_MAX_SEC = 60
MT5_RETRY_BASE_SEC = 5
MT5_RETRY_MAX_SEC = 120

# Error rate limiting on VM side — 1 error per code per 60s max
VM_ERROR_COOLDOWN_SEC = 60


# ============================================================
# .ENV LOADER
# ============================================================
def _load_dotenv():
    env_file = Path(__file__).parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())

_load_dotenv()


# ============================================================
# LOGGING
# ============================================================
def setup_logging(vm_id):
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    day = datetime.utcnow().strftime("%Y%m%d")
    fp = log_dir / f"vm_{day}.log"
    fmt = "[%(asctime)s] [%(levelname)s] [%(name)s] " + f"[{vm_id}] " + "%(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.FileHandler(fp, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


# ============================================================
# LOCAL STATE (audit trail)
# ============================================================
class LocalState:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS positions (
        position_id TEXT PRIMARY KEY,
        signal_id TEXT,
        mt5_ticket INTEGER,
        direction INTEGER,
        symbol TEXT,
        open_ts INTEGER,
        fill_price REAL,
        initial_sl_price REAL,
        current_sl_price REAL,
        lots REAL,
        close_ts INTEGER,
        exit_price REAL,
        exit_reason TEXT,
        realized_pnl REAL,
        status TEXT
    );
    CREATE TABLE IF NOT EXISTS meta (
        k TEXT PRIMARY KEY,
        v TEXT
    );
    """

    def __init__(self, path="state.db"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.executescript(self.SCHEMA)
        self.conn.commit()

    def upsert_position(self, pos):
        cols = ",".join(pos.keys())
        ph = ",".join("?" for _ in pos)
        self.conn.execute(f"INSERT OR REPLACE INTO positions ({cols}) VALUES ({ph})", list(pos.values()))
        self.conn.commit()

    def close_position(self, position_id, close_data):
        sets = ",".join(f"{k}=?" for k in close_data.keys())
        vals = list(close_data.values()) + [position_id]
        self.conn.execute(f"UPDATE positions SET {sets} WHERE position_id=?", vals)
        self.conn.commit()

    def open_positions(self):
        rows = self.conn.execute(
            "SELECT position_id, signal_id, mt5_ticket, direction, symbol, "
            "open_ts, fill_price, initial_sl_price, current_sl_price, lots "
            "FROM positions WHERE status='OPEN'"
        ).fetchall()
        return [{
            "position_id": r[0], "signal_id": r[1], "mt5_ticket": r[2], "direction": r[3],
            "symbol": r[4], "open_ts": r[5], "fill_price": r[6],
            "initial_sl_price": r[7], "current_sl_price": r[8], "lots": r[9],
        } for r in rows]

    def set_meta(self, k, v):
        self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k, str(v)))
        self.conn.commit()

    def get_meta(self, k, default=None):
        row = self.conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return row[0] if row else default


# ============================================================
# VM ENGINE
# ============================================================
class VMEngine:
    def __init__(self, vm_id, mother_host, mother_port, shared_secret):
        self.vm_id = vm_id
        self.mother_host = mother_host
        self.mother_port = mother_port
        self.shared_secret = shared_secret

        self.log = logging.getLogger("vm")
        self.state = LocalState()
        self.config = None
        self.symbol = None

        self.running = True
        self.mt5_ok = False
        self.halted_by_mother = False
        self.halted_by_dd = False

        self.today_date = None
        self.day_start_balance = 0.0

        self.mother_ws = None
        self.pending_config_event = asyncio.Event()

        # Signal tracking (dedup by signal_id — don't re-process)
        self._processed_signals = deque(maxlen=1000)

        # VM-side error rate limiter
        self._last_error_send = {}  # error_code -> ts

        # Outbound queue — NEVER blocks strategy handling
        self._outbound_queue = asyncio.Queue(maxsize=1000)

    # ==============================================================
    # CONFIG
    # ==============================================================
    def load_local_config(self):
        try:
            with open("config.json") as f:
                data = json.load(f)
            if data and "symbol" in data:
                self.apply_config(data)
                return True
        except Exception as e:
            self.log.info(f"No usable local config: {e}")
        return False

    def apply_config(self, cfg):
        self._validate_config(cfg)
        self.config = cfg
        self.symbol = cfg["symbol"]
        with open("config.json", "w") as f:
            json.dump(cfg, f, indent=2)
        self.log.info(f"Config applied. Symbol={self.symbol}")

    def _validate_config(self, cfg):
        for k in ["symbol", "cost_per_lot", "mt5", "risk"]:
            if k not in cfg:
                raise ValueError(f"config missing: {k}")
        r = cfg["risk"]
        if not (0.0 < r.get("risk_pct", 0) <= 5.0):
            raise ValueError(f"risk_pct out of (0, 5]")
        if r.get("max_lots", 0) <= 0:
            raise ValueError("max_lots must be > 0")

    # ==============================================================
    # MT5
    # ==============================================================
    def mt5_connect(self):
        path = self.config["mt5"].get("path")
        timeout = self.config["mt5"].get("timeout_ms", 60000)
        if path:
            ok = mt5.initialize(path=path, timeout=timeout)
        else:
            ok = mt5.initialize(timeout=timeout)
        if not ok:
            raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
        if not mt5.symbol_select(self.symbol, True):
            raise RuntimeError(f"symbol_select failed: {self.symbol}")
        info = mt5.account_info()
        if info is None:
            raise RuntimeError("MT5 not logged in")
        self.mt5_ok = True
        self.log.info(f"MT5 connected. Login={info.login} balance=${info.balance:,.2f}")
        return info

    def account_balance(self):
        info = mt5.account_info()
        return float(info.balance) if info else 0.0

    def account_equity(self):
        info = mt5.account_info()
        return float(info.equity) if info else 0.0

    # ==============================================================
    # OUTBOUND MESSAGING (non-blocking)
    # ==============================================================
    async def send_msg(self, msg_type, data):
        payload = {
            "type": msg_type,
            "vm_id": self.vm_id,
            "timestamp_ms": int(time.time() * 1000),
            "message_id": str(uuid.uuid4()),
            "data": data,
        }
        try:
            self._outbound_queue.put_nowait(payload)
        except asyncio.QueueFull:
            # Drop silently — don't block strategy processing
            self.log.debug("outbound queue full, dropping")

    async def send_error(self, error_code, error_message, context=None):
        """VM-side rate limit: don't spam same error every second."""
        now = time.time()
        last = self._last_error_send.get(error_code, 0)
        if now - last < VM_ERROR_COOLDOWN_SEC:
            self.log.debug(f"error {error_code} suppressed (cooldown)")
            return
        self._last_error_send[error_code] = now

        await self.send_msg("VM_ERROR", {
            "error_code": error_code,
            "error_message": error_message[:500],
            "context": context or {},
        })

    async def _outbound_sender(self):
        """Drains outbound queue to mother WS. Never blocks strategy."""
        while self.running:
            try:
                payload = await asyncio.wait_for(self._outbound_queue.get(), timeout=1.0)
                if self.mother_ws is not None and not self.mother_ws.closed:
                    try:
                        await self.mother_ws.send_str(json.dumps(payload))
                    except Exception as e:
                        self.log.debug(f"send failed: {e}")
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self.log.error(f"outbound sender: {e}")
                await asyncio.sleep(1)

    # ==============================================================
    # SIGNAL EXECUTION
    # ==============================================================
    async def handle_signal_open(self, sig):
        signal_id = sig.get("signal_id")
        if signal_id in self._processed_signals:
            self.log.debug(f"Skipping already-processed signal {signal_id}")
            return
        self._processed_signals.append(signal_id)

        expires = sig.get("expires_at_ms", 0)
        now_ms = int(time.time() * 1000)
        if now_ms > expires:
            self.log.warning(f"Signal {signal_id} expired ({now_ms - expires}ms late)")
            await self.send_msg("SIGNAL_ACK", {
                "signal_id": signal_id, "status": "expired",
            })
            return

        if self.halted_by_mother or self.halted_by_dd:
            self.log.info(f"Signal {signal_id} rejected: halted")
            await self.send_msg("SIGNAL_ACK", {
                "signal_id": signal_id, "status": "rejected", "reason": "halted",
            })
            return

        
        direction = sig["direction"]
        sl_distance = sig["sl_distance_pts"]
        symbol = self.symbol   # ← ALWAYS use VM's own config symbol


        # Compute lots
        risk_mode = self.config["risk"].get("risk_mode", "starting_balance")
        risk_pct = self.config["risk"]["risk_pct"]
        starting_bal = self.config["risk"].get("starting_balance", self.account_balance())
        base_bal = self.account_balance() if risk_mode == "current_balance" else starting_bal
        risk_usd = base_bal * risk_pct / 100.0

        raw_lots = risk_usd / max(sl_distance, 0.01)
        lot_step = self.config["risk"].get("lot_step", 0.01)
        min_lot = self.config["risk"].get("min_lot", 0.01)
        max_lot = self.config["risk"]["max_lots"]
        lots = math.floor(raw_lots / lot_step) * lot_step
        lots = max(min_lot, min(max_lot, lots))

        # Execute
        ok, result = executor.open_position(symbol, direction, lots, sl_distance, signal_id=signal_id)

        if not ok:
            self.log.error(f"open_position failed: {result}")
            await self.send_error("OPEN_FAILED", result.get("error_message", "?"),
                                    {"signal_id": signal_id, **result})
            await self.send_msg("SIGNAL_ACK", {
                "signal_id": signal_id,
                "status": "rejected",
                "reason": result.get("error_message", "?"),
            })
            return

        # Success
        position_id = f"pos_{signal_id}_{result['ticket']}"
        fill_price = result["fill_price"]
        sl_price = result["sl_price"]
        actual_lots = result["actual_lots"]
        mt5_ticket = result["ticket"]

        self.state.upsert_position({
            "position_id": position_id,
            "signal_id": signal_id,
            "mt5_ticket": mt5_ticket,
            "direction": direction,
            "symbol": symbol,
            "open_ts": int(time.time()),
            "fill_price": fill_price,
            "initial_sl_price": sl_price,
            "current_sl_price": sl_price,
            "lots": actual_lots,
            "close_ts": None,
            "exit_price": None,
            "exit_reason": None,
            "realized_pnl": None,
            "status": "OPEN",
        })

        self.log.info(f"OPEN {position_id} dir={direction} @{fill_price:.2f} SL={sl_price:.2f} lots={actual_lots}")

        await self.send_msg("SIGNAL_ACK", {
            "signal_id": signal_id,
            "status": "filled",
            "position_id": position_id,
            "mt5_ticket": mt5_ticket,
            "fill_price": fill_price,
            "fill_time": int(time.time()),
            "sl_price": sl_price,
            "lots": actual_lots,
            "direction": direction,
            "symbol": symbol,
            "slippage_pts": result.get("slippage_pts", 0),
        })

    async def handle_signal_modify_sl(self, sig):
        signal_id = sig.get("signal_id")
        new_offset = sig["new_sl_distance_pts_from_entry"]
        reason = sig.get("reason", "?")

        # Find our position for this signal
        positions = self.state.open_positions()
        target = None
        for p in positions:
            if p["signal_id"] == signal_id:
                target = p
                break
        if target is None:
            self.log.debug(f"MODIFY_SL for unknown signal {signal_id}")
            return

        # Compute new SL price relative to OUR fill price
        if target["direction"] == 1:
            new_sl_price = target["fill_price"] + new_offset
        else:
            new_sl_price = target["fill_price"] - new_offset

        ok, result = executor.modify_sl(target["symbol"], target["mt5_ticket"], new_sl_price)
        if not ok:
            self.log.warning(f"modify_sl failed: {result}")
            await self.send_error("MODIFY_SL_FAILED", result.get("error_message", "?"),
                                    {"signal_id": signal_id})
            # Report actual SL state back to mother so it can reconcile
            await self.send_msg("SL_STATE", {
                "position_id": target["position_id"],
                "signal_id": signal_id,
                "requested_sl": new_sl_price,
                "actual_sl": target["current_sl_price"],
                "reason": result.get("error_message", "modify_failed"),
            })
            return

        if result.get("unchanged"):
            self.log.debug(f"modify_sl no-op (not more favorable)")
            await self.send_msg("SL_STATE", {
                "position_id": target["position_id"],
                "signal_id": signal_id,
                "requested_sl": new_sl_price,
                "actual_sl": target["current_sl_price"],
                "reason": "not_more_favorable",
            })
            return

        self.state.upsert_position({
            "position_id": target["position_id"],
            "signal_id": target["signal_id"],
            "mt5_ticket": target["mt5_ticket"],
            "direction": target["direction"],
            "symbol": target["symbol"],
            "open_ts": target["open_ts"],
            "fill_price": target["fill_price"],
            "initial_sl_price": target["initial_sl_price"],
            "current_sl_price": result["new_sl"],
            "lots": target["lots"],
            "close_ts": None,
            "exit_price": None,
            "exit_reason": None,
            "realized_pnl": None,
            "status": "OPEN",
        })

        self.log.info(f"SL modified for {target['position_id']} → {result['new_sl']:.2f} ({reason})")

    async def handle_signal_close(self, sig):
        signal_id = sig.get("signal_id")
        reason = sig.get("reason", "?")

        positions = self.state.open_positions()
        target = None
        for p in positions:
            if p["signal_id"] == signal_id:
                target = p
                break
        if target is None:
            self.log.debug(f"CLOSE for unknown signal {signal_id}")
            return

        ok, result = executor.close_position(target["symbol"], target["mt5_ticket"])
        if not ok:
            self.log.error(f"close_position failed: {result}")
            await self.send_error("CLOSE_FAILED", result.get("error_message", "?"),
                                    {"signal_id": signal_id})
            return

        exit_price = result["exit_price"]
        realized_pnl = result["realized_pnl"]

        self.state.close_position(target["position_id"], {
            "close_ts": int(time.time()),
            "exit_price": exit_price,
            "exit_reason": reason,
            "realized_pnl": realized_pnl,
            "status": "CLOSED",
        })

        self.log.info(f"CLOSED {target['position_id']} @{exit_price:.2f} pnl={realized_pnl:.2f}")

        await self.send_msg("POSITION_CLOSED", {
            "position_id": target["position_id"],
            "signal_id": signal_id,
            "exit_price": exit_price,
            "exit_time": int(time.time()),
            "realized_pnl": realized_pnl,
            "exit_reason": reason,
        })

    # ==============================================================
    # POSITION POLLING (source of truth for state sync)
    # ==============================================================
    async def position_poller(self):
        """Every 5s: query MT5 for actual open positions, report to mother.
           Detect positions that closed WITHOUT our command (e.g. broker-side SL)."""
        while self.running:
            try:
                if not self.mt5_ok:
                    await asyncio.sleep(POSITION_POLL_INTERVAL_SEC)
                    continue

                mt5_positions = executor.get_open_positions(symbol=self.symbol)
                local_positions = self.state.open_positions()
                mt5_tickets = {p["ticket"]: p for p in mt5_positions}
                local_tickets = {p["mt5_ticket"]: p for p in local_positions}

                # Send POSITION_UPDATE for each open position
                for lp in local_positions:
                    ticket = lp["mt5_ticket"]
                    if ticket in mt5_tickets:
                        mp = mt5_tickets[ticket]
                        await self.send_msg("POSITION_UPDATE", {
                            "position_id": lp["position_id"],
                            "mt5_ticket": ticket,
                            "current_sl": mp["current_sl"],
                            "current_price": mp["current_price"],
                            "unrealized_pnl": mp["unrealized_pnl"],
                        })

                # Detect positions we think are open but MT5 says closed → SL hit locally
                for lp in local_positions:
                    ticket = lp["mt5_ticket"]
                    if ticket not in mt5_tickets:
                        # Position was closed by broker (SL hit or manual)
                        # Query deal history to find exit price
                        deals = executor.get_recent_deals(lp["open_ts"] - 60)
                        exit_price = 0
                        realized_pnl = 0
                        for d in deals:
                            if d["position_id"] == ticket:
                                exit_price = d["price"]
                                realized_pnl += d["profit"]

                        self.log.info(f"Detected external close of {lp['position_id']} @{exit_price:.2f}")
                        self.state.close_position(lp["position_id"], {
                            "close_ts": int(time.time()),
                            "exit_price": exit_price,
                            "exit_reason": "external_close",
                            "realized_pnl": realized_pnl,
                            "status": "CLOSED",
                        })
                        await self.send_msg("POSITION_CLOSED", {
                            "position_id": lp["position_id"],
                            "signal_id": lp["signal_id"],
                            "exit_price": exit_price,
                            "exit_time": int(time.time()),
                            "realized_pnl": realized_pnl,
                            "exit_reason": "external_close",
                        })

            except Exception as e:
                self.log.error(f"position_poller: {e}")
                await self.send_error("POSITION_POLL_FAILED", str(e))

            await asyncio.sleep(POSITION_POLL_INTERVAL_SEC)

    # ==============================================================
    # DAILY DD CHECK
    # ==============================================================
    def _check_daily_dd(self):
        limit = self.config["risk"].get("max_daily_loss_usd", 0)
        if limit <= 0 or not self.config["risk"].get("auto_halt_on_daily_loss", True):
            return
        # Reset day boundary using simple UTC date
        now = datetime.utcnow().date()
        if self.today_date != now:
            self.today_date = now
            self.halted_by_dd = False
            self.day_start_balance = self.account_balance()

        bal = self.account_balance()
        if self.day_start_balance == 0:
            self.day_start_balance = bal
        day_pnl = bal - self.day_start_balance
        if day_pnl <= -limit and not self.halted_by_dd:
            self.halted_by_dd = True
            self.log.warning(f"HALTED by daily DD: ${day_pnl:.2f} <= -${limit}")
            asyncio.create_task(self.send_error("DAILY_DD_HALT",
                                                 f"Daily loss ${day_pnl:.2f} exceeded ${limit}"))

    # ==============================================================
    # HEARTBEAT
    # ==============================================================
    async def heartbeat_loop(self):
        while self.running:
            try:
                bal = self.account_balance() if self.mt5_ok else 0
                eq = self.account_equity() if self.mt5_ok else 0
                positions = self.state.open_positions()
                self._check_daily_dd()

                await self.send_msg("HEARTBEAT", {
                    "current_state": "HALTED" if (self.halted_by_mother or self.halted_by_dd) else "READY",
                    "mt5_ok": self.mt5_ok,
                    "balance": bal,
                    "equity": eq,
                    "position_count": len(positions),
                })
            except Exception:
                pass
            await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)

    # ==============================================================
    # MOTHER CONNECTION
    # ==============================================================
    async def mother_connection_loop(self):
        backoff = WS_RETRY_BASE_SEC
        while self.running:
            try:
                uri = f"ws://{self.mother_host}:{self.mother_port}/fleet"
                self.log.info(f"Connecting to mother: {uri}")

                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(uri, heartbeat=30, autoping=True, timeout=15) as ws:
                        self.mother_ws = ws
                        backoff = WS_RETRY_BASE_SEC

                        # Handshake
                        await ws.send_str(json.dumps({
                            "type": "HANDSHAKE",
                            "vm_id": self.vm_id,
                            "shared_secret": self.shared_secret,
                            "timestamp_ms": int(time.time() * 1000),
                        }))
                        ack_msg = await asyncio.wait_for(ws.receive(), timeout=10)
                        if ack_msg.type != aiohttp.WSMsgType.TEXT:
                            raise RuntimeError(f"Bad handshake type: {ack_msg.type}")
                        ack_data = json.loads(ack_msg.data)
                        if ack_data.get("type") != "HANDSHAKE_OK":
                            raise RuntimeError(f"Handshake rejected: {ack_data}")

                        self.log.info("Handshake OK with mother")

                        await self.send_msg("VM_ONLINE", {"version": "4.0"})

                        # Command loop
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    m = json.loads(msg.data)
                                    await self._handle_mother_message(m)
                                except Exception as e:
                                    self.log.error(f"handle mother msg: {e}\n{traceback.format_exc()}")
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break

            except Exception as e:
                self.mother_ws = None
                self.log.warning(f"Mother connection lost: {e}. Retry in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, WS_RETRY_MAX_SEC)

    async def _handle_mother_message(self, msg):
        mt = msg.get("type")
        data = msg.get("data", {})

        if mt == "SIGNAL_OPEN":
            asyncio.create_task(self.handle_signal_open(msg))
        elif mt == "SIGNAL_MODIFY_SL":
            asyncio.create_task(self.handle_signal_modify_sl(msg))
        elif mt == "SIGNAL_CLOSE":
            asyncio.create_task(self.handle_signal_close(msg))

        elif mt == "PUSH_CONFIG":
            try:
                self.apply_config(data["full_config"])
                self.pending_config_event.set()
            except Exception as e:
                await self.send_error("CONFIG_INVALID", str(e))

        elif mt == "HALT_TRADING":
            self.halted_by_mother = True
            self.log.warning("HALTED by mother")

        elif mt == "RESUME_TRADING":
            self.halted_by_mother = False
            self.halted_by_dd = False
            self.log.info("RESUMED by mother")

        elif mt == "CLOSE_ALL_POSITIONS":
            positions = self.state.open_positions()
            for p in positions:
                ok, result = executor.close_position(p["symbol"], p["mt5_ticket"])
                if ok:
                    self.state.close_position(p["position_id"], {
                        "close_ts": int(time.time()),
                        "exit_price": result["exit_price"],
                        "exit_reason": "manual_close_all",
                        "realized_pnl": result["realized_pnl"],
                        "status": "CLOSED",
                    })
                    await self.send_msg("POSITION_CLOSED", {
                        "position_id": p["position_id"],
                        "signal_id": p["signal_id"],
                        "exit_price": result["exit_price"],
                        "exit_time": int(time.time()),
                        "realized_pnl": result["realized_pnl"],
                        "exit_reason": "manual_close_all",
                    })

        elif mt == "REPORT_ACTUAL_STATE":
            # Mother wants raw truth from our MT5
            await self._report_actual_state()
    async def _report_actual_state(self):
        """
        Query MT5 for open positions AND recent deal history.
        Send back to mother for reconciliation.
        """
        try:
            open_positions = executor.get_open_positions(symbol=self.symbol)
            # Last 24h of deals for closed-trade reconciliation
            from_ts = int(time.time()) - 86400
            recent_deals = executor.get_recent_deals(from_ts)

            await self.send_msg("ACTUAL_STATE_REPORT", {
                "reported_at_ms": int(time.time() * 1000),
                "open_positions": open_positions,
                "recent_deals": recent_deals,
                "mt5_ok": self.mt5_ok,
                "account_balance": self.account_balance(),
                "account_equity": self.account_equity(),
            })
            self.log.info(f"Sent actual state: {len(open_positions)} open positions, {len(recent_deals)} deals")
        except Exception as e:
            self.log.error(f"_report_actual_state failed: {e}")
            await self.send_error("REPORT_STATE_FAILED", str(e))
    # ==============================================================
    # MAIN
    # ==============================================================
    async def main_loop(self):
        if self.config is None:
            self.log.info("Awaiting config from mother...")
            await self.pending_config_event.wait()

        # MT5 connect with retry
        mt5_backoff = MT5_RETRY_BASE_SEC
        while self.running and not self.mt5_ok:
            try:
                self.mt5_connect()
            except Exception as e:
                self.log.error(f"MT5 connect failed: {e}. Retry in {mt5_backoff}s")
                await asyncio.sleep(mt5_backoff)
                mt5_backoff = min(mt5_backoff * 2, MT5_RETRY_MAX_SEC)

        # Just wait — signals come from mother
        while self.running:
            await asyncio.sleep(1)


# ============================================================
# ENTRY
# ============================================================
async def main():
    vm_id = os.environ.get("VM_ID", "vm1")
    mother_host = os.environ.get("MOTHER_HOST", "127.0.0.1")
    mother_port = int(os.environ.get("MOTHER_PORT", "8765"))
    shared_secret = os.environ.get("SHARED_SECRET", "changeme")

    setup_logging(vm_id)
    log = logging.getLogger("main")
    log.info(f"VM {vm_id} V3 starting. mother={mother_host}:{mother_port}")

    engine = VMEngine(vm_id, mother_host, mother_port, shared_secret)
    engine.load_local_config()

    def _shutdown(*_):
        engine.running = False
        engine.state.set_meta("last_shutdown", int(time.time()))
    for s in (sig_module.SIGTERM, sig_module.SIGINT):
        try:
            asyncio.get_event_loop().add_signal_handler(s, _shutdown)
        except NotImplementedError:
            pass

    tasks = [
        asyncio.create_task(engine.mother_connection_loop()),
        asyncio.create_task(engine.heartbeat_loop()),
        asyncio.create_task(engine.main_loop()),
        asyncio.create_task(engine._outbound_sender()),
        asyncio.create_task(engine.position_poller()),
    ]

    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        log.critical(f"Fatal: {e}\n{traceback.format_exc()}")
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
```
