"""
vm/main.py — VM orchestrator.

Owns: MT5 connection, tick loop, bar building via strategy.RenkoBuilder,
signal execution, position management, mother WebSocket link, local SQLite,
event streaming, resume-on-restart.

Strategy execution is DECOUPLED from mother comms via an outbound queue.
Trading NEVER waits for network I/O.
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
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5
import aiohttp

from strategy import RenkoBuilder, Strategy


# ============================================================
# CONSTANTS
# ============================================================
HEARTBEAT_INTERVAL_SEC = 30
BAR_BROADCAST_MIN_INTERVAL = 1.0
WS_RETRY_BASE_SEC = 2
WS_RETRY_MAX_SEC = 60
MT5_RETRY_BASE_SEC = 5
MT5_RETRY_MAX_SEC = 120
MIN_WARMUP_BARS = 200
POLL_INTERVAL_MS = 50


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
# LOCAL STATE DB
# ============================================================
class LocalState:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS trades (
        trade_id TEXT PRIMARY KEY,
        direction INTEGER,
        symbol TEXT,
        entry_ts INTEGER,
        entry_price REAL,
        sl_price REAL,
        lots REAL,
        mt5_ticket INTEGER,
        exit_ts INTEGER,
        exit_price REAL,
        exit_reason TEXT,
        bars_held INTEGER,
        minutes_held REAL,
        pnl_gross REAL,
        cost REAL,
        pnl_net REAL,
        status TEXT
    );
    CREATE TABLE IF NOT EXISTS event_buffer (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payload TEXT,
        created_ts INTEGER
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

    def insert_trade(self, t):
        cols = ",".join(t.keys())
        ph = ",".join("?" for _ in t)
        self.conn.execute(f"INSERT OR REPLACE INTO trades ({cols}) VALUES ({ph})", list(t.values()))
        self.conn.commit()

    def update_trade(self, trade_id, updates):
        sets = ",".join(f"{k}=?" for k in updates.keys())
        self.conn.execute(f"UPDATE trades SET {sets} WHERE trade_id=?", list(updates.values()) + [trade_id])
        self.conn.commit()

    def open_position(self):
        row = self.conn.execute(
            "SELECT trade_id, direction, entry_price, sl_price, lots, mt5_ticket, entry_ts "
            "FROM trades WHERE status='OPEN' LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return {
            "trade_id": row[0], "direction": row[1], "entry_price": row[2],
            "sl_price": row[3], "lots": row[4], "mt5_ticket": row[5], "entry_ts": row[6]
        }

    def todays_trades(self):
        """Trades since Central-time midnight (matches backtest daily boundaries)."""
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        now_central = datetime.now(ZoneInfo("America/Chicago"))
        midnight_central = now_central.replace(hour=0, minute=0, second=0, microsecond=0)
        start = int(midnight_central.timestamp())
        rows = self.conn.execute(
            "SELECT pnl_net FROM trades WHERE entry_ts>=? AND status='CLOSED'", (start,)
        ).fetchall()
        return [r[0] for r in rows if r[0] is not None]

    def buffer_event(self, payload_dict):
        self.conn.execute(
            "INSERT INTO event_buffer (payload, created_ts) VALUES (?, ?)",
            (json.dumps(payload_dict), int(time.time()))
        )
        self.conn.commit()

    def drain_events(self, limit=200):
        rows = self.conn.execute(
            "SELECT id, payload FROM event_buffer ORDER BY id LIMIT ?", (limit,)
        ).fetchall()
        return rows

    def delete_buffered(self, ids):
        if not ids:
            return
        marks = ",".join("?" for _ in ids)
        self.conn.execute(f"DELETE FROM event_buffer WHERE id IN ({marks})", ids)
        self.conn.commit()

    def set_meta(self, k, v):
        self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k, str(v)))
        self.conn.commit()

    def get_meta(self, k, default=None):
        row = self.conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return row[0] if row else default


# ============================================================
# CONFIG VALIDATION
# ============================================================
def validate_config(cfg):
    """Validate the per-VM config (strategy is locked, not in config)."""
    required = {
        "_top": ["symbol", "brick_size", "price_decimals", "cost_per_lot"],
        "risk": ["risk_pct", "max_lots"],
        "session": ["start_hour", "end_hour", "days"],
    }
    for k in required["_top"]:
        if k not in cfg:
            raise ValueError(f"config missing: {k}")
    for section in ("risk", "session"):
        if section not in cfg:
            raise ValueError(f"config missing section: {section}")
        for k in required[section]:
            if k not in cfg[section]:
                raise ValueError(f"config missing {section}.{k}")

    r = cfg["risk"]
    if not (0.0 < r["risk_pct"] <= 5.0):
        raise ValueError(f"risk_pct out of range (0, 5]: {r['risk_pct']}")
    if r["max_lots"] <= 0:
        raise ValueError(f"max_lots must be > 0: {r['max_lots']}")

    s = cfg["session"]
    if not (0 <= s["start_hour"] <= 23) or not (0 <= s["end_hour"] <= 23):
        raise ValueError("session hours must be 0..23")

    return cfg


# ============================================================
# VM ORCHESTRATOR
# ============================================================
class VMEngine:
    def __init__(self, vm_id, mother_host, mother_port, shared_secret):
        self.vm_id = vm_id
        self.mother_host = mother_host
        self.mother_port = mother_port
        self.shared_secret = shared_secret

        self.log = logging.getLogger("engine")
        self.state = LocalState()
        self.config = None
        self.strategy = None
        self.renko = None
        self.symbol = None

        self.running = True
        self.warming_up = False
        self.ready = False
        self.mt5_ok = False
        self.halted_by_mother = False
        self.halted_by_dd = False

        self.today_date = None
        self.day_start_balance = 0.0
        self.session_active_wallclock = False
        self.session_active_reported = False

        self.mother_ws = None
        self.last_bar_broadcast = {}
        self.pending_config_event = asyncio.Event()

        self.abs_bar_count = 0

        # CRITICAL: outbound queue for non-blocking event send
        # Strategy execution never waits for mother comms
        self._outbound_queue = asyncio.Queue(maxsize=10000)

        self._last_msc = 0
        self._is_warming_up = True

    # ---------- Config load / apply ----------
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
        validate_config(cfg)
        self.config = cfg
        self.symbol = cfg["symbol"]
        with open("config.json", "w") as f:
            json.dump(cfg, f, indent=2)
        self.renko = RenkoBuilder(
            brick_size=cfg["brick_size"],
            price_decimals=cfg.get("price_decimals", 2),
            rev_bricks=Strategy.RENKO_REV_BRICKS,
            clean_mode=Strategy.RENKO_CLEAN_MODE,
        )
        self.strategy = Strategy(cfg["session"])
        self.log.info(f"Config applied. Symbol={self.symbol} brick={cfg['brick_size']}")

    # ---------- MT5 ----------
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
            raise RuntimeError(f"Symbol select failed: {self.symbol}")
        info = mt5.account_info()
        if info is None:
            raise RuntimeError("MT5 not logged in")
        self.mt5_ok = True
        self.log.info(f"MT5 connected: login={info.login} balance=${info.balance:,.2f}")
        return info

    def mt5_shutdown(self):
        try:
            mt5.shutdown()
        except Exception:
            pass
        self.mt5_ok = False

    def account_balance(self):
        info = mt5.account_info()
        return float(info.balance) if info else 0.0

    def account_equity(self):
        info = mt5.account_info()
        return float(info.equity) if info else 0.0

    # ---------- Warmup ----------
    async def warmup(self):
        """Pull historical ticks, build bricks silently (no events fired)."""
        self.warming_up = True
        days = self.config.get("data", {}).get("warmup_days", 3)
        now = int(time.time())
        from_ts = now - days * 86400

        self.log.info(f"Warmup: pulling ticks last {days} days...")
        ticks = mt5.copy_ticks_range(
            self.symbol,
            datetime.fromtimestamp(from_ts, tz=timezone.utc),
            datetime.fromtimestamp(now, tz=timezone.utc),
            mt5.COPY_TICKS_ALL,
        )
        if ticks is None or len(ticks) == 0:
            self.log.warning("No warmup ticks retrieved")
            return

        self.log.info(f"Feeding {len(ticks):,} warmup ticks...")

        bars = []
        required = MIN_WARMUP_BARS
        last_progress_report = time.time()

        for t in ticks:
            ts_int = int(t["time"])
            bid = float(t["bid"])
            ask = float(t["ask"])
            price = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else (bid or ask or float(t["last"]))
            if price <= 0:
                continue
            vol = float(t["volume"]) if "volume" in t.dtype.names else 0.0
            new_bricks = self.renko.feed_tick(ts_int, price, vol)
            for b in new_bricks:
                bars.append(b)

            if time.time() - last_progress_report >= 2:
                await self._send_event("WARMUP_PROGRESS", {
                    "symbol": self.symbol,
                    "current_bars": len(bars),
                    "required_bars": required,
                })
                last_progress_report = time.time()

        self.abs_bar_count = len(bars)
        self.strategy.prepend_history(bars, abs_start_index=0)

        self.log.info(f"Warmup done. Bars={len(bars)}")
        await self._send_event("READY_TO_TRADE", {
            "symbols_ready": [self.symbol],
            "mt5_balance": self.account_balance(),
            "mt5_equity": self.account_equity(),
        })
        self.warming_up = False
        self.ready = True

    # ---------- Sessions / risk ----------
    def _session_check(self):
        """
        Wall-clock session gate. Fires SESSION_START / SESSION_END events.
        Uses IANA `America/Chicago` for auto-DST — OS timezone is ignored.
        """
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo

        now_utc = datetime.now(timezone.utc)
        now_central = now_utc.astimezone(ZoneInfo("America/Chicago"))
        today = now_central.date()
        cst_hour = now_central.hour
        cst_weekday = now_central.weekday()

        session_hours = set(range(self.config["session"]["start_hour"],
                                    self.config["session"]["end_hour"] + 1))
        wd_map = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
        active_days = {wd_map[d] for d in self.config["session"]["days"]}

        # Day rollover based on Central date, not UTC date
        if self.today_date != today:
            self.today_date = today
            self.halted_by_dd = False
            self.day_start_balance = self.account_balance()
            self.log.info(f"Day rollover (Central): {today}")

        in_session = (cst_hour in session_hours) and (cst_weekday in active_days)

        if self.today_date != today:
            self.today_date = today
            self.halted_by_dd = False
            self.day_start_balance = self.account_balance()
            self.log.info(f"Day rollover: {today}")

        in_session = (cst_hour in session_hours) and (now.weekday() in active_days)

        if in_session and not self.session_active_wallclock:
            self.session_active_wallclock = True
            asyncio.create_task(self._send_event("SESSION_START", {
                "session_name": "NY",
                "start_time": int(time.time()),
            }))
            self.log.info("SESSION_START (NY)")

        if not in_session and self.session_active_wallclock:
            self.session_active_wallclock = False
            pnls = self.state.todays_trades()
            asyncio.create_task(self._send_event("SESSION_END", {
                "session_name": "NY",
                "end_time": int(time.time()),
                "session_pnl": sum(pnls),
                "session_trades": len(pnls),
            }))
            self.log.info(f"SESSION_END. trades={len(pnls)} pnl=${sum(pnls):.2f}")

    def _check_daily_dd(self):
        limit = self.config["risk"].get("max_daily_loss_usd", 0)
        if limit <= 0 or not self.config["risk"].get("auto_halt_on_daily_loss", True):
            return
        bal = self.account_balance()
        if self.day_start_balance == 0:
            self.day_start_balance = bal
        day_pnl = bal - self.day_start_balance
        if day_pnl <= -limit and not self.halted_by_dd:
            self.halted_by_dd = True
            asyncio.create_task(self._send_event("WARNING", {
                "warning_code": "DAILY_DD_HALT",
                "message": f"Daily loss ${day_pnl:.2f} exceeded ${limit}",
                "context": {"day_pnl": day_pnl, "limit": limit},
            }))
            self.log.warning(f"HALTED by daily DD: ${day_pnl:.2f} <= -${limit}")

    # ---------- Bar handling / signal execution ----------
    async def on_new_brick(self, brick):
        self.abs_bar_count += 1
        self.strategy.append_brick(brick)

        # Throttled BAR_FORMED broadcast (non-blocking via queue)
        now = time.time()
        last = self.last_bar_broadcast.get(self.symbol, 0)
        if now - last >= BAR_BROADCAST_MIN_INTERVAL:
            closes = [b["close"] for b in self.strategy.bars]
            main_ma = self.strategy.main_hma._compute(closes)
            fast_ma = self.strategy.fast_hma._compute(closes)
            await self._send_event("BAR_FORMED", {
                "symbol": self.symbol,
                "brick": brick,
                "main_ma": main_ma,
                "fast_ma": fast_ma,
            })
            self.last_bar_broadcast[self.symbol] = now

        # Handle exit first if in position
        position = self.state.open_position()
        if position:
            exit_sig = self._recompute_exit(position)
            if exit_sig:
                await self._handle_exit(position, exit_sig)
            return

        # No position — check for entry
        if self.halted_by_mother or self.halted_by_dd:
            return

        signal = self.strategy.evaluate(
            live_session_active=self.session_active_wallclock,
            in_position=False,
        )
        if signal is None:
            return

        await self._handle_open(signal)

    def _recompute_exit(self, position):
        entry_abs_idx = int(self.state.get_meta(f"entry_abs_idx_{position['trade_id']}", -1))
        if entry_abs_idx < 0:
            entry_abs_idx = self.abs_bar_count - 1
        return self.strategy._check_exit({
            "direction": position["direction"],
            "sl_price": position["sl_price"],
            "entry_abs_index": entry_abs_idx,
        })

    async def _handle_open(self, signal):
        risk_mode = self.config["risk"].get("risk_mode", "starting_balance")
        risk_pct = self.config["risk"]["risk_pct"]
        starting_bal = self.config["risk"].get("starting_balance", self.account_balance())
        base_bal = self.account_balance() if risk_mode == "current_balance" else starting_bal
        risk_usd = base_bal * risk_pct / 100.0

        sl_dist = abs(signal.entry_price - signal.sl_price)
        if sl_dist <= 0:
            return

        raw_lots = risk_usd / sl_dist
        lot_step = self.config["risk"].get("lot_step", 0.01)
        min_lot = self.config["risk"].get("min_lot", 0.01)
        max_lot = self.config["risk"]["max_lots"]
        lots = math.floor(raw_lots / lot_step) * lot_step
        lots = max(min_lot, min(max_lot, lots))

        info = mt5.symbol_info(self.symbol)
        if info is not None:
            min_stop = info.trade_stops_level * info.point
            if min_stop > 0 and sl_dist < min_stop:
                self.log.warning(f"SL dist {sl_dist} < broker min {min_stop}, skip")
                return

        try:
            result = self._mt5_open(signal.direction, lots, signal.sl_price)
        except Exception as e:
            self.log.error(f"MT5 open failed: {e}")
            await self._send_event("ERROR", {
                "error_code": "OPEN_FAILED",
                "error_message": str(e), "stack_trace": "", "context": {}
            })
            return

        trade_id = str(uuid.uuid4())
        cost = self.config.get("cost_per_lot", 1.20) * lots

        self.state.insert_trade({
            "trade_id": trade_id, "direction": signal.direction, "symbol": self.symbol,
            "entry_ts": signal.entry_brick["time"], "entry_price": signal.entry_price,
            "sl_price": signal.sl_price, "lots": lots, "mt5_ticket": result.order,
            "exit_ts": None, "exit_price": None, "exit_reason": None,
            "bars_held": None, "minutes_held": None,
            "pnl_gross": None, "cost": cost, "pnl_net": None, "status": "OPEN",
        })
        self.state.set_meta(f"entry_abs_idx_{trade_id}", self.abs_bar_count - 1)

        self.strategy.mark_entered(signal.direction)

        self.log.info(f"OPEN {'LONG' if signal.direction == 1 else 'SHORT'} "
                       f"@ {signal.entry_price:.2f} SL {signal.sl_price:.2f} lots {lots:.2f}")

        await self._send_event("TRADE_OPEN", {
            "trade_id": trade_id, "symbol": self.symbol, "direction": signal.direction,
            "entry_price": signal.entry_price, "sl_price": signal.sl_price, "lots": lots,
            "entry_brick": signal.entry_brick,
            "entry_brick_index": signal.entry_brick_index,
            "main_ma_value": signal.main_ma_value,
            "fast_ma_value": signal.fast_ma_value,
            "fast_slope_value": signal.fast_slope_value,
            "main_slope_value": signal.main_slope_value,
            "confirmation_streak": signal.confirmation_streak,
            "filters_passed": signal.filters_passed,
        })

    def _mt5_open(self, direction, lots, sl_price):
        tick = mt5.symbol_info_tick(self.symbol)
        price = tick.ask if direction == 1 else tick.bid
        order_type = mt5.ORDER_TYPE_BUY if direction == 1 else mt5.ORDER_TYPE_SELL
        req = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": float(lots),
            "type": order_type, "price": price, "sl": float(sl_price), "tp": 0.0,
            "deviation": 20, "magic": 900001, "comment": "JinniGrid",
            "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(req)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"retcode={result.retcode if result else 'None'} err={mt5.last_error()}")
        return result

    def _mt5_close(self, ticket, direction, lots):
        tick = mt5.symbol_info_tick(self.symbol)
        price = tick.bid if direction == 1 else tick.ask
        opp = mt5.ORDER_TYPE_SELL if direction == 1 else mt5.ORDER_TYPE_BUY
        req = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": float(lots),
            "type": opp, "position": int(ticket), "price": price,
            "deviation": 20, "magic": 900001, "comment": "JinniGrid close",
            "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(req)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"retcode={result.retcode if result else 'None'} err={mt5.last_error()}")
        return result

    async def _handle_exit(self, position, exit_sig):
        try:
            self._mt5_close(position["mt5_ticket"], position["direction"], position["lots"])
        except Exception as e:
            self.log.error(f"MT5 close failed: {e}")
            await self._send_event("ERROR", {
                "error_code": "CLOSE_FAILED",
                "error_message": str(e), "stack_trace": "", "context": {}
            })
            return

        pts = (exit_sig.exit_price - position["entry_price"]) * position["direction"]
        gross = pts * position["lots"]
        cost = self.config.get("cost_per_lot", 1.20) * position["lots"]
        net = gross - cost

        exit_ts = exit_sig.exit_brick["time"]
        bars_held = self.abs_bar_count - 1 - int(
            self.state.get_meta(f"entry_abs_idx_{position['trade_id']}", self.abs_bar_count - 1)
        )
        minutes_held = (exit_ts - position["entry_ts"]) / 60.0

        self.state.update_trade(position["trade_id"], {
            "exit_ts": exit_ts, "exit_price": exit_sig.exit_price,
            "exit_reason": exit_sig.reason,
            "bars_held": bars_held, "minutes_held": minutes_held,
            "pnl_gross": gross, "pnl_net": net, "status": "CLOSED",
        })

        self.log.info(f"CLOSE {position['trade_id']} @ {exit_sig.exit_price:.2f} "
                       f"pnl=${net:.2f} reason={exit_sig.reason}")

        await self._send_event("TRADE_CLOSE", {
            "trade_id": position["trade_id"], "exit_time": exit_ts,
            "exit_price": exit_sig.exit_price, "exit_reason": exit_sig.reason,
            "bars_held": bars_held, "minutes_held": minutes_held,
            "pnl_gross": gross, "cost": cost, "pnl_net": net,
            "exit_brick": exit_sig.exit_brick,
        })

        self._check_daily_dd()

    # ============================================================
    # MOTHER COMMS — DECOUPLED FROM STRATEGY
    # ============================================================
    async def _send_event(self, event_type, data):
        """
        Fire-and-forget. NEVER blocks strategy execution.
        Enqueues to outbound queue; dedicated sender task handles delivery.
        If queue is full, spills to SQLite buffer for later replay.
        """
        payload = {
            "type": event_type,
            "timestamp": int(time.time() * 1000),
            "vm_id": self.vm_id,
            "message_id": str(uuid.uuid4()),
            "data": data,
        }
        try:
            self._outbound_queue.put_nowait(payload)
        except asyncio.QueueFull:
            self.state.buffer_event(payload)

    async def _outbound_sender_loop(self):
        """
        Dedicated background task drains outbound queue and sends to mother.
        Isolated from strategy path — mother slowness/disconnect never blocks trading.
        """
        while self.running:
            try:
                payload = await asyncio.wait_for(self._outbound_queue.get(), timeout=1.0)
                sent = False
                if self.mother_ws is not None and not self.mother_ws.closed:
                    try:
                        await self.mother_ws.send_str(json.dumps(payload))
                        sent = True
                    except Exception as e:
                        self.log.debug(f"send failed: {e}")
                if not sent:
                    self.state.buffer_event(payload)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self.log.error(f"Outbound sender error: {e}")
                await asyncio.sleep(1)

    async def _drain_buffered(self):
        """Replay events that were buffered while mother was disconnected."""
        rows = self.state.drain_events(500)
        if not rows:
            return
        sent_ids = []
        for row_id, payload_str in rows:
            try:
                await self.mother_ws.send_str(payload_str)
                sent_ids.append(row_id)
            except Exception:
                break
        self.state.delete_buffered(sent_ids)
        if sent_ids:
            self.log.info(f"Replayed {len(sent_ids)} buffered events")

    async def mother_connection_loop(self):
        """Persistent aiohttp WebSocket link to mother with exponential backoff."""
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
                            "timestamp": int(time.time() * 1000),
                        }))
                        ack_msg = await asyncio.wait_for(ws.receive(), timeout=10)
                        if ack_msg.type != aiohttp.WSMsgType.TEXT:
                            raise RuntimeError(f"Handshake bad type: {ack_msg.type}")
                        ack_data = json.loads(ack_msg.data)
                        if ack_data.get("type") != "HANDSHAKE_OK":
                            raise RuntimeError(f"Handshake rejected: {ack_data}")

                        # Announce online
                        await self._send_event("VM_ONLINE", {
                            "version": "1.0",
                            "capabilities": ["trade", "renko8", "hma"],
                            "last_shutdown_time": self.state.get_meta("last_shutdown", 0),
                        })

                        if self.config is None:
                            await self._send_event("AWAITING_CONFIG", {"reason": "no local config"})

                        # Drain any buffered events
                        await self._drain_buffered()

                        # Command loop
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    m = json.loads(msg.data)
                                    await self._handle_mother_command(m)
                                except Exception as e:
                                    self.log.error(f"Command handling error: {e}\n{traceback.format_exc()}")
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break

            except Exception as e:
                self.mother_ws = None
                self.log.warning(f"Mother connection lost: {e}. Retry in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, WS_RETRY_MAX_SEC)

    async def _handle_mother_command(self, msg):
        cmd = msg.get("type")
        data = msg.get("data", {})
        self.log.info(f"Command from mother: {cmd}")

        if cmd == "PUSH_CONFIG":
            try:
                self.apply_config(data["full_config"])
                await self._send_event("CONFIG_APPLIED", {
                    "config_hash": str(hash(json.dumps(data["full_config"], sort_keys=True))),
                })
                self.pending_config_event.set()
            except Exception as e:
                await self._send_event("ERROR", {
                    "error_code": "CONFIG_INVALID",
                    "error_message": str(e), "stack_trace": "", "context": {},
                })

        elif cmd == "HALT_TRADING":
            self.halted_by_mother = True
            self.log.warning(f"HALTED by mother: {data.get('reason', '')}")

        elif cmd == "RESUME_TRADING":
            self.halted_by_mother = False
            self.halted_by_dd = False
            self.log.info(f"RESUMED by mother: {data.get('reason', '')}")

        elif cmd == "CLOSE_ALL_POSITIONS":
            pos = self.state.open_position()
            if pos:
                try:
                    self._mt5_close(pos["mt5_ticket"], pos["direction"], pos["lots"])
                    self.state.update_trade(pos["trade_id"], {
                        "status": "CLOSED", "exit_reason": "MANUAL_CLOSE",
                        "exit_ts": int(time.time()),
                    })
                    if hasattr(self.strategy, "mark_exited"):
                        self.strategy.mark_exited()
                    await self._send_event("TRADE_CLOSE", {
                        "trade_id": pos["trade_id"], "exit_reason": "MANUAL_CLOSE",
                        "exit_time": int(time.time()),
                    })
                except Exception as e:
                    await self._send_event("ERROR", {
                        "error_code": "MANUAL_CLOSE_FAILED",
                        "error_message": str(e), "stack_trace": "", "context": {},
                    })

        elif cmd == "SHUTDOWN":
            self.log.info("Shutdown requested by mother")
            self.state.set_meta("last_shutdown", int(time.time()))
            self.running = False

        elif cmd == "GET_STATE":
            includes = data.get("include", [])
            snap = {"vm_id": self.vm_id}
            if "positions" in includes:
                snap["position"] = self.state.open_position()
            if "mt5_status" in includes:
                snap["mt5_ok"] = self.mt5_ok
                snap["balance"] = self.account_balance()
                snap["equity"] = self.account_equity()
            await self._send_event("STATE_SNAPSHOT", snap)

        else:
            self.log.warning(f"Unknown command: {cmd}")

    # ---------- Heartbeat ----------
    async def heartbeat_loop(self):
        while self.running:
            try:
                bal = self.account_balance() if self.mt5_ok else 0
                eq = self.account_equity() if self.mt5_ok else 0
                await self._send_event("HEARTBEAT", {
                    "current_state": "TRADING" if self.ready and not (self.halted_by_mother or self.halted_by_dd)
                                     else "WARMING_UP" if self.warming_up
                                     else "HALTED" if (self.halted_by_mother or self.halted_by_dd)
                                     else "AWAITING_CONFIG",
                    "mt5_connected": self.mt5_ok,
                    "position_count": 1 if self.state.open_position() else 0,
                    "today_trades": len(self.state.todays_trades()),
                    "balance": bal,
                    "equity": eq,
                })
            except Exception:
                pass
            await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)

    # ---------- Main tick loop ----------
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
                await self._send_event("MT5_DISCONNECTED", {
                    "last_price_time": 0, "retry_count": 1,
                })
                await asyncio.sleep(mt5_backoff)
                mt5_backoff = min(mt5_backoff * 2, MT5_RETRY_MAX_SEC)

        # Warmup
        await self.warmup()

        # Live loop
        last_tick_ts = 0
        last_msc = 0
        self.log.info("Entering live tick loop")
        while self.running:
            try:
                self._session_check()

                tick = mt5.symbol_info_tick(self.symbol)
                if tick is None:
                    await asyncio.sleep(POLL_INTERVAL_MS / 1000)
                    continue

                ts_int = int(tick.time)
                bid = float(tick.bid)
                ask = float(tick.ask)
                if bid > 0 and ask > 0:
                    price = (bid + ask) / 2.0
                elif bid > 0 or ask > 0:
                    price = bid or ask
                else:
                    await asyncio.sleep(POLL_INTERVAL_MS / 1000)
                    continue

                if ts_int != last_tick_ts or tick.time_msc != last_msc:
                    new_bricks = self.renko.feed_tick(ts_int, price, float(tick.volume))
                    last_tick_ts = ts_int
                    last_msc = tick.time_msc
                    for brick in new_bricks:
                        await self.on_new_brick(brick)

                await asyncio.sleep(POLL_INTERVAL_MS / 1000)

            except Exception as e:
                self.log.error(f"Live loop error: {e}\n{traceback.format_exc()}")
                await self._send_event("ERROR", {
                    "error_code": "LIVE_LOOP",
                    "error_message": str(e), "stack_trace": traceback.format_exc()[:2000],
                    "context": {},
                })
                await asyncio.sleep(2)

        self.mt5_shutdown()
        self.log.info("VM shutdown complete")


# ============================================================
# ENTRY POINT
# ============================================================
async def main():
    vm_id = os.environ.get("VM_ID", "vm1")
    mother_host = os.environ.get("MOTHER_HOST", "127.0.0.1")
    mother_port = int(os.environ.get("MOTHER_PORT", "8765"))
    shared_secret = os.environ.get("SHARED_SECRET", "changeme")

    setup_logging(vm_id)
    log = logging.getLogger("main")
    log.info(f"VM {vm_id} starting. mother={mother_host}:{mother_port}")

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
        asyncio.create_task(engine._outbound_sender_loop()),
    ]
    try:
        await asyncio.gather(*tasks)
    except Exception as e:
        log.critical(f"Fatal: {e}\n{traceback.format_exc()}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass