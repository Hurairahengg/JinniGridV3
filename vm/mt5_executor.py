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

    # Prefer authoritative realized PnL from the closing deal history
    exit_price = float(result.price)
    realized = float(pos.profit)
    try:
        info = get_deals_by_position(int(ticket))
        if info.get("found"):
            realized = info["realized_pnl"]
            if info.get("exit_price"):
                exit_price = info["exit_price"]
    except Exception:
        pass
    return True, {
        "exit_price": exit_price,
        "realized_pnl": realized,
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

def get_deals_by_position(ticket, magic=MAGIC_NUMBER):
    """
    Reliable close info for ONE position, keyed by position ticket.
    Returns real exit price + realized pnl (profit+swap+commission) and an
    inferred reason from the OUT deal. This is far more reliable than a
    time-windowed scan and fixes zero-PnL / mislabeled external closes.
    """
    try:
        deals = mt5.history_deals_get(position=int(ticket))
    except Exception:
        deals = None
    if deals is None or len(deals) == 0:
        return {"found": False, "exit_price": 0.0, "realized_pnl": 0.0,
                "reason": "external_close", "entry_price": 0.0}

    total = 0.0
    exit_price = 0.0
    entry_price = 0.0
    reason = "external_close"
    for d in deals:
        try:
            total += float(d.profit) + float(getattr(d, "swap", 0.0)) + float(getattr(d, "commission", 0.0))
        except Exception:
            pass
        if d.entry == mt5.DEAL_ENTRY_IN:
            entry_price = float(d.price)
        elif d.entry == mt5.DEAL_ENTRY_OUT:
            exit_price = float(d.price)
            r = getattr(d, "reason", None)
            if r == mt5.DEAL_REASON_SL:
                reason = "sl_hit"
            elif r == mt5.DEAL_REASON_TP:
                reason = "tp_hit"
            elif r in (mt5.DEAL_REASON_CLIENT, mt5.DEAL_REASON_EXPERT, mt5.DEAL_REASON_MOBILE, mt5.DEAL_REASON_WEB):
                reason = "manual_or_command"
    return {"found": True, "exit_price": exit_price, "realized_pnl": total,
            "reason": reason, "entry_price": entry_price}



