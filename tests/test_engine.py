import pytest
import pandas as pd
import numpy as np
from config import RadarConfig
from core.engine import BreakoutScoringEngine
from core.indicators import calculate_volume_zscore, calculate_candle_metrics

@pytest.fixture
def sample_df_breakout_long():
    # Create 50 bars of low volatility followed by an aggressive bullish breakout bar
    periods = 50
    prices = np.linspace(100, 101, periods)
    volumes = np.full(periods, 1000.0)

    # Squeeze compression then volume explosion on last bar
    volumes[-1] = 8000.0
    prices[-1] = 108.0

    df = pd.DataFrame({
        'open': np.append(prices[:-1], 102.0),
        'high': np.append(prices[:-1] + 0.1, 108.2),
        'low': np.append(prices[:-1] - 0.1, 101.9),
        'close': prices,
        'volume': volumes
    })
    return df

def test_volume_zscore_spike():
    volumes = pd.Series([100.0] * 48 + [1000.0])
    z_score = calculate_volume_zscore(volumes, period=48)
    assert z_score > 3.0

def test_candle_metrics_bullish():
    metrics = calculate_candle_metrics(open_p=100, high=110, low=99, close=109)
    assert metrics["is_bullish"] is True
    assert metrics["body_ratio"] > 0.8
    assert metrics["upper_wick_ratio"] < 0.1

def test_candle_metrics_bearish():
    metrics = calculate_candle_metrics(open_p=110, high=111, low=99, close=100)
    assert metrics["is_bullish"] is False
    assert metrics["body_ratio"] > 0.8
    assert metrics["lower_wick_ratio"] < 0.1

def test_engine_detects_long_breakout(sample_df_breakout_long):
    engine = BreakoutScoringEngine()
    hist_oi = [10000.0, 10500.0]  # +5% OI
    res = engine.evaluate_symbol("BTCUSDT", sample_df_breakout_long, hist_oi)

    assert res["direction"] == "LONG"
    assert res["score"] >= RadarConfig.SCORE_WATCHLIST
    assert "VOL_SPIKE" in res["flags"]
    assert "OI_EXPANSION" in res["flags"]

def test_engine_detects_short_breakdown():
    engine = BreakoutScoringEngine()
    periods = 50
    df_short = pd.DataFrame({
        'open': [100.0] * 49 + [90.0],
        'high': [100.2] * 49 + [90.1],
        'low': [99.8] * 49 + [80.0],
        'close': [100.0] * 49 + [80.2],
        'volume': [1000.0] * 49 + [9000.0]
    })
    hist_oi = [5000.0, 5300.0]
    res = engine.evaluate_symbol("ETHUSDT", df_short, hist_oi)
    assert res["direction"] == "SHORT"
    assert res["score"] >= RadarConfig.SCORE_WATCHLIST
