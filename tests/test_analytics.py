import pytest
import pandas as pd
import numpy as np
import config
from core.analytics import (
    calculate_diurnal_volume_zscore,
    calculate_carter_squeeze,
    evaluate_order_flow_regime,
    calculate_beta_relative_strength,
    compute_breakout_probability
)

def test_diurnal_volume_zscore():
    # Construct 168 hours of 1h candles with distinct hourly volume patterns
    timestamps = pd.date_range("2023-01-01", periods=168, freq="1h")
    # Base volume pattern: hour % 24 * 100
    volumes = [(ts.hour + 1) * 100.0 for ts in timestamps]
    df = pd.DataFrame({"open_time": timestamps, "volume": volumes})

    # Test exact hour matching
    z = calculate_diurnal_volume_zscore(df)
    # Since volume at current hour equals historical mean for that hour, z-score should be 0.0
    assert abs(z) < 0.1

    # Spike volume in current candle
    df.loc[df.index[-1], "volume"] = (df.iloc[-1]["open_time"].hour + 1) * 500.0
    z_spike = calculate_diurnal_volume_zscore(df)
    assert z_spike > 2.0

    # Clipping check: volume spike capped at 10.0
    df.loc[df.index[-1], "volume"] = 1e9
    z_clipped = calculate_diurnal_volume_zscore(df)
    assert z_clipped == 10.0


def test_carter_squeeze():
    # Construct 130 candles where volatility steadily narrows into a tight squeeze
    np.random.seed(42)
    n = 130
    noise_scale = np.linspace(0.1, 0.001, n)
    close = np.full(n, 100.0) + np.random.normal(0, 1, n) * noise_scale
    high = close + noise_scale
    low = close - noise_scale

    df_coiled = pd.DataFrame({"close": close, "high": high, "low": low})
    is_coiled, is_fire, bbw_rank = calculate_carter_squeeze(df_coiled)
    assert is_coiled is True
    assert is_fire is False
    assert bbw_rank <= config.BBW_COMPRESSION_PERCENTILE

    # Test Squeeze Fire: Prior candle was coiled, current candle explodes upwards
    df_fire = df_coiled.copy()
    df_fire.loc[df_fire.index[-1], "close"] = 110.0
    df_fire.loc[df_fire.index[-1], "high"] = 112.0
    df_fire.loc[df_fire.index[-1], "low"] = 100.0

    is_coiled_fire, is_fire_trigger, _ = calculate_carter_squeeze(df_fire)
    assert is_fire_trigger is True


def test_order_flow_regime_matrix():
    # 1. Aggressive Long Inflow: ΔOI > 2%, ΔP > 0.5%
    oi_agg_long = [100000.0, 103000.0]  # +3%
    p_agg_long = [100.0, 101.0]         # +1%
    regime, delta_oi = evaluate_order_flow_regime(oi_agg_long, p_agg_long)
    assert regime == "AGG_LONG_INFLOW"
    assert delta_oi > 0.02

    # 2. Short Covering Spike: ΔOI < -2%, ΔP > 0.5%
    oi_short_cov = [100000.0, 96000.0]  # -4%
    p_short_cov = [100.0, 101.0]        # +1%
    regime_sc, _ = evaluate_order_flow_regime(oi_short_cov, p_short_cov)
    assert regime_sc == "SHORT_COVERING_SPIKE"

    # 3. Aggressive Short Inflow: ΔOI > 2%, ΔP < -0.5%
    oi_agg_short = [100000.0, 104000.0] # +4%
    p_agg_short = [100.0, 98.5]         # -1.5%
    regime_as, _ = evaluate_order_flow_regime(oi_agg_short, p_agg_short)
    assert regime_as == "AGG_SHORT_INFLOW"

    # 4. Long Capitulation: ΔOI < -2%, ΔP < -0.5%
    oi_cap = [100000.0, 95000.0]         # -5%
    p_cap = [100.0, 98.0]                # -2%
    regime_lc, _ = evaluate_order_flow_regime(oi_cap, p_cap)
    assert regime_lc == "LONG_CAPITULATION"


def test_beta_relative_strength():
    np.random.seed(42)
    btc_returns = np.random.normal(0.001, 0.01, 30)
    # Asset returns identical to BTC returns -> Beta ~ 1, Alpha ~ 0
    asset_returns_correlated = btc_returns.copy()
    alpha_corr = calculate_beta_relative_strength(asset_returns_correlated, btc_returns)
    assert abs(alpha_corr) < 0.5

    # Asset returns outperforming BTC on the last 4 candles
    asset_outperform = btc_returns.copy()
    asset_outperform[-4:] += 0.02
    alpha_out = calculate_beta_relative_strength(asset_outperform, btc_returns)
    assert alpha_out > 1.0


def test_breakout_probability_sigmoid():
    # Base features -> Logit near LOGISTIC_BIAS (-2.10) -> Prob ~ 11%
    base_features = {
        "diurnal_vol_zscore": 0.0,
        "is_coiled": False,
        "is_fire": False,
        "oi_regime": "NEUTRAL",
        "beta_alpha": 0.0,
        "body_ratio": 0.50,
        "upper_wick_ratio": 0.10,
        "pct_move_15m": 0.001
    }
    prob_base = compute_breakout_probability(base_features)
    assert 5.0 <= prob_base <= 20.0

    # High confluence breakout features -> High logit -> High prob
    high_features = {
        "diurnal_vol_zscore": 3.5,
        "is_coiled": True,
        "is_fire": True,
        "oi_regime": "AGG_LONG_INFLOW",
        "beta_alpha": 2.5,
        "body_ratio": 0.85,
        "upper_wick_ratio": 0.05,
        "pct_move_15m": 0.015
    }
    prob_high = compute_breakout_probability(high_features)
    assert prob_high >= 85.0
