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
        ok, result = executor.open_position(symbol, direction, lots, sl_distance)

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

        elif mt == "SHUTDOWN":
            self.log.info("Shutdown requested by mother")
            self.running = False

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