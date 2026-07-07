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
        ]:
            try:
                self.conn.execute(f"ALTER TABLE trades ADD COLUMN {col}")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass  # already exists

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

        tasks = [
            asyncio.create_task(self.tick_loop()),
            asyncio.create_task(self.stale_monitor()),
            asyncio.create_task(self.dedup_cleanup_loop()),
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