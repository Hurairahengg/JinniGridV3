"""
mother/core/bars.py — Renko brick engine.

IDENTICAL logic to vm/strategy.py's RenkoBuilder. This is duplicated on
purpose so mother and VM are independently deployable. Any drift here
breaks validation. If you edit one, edit both — or extract to a shared
package later.
"""


class RenkoBuilder:
    """Feed ticks one at a time. Returns newly-completed bricks per call."""

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