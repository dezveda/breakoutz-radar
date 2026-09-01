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

_INTERVAL_MAP = {"15m": "15m", "1h": "1h"}


class BinanceDataFeed(BaseExchangeFeed):
    """Binance USD-M Futures: WebSocket klines for real-time updates, REST for seed/OI."""

    name = "BINANCE"

    def __init__(self, cfg: Optional[RadarConfig] = None):
        super().__init__()
        self.cfg = cfg or RadarConfig()
        self.endpoint = self.cfg.EXCHANGES["BINANCE"]
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
        url = f"{self.endpoint.rest_base}/fapi/v1/exchangeInfo"
        try:
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    logger.error("BINANCE exchangeInfo failed: %s", resp.status)
                    return []
                data = await resp.json()
                return [
                    s["symbol"] for s in data.get("symbols", [])
                    if s["contractType"] == "PERPETUAL"
                    and s["quoteAsset"] == "USDT"
                    and s["status"] == "TRADING"
                    and s["symbol"] not in self.cfg.BLACKLIST
                ]
        except Exception as e:
            logger.error("BINANCE fetch_active_usdt_pairs error: %s", e)
            return []

    async def fetch_historical_klines(self, symbol: str, interval: str, limit: int = 100) -> pd.DataFrame:
        await self.initialize()
        url = f"{self.endpoint.rest_base}/fapi/v1/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.warning("BINANCE klines %s failed: %s", symbol, resp.status)
                    return pd.DataFrame()
                raw = await resp.json()
                df = pd.DataFrame(raw, columns=[
                    "open_time", "open", "high", "low", "close", "volume",
                    "close_time", "qav", "num_trades", "taker_base_vol", "taker_quote_vol", "ignore"
                ])
                df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
                numeric_cols = ["open", "high", "low", "close", "volume"]
                df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, axis=1)
                return df
        except Exception as e:
            logger.error("BINANCE fetch_historical_klines(%s) error: %s", symbol, e)
            return pd.DataFrame()

    async def fetch_open_interest_hist(self, symbol: str) -> List[float]:
        await self.initialize()
        url = f"{self.endpoint.rest_base}/futures/data/openInterestHist"
        params = {"symbol": symbol, "period": "15m", "limit": 5}
        try:
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return [float(x["sumOpenInterestValue"]) for x in data]
        except Exception as e:
            logger.warning("BINANCE fetch_open_interest_hist(%s) error: %s", symbol, e)
            return []

    async def listen_multiplex_kline_stream(
        self, symbols: List[str], interval: str, callback: Callable[[str, Dict], Coroutine]
    ) -> None:
        self._running = True
        backoff = 1
        stream_payload = "/".join([f"{s.lower()}@kline_{interval}" for s in symbols[:150]])
        ws_url = f"{self.endpoint.ws_base}{stream_payload}"

        while self._running:
            try:
                logger.info("BINANCE: connecting WS multiplex stream...")
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as ws:
                    backoff = 1
                    logger.info("BINANCE: WS connected.")
                    while self._running:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        payload = data.get("data", {})
                        k = payload.get("k")
                        if not k:
                            continue
                        if not k.get("x"):  # candle not closed yet
                            continue
                        symbol = k["s"]
                        normalized = {
                            "open_time": k["t"],
                            "open": float(k["o"]),
                            "high": float(k["h"]),
                            "low": float(k["l"]),
                            "close": float(k["c"]),
                            "volume": float(k["v"]),
                        }
                        await callback(symbol, normalized)
            except Exception as err:
                if not self._running:
                    break
                logger.warning("BINANCE WS disconnected (%s). Reconnecting in %ss...", err, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.endpoint.ws_reconnect_max_backoff)
