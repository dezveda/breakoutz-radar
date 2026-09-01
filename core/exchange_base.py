"""Abstract exchange feed interface.

Every concrete feed (data/binance_feed.py, bybit_feed.py, kucoin_feed.py,
okx_feed.py) implements this contract so core/engine.py and the UI never
branch on exchange identity. Normalizing here is what makes the
"individual mode" and "synthesis mode" table share the exact same
field set — the UI only ever talks to this interface.
"""
from abc import ABC, abstractmethod
from typing import Callable, Coroutine, Dict, List, Optional
import logging
import pandas as pd

logger = logging.getLogger(__name__)


class BaseExchangeFeed(ABC):
    """Contract every exchange adapter must satisfy."""

    name: str = "UNKNOWN"

    def __init__(self):
        self.used_weight: int = 0
        self._running: bool = False

    @abstractmethod
    async def initialize(self) -> None:
        """Open any HTTP session / acquire WS tokens needed before use."""
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        """Release sockets/sessions."""
        raise NotImplementedError

    @abstractmethod
    async def fetch_active_usdt_pairs(self) -> List[str]:
        """Return TRADING USDT-margined perpetual symbols for this exchange."""
        raise NotImplementedError

    @abstractmethod
    async def fetch_historical_klines(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        """Seed OHLCV data. Must return columns: open_time, open, high, low, close, volume."""
        raise NotImplementedError

    @abstractmethod
    async def fetch_open_interest_hist(self, symbol: str) -> List[float]:
        """Return a short recent history of OI notional values, oldest first."""
        raise NotImplementedError

    @abstractmethod
    async def listen_multiplex_kline_stream(
        self, symbols: List[str], interval: str, callback: Callable[[str, Dict], Coroutine]
    ) -> None:
        """Maintain a persistent multiplexed kline WS stream with reconnect/backoff.
        callback receives (symbol, kline_dict) once per closed candle."""
        raise NotImplementedError

    def stop(self) -> None:
        self._running = False
