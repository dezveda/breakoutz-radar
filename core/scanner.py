import asyncio
import aiohttp
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
import config
from core.analytics import (
    calculate_diurnal_volume_zscore,
    calculate_carter_squeeze,
    evaluate_order_flow_regime,
    calculate_beta_relative_strength,
    compute_breakout_probability
)

class MarketScanner:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.btc_returns_cache: np.ndarray = np.array([])

    async def fetch_klines(self, symbol: str, interval: str, limit: int = 100) -> Optional[pd.DataFrame]:
        """Fetches historical OHLCV data from Binance REST API and formats open_time as datetime."""
        url = f"{config.BASE_URL}/fapi/v1/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        try:
            async with self.session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    df = pd.DataFrame(data, columns=[
                        "open_time", "open", "high", "low", "close", "volume",
                        "close_time", "qav", "num_trades", "taker_base_vol", "taker_quote_vol", "ignore"
                    ])
                    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
                    numeric_cols = ["open", "high", "low", "close", "volume"]
                    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, axis=1)
                    return df
        except Exception:
            pass
        return None

    async def update_benchmark_cache(self) -> None:
        """Fetches BTCUSDT 15m returns and updates btc_returns_cache."""
        btc_klines = await self.fetch_klines(config.BENCHMARK_SYMBOL, "15m", limit=100)
        if btc_klines is not None and not btc_klines.empty and len(btc_klines) > 1:
            returns = btc_klines["close"].pct_change().dropna().values
            self.btc_returns_cache = returns

    async def fetch_open_interest_hist(self, symbol: str) -> List[float]:
        """Fetches historical Open Interest to compute accurate ΔOI."""
        url = f"{config.BASE_URL}/futures/data/openInterestHist?symbol={symbol}&period=15m&limit=5"
        try:
            async with self.session.get(url, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    return [float(x["sumOpenInterestValue"]) for x in data]
        except Exception:
            pass
        return []

    async def evaluate_symbol(self, symbol: str, ticker_data: dict) -> Optional[dict]:
        # Fetch 15m & 1h Klines concurrently
        kline_15m_task = self.fetch_klines(symbol, "15m", limit=130)
        kline_1h_task = self.fetch_klines(symbol, "1h", limit=config.VOLUME_LOOKBACK_HOURS)
        oi_task = self.fetch_open_interest_hist(symbol)

        klines_15m, klines_1h, oi_hist = await asyncio.gather(kline_15m_task, kline_1h_task, oi_task)

        if klines_15m is None or klines_1h is None or len(klines_15m) < 30:
            return None

        # 1. Diurnal De-seasonalized Volume Z-Score
        diurnal_z = calculate_diurnal_volume_zscore(klines_1h)

        # 2. Carter Squeeze & Volatility Compression Percentile
        is_coiled, is_fire, bbw_rank = calculate_carter_squeeze(klines_15m)

        # 3. Microstructure candle breakdown (15m live forming)
        c_open = klines_15m['open'].iloc[-1]
        c_close = klines_15m['close'].iloc[-1]
        c_high = klines_15m['high'].iloc[-1]
        c_low = klines_15m['low'].iloc[-1]

        candle_range = max(c_high - c_low, 1e-9)
        body_ratio = abs(c_close - c_open) / candle_range
        upper_wick = (c_high - max(c_open, c_close)) / candle_range
        pct_move = (c_close - c_open) / c_open

        # 4. Order Flow & ΔOI Regime
        price_hist = klines_15m['close'].values[-len(oi_hist):].tolist() if oi_hist else []
        oi_regime, delta_oi = evaluate_order_flow_regime(oi_hist, price_hist)

        # 5. Beta Residual Relative Strength vs BTC
        asset_returns = klines_15m['close'].pct_change().dropna().values
        beta_alpha = calculate_beta_relative_strength(asset_returns, self.btc_returns_cache)

        # 6. Calibrated Probabilistic Inference Engine
        features = {
            "diurnal_vol_zscore": diurnal_z,
            "is_coiled": is_coiled,
            "is_fire": is_fire,
            "oi_regime": oi_regime,
            "beta_alpha": beta_alpha,
            "body_ratio": body_ratio,
            "upper_wick_ratio": upper_wick,
            "pct_move_15m": pct_move
        }

        probability = compute_breakout_probability(features)
        if probability < config.DISPLAY_MIN_PROBABILITY:
            return None

        flags = []
        if is_fire: flags.append("SQUEEZE_FIRE")
        elif is_coiled: flags.append("COILED")
        if diurnal_z >= 2.0: flags.append("VOL_SURGE")
        if oi_regime == "AGG_LONG_INFLOW": flags.append("OI_EXPANSION")
        if beta_alpha >= 1.0: flags.append("BETA_ALPHA")

        return {
            "symbol": symbol,
            "price": c_close,
            "change_24h": float(ticker_data.get("priceChangePercent", 0.0)),
            "probability": probability,
            "diurnal_z": diurnal_z,
            "bbw_rank": bbw_rank,
            "oi_regime": oi_regime,
            "delta_oi": delta_oi * 100.0,
            "beta_alpha": beta_alpha,
            "flags": flags
        }
