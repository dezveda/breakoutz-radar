from dataclasses import dataclass
from typing import Tuple

@dataclass(frozen=True)
class RadarConfig:
    # API Endpoints
    BINANCE_REST_BASE: str = "https://fapi.binance.com"
    BINANCE_WS_BASE: str = "wss://fstream.binance.com/ws"

    # Timeframes & Lookbacks
    TIMEFRAME_FAST: str = "15m"
    TIMEFRAME_SLOW: str = "1h"
    LOOKBACK_PERIODS: int = 48
    SMA_FAST: int = 7
    SMA_SLOW: int = 25

    # Volatility Squeeze (Bollinger Bands)
    BB_PERIOD: int = 20
    BB_STD: float = 2.0
    BBW_COMPRESSION_THRESHOLD: float = 0.035

    # Volume & Order Flow Thresholds
    VOL_ZSCORE_TRIGGER: float = 2.5
    DELTA_OI_THRESHOLD_PCT: float = 2.0  # +2% increase in OI during breakout
    CANDLE_BODY_MIN_RATIO: float = 0.65  # Min body to range ratio
    MAX_REJECTION_WICK_RATIO: float = 0.25 # Max opposing wick ratio

    # Scoring Weights (Total = 100)
    WEIGHT_COMPRESSION: int = 25
    WEIGHT_VOL_SPIKE: int = 30
    WEIGHT_DELTA_OI: int = 20
    WEIGHT_CANDLE_QUALITY: int = 15
    WEIGHT_TREND_ALIGNMENT: int = 10

    # Score Tiers
    SCORE_SNIPER: int = 80
    SCORE_WATCHLIST: int = 60

    # Network & Engine
    MAX_CONCURRENT_REQUESTS: int = 20
    WS_RECONNECT_MAX_BACKOFF: int = 60
