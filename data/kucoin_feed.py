import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from typing import Callable, Coroutine, Dict, List, Optional

import aiohttp
import websockets
import pandas as pd

from config import RadarConfig
from core.exchange_base import BaseExchangeFeed

logger = logging.getLogger(__name__)

# KuCoin Futures granularity is plain minutes.
_INTERVAL_MAP = {"15m": 15, "1h": 60}


class KucoinDataFeed(BaseExchangeFeed):
    """KuCoin Futures feed. WebSocket requires a short-lived bullet token
    obtained via REST before connecting (no static WS base URL)."""

    name = "KUCOIN"

    def __init__(self, cfg: Optional[RadarConfig] = None):
        super().__init__()
        self.cfg = cfg or RadarConfig()
        self.endpoint = self.cfg.EXCHANGES["KUCOIN"]
        self.session: Optional[aiohttp.ClientSession] = None
        # KuCoin's public REST has no OI-history endpoint; we accumulate our
        # own short rolling window from repeated snapshot polls.
        self._oi_cache: Dict[str, List[float]] = defaultdict(list)
        # Candle-boundary detection state for the incremental WS feed.
        self._last_open_time: Dict[str, int] = {}
        self._pending_candle: Dict[str, Dict] = {}

    async def initialize(self) -> None:
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={"User-Agent": "BreakoutRadar/3.0"},
                timeout=aiohttp.ClientTimeout(total=10),
            )

    async def close(self) -> None:
        self._running = False
        if self.session and not self.session.closed:
            await self.session.close()

    async def fetch_active_usdt_pairs(self) -> List[str]:
        await self.initialize()
        url = f"{self.endpoint.rest_base}/api/v1/contracts/active"
        try:
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    logger.error("KUCOIN contracts/active failed: %s", resp.status)
                    return []
                data = await resp.json()
                items = data.get("data", [])
                return [
                    s["symbol"] for s in items
                    if s.get("quoteCurrency") == "USDT"
                    and s.get("status") == "Open"
                    and s["symbol"] not in self.cfg.BLACKLIST
                ]
        except Exception as e:
            logger.error("KUCOIN fetch_active_usdt_pairs error: %s", e)
            return []

    async def fetch_historical_klines(self, symbol: str, interval: str, limit: int = 100) -> pd.DataFrame:
        await self.initialize()
        granularity = _INTERVAL_MAP.get(interval, 15)
        url = f"{self.endpoint.rest_base}/api/v1/kline/query"
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - granularity * 60_000 * limit
        params = {"symbol": symbol, "granularity": granularity, "from": start_ms, "to": end_ms}
        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.warning("KUCOIN klines %s failed: %s", symbol, resp.status)
                    return pd.DataFrame()
                data = await resp.json()
                rows = data.get("data", [])
                if not rows:
                    return pd.DataFrame()
                df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume"])
                df["open_time"] = pd.to_datetime(pd.to_numeric(df["open_time"]), unit="ms")
                numeric_cols = ["open", "high", "low", "close", "volume"]
                df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, axis=1)
                return df
        except Exception as e:
            logger.error("KUCOIN fetch_historical_klines(%s) error: %s", symbol, e)
            return pd.DataFrame()

    async def fetch_open_interest_hist(self, symbol: str) -> List[float]:
        """KuCoin's public REST exposes only a current OI snapshot, not
        history. We poll it and keep our own trailing window per symbol."""
        await self.initialize()
        url = f"{self.endpoint.rest_base}/api/v1/contracts/{symbol}"
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    return self._oi_cache[symbol]
                data = await resp.json()
                oi = data.get("data", {}).get("openInterest")
                if oi is not None:
                    cache = self._oi_cache[symbol]
                    cache.append(float(oi))
                    self._oi_cache[symbol] = cache[-5:]
                return self._oi_cache[symbol]
        except Exception as e:
            logger.warning("KUCOIN fetch_open_interest_hist(%s) error: %s", symbol, e)
            return self._oi_cache[symbol]

    async def _get_ws_token(self) -> Optional[str]:
        await self.initialize()
        url = f"{self.endpoint.rest_base}/api/v1/bullet-public"
        try:
            async with self.session.post(url) as resp:
                if resp.status != 200:
                    logger.error("KUCOIN bullet-public failed: %s", resp.status)
                    return None
                data = await resp.json()
                token = data["data"]["token"]
                server = data["data"]["instanceServers"][0]["endpoint"]
                ping_interval = data["data"]["instanceServers"][0].get("pingInterval", 18000) / 1000
                connect_id = uuid.uuid4().hex
                return f"{server}?token={token}&connectId={connect_id}", ping_interval
        except Exception as e:
            logger.error("KUCOIN _get_ws_token error: %s", e)
            return None

    async def listen_multiplex_kline_stream(
        self, symbols: List[str], interval: str, callback: Callable[[str, Dict], Coroutine]
    ) -> None:
        self._running = True
        backoff = 1
        granularity = _INTERVAL_MAP.get(interval, 15)

        while self._running:
            try:
                token_result = await self._get_ws_token()
                if not token_result:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, self.endpoint.ws_reconnect_max_backoff)
                    continue
                ws_url, ping_interval = token_result

                logger.info("KUCOIN: connecting WS futures feed...")
                async with websockets.connect(ws_url, ping_interval=None) as ws:
                    backoff = 1
                    topic = "/contractMarket/limitCandle:" + ",".join(
                        f"{s}_{granularity}min" for s in symbols[:100]
                    )
                    await ws.send(json.dumps({
                        "id": uuid.uuid4().hex, "type": "subscribe",
                        "topic": topic, "response": True,
                    }))
                    logger.info("KUCOIN: WS connected, %d symbols subscribed.", len(symbols[:100]))

                    async def _pinger():
                        while self._running:
                            await asyncio.sleep(ping_interval)
                            await ws.send(json.dumps({"id": uuid.uuid4().hex, "type": "ping"}))

                    ping_task = asyncio.create_task(_pinger())
                    try:
                        while self._running:
                            msg = await ws.recv()
                            data = json.loads(msg)
                            if data.get("type") != "message":
                                continue
                            payload = data.get("data", {})
                            candles = payload.get("candles")
                            symbol = payload.get("symbol")
                            if not candles or not symbol:
                                continue
                            open_time = int(candles[0])
                            candle = {
                                "open_time": open_time * 1000 if open_time < 10**12 else open_time,
                                "open": float(candles[1]),
                                "close": float(candles[2]),
                                "high": float(candles[3]),
                                "low": float(candles[4]),
                                "volume": float(candles[5]),
                            }
                            # KuCoin pushes every update within the still-forming
                            # candle; emit only when the bucket rolls over, i.e.
                            # the previous candle for this symbol has closed.
                            last_open = self._last_open_time.get(symbol)
                            if last_open is not None and candle["open_time"] != last_open:
                                closed = self._pending_candle.get(symbol)
                                if closed:
                                    await callback(symbol, closed)
                            self._last_open_time[symbol] = candle["open_time"]
                            self._pending_candle[symbol] = candle
                    finally:
                        ping_task.cancel()
            except Exception as err:
                if not self._running:
                    break
                logger.warning("KUCOIN WS disconnected (%s). Reconnecting in %ss...", err, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.endpoint.ws_reconnect_max_backoff)
