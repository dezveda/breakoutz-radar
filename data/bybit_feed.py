import asyncio
import json
import logging
import aiohttp
import websockets
import pandas as pd
from typing import Callable, Coroutine, Dict, List, Optional

from config import RadarConfig
from core.exchange_base import BaseExchangeFeed

logger = logging.getLogger(__name__)

# Bybit v5 kline intervals are plain minute strings (not "15m"/"1h").
_INTERVAL_MAP = {"15m": "15", "1h": "60"}
_SUBSCRIBE_CHUNK = 10  # topics per subscribe frame, conservative vs Bybit arg limits


class BybitDataFeed(BaseExchangeFeed):
    """Bybit v5 linear (USDT perpetual) futures feed."""

    name = "BYBIT"

    def __init__(self, cfg: Optional[RadarConfig] = None):
        super().__init__()
        self.cfg = cfg or RadarConfig()
        self.endpoint = self.cfg.EXCHANGES["BYBIT"]
        self.session: Optional[aiohttp.ClientSession] = None

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
        url = f"{self.endpoint.rest_base}/v5/market/instruments-info"
        params = {"category": "linear"}
        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.error("BYBIT instruments-info failed: %s", resp.status)
                    return []
                data = await resp.json()
                items = data.get("result", {}).get("list", [])
                return [
                    s["symbol"] for s in items
                    if s.get("quoteCoin") == "USDT"
                    and s.get("status") == "Trading"
                    and s.get("contractType") in ("LinearPerpetual",)
                    and s["symbol"] not in self.cfg.BLACKLIST
                ]
        except Exception as e:
            logger.error("BYBIT fetch_active_usdt_pairs error: %s", e)
            return []

    async def fetch_historical_klines(self, symbol: str, interval: str, limit: int = 100) -> pd.DataFrame:
        await self.initialize()
        url = f"{self.endpoint.rest_base}/v5/market/kline"
        params = {
            "category": "linear",
            "symbol": symbol,
            "interval": _INTERVAL_MAP.get(interval, interval),
            "limit": limit,
        }
        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.warning("BYBIT klines %s failed: %s", symbol, resp.status)
                    return pd.DataFrame()
                data = await resp.json()
                rows = data.get("result", {}).get("list", [])
                if not rows:
                    return pd.DataFrame()
                # Bybit returns newest-first; reverse to chronological order.
                rows = list(reversed(rows))
                df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume", "turnover"])
                df["open_time"] = pd.to_datetime(pd.to_numeric(df["open_time"]), unit="ms")
                numeric_cols = ["open", "high", "low", "close", "volume"]
                df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, axis=1)
                return df[["open_time", "open", "high", "low", "close", "volume"]]
        except Exception as e:
            logger.error("BYBIT fetch_historical_klines(%s) error: %s", symbol, e)
            return pd.DataFrame()

    async def fetch_open_interest_hist(self, symbol: str) -> List[float]:
        await self.initialize()
        url = f"{self.endpoint.rest_base}/v5/market/open-interest"
        params = {"category": "linear", "symbol": symbol, "intervalTime": "15min", "limit": 5}
        try:
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                rows = data.get("result", {}).get("list", [])
                rows = list(reversed(rows))  # chronological, oldest first
                return [float(x["openInterest"]) for x in rows]
        except Exception as e:
            logger.warning("BYBIT fetch_open_interest_hist(%s) error: %s", symbol, e)
            return []

    async def listen_multiplex_kline_stream(
        self, symbols: List[str], interval: str, callback: Callable[[str, Dict], Coroutine]
    ) -> None:
        self._running = True
        backoff = 1
        bybit_interval = _INTERVAL_MAP.get(interval, interval)
        topics = [f"kline.{bybit_interval}.{s}" for s in symbols[:150]]

        while self._running:
            try:
                logger.info("BYBIT: connecting WS public/linear...")
                async with websockets.connect(self.endpoint.ws_base, ping_interval=20, ping_timeout=10) as ws:
                    backoff = 1
                    for i in range(0, len(topics), _SUBSCRIBE_CHUNK):
                        await ws.send(json.dumps({"op": "subscribe", "args": topics[i:i + _SUBSCRIBE_CHUNK]}))
                        await asyncio.sleep(0.1)  # avoid tripping Bybit's subscribe rate limit
                    logger.info("BYBIT: WS connected, %d topics subscribed.", len(topics))
                    while self._running:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        topic = data.get("topic", "")
                        if not topic.startswith("kline."):
                            continue
                        symbol = topic.split(".")[-1]
                        for k in data.get("data", []):
                            if not k.get("confirm"):  # candle not closed yet
                                continue
                            normalized = {
                                "open_time": k["start"],
                                "open": float(k["open"]),
                                "high": float(k["high"]),
                                "low": float(k["low"]),
                                "close": float(k["close"]),
                                "volume": float(k["volume"]),
                            }
                            await callback(symbol, normalized)
            except Exception as err:
                if not self._running:
                    break
                logger.warning("BYBIT WS disconnected (%s). Reconnecting in %ss...", err, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.endpoint.ws_reconnect_max_backoff)
