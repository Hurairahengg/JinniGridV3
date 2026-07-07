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


def open_position(symbol, direction, lots, sl_distance_pts, magic=MAGIC_NUMBER):
    """
    Open market position at broker's current bid/ask.
    SL is placed at (fill_price - sl_distance) for LONG, (fill_price + sl_distance) for SHORT.

    Returns:
      (True, {"ticket": int, "fill_price": float, "sl_price": float,
              "actual_lots": float, "slippage_pts": float})
      OR
      (False, {"error_code": int, "error_message": str, "retcode": int})
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

    # Verify SL respects broker's minimum stop distance
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
        "comment": "JinniGrid V3",
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
    Returns list of dicts with position info.
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
