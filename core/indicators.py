import numpy as np
import pandas as pd
from typing import Tuple, Dict, Any

def calculate_bollinger_bandwidth(close: pd.Series, period: int = 20, std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series]:
    """Calculates Bollinger Bands and Bandwidth (BBW)."""
    basis = close.rolling(window=period).mean()
    dev = std_dev * close.rolling(window=period).std()
    upper = basis + dev
    lower = basis - dev
    bbw = (upper - lower) / basis
    return bbw, basis

def calculate_volume_zscore(volume: pd.Series, period: int = 48) -> float:
    """Computes standard score (Z-Score) for current volume vs historical distribution."""
    if len(volume) < period:
        return 0.0
    hist_series = volume.iloc[-period:-1]
    hist_std = float(hist_series.std())
    hist_mean = float(hist_series.mean())
    curr_vol = float(volume.iloc[-1])
    if hist_std == 0 or np.isnan(hist_std):
        return 0.0 if curr_vol == hist_mean else (10.0 if curr_vol > hist_mean else -10.0)
    return float((curr_vol - hist_mean) / hist_std)

def calculate_candle_metrics(open_p: float, high: float, low: float, close: float) -> Dict[str, float]:
    """Calculates body ratio, upper wick ratio, and lower wick ratio."""
    candle_range = high - low
    if candle_range <= 0:
        return {"body_ratio": 0.0, "upper_wick_ratio": 0.0, "lower_wick_ratio": 0.0, "is_bullish": False}

    body = abs(close - open_p)
    upper_wick = high - max(open_p, close)
    lower_wick = min(open_p, close) - low

    return {
        "body_ratio": body / candle_range,
        "upper_wick_ratio": upper_wick / candle_range,
        "lower_wick_ratio": lower_wick / candle_range,
        "is_bullish": close > open_p
    }

def calculate_delta_oi(historical_oi: list[float]) -> float:
    """Calculates percentage change in Open Interest over the last 2 observed intervals."""
    if len(historical_oi) < 2 or historical_oi[-2] == 0:
        return 0.0
    return ((historical_oi[-1] - historical_oi[-2]) / historical_oi[-2]) * 100.0
