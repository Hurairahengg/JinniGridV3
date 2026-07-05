"""
mother/main.py — Mother orchestrator.

Owns: WebSocket fleet server, HTTP dashboard server, SQLite fleet.db,
validator (with own MT5 tick stream), config manager (per-VM), Telegram
notifier, and event/command routing between VMs and dashboard.

Never trades. Only observes, validates, coordinates.
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
from datetime import datetime, timezone
from pathlib import Path

import requests
from aiohttp import web

from core.validator import Validator, validate_config


# ============================================================
# MOTHER CONFIG LOADER
# ============================================================
MOTHER_CONFIG_PATH = Path("config.json")


def load_mother_config():
    if not MOTHER_CONFIG_PATH.exists():
        raise RuntimeError(f"Missing {MOTHER_CONFIG_PATH}. Create it (see README).")
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

# Strategy periods are LOCKED constants (hardcoded in vm/strategy.py).
# Mother needs them for validator symbol registration only.
LOCKED_MAIN_MA_PERIOD = 21
LOCKED_FAST_MA_PERIOD = 14


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
# TELEGRAM (mother-owned)
# ============================================================
class Telegram:
    def __init__(self, cfg_tg):
        self.enabled = cfg_tg.get("enabled", False)
        self.token = cfg_tg.get("bot_token", "")
        self.chat_id = cfg_tg.get("chat_id", "")
        self.opts = cfg_tg
        self._url = f"https://api.telegram.org/bot{self.token}/sendMessage" if self.token else None
        self.log = logging.getLogger("telegram")

    def _send(self, text):
        if not self.enabled or not self._url:
            return
        try:
            requests.post(
                self._url,
                data={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                timeout=8,
            )
        except Exception as e:
            self.log.error(f"send error: {e}")

    def startup(self):
        if self.opts.get("send_startup"):
            self._send("🚀 <b>JinniGrid Mother started</b>")

    def vm_online(self, vm_id):
        if self.opts.get("send_vm_online"):
            self._send(f"🟢 <b>[{vm_id}]</b> VM online")

    def vm_offline(self, vm_id):
        if self.opts.get("send_vm_offline"):
            self._send(f"🔴 <b>[{vm_id}]</b> VM offline")

    def trade_open(self, vm_id, data):
        if not self.opts.get("send_every_trade"):
            return
        d = "LONG" if data["direction"] == 1 else "SHORT"
        arrow = "📈" if data["direction"] == 1 else "📉"
        self._send(
            f"{arrow} <b>[{vm_id}] {d} opened</b>\n"
            f"Symbol: <code>{data.get('symbol', '')}</code>\n"
            f"Entry: <code>{data['entry_price']:.2f}</code>\n"
            f"SL: <code>{data['sl_price']:.2f}</code>\n"
            f"Lots: <code>{data['lots']:.2f}</code>\n"
            f"Main HMA: <code>{data.get('main_ma_value', 0):.2f}</code> ({data.get('main_slope_value', 0):+.3f}%)\n"
            f"Fast HMA: <code>{data.get('fast_ma_value', 0):.2f}</code> ({data.get('fast_slope_value', 0):+.3f}%)"
        )

    def trade_close(self, vm_id, data):
        if not self.opts.get("send_every_trade"):
            return
        pnl = data.get("pnl_net", 0)
        emoji = "✅" if pnl > 0 else "🚨"
        sign = "+" if pnl >= 0 else ""
        result = "WIN" if pnl > 0 else "LOSS"
        self._send(
            f"{emoji} <b>[{vm_id}] Trade closed {result}</b>\n"
            f"Exit: <code>{data['exit_price']:.2f}</code>\n"
            f"PnL: <code>{sign}${pnl:.2f}</code>\n"
            f"Reason: <code>{data['exit_reason']}</code>\n"
            f"Held: {data.get('bars_held', 0)} bars / {data.get('minutes_held', 0):.1f} min"
        )

    def validation_alert(self, vm_id, trade_id, status, confidence):
        if not self.opts.get("send_validation_mismatches"):
            return
        self._send(
            f"⚠️ <b>[{vm_id}] Validation {status}</b>\n"
            f"Trade: <code>{trade_id[:12]}</code>\n"
            f"Confidence: <code>{confidence:.1f}%</code>"
        )

    def error(self, vm_id, msg):
        if self.opts.get("send_errors"):
            self._send(f"❌ <b>[{vm_id}]</b> {msg[:400]}")

    def warning(self, vm_id, msg):
        if self.opts.get("send_errors"):
            self._send(f"⚠️ <b>[{vm_id}]</b> {msg[:400]}")


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
        config_hash TEXT,
        validation_score REAL DEFAULT 100.0,
        symbol TEXT,
        balance REAL DEFAULT 0,
        equity REAL DEFAULT 0,
        peak_balance REAL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS trades (
        id TEXT PRIMARY KEY,
        vm_id TEXT,
        symbol TEXT,
        direction INTEGER,
        entry_time INTEGER,
        entry_price REAL,
        exit_time INTEGER,
        exit_price REAL,
        sl_price REAL,
        lots REAL,
        pnl_gross REAL,
        cost REAL,
        pnl_net REAL,
        exit_reason TEXT,
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
    CREATE INDEX IF NOT EXISTS idx_events_vm ON events(vm_id);

    CREATE TABLE IF NOT EXISTS positions (
        id TEXT PRIMARY KEY,
        vm_id TEXT,
        symbol TEXT,
        direction INTEGER,
        entry_time INTEGER,
        entry_price REAL,
        current_sl REAL,
        current_price REAL,
        unrealized_pnl REAL,
        opened_at INTEGER,
        last_update INTEGER
    );

    CREATE TABLE IF NOT EXISTS validation_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id TEXT,
        vm_id TEXT,
        result_status TEXT,
        confidence_score REAL,
        entry_price_diff REAL,
        main_ma_diff REAL,
        fast_ma_diff REAL,
        fast_slope_diff REAL,
        main_slope_diff REAL,
        details TEXT,
        validated_at INTEGER
    );

    CREATE TABLE IF NOT EXISTS config_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vm_id TEXT,
        config_snapshot TEXT,
        changed_by TEXT,
        change_reason TEXT,
        timestamp INTEGER
    );

    CREATE TABLE IF NOT EXISTS fleet_kpis (
        timestamp INTEGER PRIMARY KEY,
        total_balance REAL,
        today_pnl REAL,
        active_positions INTEGER,
        connected_vms INTEGER,
        validation_score REAL
    );

    CREATE TABLE IF NOT EXISTS equity_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vm_id TEXT,
        timestamp INTEGER,
        balance REAL,
        equity REAL
    );
    CREATE INDEX IF NOT EXISTS idx_eq_vm_ts ON equity_snapshots(vm_id, timestamp);
    """

    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.executescript(self.SCHEMA)
        self.conn.commit()

    def upsert_vm(self, vm_id, updates):
        existing = self.conn.execute("SELECT id FROM vms WHERE id=?", (vm_id,)).fetchone()
        if existing:
            sets = ",".join(f"{k}=?" for k in updates.keys())
            self.conn.execute(f"UPDATE vms SET {sets} WHERE id=?", list(updates.values()) + [vm_id])
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
            (id, vm_id, symbol, direction, entry_time, entry_price, sl_price, lots)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (trade["trade_id"], vm_id, trade["symbol"], trade["direction"],
              trade["entry_brick"]["time"], trade["entry_price"], trade["sl_price"], trade["lots"]))
        self.conn.commit()

    def update_trade_close(self, trade_id, close_data):
        self.conn.execute("""
            UPDATE trades SET exit_time=?, exit_price=?, exit_reason=?, pnl_gross=?, cost=?, pnl_net=?
            WHERE id=?
        """, (close_data["exit_time"], close_data["exit_price"], close_data["exit_reason"],
              close_data["pnl_gross"], close_data["cost"], close_data["pnl_net"], trade_id))
        self.conn.commit()

    def attach_validation(self, trade_id, vm_id, result):
        self.conn.execute("""
            UPDATE trades SET validation_status=?, validation_confidence=?, mismatch_details=?
            WHERE id=?
        """, (result.status, result.confidence, json.dumps(result.details), trade_id))
        self.conn.execute("""
            INSERT INTO validation_results
            (trade_id, vm_id, result_status, confidence_score, entry_price_diff,
             main_ma_diff, fast_ma_diff, fast_slope_diff, main_slope_diff, details, validated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (trade_id, vm_id, result.status, result.confidence,
              result.entry_price_diff_pct, result.main_ma_diff_pct, result.fast_ma_diff_pct,
              result.fast_slope_diff_abs, result.main_slope_diff_abs,
              json.dumps(result.details), int(time.time())))
        self.conn.commit()

    def save_config_history(self, vm_id, config, changed_by, reason):
        self.conn.execute("""
            INSERT INTO config_history (vm_id, config_snapshot, changed_by, change_reason, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (vm_id, json.dumps(config), changed_by, reason, int(time.time())))
        self.conn.commit()

    def snapshot_equity(self, vm_id, balance, equity):
        self.conn.execute(
            "INSERT INTO equity_snapshots (vm_id, timestamp, balance, equity) VALUES (?, ?, ?, ?)",
            (vm_id, int(time.time()), balance, equity)
        )
        self.conn.commit()

    def snapshot_fleet_kpis(self, kpis):
        self.conn.execute("""
            INSERT OR REPLACE INTO fleet_kpis
            (timestamp, total_balance, today_pnl, active_positions, connected_vms, validation_score)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (int(time.time()), kpis["total_balance"], kpis["today_pnl"],
              kpis["active_positions"], kpis["connected_vms"], kpis["validation_score"]))
        self.conn.commit()

    def get_vms(self):
        rows = self.conn.execute("SELECT * FROM vms").fetchall()
        cols = [d[0] for d in self.conn.execute("SELECT * FROM vms LIMIT 0").description]
        return [dict(zip(cols, r)) for r in rows]

    def get_trades_last(self, limit=500):
        rows = self.conn.execute(
            "SELECT id, vm_id, symbol, direction, entry_time, entry_price, exit_time, exit_price, "
            "sl_price, lots, pnl_gross, cost, pnl_net, exit_reason, validation_status, "
            "validation_confidence FROM trades ORDER BY entry_time DESC LIMIT ?",
            (limit,)
        ).fetchall()
        keys = ["trade_id", "vm_id", "symbol", "direction", "entry_ts", "entry_price",
                "exit_ts", "exit_price", "sl_price", "lots", "pnl_gross", "cost",
                "pnl_dollars_net", "exit_reason", "validation_status", "validation_confidence"]
        return [dict(zip(keys, r)) for r in rows]

    def get_events_last(self, vm_id=None, limit=200):
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
            self.log.error(f"Failed to load config {p}: {e}")
            return None

    def save(self, vm_id, config, changed_by="user", reason=""):
        ok, errors, warnings = validate_config(config)
        if not ok:
            return False, errors, warnings
        p = self.path_for(vm_id)
        with open(p, "w") as f:
            json.dump(config, f, indent=2)
        snap_name = f"{vm_id}_{int(time.time())}.json"
        with open(CONFIG_HISTORY_DIR / snap_name, "w") as f:
            json.dump(config, f, indent=2)
        self.db.save_config_history(vm_id, config, changed_by, reason)
        return True, [], warnings

    def config_hash(self, config):
        return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16]

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
# FLEET STATE (in-memory)
# ============================================================
class FleetState:
    def __init__(self):
        self.vms = {}
        self.positions = {}
        self.recent_bars = {}
        self.alerts = []

    def upsert_vm(self, vm_id, **patch):
        if vm_id not in self.vms:
            self.vms[vm_id] = {
                "vm_id": vm_id, "status": "unknown", "balance": 0, "equity": 0,
                "position_count": 0, "today_trades": 0, "validation_score": 100.0
            }
        self.vms[vm_id].update(patch)


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
        self.validator = Validator(on_validation_ready=self._on_validation, log=self.log)
        self.tg = Telegram(MOTHER_CFG["telegram"])
        self.running = True
        self._startup_ts = int(time.time())

    # ---------- Startup ----------
    async def start(self):
        self.log.info("=" * 60)
        self.log.info("Mother startup")
        self.log.info(f"Dashboard port: {DASHBOARD_PORT}")
        self.log.info(f"Fleet port: {FLEET_PORT}")
        self.log.info(f"Telegram enabled: {self.tg.enabled}")
        self.log.info("=" * 60)

        self.tg.startup()

        configs = self.cfg_mgr.list_all()
        # Pre-populate state.vms with configured VMs (so dashboard shows them even before they connect)
        for vm_id, cfg in configs.items():
            if vm_id not in self.state.vms:
                self.state.upsert_vm(
                    vm_id,
                    status="not_connected",
                    symbol=cfg.get("symbol", ""),
                    balance=0,
                    equity=0,
                    last_seen=0,
                )
        self.log.info(f"Pre-populated {len(configs)} VMs from configs")
        self.log.info(f"Loaded {len(configs)} VM configs: {list(configs.keys())}")

        # Try validator MT5 connection
        if MOTHER_CFG["validator"]["enabled"]:
            try:
                self.validator.mt5_connect()
            except Exception as e:
                self.log.warning(f"Validator MT5 unavailable: {e}. Trades will NOT be validated.")
        else:
            self.log.info("Validator disabled in mother config")

        # Register symbols + warmup
        if self.validator.mt5_ok:
            for vm_id, cfg in configs.items():
                self.validator.register_symbol(
                    cfg["symbol"], cfg["brick_size"],
                    LOCKED_MAIN_MA_PERIOD, LOCKED_FAST_MA_PERIOD,
                )
            warmup_tasks = []
            for (symbol, bs) in list(self.validator.monitors.keys()):
                warmup_tasks.append(
                    self.validator.warmup_symbol(symbol, bs, days=MOTHER_CFG["validator"]["warmup_days"])
                )
            if warmup_tasks:
                await asyncio.gather(*warmup_tasks, return_exceptions=True)

    # ---------- Fleet WebSocket (VM connections) ----------
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
                self.log.warning(f"Rejected handshake from {handshake.get('vm_id')}: bad secret")
                return ws

            vm_id = handshake["vm_id"]
            self.vm_connections[vm_id] = ws
            await ws.send_json({"type": "HANDSHAKE_OK", "server_ts": int(time.time() * 1000)})
            self.log.info(f"VM {vm_id} connected")
            self.state.upsert_vm(vm_id, status="online", last_seen=int(time.time()))
            self.tg.vm_online(vm_id)

            # Auto-push config if exists
            cfg = self.cfg_mgr.load(vm_id)
            if cfg is not None:
                await ws.send_json({
                    "type": "PUSH_CONFIG",
                    "timestamp": int(time.time() * 1000),
                    "message_id": str(uuid.uuid4()),
                    "data": {"full_config": cfg},
                })
                self.log.info(f"Auto-pushed config to {vm_id}")
                await self._broadcast_dashboard({
                    "type": "toast", "level": "info",
                    "message": f"VM {vm_id} auto-configured"
                })
            else:
                self.log.info(f"VM {vm_id} awaiting config (no configs/{vm_id}.json)")
                await self._broadcast_dashboard({
                    "type": "toast", "level": "warning",
                    "message": f"VM {vm_id} awaiting config"
                })

            # Event loop
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self._handle_vm_event(vm_id, data)
                    except Exception as e:
                        self.log.error(f"VM event error: {e}\n{traceback.format_exc()}")

        except Exception as e:
            self.log.error(f"VM WS error: {e}")
        finally:
            if vm_id and vm_id in self.vm_connections:
                del self.vm_connections[vm_id]
                self.state.upsert_vm(vm_id, status="offline")
                await self._broadcast_dashboard({
                    "type": "vm_status_change", "vm_id": vm_id, "status": "offline"
                })
                self.tg.vm_offline(vm_id)
                self.log.info(f"VM {vm_id} disconnected")
        return ws

    async def _handle_vm_event(self, vm_id, msg):
        event_type = msg.get("type")
        data = msg.get("data", {})

        # Persist non-noisy events
        if event_type not in ("HEARTBEAT", "BAR_FORMED"):
            severity = ("ERROR" if event_type == "ERROR"
                        else "WARNING" if event_type == "WARNING"
                        else "INFO")
            self.db.insert_event(vm_id, event_type, severity, data)

        # Route
        if event_type == "VM_ONLINE":
            self.state.upsert_vm(vm_id, status="online", last_seen=int(time.time()))

        elif event_type == "HEARTBEAT":
            update = {
                "status": data.get("current_state", "online").lower(),
                "last_seen": int(time.time()),
                "position_count": data.get("position_count", 0),
                "today_trades": data.get("today_trades", 0),
            }
            # Persist balance from heartbeat if provided
            if data.get("balance"):
                update["balance"] = data["balance"]
            if data.get("equity"):
                update["equity"] = data["equity"]
            self.state.upsert_vm(vm_id, **update)


        elif event_type == "AWAITING_CONFIG":
            self.state.upsert_vm(vm_id, status="awaiting_config")

        elif event_type == "CONFIG_APPLIED":
            self.state.upsert_vm(vm_id, config_hash=data.get("config_hash"))

        elif event_type == "WARMUP_PROGRESS":
            self.state.upsert_vm(
                vm_id, status="warming_up",
                warmup_current=data.get("current_bars", 0),
                warmup_required=data.get("required_bars", 200),
            )

        elif event_type == "READY_TO_TRADE":
            bal = data.get("mt5_balance", 0)
            eq = data.get("mt5_equity", 0)
            self.state.upsert_vm(vm_id, status="trading", balance=bal, equity=eq)
            self.db.upsert_vm(vm_id, {
                "status": "trading", "balance": bal, "equity": eq,
                "last_seen": int(time.time()),
            })
            self.db.snapshot_equity(vm_id, bal, eq)

        elif event_type == "BAR_FORMED":
            # Live chart update — not persisted (too noisy)
            symbol = data.get("symbol")
            brick = data.get("brick")
            if brick:
                await self._broadcast_dashboard({
                    "type": "bar_new", "vm_id": vm_id, "symbol": symbol,
                    "bar": brick, "main_ma": data.get("main_ma"), "fast_ma": data.get("fast_ma"),
                })
                return

        elif event_type == "TRADE_OPEN":
            self.db.upsert_trade_open(vm_id, data)
            self.tg.trade_open(vm_id, data)

            # Independent validation
            try:
                result = self.validator.validate_trade(data)
                self.db.attach_validation(data["trade_id"], vm_id, result)
                if result.status in ("MAJOR_MISMATCH", "NO_SIGNAL"):
                    await self._broadcast_dashboard({
                        "type": "toast", "level": "error",
                        "message": f"⚠️ {vm_id}: {result.status} on trade {data['trade_id'][:8]}"
                    })
                    self.tg.validation_alert(vm_id, data["trade_id"], result.status, result.confidence)
                await self._broadcast_dashboard({
                    "type": "validation_result",
                    "trade_id": data["trade_id"],
                    "vm_id": vm_id,
                    "result": {
                        "status": result.status,
                        "confidence": result.confidence,
                        "details": result.details,
                    }
                })
            except Exception as e:
                self.log.error(f"Validation failed: {e}")

        elif event_type == "TRADE_CLOSE":
            self.db.update_trade_close(data["trade_id"], data)
            self.tg.trade_close(vm_id, data)

        elif event_type == "ERROR":
            await self._broadcast_dashboard({
                "type": "toast", "level": "error",
                "message": f"❌ {vm_id}: {data.get('error_message', 'unknown')[:100]}"
            })
            self.tg.error(vm_id, data.get("error_message", ""))

        elif event_type == "WARNING":
            await self._broadcast_dashboard({
                "type": "toast", "level": "warning",
                "message": f"⚠️ {vm_id}: {data.get('message', '')[:100]}"
            })
            self.tg.warning(vm_id, data.get("message", ""))

        # Generic broadcast to dashboard
        await self._broadcast_dashboard({
            "type": "vm_event",
            "vm_id": vm_id,
            "event_type": event_type,
            "data": data,
            "timestamp": int(time.time() * 1000),
        })

    def _on_validation(self, trade_id, vm_id, result):
        # Not used — validation runs synchronously in _handle_vm_event
        pass

    # ---------- Command routing (mother → VM) ----------
    async def send_command_to_vm(self, vm_id, cmd_type, data):
        ws = self.vm_connections.get(vm_id)
        if ws is None:
            return False, "VM not connected"
        try:
            await ws.send_json({
                "type": cmd_type,
                "timestamp": int(time.time() * 1000),
                "message_id": str(uuid.uuid4()),
                "data": data,
            })
            return True, "ok"
        except Exception as e:
            return False, str(e)

    # ---------- Dashboard broadcast ----------
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

    # ---------- HTTP handlers ----------
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
            "uptime_seconds": int(time.time()) - self._startup_ts,
            "vms_connected": len(self.vm_connections),
            "validator_mt5_ok": self.validator.mt5_ok,
        })

    async def handle_ready(self, request):
        ready = self.validator.mt5_ok
        return web.json_response({"ready": ready}, status=200 if ready else 503)

    async def handle_dashboard_ws(self, request):
        ws = web.WebSocketResponse(heartbeat=30, autoping=True)
        await ws.prepare(request)
        self.dashboard_clients.add(ws)
        self.log.info(f"Dashboard client connected. total={len(list(self.dashboard_clients))}")
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
            self.log.info("Dashboard client disconnected")
        return ws

    async def _handle_dashboard_msg(self, ws, msg):
        t = msg.get("type")

        if t == "hello":
            await self._send_initial_state(ws)

        elif t == "command":
            action = msg.get("action")
            vm_id = msg.get("vm_id")
            self.log.info(f"Dashboard command: {action} on {vm_id}")

            if action == "halt":
                await self.send_command_to_vm(vm_id, "HALT_TRADING", {"reason": "dashboard"})
                self.db.insert_event(vm_id, "DASHBOARD_ACTION", "INFO",
                                     {"action": "halt", "by": "dashboard"})
            elif action == "resume":
                await self.send_command_to_vm(vm_id, "RESUME_TRADING", {"reason": "dashboard"})
                self.db.insert_event(vm_id, "DASHBOARD_ACTION", "INFO",
                                     {"action": "resume", "by": "dashboard"})
            elif action == "close_all":
                await self.send_command_to_vm(vm_id, "CLOSE_ALL_POSITIONS",
                                              {"reason": "dashboard", "close_type": "market"})
                self.db.insert_event(vm_id, "DASHBOARD_ACTION", "INFO",
                                     {"action": "close_all", "by": "dashboard"})
            elif action == "shutdown":
                await self.send_command_to_vm(vm_id, "SHUTDOWN",
                                              {"graceful": True, "delay_seconds": 0})
                self.db.insert_event(vm_id, "DASHBOARD_ACTION", "WARNING",
                                     {"action": "shutdown", "by": "dashboard"})

            elif action == "push_config":
                cfg = msg.get("config")
                reason = msg.get("reason", "manual edit via dashboard")

                # Capture diff for logs
                old_cfg = self.cfg_mgr.load(vm_id) or {}
                diff_summary = self._diff_summary(old_cfg, cfg)

                ok, errors, warnings = self.cfg_mgr.save(
                    vm_id, cfg, changed_by="dashboard", reason=reason
                )
                if not ok:
                    await ws.send_json({
                        "type": "config_result", "vm_id": vm_id,
                        "ok": False, "errors": errors, "warnings": warnings
                    })
                    self.db.insert_event(vm_id, "CONFIG_REJECTED", "ERROR",
                                         {"errors": errors, "reason": reason})
                    return

                # Log config change with diff details
                self.db.insert_event(vm_id, "CONFIG_UPDATED", "INFO", {
                    "changes": diff_summary,
                    "reason": reason,
                    "by": "dashboard",
                })
                self.log.info(f"Config updated for {vm_id}: {len(diff_summary)} field(s) changed")

                # Push to VM
                sent, err = await self.send_command_to_vm(
                    vm_id, "PUSH_CONFIG", {"full_config": cfg}
                )
                await ws.send_json({
                    "type": "config_result", "vm_id": vm_id,
                    "ok": sent, "errors": [] if sent else [err],
                    "warnings": warnings
                })
                if sent:
                    self.db.insert_event(vm_id, "CONFIG_PUSHED", "INFO", {
                        "reason": reason, "delivered": True
                    })
                    await self._broadcast_dashboard({
                        "type": "toast", "level": "success",
                        "message": f"Config pushed to {vm_id}"
                    })

    def _diff_summary(self, old, new, prefix=""):
        """Return a flat dict of {path: (old_val, new_val)} for changed fields."""
        changes = {}
        for k in set(list(old.keys()) + list(new.keys())):
            path = f"{prefix}.{k}" if prefix else k
            old_v = old.get(k)
            new_v = new.get(k)
            if isinstance(old_v, dict) and isinstance(new_v, dict):
                changes.update(self._diff_summary(old_v, new_v, path))
            elif old_v != new_v:
                changes[path] = {"old": old_v, "new": new_v}
        return changes

    async def _send_initial_state(self, ws):
        # Merge state.vms with all known configs
        all_configs = self.cfg_mgr.list_all()
        merged = {}

        # First, include every VM we have config for
        for vm_id, cfg in all_configs.items():
            state_data = self.state.vms.get(vm_id, {"vm_id": vm_id, "status": "not_connected"})
            merged[vm_id] = dict(state_data)
            merged[vm_id]["config"] = cfg

        # Also include any state.vms that don't have a config yet
        for vm_id, state_data in self.state.vms.items():
            if vm_id not in merged:
                merged[vm_id] = dict(state_data)
                merged[vm_id]["config"] = {}

        # Attach trades/events/equity from DB for each
        for vm_id, vm in merged.items():
            trades = self.db.get_trades_last(500)
            vm["trades"] = [t for t in trades if t.get("vm_id") == vm_id]
            vm["events"] = self.db.get_events_last(vm_id, 200)
            vm["equity_history"] = self.db.get_equity_history(vm_id, 500)
            # Backfill missing fields
            vm.setdefault("balance", 0)
            vm.setdefault("equity", 0)
            vm.setdefault("peak_balance", 0)

        payload = {
            "type": "initial_state",
            "vms": merged,
            "server_time": int(time.time() * 1000),
        }
        await ws.send_str(json.dumps(payload))
        self.log.info(f"Sent initial state with {len(merged)} VMs to dashboard")

    # ---------- Periodic tasks ----------
    async def stale_monitor(self):
        while self.running:
            now = int(time.time())
            for vm_id, vm in list(self.state.vms.items()):
                last_seen = vm.get("last_seen", 0)
                if vm.get("status") in ("online", "trading", "warming_up") and (now - last_seen) > 120:
                    self.state.upsert_vm(vm_id, status="stale")
                    await self._broadcast_dashboard({
                        "type": "vm_status_change", "vm_id": vm_id, "status": "stale"
                    })
                    self.log.warning(f"VM {vm_id} marked STALE (no heartbeat for 120s)")
            await asyncio.sleep(30)

    async def kpi_snapshot_loop(self):
        while self.running:
            try:
                vms = self.state.vms.values()
                total_bal = sum(v.get("balance", 0) for v in vms)
                positions = sum(v.get("position_count", 0) for v in vms)
                connected = sum(1 for v in vms if v.get("status") in ("online", "trading"))
                start = int(datetime.now(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                ).timestamp())
                row = self.db.conn.execute(
                    "SELECT SUM(pnl_net) FROM trades WHERE entry_time>=? AND exit_time IS NOT NULL",
                    (start,)
                ).fetchone()
                today_pnl = row[0] or 0
                self.db.snapshot_fleet_kpis({
                    "total_balance": total_bal, "today_pnl": today_pnl,
                    "active_positions": positions, "connected_vms": connected,
                    "validation_score": 100.0,
                })
            except Exception as e:
                self.log.error(f"KPI snapshot error: {e}")
            await asyncio.sleep(60)

    # ---------- Run ----------
    async def run(self):
        # Dashboard HTTP app
        app = web.Application()
        app.router.add_get("/", self.handle_index)
        app.router.add_get("/health", self.handle_health)
        app.router.add_get("/ready", self.handle_ready)
        app.router.add_get("/ws", self.handle_dashboard_ws)
        app.router.add_get("/{name}", self.handle_asset)

        runner = web.AppRunner(app)
        await runner.setup()
        dashboard_site = web.TCPSite(runner, "0.0.0.0", DASHBOARD_PORT)
        await dashboard_site.start()
        self.log.info(f"Dashboard on port {DASHBOARD_PORT}")

        # Fleet WS app
        fleet_app = web.Application()
        fleet_app.router.add_get("/fleet", self.handle_vm_ws)
        fleet_runner = web.AppRunner(fleet_app)
        await fleet_runner.setup()
        fleet_site = web.TCPSite(fleet_runner, "0.0.0.0", FLEET_PORT)
        await fleet_site.start()
        self.log.info(f"Fleet WS on port {FLEET_PORT}")

        await self.start()

        tasks = [
            asyncio.create_task(self.validator.live_loop()),
            asyncio.create_task(self.stale_monitor()),
            asyncio.create_task(self.kpi_snapshot_loop()),
        ]

        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            self.log.info("Mother shutting down")
            self.validator.stop()
            self.running = False


# ============================================================
# ENTRY POINT
# ============================================================
async def main_async():
    setup_logging()
    log = logging.getLogger("main")
    log.info("=" * 60)
    log.info("JinniGrid Mother")
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