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