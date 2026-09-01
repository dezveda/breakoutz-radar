"""Breakout Radar - Unified Multi-Exchange Configuration.

Single source of truth for all exchanges, indicator parameters, and
scoring weights. Replaces the legacy flat-constant module: every
consumer (core/engine.py, core/indicators.py, data/*_feed.py) reads
from RadarConfig so there is exactly one config surface.

Plain class (not a pydantic model): values are accessed both as class
attributes (RadarConfig.SCORE_WATCHLIST, e.g. in tests) and via an
instance (RadarConfig().LOOKBACK_PERIODS, e.g. in the engine/feeds).
A plain class supports both without pydantic's instance/class-access
quirks.
"""
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ExchangeEndpoints:
    """REST/WS endpoints for a single exchange. All feeds normalize to
    this shape so the engine and UI never branch on exchange identity."""
    name: str
    rest_base: str
    ws_base: str
    ws_reconnect_max_backoff: int = 30


class RadarConfig:
    # ---- Exchange registry (order defines mode-button cycle order) ----
    EXCHANGES: Dict[str, ExchangeEndpoints] = {
        "BINANCE": ExchangeEndpoints(
            name="BINANCE",
            rest_base="https://fapi.binance.com",
            ws_base="wss://fstream.binance.com/stream?streams=",
        ),
        "BYBIT": ExchangeEndpoints(
            name="BYBIT",
            rest_base="https://api.bybit.com",
            ws_base="wss://stream.bybit.com/v5/public/linear",
        ),
        "KUCOIN": ExchangeEndpoints(
            name="KUCOIN",
            rest_base="https://api-futures.kucoin.com",
            ws_base="",  # KuCoin requires a bullet token; resolved at connect time.
        ),
        "OKX": ExchangeEndpoints(
            name="OKX",
            rest_base="https://www.okx.com",
            ws_base="wss://ws.okx.com:8443/ws/v5/public",
        ),
    }

    # ---- Engine / Scan cadence ----
    KLINE_INTERVAL: str = "15m"
    LOOKBACK_PERIODS: int = 50          # bars kept in the rolling buffer per symbol
    OI_POLL_SECONDS: int = 60           # REST OI refresh cadence (no cross-exchange OI stream)
    MIN_VOL_24H: float = 15_000_000.0
    MAX_SYMBOLS_TRACKED: int = 40
    BLACKLIST: tuple = ("USDCUSDT", "BUSDUSDT", "TUSDUSDT", "USDPUSDT", "FDUSDUSDT")

    # ---- Indicators (core/indicators.py) ----
    BB_PERIOD: int = 20
    BB_STD: float = 2.0
    BBW_COMPRESSION_THRESHOLD: float = 0.03
    VOL_ZSCORE_TRIGGER: float = 3.0
    DELTA_OI_THRESHOLD_PCT: float = 2.0
    SMA_FAST: int = 7
    SMA_SLOW: int = 25
    MAX_REJECTION_WICK_RATIO: float = 0.60
    CANDLE_BODY_MIN_RATIO: float = 0.70

    # ---- Scoring weights (core/engine.py) ----
    WEIGHT_COMPRESSION: int = 20
    WEIGHT_VOL_SPIKE: int = 25
    WEIGHT_DELTA_OI: int = 15
    WEIGHT_TREND_ALIGNMENT: int = 15
    WEIGHT_CANDLE_QUALITY: int = 15

    # ---- Display / classification thresholds ----
    SCORE_WATCHLIST: int = 55
    SCORE_SNIPER: int = 75
    DISPLAY_MIN_SCORE: int = 25

    # ---- Synthesis mode (core/synthesis.py) ----
    SYNTHESIS_CONFIRMATION_BONUS: int = 15   # added when >=2 exchanges confirm the same symbol/direction
    SYNTHESIS_MAX_BONUS: int = 25


# Module-level singleton for callers that just want `config.cfg.<FIELD>`
# without instantiating their own copy.
cfg = RadarConfig()
