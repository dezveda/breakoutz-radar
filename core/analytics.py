"""
Vectorized Quantitative Analytics Engine
Mathematical routines for breakout probability estimation without linear heuristics.
"""
import math
import numpy as np
from typing import Dict, Any, Tuple
import config

def calculate_diurnal_volume_zscore(df_1h) -> float:
    """
    Calculates seasonal Z-Score by comparing current 1h volume with the exact
    same diurnal hour bucket across historical sessions.
    """
    if df_1h is None or len(df_1h) < 24:
        return 0.0

    # Extract session hour from timestamp
    df = df_1h.copy()
    df['hour'] = df['open_time'].dt.hour
    current_hour = df.iloc[-1]['hour']
    current_volume = df.iloc[-1]['volume']

    same_hour_vols = df[df['hour'] == current_hour]['volume'].values[:-1]
    if len(same_hour_vols) < 3:
        mean_v = df['volume'].mean()
        std_v = df['volume'].std()
    else:
        mean_v = np.mean(same_hour_vols)
        std_v = np.std(same_hour_vols)

    z_score = (current_volume - mean_v) / (std_v + config.VOLUME_MIN_STD_EPSILON)
    return float(np.clip(z_score, -3.0, 10.0))


def calculate_carter_squeeze(df_15m) -> Tuple[bool, bool, float]:
    """
    Evaluates Carter Squeeze (Bollinger Bands inside Keltner Channels)
    and checks if BandWidth is in the historical lowest percentile rank.
    Returns: (is_coiled, is_fire, bbw_percentile)
    """
    if df_15m is None or len(df_15m) < (config.BB_LENGTH + 10):
        return False, False, 100.0

    close = df_15m['close'].values
    high = df_15m['high'].values
    low = df_15m['low'].values

    # 1. Bollinger Bands (20, 2.0)
    sma20 = np.mean(close[-config.BB_LENGTH:])
    std20 = np.std(close[-config.BB_LENGTH:])
    upper_bb = sma20 + (config.BB_MULT * std20)
    lower_bb = sma20 - (config.BB_MULT * std20)
    current_bbw = (upper_bb - lower_bb) / (sma20 + 1e-9)

    # 2. Historical BBW Percentile Rank
    rolling_bbw = []
    start_idx = max(config.BB_LENGTH, len(close) - config.BBW_PERCENTILE_WINDOW)
    for i in range(start_idx, len(close) + 1):
        sub_c = close[i - config.BB_LENGTH : i]
        if len(sub_c) == config.BB_LENGTH:
            sub_m = np.mean(sub_c)
            sub_s = np.std(sub_c)
            rolling_bbw.append((2 * config.BB_MULT * sub_s) / (sub_m + 1e-9))

    bbw_percentile = float((np.array(rolling_bbw) <= current_bbw).mean() * 100.0) if rolling_bbw else 50.0

    # 3. Keltner Channels (20, 1.5 * ATR)
    tr1 = high[-config.ATR_PERIOD:] - low[-config.ATR_PERIOD:]
    tr2 = np.abs(high[-config.ATR_PERIOD:] - close[-config.ATR_PERIOD - 1 : -1])
    tr3 = np.abs(low[-config.ATR_PERIOD:] - close[-config.ATR_PERIOD - 1 : -1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    atr = np.mean(tr)

    upper_kc = sma20 + (config.KC_MULT * atr)
    lower_kc = sma20 - (config.KC_MULT * atr)

    # Squeeze is active if BB is entirely inside KC
    is_coiled = bool((upper_bb < upper_kc) and (lower_bb > lower_kc))

    # Squeeze Fire: Prior candle was coiled, current candle expanded outside KC
    prev_sma = np.mean(close[-config.BB_LENGTH - 1 : -1])
    prev_std = np.std(close[-config.BB_LENGTH - 1 : -1])
    prev_upper_bb = prev_sma + (config.BB_MULT * prev_std)
    prev_is_coiled = prev_upper_bb < upper_kc
    is_fire = bool(prev_is_coiled and not is_coiled and (close[-1] > sma20))

    return bool(is_coiled or (bbw_percentile <= config.BBW_COMPRESSION_PERCENTILE)), is_fire, bbw_percentile


def evaluate_order_flow_regime(oi_history: list, price_history: list) -> Tuple[str, float]:
    """
    Evaluates dynamic ΔOI x ΔP to identify institutional positioning.
    Returns: (regime_label, delta_oi_percentage)
    """
    if not oi_history or len(oi_history) < 2 or not price_history or len(price_history) < 2:
        return "NEUTRAL", 0.0

    delta_oi = (oi_history[-1] - oi_history[0]) / (oi_history[0] + 1e-9)
    delta_p = (price_history[-1] - price_history[0]) / (price_history[0] + 1e-9)

    if delta_oi > config.OI_AGGRESSIVE_EXPANSION_THRESHOLD and delta_p > 0.005:
        return "AGG_LONG_INFLOW", float(delta_oi)
    elif delta_oi < -config.OI_AGGRESSIVE_EXPANSION_THRESHOLD and delta_p > 0.005:
        return "SHORT_COVERING_SPIKE", float(delta_oi)
    elif delta_oi > config.OI_AGGRESSIVE_EXPANSION_THRESHOLD and delta_p < -0.005:
        return "AGG_SHORT_INFLOW", float(delta_oi)
    elif delta_oi < -config.OI_AGGRESSIVE_EXPANSION_THRESHOLD and delta_p < -0.005:
        return "LONG_CAPITULATION", float(delta_oi)
    return "ROTATION", float(delta_oi)


def calculate_beta_relative_strength(asset_returns: np.ndarray, btc_returns: np.ndarray) -> float:
    """
    Calculates asset alpha residualized against BTC Beta: R_res = R_asset - Beta * R_btc
    """
    if len(asset_returns) < 20 or len(btc_returns) < 20:
        return 0.0

    min_len = min(len(asset_returns), len(btc_returns))
    asset_ret_sub = asset_returns[-min_len:]
    btc_ret_sub = btc_returns[-min_len:]

    variance_btc = np.var(btc_ret_sub)
    if variance_btc < 1e-9:
        beta = 0.0
    else:
        covariance = np.cov(asset_ret_sub, btc_ret_sub)[0][1]
        beta = covariance / (variance_btc + 1e-9)

    alpha_residual = np.sum(asset_ret_sub[-4:]) - (beta * np.sum(btc_ret_sub[-4:]))
    return float(alpha_residual * 100.0)


def compute_breakout_probability(features: Dict[str, Any]) -> float:
    """
    Logit calibration function: maps orthogonal microstructural factors into
    an actual statistical breakout probability % using Sigmoid activation.
    """
    logit = config.LOGISTIC_BIAS

    # Diurnal Volume contribution
    z_vol = features.get("diurnal_vol_zscore", 0.0)
    logit += config.MODEL_WEIGHTS["diurnal_vol_zscore"] * (z_vol if z_vol > 0 else 0)

    # Squeeze & Compression
    if features.get("is_coiled", False):
        logit += config.MODEL_WEIGHTS["squeeze_compression"]
    if features.get("is_fire", False):
        logit += config.MODEL_WEIGHTS["squeeze_fire"]

    # Order Flow & ΔOI
    regime = features.get("oi_regime", "NEUTRAL")
    if regime == "AGG_LONG_INFLOW":
        logit += config.MODEL_WEIGHTS["oi_expansion_regime"]
    elif regime == "SHORT_COVERING_SPIKE":
        logit += (config.MODEL_WEIGHTS["oi_expansion_regime"] * 0.5)

    # Beta Relative Alpha
    alpha = features.get("beta_alpha", 0.0)
    if alpha > 0.5:
        logit += config.MODEL_WEIGHTS["relative_strength_alpha"] * min(alpha, 3.0)

    # Live 15m Microstructure
    body_ratio = features.get("body_ratio", 0.0)
    upper_wick_ratio = features.get("upper_wick_ratio", 0.0)
    pct_move = features.get("pct_move_15m", 0.0)

    if body_ratio >= 0.70 and pct_move >= 0.005:
        logit += config.MODEL_WEIGHTS["power_candle_ratio"]

    if upper_wick_ratio >= 0.60:
        logit += config.MODEL_WEIGHTS["rejection_penalty"]

    # Sigmoid function: σ(z) = 1 / (1 + e^(-z))
    prob = 1.0 / (1.0 + math.exp(-max(min(logit, 10.0), -10.0)))
    return round(prob * 100.0, 1)
