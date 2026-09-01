import pandas as pd
from typing import Dict, Any, Optional
from config import RadarConfig
from core.indicators import (
    calculate_bollinger_bandwidth,
    calculate_volume_zscore,
    calculate_candle_metrics,
    calculate_delta_oi
)

class BreakoutScoringEngine:
    def __init__(self, config: Optional[RadarConfig] = None):
        self.cfg = config or RadarConfig()

    def evaluate_symbol(
        self,
        symbol: str,
        df_fast: pd.DataFrame,
        historical_oi: list[float]
    ) -> Dict[str, Any]:
        """
        Evaluates a symbol bidirectionally (LONG breakouts / SHORT breakdowns).
        Returns setup direction, numerical score (0-100), and trigger flags.
        """
        if len(df_fast) < self.cfg.LOOKBACK_PERIODS:
            return {"symbol": symbol, "score": 0, "direction": "NEUTRAL", "flags": ["INSUFFICIENT_DATA"]}

        closes = df_fast['close']
        highs = df_fast['high']
        lows = df_fast['low']
        volumes = df_fast['volume']

        curr_close = closes.iloc[-1]
        curr_open = df_fast['open'].iloc[-1]
        curr_high = highs.iloc[-1]
        curr_low = lows.iloc[-1]

        # 1. Volatility Compression (Bollinger Bandwidth)
        bbw, basis = calculate_bollinger_bandwidth(closes, self.cfg.BB_PERIOD, self.cfg.BB_STD)
        curr_bbw = bbw.iloc[-1]
        min_bbw_recent = bbw.iloc[-10:].min()
        is_compressed = min_bbw_recent <= self.cfg.BBW_COMPRESSION_THRESHOLD

        # 2. Volume Z-Score Spike
        vol_zscore = calculate_volume_zscore(volumes, self.cfg.LOOKBACK_PERIODS)
        is_vol_spike = vol_zscore >= self.cfg.VOL_ZSCORE_TRIGGER

        # 3. Delta Open Interest
        delta_oi = calculate_delta_oi(historical_oi)
        is_oi_building = delta_oi >= self.cfg.DELTA_OI_THRESHOLD_PCT

        # 4. Candle Morphology
        c_metrics = calculate_candle_metrics(curr_open, curr_high, curr_low, curr_close)

        # 5. Trend Moving Averages
        sma_fast = closes.rolling(self.cfg.SMA_FAST).mean().iloc[-1]
        sma_slow = closes.rolling(self.cfg.SMA_SLOW).mean().iloc[-1]

        # 6. Lookback Highs / Lows (Breakout check)
        n_high = highs.iloc[-self.cfg.LOOKBACK_PERIODS:-1].max()
        n_low = lows.iloc[-self.cfg.LOOKBACK_PERIODS:-1].min()

        # Evaluate Directions
        long_score, long_flags = self._score_direction(
            direction="LONG",
            is_compressed=is_compressed,
            vol_zscore=vol_zscore,
            delta_oi=delta_oi,
            c_metrics=c_metrics,
            is_trend_aligned=sma_fast > sma_slow,
            is_breaking_level=curr_close >= (n_high * 0.998)
        )

        short_score, short_flags = self._score_direction(
            direction="SHORT",
            is_compressed=is_compressed,
            vol_zscore=vol_zscore,
            delta_oi=delta_oi,
            c_metrics=c_metrics,
            is_trend_aligned=sma_fast < sma_slow,
            is_breaking_level=curr_close <= (n_low * 1.002)
        )

        curr_volume = float(volumes.iloc[-1])

        if long_score >= short_score and long_score > 0:
            return {"symbol": symbol, "price": float(curr_close), "volume": curr_volume, "score": long_score, "direction": "LONG", "flags": long_flags, "z_score": vol_zscore, "bbw": curr_bbw, "delta_oi": delta_oi}
        elif short_score > long_score and short_score > 0:
            return {"symbol": symbol, "price": float(curr_close), "volume": curr_volume, "score": short_score, "direction": "SHORT", "flags": short_flags, "z_score": vol_zscore, "bbw": curr_bbw, "delta_oi": delta_oi}

        return {"symbol": symbol, "price": float(curr_close), "volume": curr_volume, "score": 0, "direction": "NEUTRAL", "flags": [], "z_score": vol_zscore, "bbw": curr_bbw, "delta_oi": delta_oi}

    def _score_direction(self, direction: str, is_compressed: bool, vol_zscore: float, delta_oi: float,
                         c_metrics: Dict[str, float], is_trend_aligned: bool, is_breaking_level: bool) -> tuple[int, list[str]]:
        score = 0
        flags = []

        if is_compressed:
            score += self.cfg.WEIGHT_COMPRESSION
            flags.append("COILED")
        if vol_zscore >= self.cfg.VOL_ZSCORE_TRIGGER:
            score += self.cfg.WEIGHT_VOL_SPIKE
            flags.append("VOL_SPIKE")
        if delta_oi >= self.cfg.DELTA_OI_THRESHOLD_PCT:
            score += self.cfg.WEIGHT_DELTA_OI
            flags.append("OI_EXPANSION")
        if is_trend_aligned:
            score += self.cfg.WEIGHT_TREND_ALIGNMENT

        # Candle checks depending on direction
        wick_ok = c_metrics["upper_wick_ratio"] <= self.cfg.MAX_REJECTION_WICK_RATIO if direction == "LONG" else c_metrics["lower_wick_ratio"] <= self.cfg.MAX_REJECTION_WICK_RATIO
        dir_candle_ok = c_metrics["is_bullish"] if direction == "LONG" else not c_metrics["is_bullish"]

        if c_metrics["body_ratio"] >= self.cfg.CANDLE_BODY_MIN_RATIO and wick_ok and dir_candle_ok:
            score += self.cfg.WEIGHT_CANDLE_QUALITY
            flags.append("STRONG_BODY")

        if not is_breaking_level:
            score = int(score * 0.5)  # Penalty if not at actual range extremes

        return min(score, 100), flags
