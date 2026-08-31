"""Breakout Radar - Quantitative Core & Regime Parameters."""

# Network & Engine
BASE_URL = "https://fapi.binance.com"
SCAN_INTERVAL = 45  # Seconds
MAX_CONCURRENT_REQUESTS = 10
RATE_LIMIT_CEILING = 1000
BENCHMARK_SYMBOL = "BTCUSDT"

# Volume Diurnal Seasonality
VOLUME_LOOKBACK_HOURS = 168  # 7 days of 1h candles for hourly diurnal profile
VOLUME_MIN_STD_EPSILON = 1e-6

# Carter Squeeze & Volatility Parameters
BB_LENGTH = 20
BB_MULT = 2.0
KC_MULT = 1.5
ATR_PERIOD = 20
BBW_PERCENTILE_WINDOW = 120  # Percentile lookback window
BBW_COMPRESSION_PERCENTILE = 20.0  # Lowest 20% of historical BBW

# Order Flow & Open Interest Regimes
OI_CHANGE_LOOKBACK = 4  # 4 * 15m = 1 hour delta
OI_AGGRESSIVE_EXPANSION_THRESHOLD = 0.02  # +2.0% delta OI

# Calibrated Logistic Weights for Probability Engine: σ(w0 + Σ w_i * X_i)
LOGISTIC_BIAS = -2.10
MODEL_WEIGHTS = {
    "diurnal_vol_zscore": 0.85,    # Standardized diurnal volume spike
    "squeeze_compression": 1.20,   # Bollinger inside Keltner state
    "squeeze_fire": 1.50,          # First candle breaking out of squeeze
    "oi_expansion_regime": 1.35,   # ΔOI > 0 with positive price momentum
    "relative_strength_alpha": 1.10,# Residual return vs BTC beta
    "power_candle_ratio": 0.90,    # >70% candle body ratio
    "rejection_penalty": -2.20     # >60% upper wick rejection
}

# UI Display Thresholds
DISPLAY_MIN_PROBABILITY = 30.0  # Minimum % probability to display
SNIPER_PROBABILITY_THRESHOLD = 75.0
WATCHLIST_PROBABILITY_THRESHOLD = 55.0
