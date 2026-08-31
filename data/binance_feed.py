import asyncio
import json
import logging
import aiohttp
import websockets
import pandas as pd
from typing import Callable, Coroutine, Dict, List, Optional
from config import RadarConfig

logger = logging.getLogger(__name__)

class BinanceDataFeed:
    """
    Manages high-throughput connection to Binance USD-M Futures.
    Uses WebSockets for real-time mini-tickers / klines and REST for seed data.
    """
    def __init__(self, config: Optional[RadarConfig] = None):
        self.cfg = config or RadarConfig()
        self.session: Optional[aiohttp.ClientSession] = None
        self._running = False

    async def initialize(self):
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={"User-Agent": "BreakoutRadar/2.0"},
                timeout=aiohttp.ClientTimeout(total=10)
            )

    async def close(self):
        self._running = False
        if self.session and not self.session.closed:
            await self.session.close()

    async def fetch_active_usdt_pairs(self) -> List[str]:
        """Fetches all TRADING USDT-margined perpetual pairs."""
        await self.initialize()
        url = f"{self.cfg.BINANCE_REST_BASE}/fapi/v1/exchangeInfo"
        async with self.session.get(url) as resp:
            if resp.status != 200:
                logger.error(f"Failed to fetch exchange info: {resp.status}")
                return []
            data = await resp.json()
            return [
                s["symbol"] for s in data.get("symbols", [])
                if s["contractType"] == "PERPETUAL"
                and s["quoteAsset"] == "USDT"
                and s["status"] == "TRADING"
            ]

    async def fetch_historical_klines(self, symbol: str, interval: str = "15m", limit: int = 50) -> pd.DataFrame:
        """Fetches historical OHLCV data to initialize state."""
        await self.initialize()
        url = f"{self.cfg.BINANCE_REST_BASE}/fapi/v1/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    return pd.DataFrame()
                raw = await resp.json()
                df = pd.DataFrame(raw, columns=[
                    "open_time", "open", "high", "low", "close", "volume",
                    "close_time", "qav", "num_trades", "taker_base_vol", "taker_quote_vol", "ignore"
                ])
                numeric_cols = ["open", "high", "low", "close", "volume"]
                df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, axis=1)
                return df
        except Exception as e:
            logger.error(f"Error fetching klines for {symbol}: {e}")
            return pd.DataFrame()

    async def listen_multiplex_kline_stream(self, symbols: List[str], interval: str, callback: Callable[[Dict], Coroutine]):
        """
        Maintains persistent multiplexed WebSocket kline stream with auto-reconnection and backoff.
        """
        self._running = True
        backoff = 1
        # Subscribe in multiplex batches (max 200 streams per connection per Binance limits)
        stream_payload = "/".join([f"{s.lower()}@kline_{interval}" for s in symbols[:150]])
        ws_url = f"{self.cfg.BINANCE_WS_BASE}/{stream_payload}"

        while self._running:
            try:
                logger.info("Connecting to Binance WS multiplex stream...")
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as ws:
                    backoff = 1  # Reset backoff upon successful connection
                    logger.info("Connected to Binance WS stream.")
                    while self._running:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        if "data" in data and "k" in data["data"]:
                            await callback(data["data"]["k"])
            except (websockets.ConnectionClosed, Exception) as err:
                if not self._running:
                    break
                logger.warning(f"WebSocket disconnected ({err}). Reconnecting in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.cfg.WS_RECONNECT_MAX_BACKOFF)
