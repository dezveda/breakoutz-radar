import asyncio
import json
import logging
from collections import defaultdict
from typing import Callable, Coroutine, Dict, List, Optional

import aiohttp
import websockets
import pandas as pd

from config import RadarConfig
from core.exchange_base import BaseExchangeFeed

logger = logging.getLogger(__name__)

# OKX candle bars use this notation (not "15m"/"1h").
_INTERVAL_MAP = {"15m": "15m", "1h": "1H"}


def _to_canonical(inst_id: str) -> str:
    """BTC-USDT-SWAP -> BTCUSDT, so symbols line up with other exchanges
    for cross-exchange synthesis-mode matching."""
    return inst_id.replace("-USDT-SWAP", "USDT").replace("-", "")


def _to_inst_id(symbol: str) -> str:
    """BTCUSDT -> BTC-USDT-SWAP."""
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    return f"{base}-USDT-SWAP"


class OkxDataFeed(BaseExchangeFeed):
    """OKX v5 USDT-margined perpetual SWAP feed."""

    name = "OKX"

    def __init__(self, cfg: Optional[RadarConfig] = None):
        super().__init__()
        self.cfg = cfg or RadarConfig()
        self.endpoint = self.cfg.EXCHANGES["OKX"]
        self.session: Optional[aiohttp.ClientSession] = None
        # OKX open-interest is a live snapshot only; keep a trailing window ourselves.
        self._oi_cache: Dict[str, List[float]] = defaultdict(list)

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
        url = f"{self.endpoint.rest_base}/api/v5/public/instruments"
        params = {"instType": "SWAP"}
        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.error("OKX instruments failed: %s", resp.status)
                    return []
                data = await resp.json()
                items = data.get("data", [])
                out = []
                for s in items:
                    if s.get("settleCcy") != "USDT" or s.get("state") != "live":
                        continue
                    if not s.get("instId", "").endswith("-USDT-SWAP"):
                        continue
                    sym = _to_canonical(s["instId"])
                    if sym not in self.cfg.BLACKLIST:
                        out.append(sym)
                return out
        except Exception as e:
            logger.error("OKX fetch_active_usdt_pairs error: %s", e)
            return []

    async def fetch_historical_klines(self, symbol: str, interval: str, limit: int = 100) -> pd.DataFrame:
        await self.initialize()
        url = f"{self.endpoint.rest_base}/api/v5/market/candles"
        params = {"instId": _to_inst_id(symbol), "bar": _INTERVAL_MAP.get(interval, interval), "limit": limit}
        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.warning("OKX klines %s failed: %s", symbol, resp.status)
                    return pd.DataFrame()
                data = await resp.json()
                rows = data.get("data", [])
                if not rows:
                    return pd.DataFrame()
                rows = list(reversed(rows))  # OKX returns newest-first
                df = pd.DataFrame(rows, columns=[
                    "open_time", "open", "high", "low", "close", "volume",
                    "volCcy", "volCcyQuote", "confirm"
                ])
                df["open_time"] = pd.to_datetime(pd.to_numeric(df["open_time"]), unit="ms")
                numeric_cols = ["open", "high", "low", "close", "volume"]
                df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, axis=1)
                return df[["open_time", "open", "high", "low", "close", "volume"]]
        except Exception as e:
            logger.error("OKX fetch_historical_klines(%s) error: %s", symbol, e)
            return pd.DataFrame()

    async def fetch_open_interest_hist(self, symbol: str) -> List[float]:
        await self.initialize()
        url = f"{self.endpoint.rest_base}/api/v5/public/open-interest"
        params = {"instType": "SWAP", "instId": _to_inst_id(symbol)}
        try:
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    return self._oi_cache[symbol]
                data = await resp.json()
                rows = data.get("data", [])
                if rows:
                    cache = self._oi_cache[symbol]
                    cache.append(float(rows[0]["oi"]))
                    self._oi_cache[symbol] = cache[-5:]
                return self._oi_cache[symbol]
        except Exception as e:
            logger.warning("OKX fetch_open_interest_hist(%s) error: %s", symbol, e)
            return self._oi_cache[symbol]

    async def listen_multiplex_kline_stream(
        self, symbols: List[str], interval: str, callback: Callable[[str, Dict], Coroutine]
    ) -> None:
        self._running = True
        backoff = 1
        bar = _INTERVAL_MAP.get(interval, interval)
        channel = f"candle{bar}"
        args = [{"channel": channel, "instId": _to_inst_id(s)} for s in symbols[:150]]

        while self._running:
            try:
                logger.info("OKX: connecting WS public channel...")
                async with websockets.connect(self.endpoint.ws_base, ping_interval=20, ping_timeout=10) as ws:
                    backoff = 1
                    # OKX caps ~100 args per subscribe frame.
                    for i in range(0, len(args), 100):
                        await ws.send(json.dumps({"op": "subscribe", "args": args[i:i + 100]}))
                        await asyncio.sleep(0.1)
                    logger.info("OKX: WS connected, %d instruments subscribed.", len(args))
                    while self._running:
                        msg = await ws.recv()
                        if msg == "pong":
                            continue
                        data = json.loads(msg)
                        arg = data.get("arg", {})
                        if not str(arg.get("channel", "")).startswith("candle"):
                            continue
                        symbol = _to_canonical(arg.get("instId", ""))
                        for row in data.get("data", []):
                            if row[8] != "1":  # confirm flag: "1" = closed candle
                                continue
                            normalized = {
                                "open_time": int(row[0]),
                                "open": float(row[1]),
                                "high": float(row[2]),
                                "low": float(row[3]),
                                "close": float(row[4]),
                                "volume": float(row[5]),
                            }
                            await callback(symbol, normalized)
            except Exception as err:
                if not self._running:
                    break
                logger.warning("OKX WS disconnected (%s). Reconnecting in %ss...", err, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.endpoint.ws_reconnect_max_backoff)
